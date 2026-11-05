"""The capture pipeline's shared state: artifact versions, a source's processing status, and which steps to retry.

Every function that writes expects the caller to hold `changes.lock_user_writes` for the source's user.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, jobs, models

# The job payload key naming the source a pipeline step works on.
SOURCE_ID_KEY = "source_id"

# Steps that get more attempts than the default: a rate-limited transcription re-queues itself and each try counts.
MAX_ATTEMPTS: dict[models.JobKind, int] = {
    models.JobKind.TRANSCRIBE: 6,
    # One sequential worker would let analyze run on the raw text while a retried clean_text waits its turn; a single
    # attempt means cleaning either happens before analyze or is skipped.
    models.JobKind.CLEAN_TEXT: 1,
}

# True in the content of a `text` artifact `clean_text` wrote (the text before cleaning stays an older version).
CLEANED_KEY = "cleaned"

# The artifact each generation step writes, which tells a retry whether the step still has to run.
_STEP_OUTPUTS: dict[models.JobKind, models.ArtifactKind] = {
    models.JobKind.ANALYZE: models.ArtifactKind.SUMMARY,
    models.JobKind.PRIMER: models.ArtifactKind.PRIMER,
}


def current_artifact(
    db: sqlalchemy.orm.Session, *, source_id: uuid.UUID, kind: models.ArtifactKind
) -> models.SourceArtifact | None:
    """The source's current version of `kind`, or None when none was written."""
    return db.scalars(
        sqlalchemy.select(models.SourceArtifact).where(
            models.SourceArtifact.source_id == source_id,
            models.SourceArtifact.kind == kind.value,
            models.SourceArtifact.is_current,
        )
    ).one_or_none()


def write_artifact(
    db: sqlalchemy.orm.Session,
    *,
    source: models.Source,
    kind: models.ArtifactKind,
    content: dict[str, Any],
    model: str | None,
    prompt_version: str | None,
) -> models.SourceArtifact:
    """Add the next version of `kind` as the current one; the previous current version is kept, no longer current."""
    previous = current_artifact(db, source_id=source.id, kind=kind)
    if previous is not None:
        # Flushed first so the partial unique index never sees two current rows.
        previous.is_current = False
        previous.change_seq = changes.next_change_seq()
        db.flush()

    latest_version = db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(models.SourceArtifact.version)).where(
            models.SourceArtifact.source_id == source.id, models.SourceArtifact.kind == kind.value
        )
    )
    artifact = models.SourceArtifact(
        id=uuid.uuid4(),
        user_id=source.user_id,
        source_id=source.id,
        kind=kind.value,
        version=(latest_version or 0) + 1,
        content=content,
        is_current=True,
        model=model,
        prompt_version=prompt_version,
        change_seq=changes.next_change_seq(),
    )
    db.add(artifact)
    db.flush()
    return artifact


def set_processing(
    db: sqlalchemy.orm.Session,
    *,
    source: models.Source,
    status: models.ProcessingStatus,
    error: str | None = None,
) -> None:
    """Move the source to `status`; the error is kept only for FAILED and UNSUPPORTED."""
    source.processing = status.value
    keeps_error = status in (models.ProcessingStatus.FAILED, models.ProcessingStatus.UNSUPPORTED)
    source.processing_error = error if keeps_error else None
    source.updated_at = sqlalchemy.func.now()
    source.change_seq = changes.next_change_seq()


def required_artifacts(kind: models.SourceKind) -> tuple[models.ArtifactKind, ...]:
    """The outputs a source of `kind` needs to be READY: newsletters are summary-only, the rest also get a primer."""
    if kind == models.SourceKind.NEWSLETTER:
        return (models.ArtifactKind.SUMMARY,)
    return (models.ArtifactKind.SUMMARY, models.ArtifactKind.PRIMER)


def steps_after_text(kind: models.SourceKind) -> list[models.JobKind]:
    """The jobs that follow a source's text, in order.

    Newsletters have their boilerplate cleaned out and are then analyzed (a primer only on request); the rest are
    analyzed and get a primer.
    """
    if kind == models.SourceKind.NEWSLETTER:
        return [models.JobKind.CLEAN_TEXT, models.JobKind.ANALYZE]
    return [models.JobKind.ANALYZE, models.JobKind.PRIMER]


def finish_step(db: sqlalchemy.orm.Session, *, source: models.Source) -> None:
    """Mark the source READY once all the outputs its kind needs exist; otherwise leave it as is.

    A newsletter needs only its summary, so a requested primer finishing also returns it to READY. While a primer
    job for the source is still queued (a newsletter's analyze ran first) it stays as is, so the phone doesn't offer
    to create a primer that is already on its way. A running primer job is the step finishing, so it doesn't block.
    """
    required = required_artifacts(models.SourceKind(source.kind))
    if any(current_artifact(db, source_id=source.id, kind=kind) is None for kind in required):
        return
    if _has_queued_primer_job(db, source_id=source.id):
        return

    set_processing(db, source=source, status=models.ProcessingStatus.READY)


def _has_queued_primer_job(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID) -> bool:
    queued = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.kind == models.JobKind.PRIMER.value,
                models.Job.status == models.JobStatus.QUEUED.value,
                models.Job.payload[SOURCE_ID_KEY].astext == str(source_id),
            )
        )
    )
    return bool(queued)


def steps_to_retry(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID) -> list[models.JobKind]:
    """The jobs a retry should run: fetch when there is no text, else whichever of the kind's steps has no output.

    Cleaning is done once the current text is a cleaned one, so a retry skips it; when it is not done, every later
    step runs too, since it changes their input. When everything exists the user asked to redo it, so all of the
    kind's generation steps run again.
    """
    text = current_artifact(db, source_id=source_id, kind=models.ArtifactKind.TEXT)
    if text is None:
        return [models.JobKind.FETCH_CONTENT]

    source = db.get_one(models.Source, source_id)
    is_cleaned = text.content.get(CLEANED_KEY) is True
    steps = [
        step
        for step in steps_after_text(models.SourceKind(source.kind))
        if not (step == models.JobKind.CLEAN_TEXT and is_cleaned)
    ]
    if models.JobKind.CLEAN_TEXT in steps:
        return steps

    missing = [step for step in steps if current_artifact(db, source_id=source_id, kind=_STEP_OUTPUTS[step]) is None]
    return missing or steps


def enqueue_steps(db: sqlalchemy.orm.Session, *, source: models.Source, steps: list[models.JobKind]) -> None:
    """Queue one job per step, in order, in the caller's transaction."""
    for step in steps:
        jobs.enqueue(
            db,
            kind=step,
            user_id=source.user_id,
            payload={SOURCE_ID_KEY: str(source.id)},
            max_attempts=MAX_ATTEMPTS.get(step),
        )
