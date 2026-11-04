"""Topic actions: add, rename, merge, remove (which re-files), restore, file a source by hand, ask for a primer, and
submit the picker. Each returns the rejection reason or None; the caller holds the user's write lock and every check
runs before the first write."""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import changes, models, user_topics
from archie_shared import topics
from archie_shared.domains import Domain
from sqlalchemy import orm

from archie_api.sync import rows

MAX_CHOSEN_TOPICS = 200

_BAD_DOMAIN = "domain is not one of Archie's domains"
_EMPTY_NAME = "topic name is empty"
_LONG_NAME = f"topic name is longer than {user_topics.MAX_TOPIC_NAME_LENGTH} characters"
_NAME_TAKEN = "a topic with this name already exists"
_NAME_REMOVED = "a removed topic has this name; restore it instead"
_ID_EXISTS = "id already exists"
_SELF_MERGE = "can't merge a topic into itself"
_NOT_REMOVED = "topic is not removed"
_HAS_PRIMER = "topic already has a primer"
_PRIMER_BEING_WRITTEN = "a primer is already being written"
_ALREADY_CHOSEN = "topics already chosen"
_CHOOSE_ONE = "choose at least one topic"


class _TopicPayload(pydantic.BaseModel):
    id: uuid.UUID


class _AddTopicPayload(_TopicPayload):
    domain: str
    name: str


class _RenameTopicPayload(_TopicPayload):
    name: str


class _MergeTopicPayload(_TopicPayload):
    into_id: uuid.UUID


