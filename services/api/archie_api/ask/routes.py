"""`POST /ask/conversations/{id}/messages`: ask a question in a chat and stream the answer as server-sent events.

The first question creates the chat (its title is the question, cut to 60 characters; `about` ties it to an item).
The question is stored before the stream starts. Only whitelisted users may ask: answers spend the owner's keys.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import fastapi
import fastapi.responses
import pydantic
import sqlalchemy
from archie_db import changes, models
from archie_shared import config
from sqlalchemy import orm

from archie_api import deps
from archie_api.ask import answer, context, prompts
from archie_api.sync import conversation_actions

MAX_QUESTION_LENGTH = 4000

router = fastapi.APIRouter(prefix="/ask", tags=["ask"])


class AboutIn(pydantic.BaseModel):
    """The item a new chat is about."""

    kind: models.SearchItemKind
    id: uuid.UUID


class AskRequest(pydantic.BaseModel):
    """A question; the phone makes its id so the question it shows is the one the server stores."""

    user_message_id: uuid.UUID
    text: str = pydantic.Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    web_search: bool = False
    about: AboutIn | None = None


@router.post("/conversations/{conversation_id}/messages")
def ask(
    conversation_id: uuid.UUID,
    body: AskRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> fastapi.responses.StreamingResponse:
    """Store the question, then stream the answer (`delta`, `block`, `searching`, then `done` or `error`)."""
    question = " ".join(body.text.split())
    if not question:
        raise fastapi.HTTPException(status_code=422, detail="question is empty")
    if not user.is_whitelisted:
        raise fastapi.HTTPException(status_code=403, detail=deps.NEEDS_OWN_KEY)
    settings = config.Settings()
    if not settings.anthropic_api_key:
        raise fastapi.HTTPException(status_code=503, detail="Ask isn't set up")

    changes.lock_user_writes(db, user.id)
    if db.get(models.Message, body.user_message_id) is not None:
        raise fastapi.HTTPException(status_code=409, detail="message id already used")
    conversation = _conversation(db, user=user, conversation_id=conversation_id, question=question, about=body.about)
    request = answer.AnswerRequest(
        user_id=user.id,
        conversation_id=conversation.id,
        user_message_id=body.user_message_id,
        web_search=body.web_search,
        system=prompts.system_prompt(
            about=context.about_text(db, conversation=conversation), web_required=body.web_search
        ),
        # Read before the question is added, so the history holds only earlier exchanges.
        messages=[*context.history(db, conversation_id=conversation.id), {"role": "user", "content": question}],
        boost=context.boost(db, conversation=conversation),
        anthropic_key=settings.anthropic_api_key,
        openai_key=settings.openai_api_key or None,
    )

    db.add(
        models.Message(
            id=body.user_message_id,
            user_id=user.id,
            conversation_id=conversation.id,
            role=models.MessageRole.USER.value,
            text=question,
            segments=None,
            web_search=body.web_search,
            status=models.MessageStatus.COMPLETE.value,
            change_seq=changes.next_change_seq(),
        )
    )
    conversation_actions.touch_conversation(conversation)
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)

    # Committed before streaming: the stream holds no transaction and saves the answer in its own session.
    db.commit()
    return fastapi.responses.StreamingResponse(
        answer.stream_async(engine, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _conversation(
    db: orm.Session, *, user: models.User, conversation_id: uuid.UUID, question: str, about: AboutIn | None
) -> models.Conversation:
    """The user's live chat, or a new one with this id; another user's or a deleted chat is a 404."""
    existing = db.get(models.Conversation, conversation_id)
    if existing is not None:
        if conversation_actions.owned_conversation(db, user=user, conversation_id=conversation_id) is None:
            raise fastapi.HTTPException(status_code=404, detail=conversation_actions.NO_CONVERSATION)
        return existing

    conversation = models.Conversation(
        id=conversation_id,
        user_id=user.id,
        title=question[: models.CONVERSATION_TITLE_LENGTH],
        change_seq=changes.next_change_seq(),
    )
    if about is not None:
        _set_about(db, user=user, conversation=conversation, about=about)
    db.add(conversation)
    db.flush()
    return conversation


def _set_about(db: orm.Session, *, user: models.User, conversation: models.Conversation, about: AboutIn) -> None:
    """Tie the new chat to the user's live item, or 404."""
    if about.kind == models.SearchItemKind.SOURCE:
        source = db.get(models.Source, about.id)
        live = source is not None and source.user_id == user.id and source.deleted_at is None
        conversation.about_source_id = about.id
    elif about.kind == models.SearchItemKind.TOPIC_PRIMER:
        primer = db.get(models.TopicPrimer, about.id)
        topic = db.get(models.Topic, primer.topic_id) if primer is not None else None
        live = (
            primer is not None
            and primer.user_id == user.id
            and topic is not None
            and topic.removed_at is None
            and topic.merged_into_id is None
        )
        conversation.about_topic_primer_id = about.id
    else:
        take = db.get(models.Take, about.id)
        live = take is not None and take.user_id == user.id and take.deleted_at is None
        conversation.about_take_id = about.id
    if not live:
        raise fastapi.HTTPException(status_code=404, detail="about item not found")
    conversation.about_kind = about.kind.value
