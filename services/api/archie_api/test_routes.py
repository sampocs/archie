"""Routes that exist only outside production, so e2e tests and local dev can sign in without Apple."""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any

import fastapi
import pydantic
import sqlalchemy
from archie_db import changes, models, pipeline, user_topics
from sqlalchemy import orm

from archie_api import deps
from archie_api.ask import card_routes, card_set_tools, citations
from archie_api.auth import sessions
from archie_api.sync import conversation_actions, schemas

router = fastapi.APIRouter(prefix="/test", tags=["test"])

# The message the phone's Make cards button sends.
MAKE_CARDS_MESSAGE = "Make cards"


class TestSessionRequest(pydantic.BaseModel):
    """Who to sign in as; the user is created on first use."""

    __test__ = False

    apple_sub: str = "test-user"
    email: str | None = None
    is_whitelisted: bool = False
    seed_topics: bool = False


class TestSessionView(pydantic.BaseModel):
    """The raw session key for the signed-in test user."""

    __test__ = False

    session_key: str


@router.post("/session")
def create_test_session(
    request: TestSessionRequest, db: Annotated[orm.Session, fastapi.Depends(deps.get_db)]
) -> TestSessionView:
    """Upsert the user by `apple_sub` (optionally whitelisted) and start a session for them."""
    user = db.scalars(sqlalchemy.select(models.User).where(models.User.apple_sub == request.apple_sub)).first()
    if user is None:
        user = models.User(apple_sub=request.apple_sub, email=request.email)
        db.add(user)
        db.flush()

    # Whitelisting normally follows OWNER_EMAILS at Apple sign-in; tests that need the owner's keys ask for it.
    if request.is_whitelisted:
        user.is_whitelisted = True

    if request.seed_topics:
        changes.lock_user_writes(db, user.id)
        user_topics.seed_owner_topics(db, user=user)

    session_key = sessions.create_session(db, user_id=user.id)
    db.commit()
    return TestSessionView(session_key=session_key)


class SeedWriteUpRequest(pydantic.BaseModel):
    """A ready-made write-up for a note, so Maestro needs no model."""

    __test__ = False

    domain: str
    summary: dict[str, Any]
    sources: list[dict[str, str]] = pydantic.Field(default_factory=list)


@router.post("/notes/{source_id}/write-up", status_code=fastapi.status.HTTP_204_NO_CONTENT)
def seed_note_write_up(
    source_id: uuid.UUID, request: SeedWriteUpRequest, db: Annotated[orm.Session, fastapi.Depends(deps.get_db)]
) -> None:
    """Store `summary` as the note's current write-up, file it under `domain`, and mark it ready."""
    source = db.get(models.Source, source_id)
    if source is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)
    changes.lock_user_writes(db, source.user_id)

    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.SUMMARY,
        content={
            "summary": request.summary,
            "domain": request.domain,
            "topic": "",
            "tags": [],
            "concepts": [],
            "is_educational": True,
            "cards": [],
            "sources": request.sources,
        },
        model=None,
        prompt_version="test-seed",
    )
    source.domain = request.domain
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.READY)
    db.commit()


class SeedCardSetRequest(card_set_tools.CardSetIn):
    """A ready-made card set for a chat, so Maestro needs no model; without `conversation_id` (or with an unknown one)
    a chat with one exchange about `title` is made first."""

    __test__ = False

    conversation_id: uuid.UUID | None = None


@router.post("/card-sets")
def seed_card_set(
    request: SeedCardSetRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.CardSetProposalOut:
    """Add a `Make cards` question and an answer carrying the card set to the chat, as a real answer would."""
    changes.lock_user_writes(db, user.id)
    conversation = _seed_conversation(db, user=user, request=request)

    _seed_message(db, user=user, conversation=conversation, role=models.MessageRole.USER, text=MAKE_CARDS_MESSAGE)
    answer = _seed_message(
        db, user=user, conversation=conversation, role=models.MessageRole.ASSISTANT,
        text=f"Here are cards on {request.title}.",
    )  # fmt: skip
    proposal = card_set_tools.add_proposal(
        db,
        user_id=user.id,
        conversation_id=conversation.id,
        message_id=answer.id,
        proposal_id=uuid.uuid4(),
        card_set=request,
        created_at=datetime.datetime.now(tz=datetime.UTC),
    )
    conversation_actions.touch_conversation(conversation)

    db.commit()
    db.refresh(proposal)
    return schemas.CardSetProposalOut.model_validate(proposal)


def _seed_conversation(db: orm.Session, *, user: models.User, request: SeedCardSetRequest) -> models.Conversation:
    """The user's live chat `conversation_id`, or a new one (with that id when given) holding one exchange."""
    if request.conversation_id is not None and db.get(models.Conversation, request.conversation_id) is not None:
        existing = conversation_actions.owned_conversation(db, user=user, conversation_id=request.conversation_id)
        if existing is None:
            raise fastapi.HTTPException(status_code=404, detail=conversation_actions.NO_CONVERSATION)
        return existing

    question = f"What should I know about {request.title}?"
    conversation = models.Conversation(
        id=request.conversation_id or uuid.uuid4(),
        user_id=user.id,
        title=question[: models.CONVERSATION_TITLE_LENGTH],
        change_seq=changes.next_change_seq(),
    )
    db.add(conversation)
    db.flush()
    _seed_message(db, user=user, conversation=conversation, role=models.MessageRole.USER, text=question)
    _seed_message(
        db, user=user, conversation=conversation, role=models.MessageRole.ASSISTANT,
        text=card_routes.gist_of(request.cheat_sheet, title=request.title),
    )  # fmt: skip
    return conversation


def _seed_message(
    db: orm.Session, *, user: models.User, conversation: models.Conversation, role: models.MessageRole, text: str
) -> models.Message:
    message = models.Message(
        id=uuid.uuid4(),
        user_id=user.id,
        conversation_id=conversation.id,
        role=role.value,
        text=text,
        segments=None if role == models.MessageRole.USER else [_background_segment(text)],
        web_search=False,
        status=models.MessageStatus.COMPLETE.value,
        # now() is the transaction's start, so messages added together would tie; they must keep their order.
        created_at=sqlalchemy.func.clock_timestamp(),
        change_seq=changes.next_change_seq(),
    )
    db.add(message)
    db.flush()
    return message


def _background_segment(text: str) -> dict[str, Any]:
    return citations.Segment(label=citations.AnswerLabel.BACKGROUND, text=text, citations=[]).to_wire()
