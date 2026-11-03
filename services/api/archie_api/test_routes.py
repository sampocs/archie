"""Routes that exist only outside production, so e2e tests and local dev can sign in without Apple."""

from __future__ import annotations

from typing import Annotated

import fastapi
import pydantic
import sqlalchemy
from archie_db import models
from sqlalchemy import orm

from archie_api import deps
from archie_api.auth import sessions

router = fastapi.APIRouter(prefix="/test", tags=["test"])


class TestSessionRequest(pydantic.BaseModel):
    """Who to sign in as; the user is created on first use."""

    __test__ = False

    apple_sub: str = "test-user"
    email: str | None = None


class TestSessionView(pydantic.BaseModel):
    """The raw session key for the signed-in test user."""

    __test__ = False

    session_key: str


@router.post("/session")
def create_test_session(
    request: TestSessionRequest, db: Annotated[orm.Session, fastapi.Depends(deps.get_db)]
) -> TestSessionView:
    """Upsert the user by `apple_sub` and start a session for them."""
    user = db.scalars(sqlalchemy.select(models.User).where(models.User.apple_sub == request.apple_sub)).first()
    if user is None:
        user = models.User(apple_sub=request.apple_sub, email=request.email)
        db.add(user)
        db.flush()

    session_key = sessions.create_session(db, user_id=user.id)
    db.commit()
    return TestSessionView(session_key=session_key)
