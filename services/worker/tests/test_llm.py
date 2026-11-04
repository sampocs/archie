"""Model calls: prices, key selection, and the primary/fallback flow against recorded Anthropic responses.

Re-record with `uv run pytest services/worker/tests/test_llm.py --record-mode=once -m postgres` after deleting a
cassette. `llm_fallback.yaml` can't come from one `complete` call (both models stop at the same token cap on the
same prompt), so it holds two real recordings in order: Haiku capped at 1 token (stops on `max_tokens`), then Sonnet
at 16 (`end_turn`). Replay matching ignores `max_tokens`, so `complete` is served Haiku's truncated reply and then
Sonnet's.
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any

import anthropic
import httpx2
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session
from archie_shared import config
from archie_testing import recording
from archie_worker import errors, llm

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

SYSTEM_PROMPT = "Reply with the word ok."
USER_MESSAGE = "hi"
ENOUGH_TOKENS = 16
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

Cassette = Callable[[str], AbstractContextManager[Any]]


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


@pytest.fixture
def cassette(request: pytest.FixtureRequest) -> Cassette:
    """Returns `cassette(name)`: the recorded Anthropic HTTP for one test."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    return lambda name: recorder.use_cassette(f"{name}.yaml")


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def context(engine: sqlalchemy.Engine) -> llm.CallContext:
    """A real user, source and job for the cost records to point at."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        db.add(
            models.Source(
                id=source_id,
                user_id=user.id,
                url="https://example.com/",
                normalized_url="https://example.com/",
                kind=models.SourceKind.LINK.value,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                change_seq=changes.next_change_seq(),
            )
        )
        job = jobs.enqueue(db, kind=models.JobKind.ANALYZE, user_id=user.id, payload={})
        db.commit()
        return llm.CallContext(user_id=user.id, source_id=source_id, job_id=job.id, step=models.JobKind.ANALYZE)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (llm.HAIKU, Decimal("0.60")),
        (llm.SONNET, Decimal("12")),
        (llm.OPUS, Decimal("24")),
    ],
)
def test_cost_is_priced_per_million_tokens(model: str, expected: Decimal) -> None:
    """A million tokens each way costs the model's input price plus its output price."""
    assert llm.cost_usd(model=model, input_tokens=1_000_000, output_tokens=1_000_000) == expected


def test_cost_scales_input_and_output_separately() -> None:
    """Input and output tokens use their own prices."""
    assert llm.cost_usd(model=llm.SONNET, input_tokens=500_000, output_tokens=0) == Decimal("1")
    assert llm.cost_usd(model=llm.SONNET, input_tokens=0, output_tokens=500_000) == Decimal("5")


def test_unknown_model_has_no_price() -> None:
    """An unpriced model fails loudly rather than recording a zero cost."""
    with pytest.raises(KeyError):
        llm.cost_usd(model="claude-mystery", input_tokens=1, output_tokens=1)


def test_audio_is_priced_per_audio_hour() -> None:
    """Audio is billed per audio hour, per provider."""
    assert llm.audio_cost_usd(model=llm.GROQ_WHISPER, audio_seconds=Decimal(3600)) == Decimal("0.04")
    assert llm.audio_cost_usd(model=llm.OPENAI_TRANSCRIBE, audio_seconds=Decimal(1800)) == Decimal("0.09")


def test_unknown_audio_model_has_no_price() -> None:
    """A transcription model without a known price raises, like an unknown chat model."""
    with pytest.raises(KeyError):
        llm.audio_cost_usd(model="whisper-9000", audio_seconds=Decimal(60))


@pytest.mark.postgres
def test_record_audio_call_stores_an_audio_cost_row(engine: sqlalchemy.Engine, context: llm.CallContext) -> None:
    """One call writes one row: no tokens, the audio length, and its cost."""
    transcribe_context = llm.CallContext(
        user_id=context.user_id, source_id=context.source_id, job_id=context.job_id, step=models.JobKind.TRANSCRIBE
    )

    llm.record_audio_call(
        engine,
        context=transcribe_context,
        provider=models.TranscriptProvider.GROQ,
        model=llm.GROQ_WHISPER,
        audio_seconds=Decimal("90.5"),
    )

    (row,) = _calls(engine)
    assert (row.input_tokens, row.output_tokens, row.stop_reason) == (0, 0, None)
    assert (row.audio_seconds, row.provider, row.step) == (Decimal("90.500"), "groq", "transcribe")
    assert row.cost_usd > 0


def test_user_without_the_owners_keys_needs_their_own() -> None:
    """A non-whitelisted user's job fails for good, telling them to add their own key."""
    with pytest.raises(errors.PermanentJobError) as raised:
        llm.api_key_for(models.User(apple_sub="sub", is_whitelisted=False))

    assert raised.value.reason == errors.FailureReason.NEEDS_API_KEY


def test_whitelisted_user_gets_the_owners_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A whitelisted user's calls are paid by the configured key."""
    monkeypatch.setenv(config.ANTHROPIC_API_KEY_ENV, "owner-key")

    assert llm.api_key_for(models.User(apple_sub="sub", is_whitelisted=True)) == "owner-key"


@pytest.mark.postgres
def test_primary_answer_is_returned_and_costed(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette
) -> None:
    """A normal reply comes from the primary model and leaves exactly one priced record."""
    with cassette("llm_ok"):
        completion = _complete(engine, context, llm.ModelPair(llm.HAIKU, llm.SONNET), max_tokens=ENOUGH_TOKENS)

    assert completion.model == llm.HAIKU
    assert completion.text.strip().lower().startswith("ok")

    [call] = _calls(engine)
    assert call.model == llm.HAIKU
    assert call.provider == "anthropic"
    assert call.stop_reason == "end_turn"
    assert call.input_tokens > 0
    assert call.output_tokens > 0
    assert call.cost_usd == llm.cost_usd(
        model=llm.HAIKU, input_tokens=call.input_tokens, output_tokens=call.output_tokens
    ).quantize(Decimal("0.000001"))
    assert (call.user_id, call.source_id, call.job_id, call.step) == (
        context.user_id,
        context.source_id,
        context.job_id,
        models.JobKind.ANALYZE.value,
    )


