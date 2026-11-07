"""`archie-worker backfill-embed`: queue `embed` for every live item that existed before search, once after deploy.

Every live source with a current text or summary, every current topic primer of a live topic, and every live take
whose current version has a body. Items already waiting for `embed` are skipped, so running it twice queues nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session
from archie_shared import config, logging

_logger = logging.get_logger(logging.LoggerName.WORKER, "backfill_embed")


def main() -> None:
    """Queue the jobs against `DATABASE_URL` and report how many."""
    logging.configure()
    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        count = backfill_all(db)
        db.commit()
    _logger.info("Queued embed for %d items", count)


def backfill_all(db: sqlalchemy.orm.Session) -> int:
    """Queue one `embed` per live item, in the caller's transaction; returns how many were queued."""
    items = [*_sources(db), *_topic_primers(db), *_takes(db)]
    queued = 0
    for item in items:
        changes.lock_user_writes(db, item.user_id)
        before = _queued_count(db)
        jobs.enqueue_embed(db, user_id=item.user_id, item_kind=item.kind, item_id=item.item_id)
        queued += _queued_count(db) - before
    return queued


@dataclass(frozen=True)
class _Item:
    """One live item to index."""

    user_id: int
    kind: models.SearchItemKind
    item_id: uuid.UUID


def _sources(db: sqlalchemy.orm.Session) -> list[_Item]:
    has_words = sqlalchemy.exists().where(
        models.SourceArtifact.source_id == models.Source.id,
        models.SourceArtifact.is_current,
        models.SourceArtifact.kind.in_([models.ArtifactKind.TEXT.value, models.ArtifactKind.SUMMARY.value]),
    )
    rows = db.execute(
        sqlalchemy.select(models.Source.user_id, models.Source.id).where(
            models.Source.deleted_at.is_(None), models.Source.merged_into_id.is_(None), has_words
        )
    )
    return [_Item(user_id=user_id, kind=models.SearchItemKind.SOURCE, item_id=item_id) for user_id, item_id in rows]


def _topic_primers(db: sqlalchemy.orm.Session) -> list[_Item]:
    rows = db.execute(
        sqlalchemy.select(models.TopicPrimer.user_id, models.TopicPrimer.id)
        .join(models.Topic, models.Topic.id == models.TopicPrimer.topic_id)
        .where(models.TopicPrimer.is_current, models.Topic.removed_at.is_(None), models.Topic.merged_into_id.is_(None))
    )
    return [
        _Item(user_id=user_id, kind=models.SearchItemKind.TOPIC_PRIMER, item_id=item_id) for user_id, item_id in rows
    ]


def _takes(db: sqlalchemy.orm.Session) -> list[_Item]:
    rows = db.execute(
        sqlalchemy.select(models.Take.user_id, models.Take.id)
        .join(
            models.TakeVersion,
            sqlalchemy.and_(
                models.TakeVersion.take_id == models.Take.id, models.TakeVersion.version == models.Take.current_version
            ),
        )
        .where(models.Take.deleted_at.is_(None), models.TakeVersion.body.is_not(None))
    )
    return [_Item(user_id=user_id, kind=models.SearchItemKind.TAKE, item_id=item_id) for user_id, item_id in rows]


def _queued_count(db: sqlalchemy.orm.Session) -> int:
    return (
        db.scalar(
            sqlalchemy.select(sqlalchemy.func.count()).where(
                models.Job.kind == models.JobKind.EMBED.value, models.Job.status == models.JobStatus.QUEUED.value
            )
        )
        or 0
    )
