"""Topic primer versions, shared by the worker (Archie writes them) and the API (Ask edits and restores).

Each version is its own row and exactly one per topic is current. Every function that writes expects the caller to
hold `changes.lock_user_writes` for the topic's user.
"""

from __future__ import annotations

import uuid

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, models


def current(db: sqlalchemy.orm.Session, *, topic_id: uuid.UUID) -> models.TopicPrimer | None:
    """The topic's current primer version, or None when it has none."""
    return db.scalars(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == topic_id, models.TopicPrimer.is_current
        )
    ).one_or_none()


def at_version(db: sqlalchemy.orm.Session, *, topic_id: uuid.UUID, version: int) -> models.TopicPrimer | None:
    """The topic's primer version numbered `version`, or None."""
    return db.scalar(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == topic_id, models.TopicPrimer.version == version
        )
    )


def write(
    db: sqlalchemy.orm.Session,
    *,
    topic: models.Topic,
    markdown: str,
    model: str | None,
    prompt_version: str | None,
    origin: models.VersionOrigin = models.VersionOrigin.ARCHIE,
    derived_from_id: uuid.UUID | None = None,
    instruction: str | None = None,
) -> models.TopicPrimer:
    """Add the next version as current; the previous current one stays, no longer current.

    The read state (opened, snoozed) carries over, so an edit doesn't make the primer look unread again.
    """
    previous = current(db, topic_id=topic.id)
    if previous is not None:
        # Flushed first so the partial unique index never sees two current rows.
        previous.is_current = False
        previous.change_seq = changes.next_change_seq()
        db.flush()

    latest_version = db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(models.TopicPrimer.version)).where(
            models.TopicPrimer.topic_id == topic.id
        )
    )
    primer = models.TopicPrimer(
        id=uuid.uuid4(),
        user_id=topic.user_id,
        topic_id=topic.id,
        version=(latest_version or 0) + 1,
        is_current=True,
        content={"markdown": markdown},
        model=model,
        prompt_version=prompt_version,
        origin=origin.value,
        derived_from_id=derived_from_id,
        instruction=instruction,
        opened_at=previous.opened_at if previous is not None else None,
        snoozed_until=previous.snoozed_until if previous is not None else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(primer)
    db.flush()
    return primer
