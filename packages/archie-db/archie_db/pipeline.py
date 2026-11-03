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
    """Move the source to `status`; the error is kept only for FAILED."""
    source.processing = status.value
    source.processing_error = error if status == models.ProcessingStatus.FAILED else None
    source.updated_at = sqlalchemy.func.now()
    source.change_seq = changes.next_change_seq()


def finish_step(db: sqlalchemy.orm.Session, *, source: models.Source) -> None:
    """Mark the source READY once both its summary and primer exist; otherwise leave it as is."""
    required = (models.ArtifactKind.SUMMARY, models.ArtifactKind.PRIMER)
    if any(current_artifact(db, source_id=source.id, kind=kind) is None for kind in required):
        return

    set_processing(db, source=source, status=models.ProcessingStatus.READY)


def steps_to_retry(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID) -> list[models.JobKind]:
    """The jobs a retry should run: fetch when there is no text, else whichever of analyze/primer has no output.

    When everything exists the user asked to redo it, so both generation steps run again.
    """
    if current_artifact(db, source_id=source_id, kind=models.ArtifactKind.TEXT) is None:
        return [models.JobKind.FETCH_CONTENT]

    step_outputs = (
        (models.JobKind.ANALYZE, models.ArtifactKind.SUMMARY),
        (models.JobKind.PRIMER, models.ArtifactKind.PRIMER),
    )
    missing = [step for step, kind in step_outputs if current_artifact(db, source_id=source_id, kind=kind) is None]
    return missing or [step for step, _ in step_outputs]


def enqueue_steps(db: sqlalchemy.orm.Session, *, source: models.Source, steps: list[models.JobKind]) -> None:
    """Queue one job per step, in order, in the caller's transaction."""
    for step in steps:
        jobs.enqueue(db, kind=step, user_id=source.user_id, payload={SOURCE_ID_KEY: str(source.id)})
