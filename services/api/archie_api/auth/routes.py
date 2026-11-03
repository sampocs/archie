"""Auth routes: logout, plus `/me` so the app can check on launch that its session is still good."""

from __future__ import annotations

from typing import Annotated

import fastapi
import pydantic
from archie_db import models
from sqlalchemy import orm

from archie_api import deps
from archie_api.auth import sessions

router = fastapi.APIRouter(tags=["auth"])


class MeView(pydantic.BaseModel):
    """The signed-in user, as the app sees it."""

    user_id: int


@router.get("/me")
def me(user: Annotated[models.User, fastapi.Depends(deps.current_user)]) -> MeView:
    """Return the signed-in user; 401 means the app must sign in again."""
    return MeView(user_id=user.id)


@router.post("/auth/logout", status_code=fastapi.status.HTTP_204_NO_CONTENT)
def logout(
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    raw_key: Annotated[str, fastapi.Depends(deps.current_session_key)],
    _user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> None:
    """Revoke the caller's session key."""
    sessions.revoke_session(db, raw_key=raw_key)
    db.commit()
