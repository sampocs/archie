"""Make a card from an Ask answer: Haiku drafts it (owner's key, whitelisted only), the owner's edit is saved.

The draft call holds no transaction. A saved card is a `concept` card whose origin is the chat (`conversation_id`),
with `message_id` naming the answer; it starts new, as every new card does, and reaches the phone through pull.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import anthropic
import fastapi
import pydantic
import sqlalchemy
from archie_db import changes, models
from archie_llm import llm
from archie_shared import config, logging
from sqlalchemy import orm

from archie_api import deps
from archie_api.ask import card_prompts
from archie_api.sync import schemas

DRAFT_MAX_TOKENS = 1000

router = fastapi.APIRouter(prefix="/ask", tags=["ask"])
_logger = logging.get_logger(logging.LoggerName.API, "ask_cards")


class CardDraftView(pydantic.BaseModel):
    """A drafted card for the owner to edit."""

    question: str
    answer: str


class _Draft(pydantic.BaseModel):
    """The model's JSON."""

    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)


class CardIn(pydantic.BaseModel):
    """The card as the owner edited it."""

    message_id: uuid.UUID
    question: str = pydantic.Field(min_length=1, max_length=500)
    answer: str = pydantic.Field(min_length=1, max_length=2000)


@router.post("/messages/{message_id}/card-draft")
def card_draft(
    message_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> CardDraftView:
    """Draft one card from the answer with Haiku (Sonnet if Haiku gives no usable answer)."""
    if not user.is_whitelisted:
        raise fastapi.HTTPException(status_code=403, detail=deps.NEEDS_OWN_KEY)
    answer = _owned_answer(db, user=user, message_id=message_id)
    user_message = card_prompts.card_draft_message(question=_question_before(db, answer=answer), answer=answer.text)
    context = llm.CallContext(user_id=user.id, source_id=None, job_id=None, step=llm.CARD_DRAFT_STEP)
    api_key = config.Settings().require_anthropic_api_key()
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)

    # No transaction is held during the model call.
    db.commit()
    try:
        completion = llm.complete(
            engine,
            api_key=api_key,
            context=context,
            models=llm.CARD_DRAFT_MODELS,
            system=card_prompts.CARD_DRAFT_SYSTEM,
            user_message=user_message,
            max_tokens=DRAFT_MAX_TOKENS,
            json_schema=card_prompts.CARD_DRAFT_SCHEMA,
        )
        draft = _Draft.model_validate_json(completion.text)
    except (anthropic.APIError, llm.ModelOutputError, pydantic.ValidationError) as error:
        _logger.warning("Card draft failed: %r", error)
        raise fastapi.HTTPException(status_code=502, detail="draft failed") from error
    return CardDraftView(question=draft.question.strip(), answer=draft.answer.strip())


@router.post("/cards")
def create_card(
    body: CardIn,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.CardOut:
    """Save the owner's card; Review offers it at once."""
    question, answer_text = body.question.strip(), body.answer.strip()
    if not question or not answer_text:
        raise fastapi.HTTPException(status_code=422, detail="card is empty")

    changes.lock_user_writes(db, user.id)
    answer = _owned_answer(db, user=user, message_id=body.message_id)
    card = models.Card(
        id=uuid.uuid4(),
        user_id=user.id,
        conversation_id=answer.conversation_id,
        message_id=answer.id,
        kind=models.CardKind.CONCEPT.value,
        question=question,
        answer=answer_text,
        change_seq=changes.next_change_seq(),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return schemas.CardOut.model_validate(card)


def _owned_answer(db: orm.Session, *, user: models.User, message_id: uuid.UUID) -> models.Message:
    """The user's answer in a live chat, or 404."""
    message = db.get(models.Message, message_id)
    conversation = db.get(models.Conversation, message.conversation_id) if message is not None else None
    is_owned = (
        message is not None
        and conversation is not None
        and conversation.user_id == user.id
        and conversation.deleted_at is None
        and message.role == models.MessageRole.ASSISTANT
        and bool(message.text.strip())
    )
    if not is_owned:
        raise fastapi.HTTPException(status_code=404, detail="answer not found")
    assert message is not None
    return message


def _question_before(db: orm.Session, *, answer: models.Message) -> str | None:
    """The owner's question the answer replied to."""
    return db.scalar(
        sqlalchemy.select(models.Message.text)
        .where(
            models.Message.conversation_id == answer.conversation_id,
            models.Message.role == models.MessageRole.USER.value,
            models.Message.created_at <= answer.created_at,
        )
        .order_by(models.Message.created_at.desc(), models.Message.id.desc())
        .limit(1)
    )
