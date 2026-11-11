"""Queueing `name_chat`: a chat is named once, after its first complete answer, by a worker job.

A chat is created titled after its first question (`creation_title`). The job carries that title so its write (and the
fallback's) lands only while the chat still has it: a name the owner gave first is never replaced.
"""

from __future__ import annotations

import uuid

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, jobs, models

# A `name_chat` job's payload keys: the chat to name, and the title the name may replace.
CONVERSATION_ID_KEY = "conversation_id"
EXPECTED_TITLE_KEY = "expected_title"


def creation_title(question: str) -> str:
    """The title a chat is created with: its first question, cut to `CONVERSATION_TITLE_LENGTH`."""
    return question[: models.CONVERSATION_TITLE_LENGTH]


def enqueue_if_first_complete_answer(db: sqlalchemy.orm.Session, *, conversation_id: uuid.UUID, user_id: int) -> bool:
    """Queue `name_chat` when the chat holds exactly one complete answer (the one just added); returns whether it did.

    The caller holds the user's write lock and has flushed the answer, so two answers can't both count as first.
    """
    if _complete_answer_count(db, conversation_id=conversation_id) != 1:
        return False

    question = first_question(db, conversation_id=conversation_id)
    if question is None:
        return False
    enqueue_name_chat(db, conversation_id=conversation_id, user_id=user_id, expected_title=creation_title(question))
    return True


def enqueue_name_chat(
    db: sqlalchemy.orm.Session, *, conversation_id: uuid.UUID, user_id: int, expected_title: str
) -> models.Job:
    """Queue one `name_chat` job in the caller's transaction."""
    return jobs.enqueue(
        db,
        kind=models.JobKind.NAME_CHAT,
        user_id=user_id,
        payload={CONVERSATION_ID_KEY: str(conversation_id), EXPECTED_TITLE_KEY: expected_title},
    )


def first_question(db: sqlalchemy.orm.Session, *, conversation_id: uuid.UUID) -> str | None:
    """The chat's first question, which its title was made from; None for a chat without one."""
    return db.scalar(
        sqlalchemy.select(models.Message.text)
        .where(models.Message.conversation_id == conversation_id, models.Message.role == models.MessageRole.USER.value)
        .order_by(models.Message.created_at, models.Message.id)
        .limit(1)
    )


def first_complete_answer(db: sqlalchemy.orm.Session, *, conversation_id: uuid.UUID) -> models.Message | None:
    """The chat's first answer that finished; a failed answer never names a chat."""
    return db.scalar(
        sqlalchemy.select(models.Message)
        .where(*_complete_answers(conversation_id=conversation_id))
        .order_by(models.Message.created_at, models.Message.id)
        .limit(1)
    )


def backfill_all(db: sqlalchemy.orm.Session) -> int:
    """Queue `name_chat` for every live chat with a complete answer; returns how many were queued.

    Commits once per user, so each user's write lock is held only while that user's chats are queued.
    """
    has_complete_answer = sqlalchemy.exists().where(*_complete_answers(conversation_id=models.Conversation.id))
    chats = db.execute(
        sqlalchemy.select(models.Conversation.id, models.Conversation.user_id)
        .where(models.Conversation.deleted_at.is_(None), has_complete_answer)
        .order_by(models.Conversation.user_id)
    ).all()

    chats_by_user: dict[int, list[uuid.UUID]] = {}
    for conversation_id, user_id in chats:
        chats_by_user.setdefault(user_id, []).append(conversation_id)

    queued = 0
    for user_id, conversation_ids in chats_by_user.items():
        changes.lock_user_writes(db, user_id)
        for conversation_id in conversation_ids:
            question = first_question(db, conversation_id=conversation_id)
            if question is None:
                continue
            enqueue_name_chat(
                db, conversation_id=conversation_id, user_id=user_id, expected_title=creation_title(question)
            )
            queued += 1
        db.commit()
    return queued


def _complete_answers(
    *, conversation_id: uuid.UUID | sqlalchemy.orm.InstrumentedAttribute[uuid.UUID]
) -> tuple[sqlalchemy.ColumnElement[bool], ...]:
    return (
        models.Message.conversation_id == conversation_id,
        models.Message.role == models.MessageRole.ASSISTANT.value,
        models.Message.status == models.MessageStatus.COMPLETE.value,
    )


def _complete_answer_count(db: sqlalchemy.orm.Session, *, conversation_id: uuid.UUID) -> int:
    return (
        db.scalar(sqlalchemy.select(sqlalchemy.func.count()).where(*_complete_answers(conversation_id=conversation_id)))
        or 0
    )
