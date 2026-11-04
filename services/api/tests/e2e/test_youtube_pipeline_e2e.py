"""A shared YouTube video through the real stack: captions fetched direct, analyzed with timestamps, primer written.

Re-record `pipeline_youtube.yaml` from a residential IP (YouTube blocks cloud ranges) with no SUPADATA_API_KEY set:
delete it, then `uv run pytest services/api/tests/e2e/test_youtube_pipeline_e2e.py --record-mode=once -m postgres`.
It spends a few cents and reads ANTHROPIC_API_KEY from the repo root `.env`.
"""

from __future__ import annotations

import pathlib
import re
import time
import uuid
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
RECORDING_TIMEOUT_SECONDS = 240.0
POLL_INTERVAL_SECONDS = 0.2


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay; never a Supadata key (direct path)."""
    recording.use_recording_api_key(request, monkeypatch)
    monkeypatch.delenv("SUPADATA_API_KEY", raising=False)


def test_a_queued_video_becomes_a_ready_source_with_timestamped_ideas(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """Captions become timed text, so the summary's key ideas carry [mm:ss] timestamps and the primer is written."""
    replaying = request.config.getoption("--record-mode") in (None, "none")
    timeout = READY_TIMEOUT_SECONDS if replaying else RECORDING_TIMEOUT_SECONDS
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = str(uuid.uuid4())

    with _replay(request, "pipeline_youtube"):
        _push_add_source(authed, {"id": source_id, "url": media.YOUTUBE_VIDEO_URL, "intent": "queue"})
        pulled = _poll_until_ready(authed, source_id, timeout=timeout)

    source = next(row for row in pulled["rows"]["sources"] if row["id"] == source_id)
    assert source["kind"] == "youtube"
    assert source["title"] and source["title"] != media.YOUTUBE_VIDEO_URL
    assert source["processing_error"] is None

    current = {row["kind"]: row for row in pulled["rows"]["artifacts"] if row["is_current"]}
    summary = current["summary"]["content"]["summary"]
    assert summary["gist"].strip()
    assert current["primer"]["content"]["markdown"].strip()
    timestamps = [item["timestamp"] for item in summary["key_ideas"] + summary["numbers"] if item["timestamp"]]
    assert any(TIMESTAMP_PATTERN.match(timestamp) for timestamp in timestamps)
    assert all(TIMESTAMP_PATTERN.match(timestamp) for timestamp in timestamps)

    assert [call.step for call in _llm_calls(live_stack)] == ["analyze", "primer"]


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


def _poll_until_ready(authed: httpx.Client, source_id: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        response = authed.get("/sync/pull", params={"since": 0})
        response.raise_for_status()
        pulled = response.json()
        source = next((row for row in pulled["rows"]["sources"] if row["id"] == source_id), None)
        if source is not None and source["processing"] == "ready":
            return pulled
        if time.monotonic() > deadline:
            raise TimeoutError(f"source {source_id} was not ready within {timeout}s: {source}")
        time.sleep(POLL_INTERVAL_SECONDS)


def _llm_calls(live_stack: LiveStack) -> list[models.LlmCall]:
    engine = session.engine_for(live_stack.database_url)
    try:
        with sqlalchemy.orm.Session(engine) as db:
            return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
    finally:
        engine.dispose()
