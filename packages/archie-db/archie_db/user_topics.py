"""A user's topics: lookups and writes shared by the API's actions and the worker's filing.

Every function that writes expects the caller to hold `changes.lock_user_writes` for the user.
"""

from __future__ import annotations

import uuid

import sqlalchemy
import sqlalchemy.orm
from archie_shared import topics
from archie_shared.domains import Domain

from archie_db import changes, jobs, models, pipeline

# The job payload key naming the topic a `topic_primer` job writes for.
TOPIC_ID_KEY = "topic_id"
MAX_TOPIC_NAME_LENGTH = 80


def clean_name(name: str) -> str:
    """The name as stored: whitespace runs collapsed, ends trimmed."""
    return " ".join(name.split())


def named_topic(db: sqlalchemy.orm.Session, *, user_id: int, name: str) -> models.Topic | None:
    """The user's live or removed topic whose name normalizes like `name`; merged topics never match."""
    wanted = topics.normalize_topic_name(name)
    candidates = db.scalars(
        sqlalchemy.select(models.Topic).where(models.Topic.user_id == user_id, models.Topic.merged_into_id.is_(None))
    )
    return next((topic for topic in candidates if topics.normalize_topic_name(topic.name) == wanted), None)


def create_topic(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    domain: Domain,
    name: str,
    origin: models.TopicOrigin,
    topic_id: uuid.UUID | None = None,
    removed: bool = False,
) -> models.Topic:
    """Insert a topic (a removed one when `removed`); the phone supplies the id for topics the user adds."""
    topic = models.Topic(
        id=topic_id or uuid.uuid4(),
        user_id=user_id,
        domain=domain.value,
        name=clean_name(name),
        origin=origin.value,
        removed_at=sqlalchemy.func.now() if removed else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(topic)
    db.flush()
    return topic


def seed_owner_topics(db: sqlalchemy.orm.Session, *, user: models.User) -> None:
    """Give the owner their picks as live starter topics and the other starter topics as removed; mark them chosen.

    A no-op once the user has any topic, so it is safe on every sign-in and `/me`.
    """
    has_topics = db.scalar(sqlalchemy.select(sqlalchemy.exists().where(models.Topic.user_id == user.id)))
    if has_topics:
        return

    for domain, names in topics.OWNER_TOPICS.items():
        for name in names:
            create_topic(db, user_id=user.id, domain=domain, name=name, origin=models.TopicOrigin.STARTER)
    for domain, names in topics.STARTER_EXTRAS.items():
        for name in names:
            create_topic(db, user_id=user.id, domain=domain, name=name, origin=models.TopicOrigin.STARTER, removed=True)
    user.topics_chosen_at = sqlalchemy.func.now()
    db.flush()


def live_topics(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Topic]:
    """The user's topics that are neither removed nor merged, by domain then name."""
    return list(
        db.scalars(
            sqlalchemy.select(models.Topic)
            .where(
                models.Topic.user_id == user_id,
                models.Topic.removed_at.is_(None),
                models.Topic.merged_into_id.is_(None),
            )
            .order_by(models.Topic.domain, models.Topic.name)
        )
    )


def removed_topics(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Topic]:
    """The user's removed (blocked) topics that weren't merged away."""
    return list(
        db.scalars(
            sqlalchemy.select(models.Topic).where(
                models.Topic.user_id == user_id,
                models.Topic.removed_at.is_not(None),
                models.Topic.merged_into_id.is_(None),
            )
        )
    )


def analyzed_sources(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Source]:
    """The user's live sources that have a current summary, which is what filing reads."""
    return list(
        db.scalars(
            sqlalchemy.select(models.Source)
            .join(
                models.SourceArtifact,
                sqlalchemy.and_(
                    models.SourceArtifact.source_id == models.Source.id,
                    models.SourceArtifact.kind == models.ArtifactKind.SUMMARY.value,
                    models.SourceArtifact.is_current,
                ),
            )
            .where(models.Source.user_id == user_id, models.Source.deleted_at.is_(None))
            .order_by(models.Source.created_at)
        )
    )


def enqueue_file_topic(db: sqlalchemy.orm.Session, *, source: models.Source) -> None:
    """Queue filing for one source in the caller's transaction."""
    jobs.enqueue(
        db, kind=models.JobKind.FILE_TOPIC, user_id=source.user_id, payload={pipeline.SOURCE_ID_KEY: str(source.id)}
    )


def enqueue_topic_primer(db: sqlalchemy.orm.Session, *, topic: models.Topic) -> None:
    """Queue a topic primer for one topic in the caller's transaction."""
    jobs.enqueue(db, kind=models.JobKind.TOPIC_PRIMER, user_id=topic.user_id, payload={TOPIC_ID_KEY: str(topic.id)})