class _SetSourceTopicPayload(pydantic.BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID


class _ChooseTopicsPayload(pydantic.BaseModel):
    topics: list[_AddTopicPayload] = pydantic.Field(max_length=MAX_CHOSEN_TOPICS)


def add_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Add a topic the user wants to understand, and queue its primer."""
    parsed = rows.parse(_AddTopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    reason = _new_topic_reason(db, user=user, domain=parsed.domain, name=parsed.name)
    if reason is not None:
        return reason
    if db.get(models.Topic, parsed.id) is not None:
        return _ID_EXISTS

    topic = user_topics.create_topic(
        db,
        user_id=user.id,
        domain=Domain(parsed.domain),
        name=parsed.name,
        origin=models.TopicOrigin.USER,
        topic_id=parsed.id,
    )
    user_topics.enqueue_topic_primer(db, topic=topic)
    return None


def rename_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Rename a live topic; the new name must not clash with another live or removed topic."""
    parsed = rows.parse(_RenameTopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    topic = _live_topic(db, user=user, topic_id=parsed.id)
    if topic is None:
        return rows.NO_TOPIC
    reason = _name_reason(db, user=user, name=parsed.name, ignore_id=topic.id)
    if reason is not None:
        return reason

    topic.name = user_topics.clean_name(parsed.name)
    changes.touch(topic)
    return None


def merge_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Fold a topic into another: its sources move over (and take the target's domain), and it is merged away."""
    parsed = rows.parse(_MergeTopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    if parsed.id == parsed.into_id:
        return _SELF_MERGE
    topic = _live_topic(db, user=user, topic_id=parsed.id)
    target = _live_topic(db, user=user, topic_id=parsed.into_id)
    if topic is None or target is None:
        return rows.NO_TOPIC

    for source in _sources_of(db, topic=topic):
        source.topic_id = target.id
        source.domain = target.domain
        changes.touch(source)
    topic.merged_into_id = target.id
    changes.touch(topic)
    return None


def remove_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Block a topic: its sources lose it now and are filed again, with this topic among the removed."""
    parsed = rows.parse(_TopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    topic = _live_topic(db, user=user, topic_id=parsed.id)
    if topic is None:
        return rows.NO_TOPIC

    topic.removed_at = sqlalchemy.func.now()
    changes.touch(topic)
    for source in _sources_of(db, topic=topic):
        source.topic_id = None
        changes.touch(source)
        user_topics.enqueue_file_topic(db, source=source)
    return None


def restore_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Bring a removed topic back; sources already filed elsewhere stay where they are."""
    parsed = rows.parse(_TopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    topic = rows.owned_topic(db, user=user, topic_id=parsed.id)
    if topic is None:
        return rows.NO_TOPIC
    if topic.removed_at is None:
        return _NOT_REMOVED

    topic.removed_at = None
    changes.touch(topic)
    return None


def set_source_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """File a source under a topic by hand; its domain follows the topic."""
    parsed = rows.parse(_SetSourceTopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    topic = _live_topic(db, user=user, topic_id=parsed.topic_id)
    if topic is None:
        return rows.NO_TOPIC

    source.topic_id = topic.id
    source.domain = topic.domain
    changes.touch(source)
    return None


def request_topic_primer(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Ask for a topic's primer unless it has one or one is on its way."""
    parsed = rows.parse(_TopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    topic = _live_topic(db, user=user, topic_id=parsed.id)
    if topic is None:
        return rows.NO_TOPIC

    has_primer = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(models.TopicPrimer.topic_id == topic.id, models.TopicPrimer.is_current)
        )
    )
    if has_primer:
        return _HAS_PRIMER
    writing = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.kind == models.JobKind.TOPIC_PRIMER.value,
                models.Job.status.in_([models.JobStatus.QUEUED.value, models.JobStatus.RUNNING.value]),
                models.Job.payload[user_topics.TOPIC_ID_KEY].astext == str(topic.id),
            )
        )
    )
    if writing:
        return _PRIMER_BEING_WRITTEN

    user_topics.enqueue_topic_primer(db, topic=topic)
    return None


def choose_topics(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Submit the picker: create the chosen topics, mark topics chosen, and file every analyzed source."""
    parsed = rows.parse(_ChooseTopicsPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    if user.topics_chosen_at is not None:
        return _ALREADY_CHOSEN
    if not parsed.topics:
        return _CHOOSE_ONE
    reason = _chosen_topics_reason(db, user=user, chosen=parsed.topics)
    if reason is not None:
        return reason

    for chosen in parsed.topics:
        domain = Domain(chosen.domain)
        is_starter = topics.is_starter_topic(domain=domain, name=chosen.name)
        topic = user_topics.create_topic(
            db,
            user_id=user.id,
            domain=domain,
            name=chosen.name,
            origin=models.TopicOrigin.STARTER if is_starter else models.TopicOrigin.USER,
            topic_id=chosen.id,
        )
        if not is_starter:
            user_topics.enqueue_topic_primer(db, topic=topic)

    user.topics_chosen_at = sqlalchemy.func.now()
    for source in user_topics.analyzed_sources(db, user_id=user.id):
        user_topics.enqueue_file_topic(db, source=source)
    return None


def _live_topic(db: orm.Session, *, user: models.User, topic_id: uuid.UUID) -> models.Topic | None:
    """The user's topic if it is neither removed nor merged."""
    topic = rows.owned_topic(db, user=user, topic_id=topic_id)
    return None if topic is None or topic.removed_at is not None else topic


def _new_topic_reason(
    db: orm.Session, *, user: models.User, domain: str, name: str, ignore_id: uuid.UUID | None = None
) -> str | None:
    """Why a topic with this domain and name can't be added (or a topic renamed to it), or None."""
    if domain not in set(Domain):
        return _BAD_DOMAIN
    return _name_reason(db, user=user, name=name, ignore_id=ignore_id)


def _name_reason(db: orm.Session, *, user: models.User, name: str, ignore_id: uuid.UUID | None) -> str | None:
    cleaned = user_topics.clean_name(name)
    if not cleaned:
        return _EMPTY_NAME
    if len(cleaned) > user_topics.MAX_TOPIC_NAME_LENGTH:
        return _LONG_NAME

    existing = user_topics.named_topic(db, user_id=user.id, name=cleaned)
    if existing is None or existing.id == ignore_id:
        return None
    return _NAME_REMOVED if existing.removed_at is not None else _NAME_TAKEN


def _chosen_topics_reason(db: orm.Session, *, user: models.User, chosen: list[_AddTopicPayload]) -> str | None:
    """The first reason any chosen topic can't be created, counting clashes among the chosen ones themselves."""
    seen: set[str] = set()
    for entry in chosen:
        reason = _new_topic_reason(db, user=user, domain=entry.domain, name=entry.name)
        if reason is not None:
            return reason
        if db.get(models.Topic, entry.id) is not None:
            return _ID_EXISTS

        key = topics.normalize_topic_name(entry.name)
        if key in seen:
            return _NAME_TAKEN
        seen.add(key)
    return None


def _sources_of(db: orm.Session, *, topic: models.Topic) -> list[models.Source]:
    return list(
        db.scalars(
            sqlalchemy.select(models.Source).where(
                models.Source.topic_id == topic.id, models.Source.deleted_at.is_(None)
            )
        )
    )
