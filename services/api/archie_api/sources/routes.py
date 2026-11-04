"""Per-source reads the phone makes online: a newsletter's full text (and, later, a podcast's nearby episodes)."""

from __future__ import annotations

import uuid
from typing import Annotated

import fastapi
import pydantic
from archie_db import models, pipeline
from sqlalchemy import orm

from archie_api import deps

router = fastapi.APIRouter(prefix="/sources", tags=["sources"])

_TEXT_KEY = "text"  # The `text` artifact's content key (the worker's `content.TEXT_KEY`).


class SourceTextView(pydantic.BaseModel):
    """A newsletter's stored text, for "Open the full email"."""

    text: str


@router.get("/{source_id}/text")
def source_text(
    source_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> SourceTextView:
    """The caller's newsletter text; 404 for any other source, someone else's, or one without text yet."""
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user.id or source.deleted_at is not None:
        raise _not_found()
    if source.kind != models.SourceKind.NEWSLETTER:
        raise _not_found()

    artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if artifact is None:
        raise _not_found()
    return SourceTextView(text=artifact.content[_TEXT_KEY])


def _not_found() -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail="no such source text")
