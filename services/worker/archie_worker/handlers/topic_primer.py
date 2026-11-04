"""`topic_primer`: write the general background for one of the user's topics, as markdown.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
A removed or merged topic, or one that already has a primer, gets nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, user_topics

from archie_worker import llm, prompts

MAX_OUTPUT_TOKENS = 6000
MAX_SOURCE_TITLES = 30


@dataclass(frozen=True)
class _PrimerRun:
    """What the model call needs, copied out of the session."""

    topic_id: uuid.UUID
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the topic's primer with the primer models and store it as its current version."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.PRIMER_MODELS,
        system=prompts.TOPIC_PRIMER_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
    )

    changes.lock_user_writes(db, run.user_id)
    topic = db.get_one(models.Topic, run.topic_id)
    db.refresh(topic)
    if topic.removed_at is not None or topic.merged_into_id is not None:
        return

    write_topic_primer(db, topic=topic, markdown=completion.text, model=completion.model)


def write_topic_primer(
    db: sqlalchemy.orm.Session, *, topic: models.Topic, markdown: str, model: str
) -> models.TopicPrimer:
    """Add the next version as current; the previous current one stays, no longer current. Caller holds the lock."""
    previous = db.scalars(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == topic.id, models.TopicPrimer.is_current
        )
    ).one_or_none()
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
        prompt_version=prompts.TOPIC_PRIMER_PROMPT_VERSION,
        change_seq=changes.next_change_seq(),
    )
    db.add(primer)
    db.flush()
    return primer


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _PrimerRun | None:
    """Read what the model call needs and commit; None when the topic is gone, removed, merged or has a primer."""
    topic = db.get(models.Topic, uuid.UUID(job.payload[user_topics.TOPIC_ID_KEY]))
    if topic is None or topic.removed_at is not None or topic.merged_into_id is not None:
        return None

    has_current_primer = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(models.TopicPrimer.topic_id == topic.id, models.TopicPrimer.is_current)
        )
    )
    if has_current_primer:
        return None

    api_key = llm.api_key_for(db.get_one(models.User, topic.user_id))

    titles = db.scalars(
        sqlalchemy.select(models.Source.title)
        .where(
            models.Source.topic_id == topic.id,
            models.Source.deleted_at.is_(None),
            models.Source.title.is_not(None),
        )
        .order_by(models.Source.created_at.desc())
        .limit(MAX_SOURCE_TITLES)
    ).all()

    run = _PrimerRun(
        topic_id=topic.id,
        user_id=topic.user_id,
        context=llm.CallContext(user_id=topic.user_id, source_id=None, job_id=job.id, step=models.JobKind.TOPIC_PRIMER),
        api_key=api_key,
        user_message=prompts.topic_primer_message(domain=topic.domain, topic=topic.name, source_titles=list(titles)),
    )
    db.commit()
    return run
