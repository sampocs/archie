"""The job loop: claim a due job, run its handler, and record the outcome.

Postgres is the queue. `FOR UPDATE SKIP LOCKED` lets several workers poll safely, and the claim
commits before the handler runs so a running job is visible (and recoverable if the process dies).
"""

from __future__ import annotations

import datetime
import threading
from collections.abc import Callable, Mapping

import sqlalchemy
import sqlalchemy.orm
from archie_db import models
from archie_shared import logging

Handler = Callable[[sqlalchemy.orm.Session, models.Job], None]

# Seconds to wait before attempt 2, 3, ...; the last value repeats.
BACKOFF_SECONDS = (10, 60, 300)
# A job running longer than this is assumed orphaned by a crashed worker.
STALE_AFTER = datetime.timedelta(seconds=600)
IDLE_POLL_SECONDS = 2.0
REQUEUE_STALE_EVERY = datetime.timedelta(seconds=60)

_MAX_ERROR_LENGTH = 2000

_logger = logging.get_logger(logging.LoggerName.WORKER, "loop")


def claim_next(db: sqlalchemy.orm.Session) -> models.Job | None:
    """Lock one due job so no other worker takes it, and mark it running."""
    job = db.execute(
        sqlalchemy.select(models.Job)
        .where(models.Job.status == models.JobStatus.QUEUED.value, models.Job.next_run_at <= sqlalchemy.func.now())
        .order_by(models.Job.next_run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None

    job.status = models.JobStatus.RUNNING.value
    job.started_at = sqlalchemy.func.now()
    job.attempts += 1
    return job


def run_one(engine: sqlalchemy.Engine, *, handlers: Mapping[models.JobKind, Handler]) -> bool:
    """Claim and run one due job; returns whether a job ran."""
    # Claim in its own short transaction so the job is visibly running while the handler works.
    with sqlalchemy.orm.Session(engine) as db:
        job = claim_next(db)
        if job is None:
            return False
        job_id = job.id
        db.commit()

    try:
        _run_handler(engine, job_id=job_id, handlers=handlers)
    except Exception as error:
        # The one intended catch-all: whatever a handler raises, the job must be retried or failed
        # rather than crash the worker or stay `running` until the stale sweep.
        _record_failure(engine, job_id=job_id, error=error)
    return True


def requeue_stale(db: sqlalchemy.orm.Session, *, now: datetime.datetime) -> int:
    """Recover jobs orphaned by a crashed worker: re-queue them, or fail those out of attempts. Returns the count."""
    stale = (
        models.Job.status == models.JobStatus.RUNNING.value,
        models.Job.started_at < now - STALE_AFTER,
    )
    failed_ids = db.scalars(
        sqlalchemy.update(models.Job)
        .where(*stale, models.Job.attempts >= models.Job.max_attempts)
        .values(status=models.JobStatus.FAILED.value, last_error="worker stopped before the job finished")
        .returning(models.Job.id)
    ).all()
    requeued_ids = db.scalars(
        sqlalchemy.update(models.Job)
        .where(*stale)
        .values(status=models.JobStatus.QUEUED.value, next_run_at=now)
        .returning(models.Job.id)
    ).all()
    db.commit()
    return len(failed_ids) + len(requeued_ids)


def run_forever(engine: sqlalchemy.Engine, *, stop: threading.Event) -> None:
    """Run jobs until `stop` is set, sweeping for stale jobs once a minute and sleeping when idle."""
    # Imported here: the handlers import `Handler` from this module.
    from archie_worker import handlers

    next_sweep_at = datetime.datetime.now(datetime.UTC)
    while not stop.is_set():
        now = datetime.datetime.now(datetime.UTC)
        if now >= next_sweep_at:
            with sqlalchemy.orm.Session(engine) as db:
                requeue_stale(db, now=now)
            next_sweep_at = now + REQUEUE_STALE_EVERY

        if not run_one(engine, handlers=handlers.HANDLERS):
            stop.wait(IDLE_POLL_SECONDS)


def _run_handler(engine: sqlalchemy.Engine, *, job_id: int, handlers: Mapping[models.JobKind, Handler]) -> None:
    """Run the job's handler and mark it done, all in one transaction."""
    with sqlalchemy.orm.Session(engine) as db:
        job = db.get_one(models.Job, job_id)
        handlers[models.JobKind(job.kind)](db, job)
        job.status = models.JobStatus.DONE.value
        job.last_error = None
        db.commit()


def _record_failure(engine: sqlalchemy.Engine, *, job_id: int, error: Exception) -> None:
    """Fail the job for good once its attempts run out; otherwise re-queue it after a backoff."""
    _logger.warning("Job %s failed: %r", job_id, error)

    with sqlalchemy.orm.Session(engine) as db:
        job = db.get_one(models.Job, job_id)
        job.last_error = repr(error)[:_MAX_ERROR_LENGTH]
        if job.attempts >= job.max_attempts:
            job.status = models.JobStatus.FAILED.value
        else:
            backoff = datetime.timedelta(seconds=BACKOFF_SECONDS[min(job.attempts - 1, len(BACKOFF_SECONDS) - 1)])
            job.status = models.JobStatus.QUEUED.value
            job.next_run_at = sqlalchemy.func.now() + backoff
        db.commit()
