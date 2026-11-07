"""What a chat's model call is given besides the question: earlier messages, and the about item's details and boost."""

from __future__ import annotations

import datetime
import uuid
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy
from archie_db import models, pipeline, search, takes
from sqlalchemy import orm

HISTORY_MESSAGES = 20
ABOUT_PRIMER_CHARACTERS = 2000


@dataclass(frozen=True)
class HistoryMessage:
    """The parts of a stored message that history needs."""

    role: models.MessageRole
    text: str
    status: models.MessageStatus


def owner_zone(name: str | None) -> datetime.tzinfo:
    """The phone's IANA time zone, or UTC when it sent none or one this server doesn't know."""
    if not name:
        return datetime.UTC
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        # Outside input: an unknown or malformed name (ValueError, e.g. a path) only costs the owner's days.
        return datetime.UTC


def history(db: orm.Session, *, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    """The conversation's earlier finished exchanges as Messages API turns, oldest first."""
    stored = db.scalars(
        sqlalchemy.select(models.Message)
        .where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at, models.Message.id)
    ).all()
    return history_messages(
        [
            HistoryMessage(role=models.MessageRole(row.role), text=row.text, status=models.MessageStatus(row.status))
            for row in stored
        ]
    )


def history_messages(rows: Sequence[HistoryMessage]) -> list[dict[str, Any]]:
    """Question-answer pairs whose answer finished, as plain text (no citations), the last `HISTORY_MESSAGES` of them.

    A failed answer is dropped with its question, so the history always alternates and starts with a question.
    """
    turns: list[dict[str, Any]] = []
    for question, answer in zip(rows, rows[1:], strict=False):
        is_pair = question.role == models.MessageRole.USER and answer.role == models.MessageRole.ASSISTANT
        if is_pair and answer.status == models.MessageStatus.COMPLETE and answer.text.strip():
            turns += [{"role": "user", "content": question.text}, {"role": "assistant", "content": answer.text}]
    return turns[-HISTORY_MESSAGES:]


def about_text(db: orm.Session, *, conversation: models.Conversation) -> str | None:
    """The about item's title, summary and the owner's note, for the system prompt; None for a general chat."""
    if conversation.about_source_id is not None:
        return _source_text(db, source_id=conversation.about_source_id)
    if conversation.about_topic_primer_id is not None:
        primer = _current_primer(db, primer_id=conversation.about_topic_primer_id)
        if primer is None:
            return None
        topic = db.get_one(models.Topic, primer.topic_id)
        return f"Topic primer: {topic.name}\n\n{primer.content['markdown'][:ABOUT_PRIMER_CHARACTERS]}"
    if conversation.about_take_id is not None:
        take = db.get_one(models.Take, conversation.about_take_id)
        version = takes.current_version(db, take=take)
        body = (version.body or version.raw_body) if version is not None else ""
        return f"The owner's own {takes.KIND_NAMES[models.TakeKind(take.kind)]}: {take.title}\n\n{body}"
    return None


def boost(db: orm.Session, *, conversation: models.Conversation) -> search.ItemRef | None:
    """The item whose passages rank first; a topic primer is boosted as its topic's current version."""
    if conversation.about_source_id is not None:
        return search.ItemRef(kind=models.SearchItemKind.SOURCE, id=conversation.about_source_id)
    if conversation.about_take_id is not None:
        return search.ItemRef(kind=models.SearchItemKind.TAKE, id=conversation.about_take_id)
    if conversation.about_topic_primer_id is not None:
        primer = _current_primer(db, primer_id=conversation.about_topic_primer_id)
        return search.ItemRef(kind=models.SearchItemKind.TOPIC_PRIMER, id=primer.id) if primer else None
    return None


def _current_primer(db: orm.Session, *, primer_id: uuid.UUID) -> models.TopicPrimer | None:
    """The current version of the topic primer `primer_id` is a version of (the chat may predate a rewrite)."""
    started_with = db.get(models.TopicPrimer, primer_id)
    if started_with is None:
        return None
    return db.scalars(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == started_with.topic_id, models.TopicPrimer.is_current
        )
    ).one_or_none()


def _source_text(db: orm.Session, *, source_id: uuid.UUID) -> str:
    source = db.get_one(models.Source, source_id)
    lines = [f"{source.kind.capitalize()}: {source.title or source.url}"]
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    if summary is not None:
        content = summary.content["summary"]
        lines.append(f"Gist: {content['gist']}")
        lines += [f"- {item['idea']}" for item in content.get("key_ideas", [])]
    if source.note:
        lines.append(f"The owner's note: {source.note}")
    return "\n".join(lines)
