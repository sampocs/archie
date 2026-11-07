"""`GET /search`: Library search, merging keyword and meaning matches into items with the passage that matched.

Meaning search embeds the query with the owner's OpenAI key, so it runs only for whitelisted users; everyone gets
keyword search. No transaction is held during the embeddings call, and a failed call falls back to keyword search.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import fastapi
import httpx
import pydantic
import sqlalchemy
from archie_db import models, search
from archie_llm import embeddings, llm
from archie_shared import config, logging
from sqlalchemy import orm

from archie_api import deps

MAX_QUERY_LENGTH = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
QUERY_TIMEOUT_SECONDS = 5

router = fastapi.APIRouter(tags=["search"])
_logger = logging.get_logger(logging.LoggerName.API, "search")


class SearchResultView(pydantic.BaseModel):
    """One item and the passage of it that matched best."""

    item_kind: models.SearchItemKind
    item_id: uuid.UUID
    title: str
    passage: str
    owner_kind: models.ChunkOwner
    start_seconds: float | None


class SearchView(pydantic.BaseModel):
    """Items, best first."""

    results: list[SearchResultView]


@router.get("/search")
def search_library(
    q: Annotated[str, fastapi.Query(min_length=1, max_length=MAX_QUERY_LENGTH)],
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
    limit: Annotated[int, fastapi.Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> SearchView:
    """The user's live items matching `q`, each once with its best passage."""
    query = q.strip()
    if not query:
        raise fastapi.HTTPException(status_code=422, detail="query is empty")
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    user_id, is_whitelisted = user.id, user.is_whitelisted

    # No transaction is held during the embeddings call.
    db.commit()
    embedding = query_embedding(engine, user_id=user_id, is_whitelisted=is_whitelisted, query=query)

    hits = search.search_chunks(
        db,
        user_id=user_id,
        query=query,
        query_embedding=embedding,
        limit=search.KEYWORD_CANDIDATES + search.MEANING_CANDIDATES,
    )
    return SearchView(
        results=[
            SearchResultView(
                item_kind=hit.item.kind,
                item_id=hit.item.id,
                title=hit.title,
                passage=search.passage(hit.text, query=query, keyword_match=hit.keyword_match),
                owner_kind=hit.owner_kind,
                start_seconds=hit.start_seconds,
            )
            for hit in search.best_per_item(hits, limit=limit)
        ]
    )


def query_embedding(engine: sqlalchemy.Engine, *, user_id: int, is_whitelisted: bool, query: str) -> list[float] | None:
    """The query's embedding for a whitelisted user on a server with an OpenAI key; None otherwise or on failure."""
    api_key = config.Settings().openai_api_key
    if not is_whitelisted or not api_key:
        return None

    context = llm.CallContext(user_id=user_id, source_id=None, job_id=None, step=llm.EMBED_STEP)
    try:
        [vector] = embeddings.embed(
            engine, api_key=api_key, context=context, texts=[query], timeout_seconds=QUERY_TIMEOUT_SECONDS
        )
    except (httpx.HTTPError, embeddings.EmbeddingError) as error:
        # Keyword results are still worth showing; the phone can't tell the difference.
        _logger.warning("Query embedding failed, searching by keyword only: %r", error)
        return None
    return vector
