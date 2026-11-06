"""The /review routes through the real API: grading and rewriting by Haiku, spoken answers by Groq Whisper.

Outside HTTP (Anthropic, Groq) is replayed from recorded real responses. Re-record with `uv run pytest
services/api/tests/e2e/test_review_routes_e2e.py --record-mode=once -m postgres` after deleting the cassette; it spends
a few cents and reads ANTHROPIC_API_KEY and GROQ_API_KEY from the repo root `.env`.
"""

from __future__ import annotations

import datetime
import pathlib
import uuid
from decimal import Decimal
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
AUDIO_PATH = pathlib.Path(__file__).parents[1] / "fixtures" / "audio" / "answer.m4a"

QUESTION = "Why does the Fed raise rates when inflation is high?"
ANSWER = "Higher rates make borrowing costlier, which slows spending and cools inflation."


@pytest.fixture(autouse=True)
def recording_api_keys(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real keys while recording, placeholders on replay."""
    recording.use_recording_api_key(
        request,
        monkeypatch,
        env_names=(config.ANTHROPIC_API_KEY_ENV, config.GROQ_API_KEY_ENV, config.OPENAI_API_KEY_ENV),
    )


def test_grading_an_answer_by_its_idea_is_one_costed_haiku_call(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """A paraphrase of the accepted answer gets a verdict, and the call is recorded without a job."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    card = _seed_card(live_stack, user_id=_user_id(authed))

    with _replay(request, "review_grade"):
        response = authed.post(
            "/review/grade", json={"card_id": str(card.id), "answer": "to make loans expensive so people spend less"}
        )

    assert response.status_code == 200
    verdict = response.json()
    assert verdict["grade"] in {grade.value for grade in models.ReviewGrade}
    assert isinstance(verdict["missing"], str)
    assert (verdict["missing"] == "") == (verdict["grade"] == models.ReviewGrade.GOT_IT)

    [call] = _llm_calls(live_stack)
    assert (call.step, call.job_id, call.model, call.source_id) == ("grade", None, "claude-haiku-5-5", card.source_id)


def test_grading_a_card_that_is_not_the_callers_or_is_dropped_is_a_404(live_stack: LiveStack) -> None:
    """Another user's card and a dropped card look the same: not found."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger", is_whitelisted=True))
    card = _seed_card(live_stack, user_id=_user_id(owner))
    dropped = _seed_card(live_stack, user_id=_user_id(owner), deleted=True)

    assert stranger.post("/review/grade", json={"card_id": str(card.id), "answer": "x"}).status_code == 404
    assert owner.post("/review/grade", json={"card_id": str(dropped.id), "answer": "x"}).status_code == 404
    assert stranger.post(f"/review/cards/{card.id}/care", json={"note": "x"}).status_code == 404
    assert _llm_calls(live_stack) == []


def test_a_user_without_the_owners_keys_gets_403_and_an_empty_answer_422(live_stack: LiveStack) -> None:
    """Grading spends the owner's key, so a non-whitelisted user is refused before any request is made."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=False))
    card = _seed_card(live_stack, user_id=_user_id(authed))

    refused = authed.post("/review/grade", json={"card_id": str(card.id), "answer": "anything"})
    assert (refused.status_code, refused.json()) == (403, {"detail": "needs your own API key"})
    assert authed.post(f"/review/cards/{card.id}/care", json={"note": "anything"}).status_code == 403

    whitelisted = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    owned = _seed_card(live_stack, user_id=_user_id(whitelisted))
    assert whitelisted.post("/review/grade", json={"card_id": str(owned.id), "answer": ""}).status_code == 422
    assert _llm_calls(live_stack) == []


def test_a_care_note_rewrites_the_answer_and_is_remembered(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """The card comes back with a new answer, a pull carries it at a later position, and the note is a preference."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    card = _seed_card(live_stack, user_id=_user_id(authed))
    before = _pulled_card(authed, card.id)
    note = "I mostly care that borrowing gets costlier"

    with _replay(request, "review_care"):
        response = authed.post(f"/review/cards/{card.id}/care", json={"note": note})

    assert response.status_code == 200
    returned = response.json()
    assert returned["id"] == str(card.id)
    assert returned["answer"] != ANSWER

    pulled = _pulled_card(authed, card.id)
    assert pulled["answer"] == returned["answer"]
    assert pulled["change_seq"] > before["change_seq"]

    [preference] = _preferences(live_stack)
    assert (preference.kind, preference.note, preference.card_id) == (
        models.CardPreferenceKind.CARE.value,
        note,
        card.id,
    )
    [call] = _llm_calls(live_stack)
    assert (call.step, call.job_id) == ("care", None)


def test_a_spoken_answer_is_transcribed_by_groq_and_costed_by_its_length(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """The recorded clip comes back as text, and the call is billed at the phone's stated duration."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    card = _seed_card(live_stack, user_id=_user_id(authed))

    with _replay(request, "review_transcribe"):
        response = authed.post(
            "/review/transcribe",
            data={"card_id": str(card.id), "duration_ms": "4000"},
            files={"audio": ("answer.m4a", AUDIO_PATH.read_bytes(), "audio/m4a")},
        )

    assert response.status_code == 200
    assert "inflation" in response.json()["text"].lower()

    [call] = _llm_calls(live_stack)
    assert (call.step, call.provider, call.model) == ("transcribe_answer", "groq", "whisper-large-v3-turbo")
    assert call.audio_seconds == Decimal("4.000")


def test_transcription_refuses_long_big_unowned_or_unconfigured_requests(
    live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over 125 s or 5 MB is 413, a non-whitelisted user 403, a server with no speech key 503: none reach a provider."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    card = _seed_card(live_stack, user_id=_user_id(authed))
    audio = AUDIO_PATH.read_bytes()

    def transcribe(
        client: httpx.Client, *, card: models.Card = card, duration_ms: int = 4000, content: bytes = audio
    ) -> httpx.Response:
        return client.post(
            "/review/transcribe",
            data={"card_id": str(card.id), "duration_ms": str(duration_ms)},
            files={"audio": ("answer.m4a", content, "audio/m4a")},
        )

    assert transcribe(authed, duration_ms=200_000).status_code == 413
    assert transcribe(authed, content=b"0" * 5_000_001).status_code == 413

    # The size is judged from Content-Length before the body is parsed, so even an unauthenticated upload is refused
    # unread, and a body with no declared length (chunked) is too.
    anonymous = httpx.Client(base_url=str(authed.base_url))
    assert transcribe(anonymous, content=b"0" * 5_100_000).status_code == 413
    chunked = authed.post(
        "/review/transcribe",
        headers={"content-type": "multipart/form-data; boundary=x"},
        content=iter([b"--x--\r\n"]),
    )
    assert chunked.status_code == 413

    unowned = live_stack.authed(live_stack.sign_in(apple_sub="stranger", is_whitelisted=False))
    assert transcribe(unowned, card=_seed_card(live_stack, user_id=_user_id(unowned))).status_code == 403

    monkeypatch.delenv(config.GROQ_API_KEY_ENV)
    monkeypatch.delenv(config.OPENAI_API_KEY_ENV)
    unconfigured = transcribe(authed)
    assert (unconfigured.status_code, unconfigured.json()) == (503, {"detail": "transcription isn't set up"})
    assert _llm_calls(live_stack) == []


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    # The test's own calls to the live API must reach it; only the outside calls are replayed.
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=True)


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _seed_card(live_stack: LiveStack, *, user_id: int, deleted: bool = False) -> models.Card:
    """A mechanism card on a consumed source, the shape review grades."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        url = f"https://example.com/{uuid.uuid4()}"
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=url,
            normalized_url=url,
            kind=models.SourceKind.ARTICLE.value,
            state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value,
            processing=models.ProcessingStatus.READY.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        card = models.Card(
            id=uuid.uuid4(),
            user_id=user_id,
            source_id=source.id,
            kind=models.CardKind.MECHANISM.value,
            question=QUESTION,
            answer=ANSWER,
            deleted_at=datetime.datetime.now(datetime.UTC) if deleted else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(card)
        db.commit()
        db.refresh(card)
        db.expunge(card)
        return card


def _pulled_card(authed: httpx.Client, card_id: uuid.UUID) -> dict[str, Any]:
    rows = authed.get("/sync/pull", params={"since": 0}).json()["rows"]["cards"]
    return next(row for row in rows if row["id"] == str(card_id))


def _llm_calls(live_stack: LiveStack) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(session.engine_for(live_stack.database_url)) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))


def _preferences(live_stack: LiveStack) -> list[models.CardPreference]:
    with sqlalchemy.orm.Session(session.engine_for(live_stack.database_url)) as db:
        return list(db.scalars(sqlalchemy.select(models.CardPreference)))
