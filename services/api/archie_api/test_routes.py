"""Routes that exist only outside production, so e2e tests and local dev can sign in without Apple."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import fastapi
import pydantic
import sqlalchemy
from archie_db import changes, models, pipeline, user_topics
from sqlalchemy import orm

from archie_api import deps
from archie_api.auth import sessions

router = fastapi.APIRouter(prefix="/test", tags=["test"])


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
