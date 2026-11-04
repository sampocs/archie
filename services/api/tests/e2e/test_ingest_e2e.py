"""Newsletter ingest through the real stack: a raw email posted to `/ingest/email` becomes an analyzed Inbox source.

The API, the worker loop and Postgres are real; the emails are real newsletters (scrubbed fixtures) and Anthropic is
replayed from recorded real responses. Re-record with `uv run pytest services/api/tests/e2e/test_ingest_e2e.py
--record-mode=once -m postgres` after deleting the cassettes; it spends a few cents and reads ANTHROPIC_API_KEY from
the repo root `.env`.
"""

from __future__ import annotations

import email.message
import pathlib
import time
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api.ingest import routes
from archie_db import ingest_address, models, session
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
FIXTURE_DIR = pathlib.Path(__file__).parents[1] / "fixtures" / "newsletters"

INGEST_SECRET = "test-ingest-secret"
INGEST_DOMAIN = "example.com"
SUBSTACK_SUBJECT = "How Netflix Uses AI Agents for Performance Engineering"
SUBSTACK_URL = "https://blog.bytebytego.com/p/how-netflix-uses-ai-agents-for-performance"
OVER_LIMIT_BYTES = 11 * 1024 * 1024

READY_TIMEOUT_SECONDS = 30.0
RECORDING_TIMEOUT_SECONDS = 240.0
POLL_INTERVAL_SECONDS = 0.2


@pytest.fixture(autouse=True)
def ingest_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The secret and domain the endpoint reads per request."""
    monkeypatch.setenv("INGEST_SECRET", INGEST_SECRET)
    monkeypatch.setenv("INGEST_EMAIL_DOMAIN", INGEST_DOMAIN)


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


@pytest.fixture
def poll_timeout(request: pytest.FixtureRequest) -> float:
    """How long to wait for the worker: short on replay, long while recording live model calls."""
    replaying = request.config.getoption("--record-mode") in (None, "none")
    return READY_TIMEOUT_SECONDS if replaying else RECORDING_TIMEOUT_SECONDS


def test_a_wrong_or_missing_secret_is_refused_and_nothing_is_stored(live_stack: LiveStack) -> None:
    """The shared secret gates the endpoint; a bad one stores nothing."""
    address = _ingest_address(live_stack)
    raw = _fixture("substack_bytebytego")

    missing = live_stack.client.post("/ingest/email", content=raw, headers={"x-ingest-to": address})
    wrong = _deliver(live_stack, raw=raw, to=address, secret="not-the-secret")

    assert (missing.status_code, wrong.status_code) == (401, 401)
    assert _source_rows(live_stack) == []


def test_every_delivery_is_refused_when_no_secret_is_configured(
    live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unset INGEST_SECRET must not mean "open to everyone"."""
    address = _ingest_address(live_stack)
    monkeypatch.delenv("INGEST_SECRET")

    response = _deliver(live_stack, raw=_fixture("substack_bytebytego"), to=address, secret="")

    assert response.status_code == 401
    assert _source_rows(live_stack) == []


def test_an_email_over_ten_megabytes_is_refused_whether_or_not_its_length_is_declared(live_stack: LiveStack) -> None:
    """The cap holds by declared content-length and by counting the streamed bytes."""
    address = _ingest_address(live_stack)
    oversized = b"x" * OVER_LIMIT_BYTES

    declared = _deliver(live_stack, raw=oversized, to=address)
    # A generator body has no content-length, so only the counting while reading can stop it.
    undeclared = live_stack.client.post(
        "/ingest/email",
        content=(oversized[start : start + 65536] for start in range(0, len(oversized), 65536)),
        headers={"x-ingest-secret": INGEST_SECRET, "x-ingest-to": address},
    )

    assert (declared.status_code, undeclared.status_code) == (413, 413)
    assert _source_rows(live_stack) == []


def test_an_email_for_an_unknown_recipient_is_accepted_and_dropped(live_stack: LiveStack) -> None:
    """Unknown recipients get 202 so Cloudflare does not retry, and nothing is stored."""
    _ingest_address(live_stack)

    response = _deliver(live_stack, raw=_fixture("substack_bytebytego"), to=f"nobody0000@{INGEST_DOMAIN}")

    assert (response.status_code, response.json()) == (202, {"status": "accepted"})
    assert _source_rows(live_stack) == []


def test_an_email_with_no_readable_text_is_stored_as_a_failed_source_without_a_capture_or_job(
    live_stack: LiveStack,
) -> None:
    """A message with only an image has nothing to analyze: the source fails with a reason and queues nothing."""
    message = email.message.EmailMessage()
    message["From"] = "writer@example.com"
    message["Subject"] = "Just a picture"
    message["Message-ID"] = "<picture-only@example.com>"
    message.set_content(b"\x89PNG\r\n", maintype="image", subtype="png", filename="photo.png")

    response = _deliver(live_stack, raw=message.as_bytes(), to=_ingest_address(live_stack))

    assert response.status_code == 202
    [source] = _source_rows(live_stack)
    assert (source.processing, source.processing_error) == ("failed", routes.UNREADABLE_EMAIL_ERROR)
    assert _query(live_stack, sqlalchemy.select(models.SourceCapture)) == []
    assert _query(live_stack, sqlalchemy.select(models.Job)) == []


