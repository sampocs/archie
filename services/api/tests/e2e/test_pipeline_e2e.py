"""The capture pipeline through the real stack: push a link from the phone and pull its summary, primer and cards.

The API, the worker loop and Postgres are real. Outside HTTP (the article page, fxtwitter, Anthropic) is replayed from
recorded real responses. Re-record with `uv run pytest services/api/tests/e2e/test_pipeline_e2e.py
--record-mode=once -m postgres` after deleting the cassette; it spends a few cents and reads ANTHROPIC_API_KEY from
the repo root `.env`.
"""

from __future__ import annotations

import pathlib
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import models, session
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = [pytest.mark.postgres, pytest.mark.worker]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

ARTICLE_URL = "https://www.paulgraham.com/greatwork.html"
ARTICLE_TITLE = "How to Do Great Work"
X_THREAD_URL = "https://x.com/sama/status/2107691261776052633"

MIN_CARDS = 3
MAX_CARDS = 5
READY_TIMEOUT_SECONDS = 30.0
# Live model calls (analyze, then a long Sonnet primer) take much longer than replaying them.
RECORDING_TIMEOUT_SECONDS = 240.0
POLL_INTERVAL_SECONDS = 0.2


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


@pytest.fixture
def poll_timeout(request: pytest.FixtureRequest) -> float:
    """How long to wait for the worker: short on replay, long while recording live model calls."""
    replaying = request.config.getoption("--record-mode") in (None, "none")
    return READY_TIMEOUT_SECONDS if replaying else RECORDING_TIMEOUT_SECONDS


def test_a_finished_article_becomes_a_ready_source_with_a_summary_a_primer_and_cards(
    live_stack: LiveStack, request: pytest.FixtureRequest, poll_timeout: float
) -> None:
    """Sharing an article as finished: fetch, analyze and primer run, and one pull carries everything, costed."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = str(uuid.uuid4())
    payload = {"id": source_id, "url": ARTICLE_URL, "intent": "finished", "reaction": "easy", "note": "re-read yearly"}

    with _replay(request, "pipeline_article"):
        _push_add_source(authed, payload)
        pulled = _poll_until(authed, source_id, processing="ready", timeout=poll_timeout)

    source = _row_by_id(pulled["rows"]["sources"], source_id)
    assert source["title"] == ARTICLE_TITLE
    assert (source["intent"], source["state"]) == ("finished", "consumed")
    assert (source["reaction"], source["note"]) == ("easy", "re-read yearly")
    assert source["processing_error"] is None
    _assert_summary_primer_and_cards(pulled, source_id)
    _assert_two_costed_calls(live_stack)


def test_a_queued_x_thread_becomes_a_ready_source(
    live_stack: LiveStack, request: pytest.FixtureRequest, poll_timeout: float
) -> None:
    """An X post is read through fxtwitter (the whole thread), then analyzed like an article."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = str(uuid.uuid4())

    with _replay(request, "pipeline_x_thread"):
        _push_add_source(authed, {"id": source_id, "url": X_THREAD_URL, "intent": "queue"})
        pulled = _poll_until(authed, source_id, processing="ready", timeout=poll_timeout)

    source = _row_by_id(pulled["rows"]["sources"], source_id)
    assert (source["kind"], source["intent"], source["state"]) == ("x", "queue", "queued")
    assert source["title"].startswith("@sama: ")
    _assert_summary_primer_and_cards(pulled, source_id, cards_required=False)
    assert len(_llm_calls(live_stack)) == 2


def test_a_user_without_the_owners_keys_sees_why_nothing_was_made(
    live_stack: LiveStack, request: pytest.FixtureRequest, poll_timeout: float
) -> None:
    """A non-whitelisted user's source ends failed with a reason, no artifacts, and no model call is billed."""
    authed = live_stack.authed(live_stack.sign_in(apple_sub="stranger"))
    source_id = str(uuid.uuid4())

    with _replay(request, "pipeline_article_unpaid"):
        _push_add_source(authed, {"id": source_id, "url": ARTICLE_URL, "intent": "queue"})
        pulled = _poll_until(authed, source_id, processing="failed", timeout=poll_timeout)

    source = _row_by_id(pulled["rows"]["sources"], source_id)
    assert source["processing_error"] is not None
    # Only the fetched page text exists; nothing generated.
    assert {row["kind"] for row in pulled["rows"]["artifacts"]} <= {"text"}
    assert _llm_calls(live_stack) == []


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    # The test's own calls to the live API must reach it; only the worker's outside calls are replayed.
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=True)


def _push_add_source(authed: httpx.Client, payload: dict[str, Any]) -> None:
    action = {"id": str(uuid.uuid4()), "type": "add_source", "payload": payload}
    response = authed.post("/sync/push", json={"actions": [action]})
    response.raise_for_status()
    assert response.json()["results"][0]["result"] == "applied"


def _poll_until(authed: httpx.Client, source_id: str, *, processing: str, timeout: float) -> dict[str, Any]:
    """Pull everything from the start until the source reaches `processing`, as the phone's sync loop would."""
    deadline = time.monotonic() + timeout
    while True:
        response = authed.get("/sync/pull", params={"since": 0})
        response.raise_for_status()
        pulled = response.json()
        source = next((row for row in pulled["rows"]["sources"] if row["id"] == source_id), None)
        if source is not None and source["processing"] == processing:
            return pulled
        if time.monotonic() > deadline:
            raise TimeoutError(f"source {source_id} was not {processing} within {timeout}s: {source}")
        time.sleep(POLL_INTERVAL_SECONDS)


def _assert_summary_primer_and_cards(pulled: dict[str, Any], source_id: str, *, cards_required: bool = True) -> None:
    current = {row["kind"]: row for row in pulled["rows"]["artifacts"] if row["is_current"]}
    assert current["summary"]["content"]["summary"]["gist"].strip()
    assert current["primer"]["content"]["markdown"].strip()

    cards = [row for row in pulled["rows"]["cards"] if row["source_id"] == source_id and row["deleted_at"] is None]
    if cards_required:
        assert MIN_CARDS <= len(cards) <= MAX_CARDS
    assert len(cards) <= MAX_CARDS


def _assert_two_costed_calls(live_stack: LiveStack) -> None:
    calls = _llm_calls(live_stack)
    assert [call.step for call in calls] == ["analyze", "primer"]
    assert all(call.cost_usd > Decimal(0) for call in calls)


def _llm_calls(live_stack: LiveStack) -> list[models.LlmCall]:
    engine = session.engine_for(live_stack.database_url)
    try:
        with sqlalchemy.orm.Session(engine) as db:
            return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
    finally:
        engine.dispose()


def _row_by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next(row for row in rows if row["id"] == row_id)
