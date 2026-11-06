"""`clean_take`: turn what the owner typed or dictated into a short markdown take, in their own words only.

It writes only the version it was queued for, and only while that version still has no body (a duplicate job or the
failure hook may have written it). When the version is still the take's current one it queues `take_cards`; a version
replaced meanwhile is cleaned for the record but gets no cards (the newer save queued its own steps). When the job gives
up, the failure hook shows the raw text as the body and marks the version, so the take page offers Try again.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, takes
from archie_llm import llm

from archie_worker import keys, prompts

MAX_OUTPUT_TOKENS = 2000


@dataclass(frozen=True)
class _CleanRun:
    """What the model call and the write need after the first transaction ends."""

    version_id: uuid.UUID
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Clean the version's raw text into its body, then queue the take's cards if it is still current."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.CLEAN_TAKE_MODELS,
        system=prompts.CLEAN_TAKE_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    body = completion.text.strip()
    if not body:
        raise ValueError(f"clean_take wrote nothing for version {run.version_id}")

    changes.lock_user_writes(db, run.user_id)
    version = db.get_one(models.TakeVersion, run.version_id)
    db.refresh(version)
    # A duplicate job or the failure hook may have written it while the call ran.
    if version.body is not None:
        return

    _write_body(db, version=version, body=body, failed=False)


def mark_failed(db: sqlalchemy.orm.Session, job: models.Job, reason: str) -> None:
    """Failure hook: the raw text becomes the body and the page offers Try again; the take still gets its cards."""
    del reason
    version = db.get(models.TakeVersion, uuid.UUID(job.payload[jobs.TAKE_VERSION_ID_KEY]))
    if version is None:
        return

    changes.lock_user_writes(db, version.user_id)
    db.refresh(version)
    if version.body is not None:
        return

    _write_body(db, version=version, body=version.raw_body, failed=True)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _CleanRun | None:
    """Read the version and build the call, then commit; None when there is nothing to clean."""
    version = db.get(models.TakeVersion, uuid.UUID(job.payload[jobs.TAKE_VERSION_ID_KEY]))
    take = db.get(models.Take, version.take_id) if version is not None else None
    if version is None or take is None or take.deleted_at is not None or version.body is not None:
        db.commit()
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, version.user_id))
    run = _CleanRun(
        version_id=version.id,
        user_id=version.user_id,
        context=llm.CallContext(user_id=version.user_id, source_id=None, job_id=job.id, step=models.JobKind.CLEAN_TAKE),
        api_key=api_key,
        user_message=prompts.clean_take_message(
            kind=models.TakeKind(take.kind), title=take.title, raw_body=version.raw_body
        ),
    )
    db.commit()
    return run


def _write_body(db: sqlalchemy.orm.Session, *, version: models.TakeVersion, body: str, failed: bool) -> None:
    """Store the shown body; the current version of a live take then gets its cards."""
    version.body = body
    version.clean_failed = failed
    takes.mark_changed(version)

    take = db.get_one(models.Take, version.take_id)
    db.refresh(take)
    if takes.is_current(take, version):
        takes.enqueue_step(db, version=version, kind=models.JobKind.TAKE_CARDS)