@pytest.mark.worker
def test_a_substack_post_becomes_a_ready_inbox_source_with_only_a_summary(
    live_stack: LiveStack, request: pytest.FixtureRequest, poll_timeout: float
) -> None:
    """Delivered mail is analyzed from its captured text: a summary, no primer, no cards, one costed call."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    address = authed.get("/me").json()["ingest_address"]
    assert address.endswith(f"@{INGEST_DOMAIN}")

    with _replay(request, "ingest_substack"):
        response = _deliver(live_stack, raw=_fixture("substack_bytebytego"), to=address)
        assert response.status_code == 202
        pulled = _poll_until_ready(authed, timeout=poll_timeout)

    source = pulled["rows"]["sources"][0]
    assert (source["kind"], source["state"], source["intent"]) == ("newsletter", "inbox", "queue")
    assert (source["sender"], source["title"], source["url"]) == ("ByteByteGo", SUBSTACK_SUBJECT, SUBSTACK_URL)
    assert source["processing_error"] is None

    current = {row["kind"]: row for row in pulled["rows"]["artifacts"] if row["is_current"]}
    assert current["summary"]["content"]["summary"]["gist"].strip()
    assert "primer" not in current
    assert [card for card in pulled["rows"]["cards"] if card["deleted_at"] is None] == []
    assert [call.step for call in _llm_calls(live_stack)] == ["analyze"]

    # Cloudflare retries deliveries: the same message again must not add a second source.
    assert _deliver(live_stack, raw=_fixture("substack_bytebytego"), to=address).status_code == 202
    assert len(_source_rows(live_stack)) == 1


@pytest.mark.worker
def test_a_morning_brew_issue_without_a_web_link_gets_a_placeholder_url_and_a_summary(
    live_stack: LiveStack, request: pytest.FixtureRequest, poll_timeout: float
) -> None:
    """With no web URL the source url is `newsletter:<message-id>`, and it is still analyzed."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    address = authed.get("/me").json()["ingest_address"]

    with _replay(request, "ingest_morning_brew"):
        assert _deliver(live_stack, raw=_fixture("morning_brew"), to=address).status_code == 202
        pulled = _poll_until_ready(authed, timeout=poll_timeout)

    source = pulled["rows"]["sources"][0]
    assert (source["sender"], source["title"]) == ("Morning Brew", "☕ Putting it to a vote")
    assert source["url"].startswith("newsletter:")
    assert [call.step for call in _llm_calls(live_stack)] == ["analyze"]


def test_a_chosen_address_delivers_to_its_user(live_stack: LiveStack) -> None:
    """After `archie-set-ingest-address`, mail to `News+tag@` (case- and +tag-insensitive) lands on that user only."""
    authed = live_stack.authed(live_stack.sign_in(apple_sub="owner", email="Owner@Example.com"))
    other = live_stack.authed(live_stack.sign_in(apple_sub="other", email="other@example.com"))
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        ingest_address.set_ingest_address(db, email="owner@example.com", address="news")
    engine.dispose()

    response = _deliver(live_stack, raw=_fixture("substack_bytebytego"), to=f"News+tag@{INGEST_DOMAIN}")

    assert response.status_code == 202
    assert authed.get("/me").json()["ingest_address"] == f"news@{INGEST_DOMAIN}"
    assert len(authed.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"]) == 1
    assert other.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def _fixture(name: str) -> bytes:
    return (FIXTURE_DIR / f"{name}.eml").read_bytes()


def _ingest_address(live_stack: LiveStack) -> str:
    authed = live_stack.authed(live_stack.sign_in())
    return authed.get("/me").json()["ingest_address"]


def _deliver(live_stack: LiveStack, *, raw: bytes, to: str, secret: str = INGEST_SECRET) -> httpx.Response:
    headers = {"x-ingest-to": to, "x-ingest-from": "sender@example.com", "content-type": "message/rfc822"}
    if secret:
        headers["x-ingest-secret"] = secret
    return live_stack.client.post("/ingest/email", content=raw, headers=headers)


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    # The test's own calls to the live API must reach it; only the worker's outside calls are replayed.
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=True)


def _poll_until_ready(authed: httpx.Client, *, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        pulled = authed.get("/sync/pull", params={"since": 0}).json()
        sources = pulled["rows"]["sources"]
        if sources and sources[0]["processing"] == "ready":
            return pulled
        if time.monotonic() > deadline:
            raise TimeoutError(f"newsletter was not ready within {timeout}s: {sources}")
        time.sleep(POLL_INTERVAL_SECONDS)


def _source_rows(live_stack: LiveStack) -> list[models.Source]:
    return _query(live_stack, sqlalchemy.select(models.Source))


def _llm_calls(live_stack: LiveStack) -> list[models.LlmCall]:
    return _query(live_stack, sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id))


def _query(live_stack: LiveStack, statement: Any) -> list[Any]:
    engine = session.engine_for(live_stack.database_url)
    try:
        with sqlalchemy.orm.Session(engine) as db:
            return list(db.scalars(statement))
    finally:
        engine.dispose()
