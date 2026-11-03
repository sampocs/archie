"""The job queue's write side: callers enqueue inside their own transaction, so work is never lost or orphaned."""

from __future__ import annotations

from typing import Any

import sqlalchemy.orm

from archie_db import models


def enqueue(db: sqlalchemy.orm.Session, *, kind: models.JobKind, user_id: int, payload: dict[str, Any]) -> models.Job:
    """Add a job that is due now; it commits (or rolls back) with the caller's transaction."""
    job = models.Job(kind=kind.value, user_id=user_id, payload=payload, status=models.JobStatus.QUEUED.value)
    db.add(job)
    db.flush()
    return job