@pytest.mark.postgres
def test_schema_call_sends_the_schema_and_returns_json(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a JSON schema, the request asks for structured output and the text is the JSON string."""
    # Replay ignores what is sent, so watch the real outgoing arguments.
    sent: list[dict[str, Any]] = []
    real_create = anthropic.resources.messages.Messages.create

    def spy_create(self: Any, **kwargs: Any) -> Any:
        sent.append(kwargs)
        return real_create(self, **kwargs)

    monkeypatch.setattr(anthropic.resources.messages.Messages, "create", spy_create)

    with cassette("llm_schema"):
        completion = _complete(
            engine,
            context,
            llm.ModelPair(llm.HAIKU, llm.SONNET),
            max_tokens=ENOUGH_TOKENS * 4,
            json_schema=ANSWER_SCHEMA,
        )

    [kwargs] = sent
    assert kwargs["output_config"] == {"format": {"type": "json_schema", "schema": ANSWER_SCHEMA}}
    assert "answer" in json.loads(completion.text)


@pytest.mark.postgres
def test_fallback_model_answers_when_the_primary_is_cut_off(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette
) -> None:
    """A primary that stops on max_tokens hands over to the fallback, and both calls are recorded."""
    with cassette("llm_fallback"):
        completion = _complete(engine, context, llm.ModelPair(llm.HAIKU, llm.SONNET), max_tokens=ENOUGH_TOKENS)

    assert completion.model == llm.SONNET
    assert completion.text.strip().lower().startswith("ok")
    assert [(call.model, call.stop_reason) for call in _calls(engine)] == [
        (llm.HAIKU, "max_tokens"),
        (llm.SONNET, "end_turn"),
    ]


@pytest.mark.postgres
def test_both_models_cut_off_is_a_model_output_error(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette
) -> None:
    """When the fallback stops the same way, the call fails, and the spend on both is still recorded."""
    with cassette("llm_max_tokens"), pytest.raises(llm.ModelOutputError):
        _complete(engine, context, llm.ModelPair(llm.HAIKU, llm.HAIKU), max_tokens=1)

    calls = _calls(engine)
    assert [call.stop_reason for call in calls] == ["max_tokens", "max_tokens"]
    assert all(call.cost_usd > 0 for call in calls)


@pytest.mark.postgres
def test_fallback_model_answers_when_the_primary_is_overloaded(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette
) -> None:
    """A 529 from the primary hands over to the fallback; only the answered call is recorded.

    The cassette is the `llm_fallback` one with its first response replaced by Anthropic's 529 error body.
    """
    with cassette("llm_overloaded"):
        completion = _complete(engine, context, llm.ModelPair(llm.HAIKU, llm.SONNET), max_tokens=ENOUGH_TOKENS)

    assert completion.model == llm.SONNET
    assert [(call.model, call.stop_reason) for call in _calls(engine)] == [(llm.SONNET, "end_turn")]


@pytest.mark.postgres
def test_an_overloaded_fallback_is_raised_for_the_loop_to_retry(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette
) -> None:
    """When the fallback answers 529 too, the error surfaces instead of being swallowed."""
    with cassette("llm_overloaded_twice"), pytest.raises(anthropic.APIStatusError) as raised:
        _complete(engine, context, llm.ModelPair(llm.HAIKU, llm.SONNET), max_tokens=ENOUGH_TOKENS)

    assert raised.value.status_code == 529
    assert _calls(engine) == []


@pytest.mark.postgres
def test_a_client_error_from_the_primary_does_not_try_the_fallback(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette
) -> None:
    """A 401 would fail the fallback the same way, so it is raised at once (the cassette holds a single call)."""
    with cassette("llm_unauthorized"), pytest.raises(anthropic.AuthenticationError):
        _complete(engine, context, llm.ModelPair(llm.HAIKU, llm.SONNET), max_tokens=ENOUGH_TOKENS)

    assert _calls(engine) == []


@pytest.mark.postgres
def test_a_dropped_connection_to_the_primary_tries_the_fallback(
    engine: sqlalchemy.Engine, context: llm.CallContext, cassette: Cassette, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The primary's request never reaches the API (a connection error); the fallback's recorded answer is used."""
    create = anthropic.resources.messages.Messages.create

    def create_unless_primary(self: Any, **kwargs: Any) -> Any:
        if kwargs["model"] == llm.HAIKU:
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        return create(self, **kwargs)

    monkeypatch.setattr(anthropic.resources.messages.Messages, "create", create_unless_primary)

    with cassette("llm_overloaded"):
        completion = _complete(engine, context, llm.ModelPair(llm.HAIKU, llm.SONNET), max_tokens=ENOUGH_TOKENS)

    assert completion.model == llm.SONNET


def _complete(
    engine: sqlalchemy.Engine,
    context: llm.CallContext,
    model_pair: llm.ModelPair,
    *,
    max_tokens: int,
    json_schema: dict[str, Any] | None = None,
) -> llm.Completion:
    return llm.complete(
        engine,
        api_key=os.environ[config.ANTHROPIC_API_KEY_ENV],
        context=context,
        models=model_pair,
        system=SYSTEM_PROMPT,
        user_message=USER_MESSAGE,
        max_tokens=max_tokens,
        json_schema=json_schema,
    )


def _calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
