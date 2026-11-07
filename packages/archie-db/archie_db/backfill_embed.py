"""Queue `embed` for every live item with no search passages yet; runs on each deploy and by hand.

Every live source with a current text or summary and no chunk, every current topic primer of a live topic with no chunk
on any version of the topic, and every live take whose current version has a body and no chunk. Items already waiting
for `embed` are skipped too, so running it twice queues nothing new.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, jobs, models


def backfill_all(db: sqlalchemy.orm.Session) -> int:
    """Queue one `embed` per unindexed live item, in the caller's transaction; returns how many were queued."""
    items = [*_sources(db), *_topic_primers(db), *_takes(db)]
    queued = 0
    for item in items:
        changes.lock_user_writes(db, item.user_id)
        queued += jobs.enqueue_embed(db, user_id=item.user_id, item_kind=item.kind, item_id=item.item_id)
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
    unindexed = ~sqlalchemy.exists().where(models.Chunk.source_id == models.Source.id)
    rows = db.execute(
        sqlalchemy.select(models.Source.user_id, models.Source.id).where(
            models.Source.deleted_at.is_(None), models.Source.merged_into_id.is_(None), has_words, unindexed
        )
    )
    return [_Item(user_id=user_id, kind=models.SearchItemKind.SOURCE, item_id=item_id) for user_id, item_id in rows]


def _topic_primers(db: sqlalchemy.orm.Session) -> list[_Item]:
    # `embed` rebuilds a topic's chunks under its current version, so a chunk on any older version counts as indexed.
    any_version = sqlalchemy.orm.aliased(models.TopicPrimer)
    unindexed = ~sqlalchemy.exists().where(
        any_version.topic_id == models.TopicPrimer.topic_id, models.Chunk.topic_primer_id == any_version.id
    )
    rows = db.execute(
        sqlalchemy.select(models.TopicPrimer.user_id, models.TopicPrimer.id)
        .join(models.Topic, models.Topic.id == models.TopicPrimer.topic_id)
        .where(
            models.TopicPrimer.is_current,
            models.Topic.removed_at.is_(None),
            models.Topic.merged_into_id.is_(None),
            unindexed,
        )
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
        .where(
            models.Take.deleted_at.is_(None),
            models.TakeVersion.body.is_not(None),
            ~sqlalchemy.exists().where(models.Chunk.take_id == models.Take.id),
        )
    )
    return [_Item(user_id=user_id, kind=models.SearchItemKind.TAKE, item_id=item_id) for user_id, item_id in rows]
