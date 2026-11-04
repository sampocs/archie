"""The caller's own rows for sync actions, payload parsing, and the top of the queue."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import pydantic
import sqlalchemy
from archie_db import models
from sqlalchemy import orm

MALFORMED = "payload is malformed"
NO_SOURCE = "source not found"
NO_TOPIC = "topic not found"


def parse[PayloadT: pydantic.BaseModel](model: type[PayloadT], payload: Mapping[str, object]) -> PayloadT | None:
    """The payload as `model`, or None when it doesn't fit (the action is then rejected as malformed)."""
    try:
        return model.model_validate(payload)
    except pydantic.ValidationError:
        return None


def owned_source(db: orm.Session, *, user: models.User, source_id: uuid.UUID) -> models.Source | None:
    """The user's live source with this id; another user's or a deleted one is treated as missing."""
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user.id or source.deleted_at is not None:
        return None
    return source


def owned_topic(db: orm.Session, *, user: models.User, topic_id: uuid.UUID) -> models.Topic | None:
    """The user's topic with this id unless it was merged away; removed topics are returned (restore needs them)."""
    topic = db.get(models.Topic, topic_id)
    if topic is None or topic.user_id != user.id or topic.merged_into_id is not None:
        return None
    return topic


def owned_topic_primer(db: orm.Session, *, user: models.User, primer_id: uuid.UUID) -> models.TopicPrimer | None:
    """The user's topic primer row with this id."""
    primer = db.get(models.TopicPrimer, primer_id)
    return primer if primer is not None and primer.user_id == user.id else None


def top_queue_position(db: orm.Session, *, user_id: int) -> float:
    """A position above every queued source of the user: one less than the lowest, or 0 for an empty queue."""
    lowest = db.scalar(
        sqlalchemy.select(sqlalchemy.func.min(models.Source.queue_position)).where(
            models.Source.user_id == user_id,
            models.Source.state == models.SourceState.QUEUED.value,
            models.Source.deleted_at.is_(None),
        )
    )
    return 0.0 if lowest is None else lowest - 1
