"""The caller's own rows for sync actions, payload parsing, the top of the queue, and queueing a primer."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import pydantic
import sqlalchemy
from archie_db import changes, models, pipeline
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
    """A position above every queue entry of the user: one less than the lowest, or 0 for an empty queue.

    Queued sources and queued primers share one position space, so both count.
    """
    live_source_of_user = sqlalchemy.and_(models.Source.user_id == user_id, models.Source.deleted_at.is_(None))
    lowest_source = db.scalar(
        sqlalchemy.select(sqlalchemy.func.min(models.Source.queue_position)).where(
            live_source_of_user, models.Source.state == models.SourceState.QUEUED.value
        )
    )
    lowest_primer = db.scalar(
        sqlalchemy.select(sqlalchemy.func.min(models.Source.primer_queue_position)).where(live_source_of_user)
    )

    positions = [position for position in (lowest_source, lowest_primer) if position is not None]
    return min(positions) - 1 if positions else 0.0


def queue_primer(db: orm.Session, *, source: models.Source) -> None:
    """Put the source's primer at the top of the queue, unsnoozed; a newsletter without one has it written.

    Newsletters get a primer only on request, so one with no current primer and none being written gets a `primer`
    job and shows as processing until it lands. The caller holds the user's write lock and has validated the source.
    """
    source.primer_queue_position = top_queue_position(db, user_id=source.user_id)
    source.primer_snoozed_until = None
    changes.touch(source)

    if source.kind == models.SourceKind.NEWSLETTER and not has_or_is_writing_primer(db, source=source):
        start_primer(db, source=source)


def has_or_is_writing_primer(db: orm.Session, *, source: models.Source) -> bool:
    """Whether the source has a current primer, or a `primer` job for it is queued or running."""
    if pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.PRIMER) is not None:
        return True

    writing = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.kind == models.JobKind.PRIMER.value,
                models.Job.status.in_([models.JobStatus.QUEUED.value, models.JobStatus.RUNNING.value]),
                models.Job.payload[pipeline.SOURCE_ID_KEY].astext == str(source.id),
            )
        )
    )
    return bool(writing)


def start_primer(db: orm.Session, *, source: models.Source) -> None:
    """Queue the source's `primer` job and show it as processing until the primer lands."""
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.PRIMER])
