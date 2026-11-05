"""The job queue's write side: callers enqueue inside their own transaction, so work is never lost or orphaned."""

from __future__ import annotations

import datetime
from typing import Any

import sqlalchemy
import sqlalchemy.orm

from archie_db import models


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
