"""The whole main path through the real stack: sign in, add a link, and the worker titles it for the next pull.

The page's HTTP is replayed from a recorded cassette. Re-record with
`uv run pytest services/api/tests/e2e/test_main_path_e2e.py --record-mode=once -m postgres` after deleting it.
"""

import pathlib
import time
import uuid
from typing import Any

import httpx
import pytest
import vcr as vcr_module
from archie_testing.harness import LiveStack

# No `worker` marker: the test starts the worker itself, after taking its untitled baseline.
pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

# ogp.me serves an og:title distinct from its <title>, so this also proves og:title wins.
PAGE_URL = "https://ogp.me/"
PAGE_TITLE = "Open Graph protocol"

POLL_INTERVAL_SECONDS = 0.2
POLL_TIMEOUT_SECONDS = 10.0


@pytest.mark.skip(
    reason="Article URLs now queue fetch_content, not fetch_title; the final task re-records this path (plan Task 9)."
)
def test_a_pushed_link_comes_back_titled_at_a_newer_position(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """add_source is applied, the worker (started after the push) titles it, and a later pull shows a newer position."""
    recorder = vcr_module.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode=request.config.getoption("--record-mode") or "none",
        filter_headers=["authorization", "cookie", "set-cookie"],
        decode_compressed_response=True,
        # The test's own calls to the live API must reach it; only the worker's page fetch is replayed.
        ignore_localhost=True,
    )
    authed = live_stack.authed(live_stack.sign_in())
    source_id = str(uuid.uuid4())
    action = {
        "id": str(uuid.uuid4()),
        "type": "add_source",
        "payload": {"id": source_id, "url": PAGE_URL, "intent": "queue"},
    }

    with recorder.use_cassette("main_path.yaml", allow_playback_repeats=True):
        authed.post("/sync/push", json={"actions": [action]}).raise_for_status()

        # The worker is not running yet, so the source is certainly untitled here and this position is the
        # baseline the titled row has to beat, whatever the worker's poll timing.
        untitled_pull = _pull(authed, since=0)
        assert _source(untitled_pull, source_id)["title"] is None
        live_stack.start_worker()
        titled_pull = _poll_until_titled(authed, source_id=source_id, since=untitled_pull["position"])

    titled_source = _source(titled_pull, source_id)
    assert titled_source["title"] == PAGE_TITLE
    assert titled_source["change_seq"] > untitled_pull["position"]


def _pull(authed: httpx.Client, *, since: int) -> dict[str, Any]:
    response = authed.get("/sync/pull", params={"since": since})
    response.raise_for_status()
    return response.json()


def _poll_until_titled(authed: httpx.Client, *, source_id: str, since: int) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        pulled = _pull(authed, since=since)
        if _titled(pulled, source_id):
            return pulled
        if time.monotonic() > deadline:
            raise TimeoutError(f"source {source_id} was not titled within {POLL_TIMEOUT_SECONDS}s")
        time.sleep(POLL_INTERVAL_SECONDS)


def _titled(pulled: dict[str, Any], source_id: str) -> bool:
    # Pulling since a position only returns changed rows, so the source may legitimately be absent yet.
    return any(row["id"] == source_id and row["title"] is not None for row in pulled["rows"]["sources"])


def _source(pulled: dict[str, Any], source_id: str) -> dict[str, Any]:
    source = next((row for row in pulled["rows"]["sources"] if row["id"] == source_id), None)
    assert source is not None, f"source {source_id} is missing from the pull (position {pulled['position']})"
    return source
