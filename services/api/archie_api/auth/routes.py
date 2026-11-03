"""Auth routes: logout, plus `/me` so the app can check on launch that its session is still good."""

from __future__ import annotations

from typing import Annotated

import fastapi
import jwt
import pydantic
from archie_db import models
from archie_shared import config
from sqlalchemy import orm

from archie_api import deps
from archie_api.auth import apple, sessions

router = fastapi.APIRouter(tags=["auth"])


class MeView(pydantic.BaseModel):
    """The signed-in user, as the app sees it."""

    user_id: int


@router.get("/me")
def me(user: Annotated[models.User, fastapi.Depends(deps.current_user)]) -> MeView:
    """Return the signed-in user; 401 means the app must sign in again."""
    return MeView(user_id=user.id)


class AppleSignInRequest(pydantic.BaseModel):
    """The identity token the app got from Sign in with Apple."""

    identity_token: str


class SessionView(pydantic.BaseModel):
    """The raw session key the app stores in the keychain."""

    session_key: str


@router.post("/auth/apple")
def sign_in_with_apple(
    request: AppleSignInRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    jwks_client: Annotated[jwt.PyJWKClient, fastapi.Depends(apple.get_jwks_client)],
) -> SessionView:
    """Verify the Apple identity token, find or create its user, and start a session; 401 if the token is bad."""
    settings = config.get_settings()
    try:
        identity = apple.verify_identity_token(
            request.identity_token, audience=settings.require_apple_audience(), jwks_client=jwks_client
        )
    except apple.InvalidAppleToken as error:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_401_UNAUTHORIZED, detail="invalid Apple token"
        ) from error

    user = apple.upsert_apple_user(db, identity=identity, owner_emails=settings.owner_email_set())
    session_key = sessions.create_session(db, user_id=user.id)
    db.commit()
    return SessionView(session_key=session_key)


@router.post("/auth/logout", status_code=fastapi.status.HTTP_204_NO_CONTENT)
def logout(
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    raw_key: Annotated[str, fastapi.Depends(deps.current_session_key)],
    _user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> None:
    """Revoke the caller's session key."""
    sessions.revoke_session(db, raw_key=raw_key)
    db.commit()
