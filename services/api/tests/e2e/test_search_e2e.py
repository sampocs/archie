"""`GET /search` through the real API: keyword search for everyone, meaning search for whitelisted users.

Chunks are seeded directly (the worker's `embed` job writes them in production). OpenAI is replayed from a recorded
real response; re-record `search_query` by deleting it and running
`uv run pytest services/api/tests/e2e/test_search_e2e.py --record-mode=once -m postgres` (needs OPENAI_API_KEY).
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_shared import config
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
LONG = (
    "Filler words about the weather. " * 20 + "The Fed doesn't print money in the sense people think. " + "More. " * 40
)


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real OpenAI key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch, env_names=(config.OPENAI_API_KEY_ENV,))


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _seed(
    live_stack: LiveStack, *, user_id: int, title: str, chunks: list[dict[str, Any]], deleted: bool = False
) -> str:
    """A source with these chunks (`text`, optional `owner_kind`, `start_seconds`, `embedding`)."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        url = f"https://example.com/{uuid.uuid4()}"
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=url,
            normalized_url=url,
            title=title,
            kind=models.SourceKind.PODCAST.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            deleted_at=sqlalchemy.func.now() if deleted else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        for index, chunk in enumerate(chunks):
            db.add(
                models.Chunk(
                    user_id=user_id,
                    source_id=source.id,
                    chunk_index=index,
                    text=chunk["text"],
                    owner_kind=chunk.get("owner_kind", models.ChunkOwner.SOURCE_TEXT.value),
                    start_seconds=chunk.get("start_seconds"),
                    embedding=chunk.get("embedding"),
                )
            )
        db.commit()
        source_id = str(source.id)
    engine.dispose()
    return source_id


def test_keyword_search_returns_items_with_the_passage_that_matched(live_stack: LiveStack) -> None:
    """One result per item, its best passage trimmed around the term, with the transcript time; deleted items never."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    podcast = _seed(
        live_stack,
        user_id=user_id,
        title="How the Fed creates money",
        chunks=[{"text": LONG, "start_seconds": 1880.0}, {"text": "Printing is a loose word."}],
    )
    _seed(live_stack, user_id=user_id, title="Deleted", chunks=[{"text": "Money printing."}], deleted=True)

    response = authed.get("/search", params={"q": "money printing"})

    assert response.status_code == 200
    [result] = response.json()["results"]
    assert (result["item_kind"], result["item_id"], result["title"]) == ("source", podcast, "How the Fed creates money")
    assert "print money" in result["passage"] and len(result["passage"]) <= 222
    assert (result["owner_kind"], result["start_seconds"]) == ("source_text", 1880.0)


def test_a_user_without_the_owners_keys_gets_keyword_search_only(live_stack: LiveStack) -> None:
    """No embeddings request is made (no cassette here), and nothing is spent."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=False))
    _seed(live_stack, user_id=_user_id(authed), title="Reserves", chunks=[{"text": "Reserves at the Fed."}])

    assert authed.get("/search", params={"q": "zzqx"}).json()["results"] == []
    assert _llm_calls(live_stack) == []


def test_meaning_search_finds_a_passage_without_the_words_and_costs_one_embed_call(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """A whitelisted query is embedded once; a chunk with an embedding comes back though no word matches."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    axis = [0.0] * models.EMBEDDING_DIMENSIONS
    axis[0] = 1.0
    source_id = _seed(
        live_stack,
        user_id=_user_id(authed),
        title="Monetary plumbing",
        chunks=[{"text": "Central banks set the price of reserves.", "embedding": axis}],
    )

    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    with recorder.use_cassette("search_query.yaml"):
        results = authed.get("/search", params={"q": "who controls money printing"}).json()["results"]

    assert [result["item_id"] for result in results] == [source_id]
    assert results[0]["passage"] == "Central banks set the price of reserves."
    [call] = _llm_calls(live_stack)
    assert (call.step, call.provider) == ("embed", "openai")


def test_a_bad_query_is_422_and_signed_out_is_401(live_stack: LiveStack) -> None:
    """Empty, blank and overlong queries and out-of-range limits are refused before any work."""
    authed = live_stack.authed(live_stack.sign_in())

    assert authed.get("/search", params={"q": ""}).status_code == 422
    assert authed.get("/search", params={"q": "x" * 201}).status_code == 422
    assert authed.get("/search", params={"q": "   "}).status_code == 422
    assert authed.get("/search", params={"q": "x", "limit": 0}).status_code == 422
    assert authed.get("/search", params={"q": "x", "limit": 51}).status_code == 422
    assert live_stack.client.get("/search", params={"q": "x"}).status_code == 401


def _llm_calls(live_stack: LiveStack) -> list[models.LlmCall]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        calls = list(db.scalars(sqlalchemy.select(models.LlmCall)))
    engine.dispose()
    return calls
