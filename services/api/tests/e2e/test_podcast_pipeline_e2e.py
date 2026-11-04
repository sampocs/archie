"""A podcast episode with a published transcript through the real stack: push the Apple link, pull timed analysis.

The API, the worker loop and Postgres are real. Outside HTTP (iTunes Lookup, the feed, the transcript, Anthropic) is
replayed from recorded real responses. Re-record with `uv run pytest services/api/tests/e2e/test_podcast_pipeline_e2e.py
--record-mode=once -m postgres` after deleting the cassette; it spends a few cents and reads ANTHROPIC_API_KEY from
the repo root `.env`. The cassette is recorded fresh so `analyze` runs on the current timed-text prompt.
"""

from __future__ import annotations

import pathlib
import re
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import models, session
from archie_testing import media, recording
from archie_testing.harness import LiveStack

pytestmark = [pytest.mark.postgres, pytest.mark.worker]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

TIMESTAMP_PATTERN = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
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


def test_an_apple_episode_with_a_published_transcript_becomes_a_ready_source_with_timestamps(
    live_stack: LiveStack, request: pytest.FixtureRequest, poll_timeout: float
) -> None:
    """Fetch (lookup, feed, transcript), analyze and primer run; the summary points at moments in the episode."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = str(uuid.uuid4())
    payload = {"id": source_id, "url": media.APPLE_TRANSCRIPT_EPISODE_URL, "intent": "finished", "reaction": "easy"}

    with _replay(request, "pipeline_podcast_apple"):
        _push_add_source(authed, payload)
        pulled = _poll_until(authed, source_id, processing="ready", timeout=poll_timeout)

    source = _row_by_id(pulled["rows"]["sources"], source_id)
    assert (source["kind"], source["processing_error"]) == ("podcast", None)
    assert media.APPLE_TRANSCRIPT_EPISODE_TITLE in source["title"]
    current = {row["kind"]: row for row in pulled["rows"]["artifacts"] if row["is_current"]}
    assert current["summary"]["content"]["summary"]["gist"].strip()
    assert current["primer"]["content"]["markdown"].strip()
    timestamps = _timestamps(current["summary"]["content"])
    assert timestamps, "no key idea or number carries a timestamp"
    assert all(TIMESTAMP_PATTERN.match(timestamp) for timestamp in timestamps)

    calls = _llm_calls(live_stack)
    assert [call.step for call in calls] == ["analyze", "primer"]
    assert all(call.cost_usd > Decimal(0) for call in calls)


def test_a_spotify_show_link_is_unsupported(live_stack: LiveStack) -> None:
    """A show link is classified unsupported with its reason; the worker only fetches its title, never an episode."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = str(uuid.uuid4())

    _push_add_source(authed, {"id": source_id, "url": media.SPOTIFY_SHOW_URL, "intent": "queue"})
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    source = _row_by_id(pulled["rows"]["sources"], source_id)
    assert (source["kind"], source["processing"]) == ("podcast", "unsupported")
    assert source["processing_error"] == "Share an episode, not the show."
    assert _llm_calls(live_stack) == []


def _timestamps(summary_content: dict[str, Any]) -> list[str]:
    """Every non-null timestamp the summary gives its key ideas and numbers."""
    summary = summary_content["summary"]
    items = [*summary.get("key_ideas", []), *summary.get("numbers", [])]
    return [item["timestamp"] for item in items if item.get("timestamp")]


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


def _llm_calls(live_stack: LiveStack) -> list[models.LlmCall]:
    engine = session.engine_for(live_stack.database_url)
    try:
        with sqlalchemy.orm.Session(engine) as db:
            return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
    finally:
        engine.dispose()


def _row_by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next(row for row in rows if row["id"] == row_id)
