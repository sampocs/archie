"""The job queue's write side: callers enqueue inside their own transaction, so work is never lost or orphaned."""

from __future__ import annotations

from typing import Any

import sqlalchemy.orm

from archie_db import models


def enqueue(
    db: sqlalchemy.orm.Session,
    *,
    kind: models.JobKind,
    user_id: int,
    payload: dict[str, Any],
    max_attempts: int | None = None,
) -> models.Job:
    """Add a job that is due now; it commits (or rolls back) with the caller's transaction.

    `max_attempts=None` keeps the column default.
    """
    job = models.Job(kind=kind.value, user_id=user_id, payload=payload, status=models.JobStatus.QUEUED.value)
    if max_attempts is not None:
        job.max_attempts = max_attempts
    db.add(job)
    db.flush()
    return job
