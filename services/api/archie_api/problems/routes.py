"""`GET /problems`: what is wrong with the signed-in user's Archie right now, computed on request."""

from __future__ import annotations

import datetime
from typing import Annotated

import fastapi
import pydantic
from archie_db import models
from sqlalchemy import orm

from archie_api import deps
from archie_api.problems import checks

router = fastapi.APIRouter(tags=["problems"])


class ProblemOut(pydantic.BaseModel):
    """One problem; `key` is stable across requests and `since` is when the condition began."""

    kind: checks.ProblemKind
    key: str
    title: str
    detail: str
    since: datetime.datetime


class ProblemsOut(pydantic.BaseModel):
    """Every problem the user has, oldest first; empty when all is well."""

    problems: list[ProblemOut]


@router.get("/problems")
def get_problems(
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> ProblemsOut:
    """Run every check for the signed-in user; nothing is stored."""
    found = checks.find_problems(db, user_id=user.id, now=datetime.datetime.now(tz=datetime.UTC))
    return ProblemsOut(problems=[ProblemOut.model_validate(problem, from_attributes=True) for problem in found])
