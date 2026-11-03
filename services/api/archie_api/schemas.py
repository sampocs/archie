# SCAFFOLD(exemplar): replaced by the real sync wire schemas in archie_api/sync/schemas.py (plan Task 6).
"""Pydantic request/response models for the API.

These are the wire contract the phone app codes against. They are intentionally separate from the
SQLAlchemy models: the wire shape can stay stable while the tables change, and the boundary is
where validation happens.
"""

import datetime
import uuid

import pydantic
from archie_db.models import SourceState


class SourceCreate(pydantic.BaseModel):
    """Request body to add a source; the phone generates the id so it can show the row offline."""

    id: uuid.UUID
    url: pydantic.HttpUrl
    state: SourceState = SourceState.QUEUED


class SourceView(pydantic.BaseModel):
    """A source as returned to clients."""

    id: uuid.UUID
    url: str
    title: str | None
    state: SourceState
    created_at: datetime.datetime
