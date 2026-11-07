"""The job queue's write side: callers enqueue inside their own transaction, so work is never lost or orphaned."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import sqlalchemy
import sqlalchemy.orm

from archie_db import models

# A `fetch_collection_item` job's payload key: the saved post to fill in.
COLLECTION_ITEM_ID_KEY = "collection_item_id"

# The payload key of `clean_take` and `take_cards` jobs: the take version to clean up or write cards from.
TAKE_VERSION_ID_KEY = "take_version_id"

# An `embed` job's payload keys: which kind of item (a `SearchItemKind`) and its id.
ITEM_KIND_KEY = "item_kind"
ITEM_ID_KEY = "item_id"


def enqueue(
    db: sqlalchemy.orm.Session,
    *,
    kind: models.JobKind,
    user_id: int,
    payload: dict[str, Any],
    max_attempts: int | None = None,
    delay: datetime.timedelta | None = None,
) -> models.Job:
    """Add a job that is due now, or after `delay`; it commits (or rolls back) with the caller's transaction.

    `max_attempts=None` keeps the column default. The due time is the database's clock plus `delay`, the same clock
    the worker compares it against.
    """
    job = models.Job(kind=kind.value, user_id=user_id, payload=payload, status=models.JobStatus.QUEUED.value)
    if max_attempts is not None:
        job.max_attempts = max_attempts
    if delay is not None:
        job.next_run_at = sqlalchemy.func.now() + delay
    db.add(job)
    db.flush()
    return job


def enqueue_embed(
    db: sqlalchemy.orm.Session, *, user_id: int, item_kind: models.SearchItemKind, item_id: uuid.UUID
) -> None:
    """Queue `embed` for one item, unless one is already waiting: the job reads the item when it runs, so one is enough.

    A source's text, summary and primer are often written within seconds of each other.
    """
    waiting = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.kind == models.JobKind.EMBED.value,
                models.Job.status == models.JobStatus.QUEUED.value,
                models.Job.payload[ITEM_ID_KEY].astext == str(item_id),
            )
        )
    )
    if waiting:
        return

    enqueue(
        db,
        kind=models.JobKind.EMBED,
        user_id=user_id,
        payload={ITEM_KIND_KEY: item_kind.value, ITEM_ID_KEY: str(item_id)},
    )
