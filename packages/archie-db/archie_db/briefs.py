"""The newsletter brief's shared rules: which newsletters it covers, the open brief, and queueing its rewrite.

Every function that writes expects the caller to hold `changes.lock_user_writes` for the user.
"""

from __future__ import annotations

import datetime

import sqlalchemy
import sqlalchemy.orm

from archie_db import jobs, models

# The `update_brief` job payload key naming whose brief to rewrite.
USER_ID_KEY = "user_id"
# Two tries are enough: the next newsletter to arrive re-triggers a rewrite anyway.
UPDATE_MAX_ATTEMPTS = 2


def covered_newsletters(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Source]:
    """What a brief covers now: every one of the user's ready, live inbox newsletters, however old, oldest first.

    Signup confirmations (`confirm_url` set) are ready too but are never briefed.
    """
    return list(
        db.scalars(
            sqlalchemy.select(models.Source)
            .where(
                models.Source.user_id == user_id,
                models.Source.kind == models.SourceKind.NEWSLETTER.value,
                models.Source.state == models.SourceState.INBOX.value,
                models.Source.processing == models.ProcessingStatus.READY.value,
                models.Source.deleted_at.is_(None),
                models.Source.confirm_url.is_(None),
            )
            .order_by(models.Source.created_at, models.Source.id)
        )
    )


def open_brief(db: sqlalchemy.orm.Session, *, user_id: int) -> models.Brief | None:
    """The user's open brief, or None when the last one was finished (or there never was one)."""
    return db.scalars(
        sqlalchemy.select(models.Brief).where(
            models.Brief.user_id == user_id, models.Brief.status == models.BriefStatus.OPEN.value
        )
    ).one_or_none()


def enqueue_update(db: sqlalchemy.orm.Session, *, user_id: int, delay: datetime.timedelta | None = None) -> None:
    """Queue an `update_brief` for the user, due after `delay` (now when `None`), unless one is already queued.

    A queued one will see every newsletter that is ready by the time it runs; a running one may have read its
    newsletters already, so it doesn't count and a follow-up is queued.
    """
    already_queued = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.kind == models.JobKind.UPDATE_BRIEF.value,
                models.Job.status == models.JobStatus.QUEUED.value,
                models.Job.user_id == user_id,
            )
        )
    )
    if already_queued:
        return

    jobs.enqueue(
        db,
        kind=models.JobKind.UPDATE_BRIEF,
        user_id=user_id,
        payload={USER_ID_KEY: user_id},
        max_attempts=UPDATE_MAX_ATTEMPTS,
        delay=delay,
    )
