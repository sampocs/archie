"""Text embeddings from OpenAI's `text-embedding-3-small`, shared by the worker (passages) and the API (queries).

Each request is recorded in `llm_calls`. Failures are raised for the caller to retry or fall back on: `httpx.HTTPError`
for a connection failure or a non-2xx answer, `EmbeddingError` for a 2xx body that isn't one vector per text.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import sqlalchemy
from archie_db import models

from archie_llm import llm

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
# OpenAI takes up to 2,048 inputs per request; 100 keeps each request small and its retry cheap.
MAX_BATCH = 100
TIMEOUT_SECONDS = 60


class EmbeddingError(Exception):
    """OpenAI answered with a body that isn't one 1536-dimension vector per input."""


def embed(
    engine: sqlalchemy.Engine,
    *,
    api_key: str,
    context: llm.CallContext,
    texts: Sequence[str],
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> list[list[float]]:
    """One vector per text, in order, in batches of up to `MAX_BATCH` texts per request."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_BATCH):
        batch = texts[start : start + MAX_BATCH]
        vectors.extend(
            _embed_batch(engine, api_key=api_key, context=context, texts=batch, timeout_seconds=timeout_seconds)
        )
    return vectors


def _embed_batch(
    engine: sqlalchemy.Engine,
    *,
    api_key: str,
    context: llm.CallContext,
    texts: Sequence[str],
    timeout_seconds: float,
) -> list[list[float]]:
    response = httpx.post(
        OPENAI_EMBEDDINGS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": llm.EMBEDDING_MODEL, "input": list(texts)},
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    body = response.json()
    vectors = _vectors_of(body, count=len(texts))
    # Recorded once the answer is known to be usable; a malformed answer is the provider's failure, not spend we keep.
    llm.record_embedding_call(engine, context=context, tokens=int(body["usage"]["prompt_tokens"]))
    return vectors


def _vectors_of(body: Any, *, count: int) -> list[list[float]]:
    try:
        ordered = sorted(body["data"], key=lambda item: item["index"])
        vectors = [[float(value) for value in item["embedding"]] for item in ordered]
        int(body["usage"]["prompt_tokens"])
    except (KeyError, TypeError, ValueError) as error:
        raise EmbeddingError(f"embeddings answer was malformed: {error!r}") from error

    if len(vectors) != count or any(len(vector) != models.EMBEDDING_DIMENSIONS for vector in vectors):
        raise EmbeddingError(f"expected {count} vectors of {models.EMBEDDING_DIMENSIONS}")
    return vectors
