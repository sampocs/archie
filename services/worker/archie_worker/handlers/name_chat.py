"""`name_chat`: name a chat after its first complete answer, from its first question, answer, card sets and item.

A chat is created titled after its first question; this job replaces that title with a short name for the subject.
Both the name and the fallback (`name_from_fallback`, when the job fails for good) are written only while the chat
still has the title the job was queued with, so a name the owner gave first wins. A name is not activity: it gets a new
change position so phones pull it, but the chat's `updated_at` stays the time of its last question or answer.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, chat_names, models
from archie_llm import llm

from archie_worker import errors, keys, prompts

MAX_OUTPUT_TOKENS = 100
# Marks a fallback name taken from the item when the first answer proposed a card set: "Derivatives · cards".
CARDS_SUFFIX = " · cards"
# A chat has no error field, so this only shows in the job's `last_error`.
NO_USABLE_NAME = "The model gave no usable chat name."

_QUOTES = "\"'“”‘’`"


@dataclass(frozen=True)
class _NamingRun:
    """What the model call needs, copied out so no ORM object is held across it."""

    conversation_id: uuid.UUID
    user_id: int
    expected_title: str
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Ask Haiku for the chat's name and write it, unless the chat was renamed or deleted meanwhile."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.NAME_CHAT_MODELS,
        system=prompts.NAME_CHAT_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.NAME_CHAT_SCHEMA,
    )
    name = parse_name(json.loads(completion.text))

    # The owner may have renamed or deleted the chat during the call; the lock makes what we read final.
    changes.lock_user_writes(db, run.user_id)
    conversation = db.get(models.Conversation, run.conversation_id)
    if conversation is None:
        return
    db.refresh(conversation)
    _rename_if_unchanged(conversation, expected_title=run.expected_title, title=name)


def parse_name(raw: Mapping[str, Any]) -> str:
    """The model's name with whitespace collapsed and stray quotes or a trailing period removed.

    Raises `PermanentJobError` for an empty or over-long name, so the chat gets its fallback name at once: asking
    again with the same input would only give the same kind of answer.
    """
    name = " ".join(str(raw["name"]).split()).strip(_QUOTES).rstrip(".").strip()
    if not name or len(name) > models.CONVERSATION_TITLE_LENGTH:
        raise errors.PermanentJobError(NO_USABLE_NAME)
    return name


def name_from_fallback(db: sqlalchemy.orm.Session, job: models.Job, reason: str) -> None:
    """Failure hook: name a chat about an item after the item; a general chat keeps its first question."""
    conversation = db.get(models.Conversation, uuid.UUID(job.payload[chat_names.CONVERSATION_ID_KEY]))
    if conversation is None:
        return

    changes.lock_user_writes(db, conversation.user_id)
    db.refresh(conversation)
    title = fallback_title(db, conversation=conversation)
    if title is None:
        return
    _rename_if_unchanged(conversation, expected_title=job.payload[chat_names.EXPECTED_TITLE_KEY], title=title)


def fallback_title(db: sqlalchemy.orm.Session, *, conversation: models.Conversation) -> str | None:
    """The item's title, with `CARDS_SUFFIX` when the first answer proposed a card set; None for a general chat."""
    item_title = _about_title(db, conversation=conversation)
    if item_title is None:
        return None

    answer = chat_names.first_complete_answer(db, conversation_id=conversation.id)
    if answer is None or not _card_set_titles(db, message_id=answer.id):
        return item_title[: models.CONVERSATION_TITLE_LENGTH].rstrip()
    return item_title[: models.CONVERSATION_TITLE_LENGTH - len(CARDS_SUFFIX)].rstrip() + CARDS_SUFFIX


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _NamingRun | None:
    """Read the chat's first exchange and item, then commit; None when the chat is gone, renamed or has no answer."""
    expected_title = str(job.payload[chat_names.EXPECTED_TITLE_KEY])
    conversation = db.get(models.Conversation, uuid.UUID(job.payload[chat_names.CONVERSATION_ID_KEY]))
    if conversation is None or conversation.deleted_at is not None or conversation.title != expected_title:
        return None
    question = chat_names.first_question(db, conversation_id=conversation.id)
    answer = chat_names.first_complete_answer(db, conversation_id=conversation.id)
    if question is None or answer is None:
        return None

    # Checked before the model call so a user without a key fails at once (PermanentJobError, then the fallback).
    api_key = keys.anthropic_key_for(db.get_one(models.User, conversation.user_id))
    run = _NamingRun(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        expected_title=expected_title,
        context=llm.CallContext(
            user_id=conversation.user_id, source_id=None, job_id=job.id, step=models.JobKind.NAME_CHAT
        ),
        api_key=api_key,
        user_message=prompts.name_chat_message(
            question=question,
            about_title=_about_title(db, conversation=conversation),
            card_set_titles=_card_set_titles(db, message_id=answer.id),
            answer=answer.text,
        ),
    )
    db.commit()
    return run


def _rename_if_unchanged(conversation: models.Conversation, *, expected_title: str, title: str) -> None:
    """Write `title` only while the chat is live and still titled `expected_title`; the caller holds the lock."""
    if conversation.deleted_at is not None or conversation.title != expected_title or title == expected_title:
        return

    conversation.title = title
    changes.bump(conversation)


def _about_title(db: sqlalchemy.orm.Session, *, conversation: models.Conversation) -> str | None:
    """The title of the item the chat is about (a topic primer by its topic's name); None for a general chat."""
    if conversation.about_source_id is not None:
        source = db.get(models.Source, conversation.about_source_id)
        return (source.title or source.url) if source is not None else None
    if conversation.about_take_id is not None:
        take = db.get(models.Take, conversation.about_take_id)
        return take.title if take is not None else None
    if conversation.about_topic_primer_id is not None:
        primer = db.get(models.TopicPrimer, conversation.about_topic_primer_id)
        topic = db.get(models.Topic, primer.topic_id) if primer is not None else None
        return topic.name if topic is not None else None
    return None


def _card_set_titles(db: sqlalchemy.orm.Session, *, message_id: uuid.UUID) -> list[str]:
    return list(
        db.scalars(
            sqlalchemy.select(models.CardSetProposal.title)
            .where(models.CardSetProposal.message_id == message_id)
            .order_by(models.CardSetProposal.created_at)
        )
    )
