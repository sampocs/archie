"""`topic_primer`: write the general background for one of the user's topics, as markdown, plus its foundation cards.

The foundation cards belong to the primer version they came with; a newer version retires those of older ones.
Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
A removed or merged topic, or one that already has a primer, gets nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, jobs, models, topic_primers, user_topics
from archie_llm import llm

from archie_worker import keys, prompts

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
    output = prompts.split_primer_output(completion.text)

    changes.lock_user_writes(db, run.user_id)
    topic = db.get_one(models.Topic, run.topic_id)
    db.refresh(topic)
    if topic.removed_at is not None or topic.merged_into_id is not None:
        return

    primer = topic_primers.write(
        db,
        topic=topic,
        markdown=output.markdown,
        model=completion.model,
        prompt_version=prompts.TOPIC_PRIMER_PROMPT_VERSION,
    )
    jobs.enqueue_embed(db, user_id=topic.user_id, item_kind=models.SearchItemKind.TOPIC_PRIMER, item_id=primer.id)
    _replace_foundation_cards(db, topic=topic, primer=primer, cards=output.foundation_cards)


def _replace_foundation_cards(
    db: sqlalchemy.orm.Session,
    *,
    topic: models.Topic,
    primer: models.TopicPrimer,
    cards: list[prompts.FoundationCard],
) -> None:
    """Retire the foundation cards of the topic's older primer versions and add the new version's."""
    previous_primer_ids = sqlalchemy.select(models.TopicPrimer.id).where(
        models.TopicPrimer.topic_id == topic.id, models.TopicPrimer.id != primer.id
    )
    card_rows.retire_cards(db, models.Card.topic_primer_id.in_(previous_primer_ids))

    for card in cards:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=topic.user_id,
                topic_primer_id=primer.id,
                kind=models.CardKind.FOUNDATION.value,
                question=card.question,
                answer=card.answer,
                detail=card_rows.joined_detail(card.detail),
                change_seq=changes.next_change_seq(),
            )
        )


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _PrimerRun | None:
    """Read what the model call needs and commit; None when the topic is gone, removed, merged or has a primer."""
    topic = db.get(models.Topic, uuid.UUID(job.payload[user_topics.TOPIC_ID_KEY]))
    if topic is None or topic.removed_at is not None or topic.merged_into_id is not None:
        return None

    if topic_primers.current(db, topic_id=topic.id) is not None:
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, topic.user_id))

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

    # The primer writes foundation cards, so the model hears what the user said about earlier cards.
    topic_message = prompts.topic_primer_message(
        domain=topic.domain, topic=topic.name, source_titles=[title for title in titles if title]
    )
    preferences = prompts.preferences_block(card_rows.recent_preferences(db, user_id=topic.user_id))
    run = _PrimerRun(
        topic_id=topic.id,
        user_id=topic.user_id,
        context=llm.CallContext(user_id=topic.user_id, source_id=None, job_id=job.id, step=models.JobKind.TOPIC_PRIMER),
        api_key=api_key,
        user_message=topic_message + preferences,
    )
    db.commit()
    return run
