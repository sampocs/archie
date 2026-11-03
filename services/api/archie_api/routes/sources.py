# SCAFFOLD(exemplar): replaced by the sync push/pull routes in archie_api/sync/routes.py (plan Task 6).
"""`/sources` routes — add a shared link and read it back.

The phone never calls these in the real app (it syncs through `/sync`), but the shape is the one
every router follows: a module-level `APIRouter`, schemas from `archie_api.schemas`, and
`HTTPException` guards that return early. The store is an in-memory stub standing in for Postgres.
"""

import datetime
import uuid

import fastapi

from archie_api import schemas

router = fastapi.APIRouter(prefix="/sources", tags=["sources"])

# SCAFFOLD: in-memory store standing in for the Postgres-backed sources table.
_SOURCES: dict[uuid.UUID, schemas.SourceView] = {}


@router.post("", status_code=fastapi.status.HTTP_201_CREATED)
def create_source(request: schemas.SourceCreate) -> schemas.SourceView:
    """Record a new source; the title stays empty until the worker fetches it."""
    if request.id in _SOURCES:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_409_CONFLICT, detail="source already exists")

    view = schemas.SourceView(
        id=request.id,
        url=str(request.url),
        title=None,
        state=request.state,
        created_at=datetime.datetime.now(tz=datetime.UTC),
    )
    _SOURCES[request.id] = view
    return view


@router.get("/{source_id}")
def get_source(source_id: uuid.UUID) -> schemas.SourceView:
    """Return a single source, or 404 if no such source exists."""
    view = _SOURCES.get(source_id)
    if view is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail="source not found")
    return view
