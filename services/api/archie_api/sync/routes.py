"""Sync routes: the phone pushes its recorded actions and pulls rows changed since its last position."""

from __future__ import annotations

from typing import Annotated

import fastapi
from archie_db import models
from sqlalchemy import orm

from archie_api import deps
from archie_api.sync import actions, pull, schemas

router = fastapi.APIRouter(prefix="/sync", tags=["sync"])


@router.post("/push")
def push(
    body: schemas.PushRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.PushResponse:
    """Apply the pushed actions in order and answer each one."""
    return schemas.PushResponse(results=actions.apply_actions(db, user=user, actions=body.actions))


@router.get("/pull")
def pull_rows(
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
    since: Annotated[int, fastapi.Query(ge=0)],
) -> schemas.PullResponse:
    """One page of rows changed after position `since`."""
    return pull.pull_changes(db, user_id=user.id, since=since)
