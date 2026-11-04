"""The starter topic list the picker offers."""

from __future__ import annotations

from typing import Annotated

import fastapi
import pydantic
from archie_db import models
from archie_shared import topics

from archie_api import deps

router = fastapi.APIRouter(prefix="/topics", tags=["topics"])


class StarterDomainView(pydantic.BaseModel):
    """One domain's starter topics, in display order."""

    domain: str
    topics: list[str]


class StarterTopicsView(pydantic.BaseModel):
    """Every domain with starter topics, in domain order."""

    domains: list[StarterDomainView]


@router.get("/starter")
def starter_topics(_user: Annotated[models.User, fastapi.Depends(deps.current_user)]) -> StarterTopicsView:
    """The picker's list; signed-in users only."""
    return StarterTopicsView(
        domains=[
            StarterDomainView(domain=domain.value, topics=list(names))
            for domain, names in topics.STARTER_TOPICS.items()
        ]
    )
