"""Push actions on saved Ask chats: renaming and deleting one; chats themselves are written by the ask route."""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import changes, models
from sqlalchemy import orm

from archie_api.sync import rows

NO_CONVERSATION = "conversation not found"


class _DeleteConversationPayload(pydantic.BaseModel):
    id: uuid.UUID


class _RenameConversationPayload(pydantic.BaseModel):
    id: uuid.UUID
    title: str


def touch_conversation(conversation: models.Conversation) -> None:
    """Mark a changed chat so phones pull it again. Call only after `lock_user_writes` in the same transaction."""
    changes.touch(conversation)


def owned_conversation(db: orm.Session, *, user: models.User, conversation_id: uuid.UUID) -> models.Conversation | None:
    """The user's live chat with this id, or None (unknown, another user's, or deleted)."""
    conversation = db.get(models.Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id or conversation.deleted_at is not None:
        return None
    return conversation


def delete_conversation(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Soft-delete a chat; its messages stay (hidden through it) and cards made from it stay in Review."""
    parsed = rows.parse(_DeleteConversationPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    conversation = owned_conversation(db, user=user, conversation_id=parsed.id)
    if conversation is None:
        return NO_CONVERSATION

    conversation.deleted_at = sqlalchemy.func.now()
    touch_conversation(conversation)
    return None


def rename_conversation(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Give a chat the owner's name: trimmed, cut to `CONVERSATION_TITLE_LENGTH`; a blank name is malformed."""
    parsed = rows.parse(_RenameConversationPayload, payload)
    if parsed is None or not parsed.title.strip():
        return rows.MALFORMED
    conversation = owned_conversation(db, user=user, conversation_id=parsed.id)
    if conversation is None:
        return NO_CONVERSATION

    conversation.title = parsed.title.strip()[: models.CONVERSATION_TITLE_LENGTH]
    touch_conversation(conversation)
    return None
