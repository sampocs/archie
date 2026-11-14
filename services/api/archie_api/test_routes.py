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
from archie_api.ask import card_routes, card_set_tools, citations, context
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


# What the failed job's error says: invented, so Maestro can look for it and it can't be mistaken for a real failure.
SEEDED_JOB_ERROR = "Seeded failure for the problems banner\nsecond line that is never shown"


@router.post("/failed-job", status_code=fastapi.status.HTTP_204_NO_CONTENT)
def seed_failed_job(
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> None:
    """Give the signed-in user a failed `analyze` job, so the problems banner has something to show."""
    db.add(
        models.Job(
            kind=models.JobKind.ANALYZE.value,
            payload={},
            user_id=user.id,
            status=models.JobStatus.FAILED.value,
            last_error=SEEDED_JOB_ERROR,
        )
    )
    db.commit()


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
    a chat with one exchange about `title` is made first, about the note `about_note_id` when given."""

    __test__ = False

    conversation_id: uuid.UUID | None = None
    about_note_id: uuid.UUID | None = None

    @pydantic.field_validator("cheat_sheet")
    @classmethod
    def _cheat_sheet(cls, text: str, info: pydantic.ValidationInfo) -> str:
        # Replaces the tool's check: whether it may be empty depends on the chat, which the route checks.
        return text.strip()


@router.post("/card-sets")
def seed_card_set(
    request: SeedCardSetRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.CardSetProposalOut:
    """Add a `Make cards` question and an answer carrying the card set to the chat, as a real answer would."""
    changes.lock_user_writes(db, user.id)
    conversation = _seed_conversation(db, user=user, request=request)
    if not request.cheat_sheet and context.note_title(db, conversation=conversation) is None:
        raise fastapi.HTTPException(status_code=422, detail="cheat_sheet: must not be blank outside a note's chat")

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
        about_source_id=_seed_note_id(db, user=user, note_id=request.about_note_id),
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


def _seed_note_id(db: orm.Session, *, user: models.User, note_id: uuid.UUID | None) -> uuid.UUID | None:
    """`note_id` when it is the user's live note; another item is a 404."""
    if note_id is None:
        return None
    note = db.get(models.Source, note_id)
    if note is None or note.user_id != user.id or note.deleted_at is not None or note.kind != models.SourceKind.NOTE:
        raise fastapi.HTTPException(status_code=404, detail="note not found")
    return note_id


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
