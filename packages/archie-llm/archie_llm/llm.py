"""Every model call goes through `complete`: it falls back to a second model and records each call's cost.

Calls made outside `complete` (the chat's tool loop, OpenAI embeddings) record their cost with `record_call` and
`record_embedding_call`.

Shared by the worker and the API.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import anthropic
import sqlalchemy
import sqlalchemy.orm
from archie_db import models
from archie_shared import logging

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"

PROVIDER = "anthropic"
OPENAI_PROVIDER = "openai"
CORRECTIONS_STEP = "corrections"
GRADE_STEP = "grade"
CARE_STEP = "care"
ANSWER_TRANSCRIPTION_STEP = "transcribe_answer"
EMBED_STEP = "embed"
ASK_STEP = "ask"
CARD_DRAFT_STEP = "card_draft"
GROQ_WHISPER = "whisper-large-v3-turbo"
OPENAI_TRANSCRIBE = "gpt-4o-mini-transcribe"
EMBEDDING_MODEL = "text-embedding-3-small"
REQUEST_TIMEOUT_SECONDS = 300

# Statuses from this one up (including Anthropic's 529 "overloaded") are the service's fault: the fallback gets a turn.
_FIRST_SERVER_ERROR_STATUS = 500

# Stop reasons that mean the model did not deliver a usable answer, so the fallback model gets a turn.
_UNUSABLE_STOP_REASONS = frozenset({"refusal", "max_tokens"})

_TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)

_logger = logging.get_logger(logging.LoggerName.LLM, "llm")


@dataclass(frozen=True)
class ModelPair:
    """A step's model and the stronger one to try when the first gives no usable answer."""

    primary: str
    # None for a step that tries one model only.
    fallback: str | None = None


ANALYZE_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
PRIMER_MODELS = ModelPair(primary=SONNET, fallback=OPUS)
CORRECTIONS_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
FILE_TOPIC_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
CLEAN_TEXT_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
BRIEF_MODELS = ModelPair(primary=SONNET, fallback=OPUS)
GRADE_MODELS = ModelPair(primary=HAIKU)
CARE_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
NEWS_QUIZ_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)

# Writing quality matters for a cleaned-up take; its cards are short and checked against the owner's own text.
CLEAN_TAKE_MODELS = ModelPair(primary=SONNET, fallback=OPUS)
TAKE_CARDS_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
CARD_DRAFT_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
NOTE_CARDS_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)

# For short, latency-sensitive calls where reasoning would only add delay.
THINKING_DISABLED: dict[str, str] = {"type": "disabled"}


@dataclass(frozen=True)
class _Price:
    input_per_million: Decimal
    output_per_million: Decimal


# USD per million tokens.
_PRICES: dict[str, _Price] = {
    HAIKU: _Price(input_per_million=Decimal("0.10"), output_per_million=Decimal("0.50")),
    SONNET: _Price(input_per_million=Decimal("2"), output_per_million=Decimal("10")),
    OPUS: _Price(input_per_million=Decimal("4"), output_per_million=Decimal("20")),
    EMBEDDING_MODEL: _Price(input_per_million=Decimal("0.02"), output_per_million=Decimal("0")),
}

# USD per web search Anthropic's server tool runs ($10 per 1,000).
WEB_SEARCH_USD = Decimal("0.01")


# USD per hour of audio.
_AUDIO_PRICES_PER_HOUR: dict[str, Decimal] = {
    GROQ_WHISPER: Decimal("0.04"),
    OPENAI_TRANSCRIBE: Decimal("0.18"),
}

_SECONDS_PER_HOUR = Decimal(3600)


@dataclass(frozen=True)
class CallContext:
    """Whom and what a call is for, stored on its cost record."""

    user_id: int
    # None for calls that belong to no source, such as a topic primer.
    source_id: uuid.UUID | None
    # None for calls that belong to no job, such as the API's.
    job_id: int | None
    # A `JobKind` value, or a sub-step name such as `CORRECTIONS_STEP` or `GRADE_STEP`.
    step: str


@dataclass(frozen=True)
class Completion:
    """The model that produced the answer and its text (the JSON string for schema calls)."""

    model: str
    text: str


class ModelOutputError(Exception):
    """Every model tried stopped on a refusal or the output cap, so there is no usable answer."""


def cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Dollar cost of one call; raises `KeyError` for a model without a known price."""
    price = _PRICES[model]
    return (price.input_per_million * input_tokens + price.output_per_million * output_tokens) / _TOKENS_PER_PRICE_UNIT


def audio_cost_usd(*, model: str, audio_seconds: Decimal) -> Decimal:
    """Dollar cost of transcribing `audio_seconds` of audio; raises `KeyError` for a model without a known price."""
    return _AUDIO_PRICES_PER_HOUR[model] * audio_seconds / _SECONDS_PER_HOUR


def complete(
    engine: sqlalchemy.Engine,
    *,
    api_key: str,
    context: CallContext,
    models: ModelPair,
    system: str,
    user_message: str,
    max_tokens: int,
    json_schema: dict[str, Any] | None = None,
    thinking: Mapping[str, Any] | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> Completion:
    """Ask `models.primary`, then `models.fallback` if it refused, ran out of tokens, or the service failed it.

    A service failure is a 5xx/529 answer or a connection error; a failure of the fallback is re-raised for the worker
    loop to retry, as is any other API error (a 4xx would fail the fallback the same way). Every answered call is
    recorded.

    `models.fallback` is optional: a pair without one tries only the primary. `thinking` holds extended-thinking
    options (e.g. `THINKING_DISABLED`), passed to `messages.create` only when given. `timeout_seconds` is the
    Anthropic client timeout, `REQUEST_TIMEOUT_SECONDS` by default.
    """
    # No SDK retries: the worker loop owns retrying, so a failed call is not silently billed twice.
    client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=timeout_seconds)
    output_options: dict[str, Any] = (
        {"output_config": {"format": {"type": "json_schema", "schema": json_schema}}} if json_schema else {}
    )

    # `models` is the ModelPair parameter here, shadowing the `archie_db.models` module inside this function.
    attempts = [model for model in (models.primary, models.fallback) if model is not None]
    thinking_options: dict[str, Any] = {"thinking": dict(thinking)} if thinking else {}
    for attempt, model in enumerate(attempts):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
                **output_options,
                **thinking_options,
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as error:
            if not _is_service_failure(error) or attempt == len(attempts) - 1:
                raise

            _logger.warning("%s failed for %s, trying %s: %r", model, context.step, models.fallback, error)
            continue

        record_call(engine, context=context, model=model, response=response)

        if response.stop_reason not in _UNUSABLE_STOP_REASONS:
            return Completion(model=model, text=_text_of(response))

        _logger.warning("%s stopped on %s for %s", model, response.stop_reason, context.step)

    raise ModelOutputError(f"{' and '.join(attempts)} gave no usable answer")


def record_audio_call(
    engine: sqlalchemy.Engine,
    *,
    context: CallContext,
    provider: models.TranscriptProvider,
    model: str,
    audio_seconds: Decimal,
) -> None:
    """Record one transcription call's cost in its own session, so the spend is kept even if the step fails later."""
    row = models.LlmCall(
        user_id=context.user_id,
        source_id=context.source_id,
        job_id=context.job_id,
        step=str(context.step),
        provider=provider.value,
        model=model,
        input_tokens=0,
        output_tokens=0,
        cost_usd=audio_cost_usd(model=model, audio_seconds=audio_seconds),
        stop_reason=None,
        audio_seconds=audio_seconds,
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.add(row)
        db.commit()


def record_call(
    engine: sqlalchemy.Engine, *, context: CallContext, model: str, response: anthropic.types.Message
) -> None:
    """Record one answered call in its own session, so the spend is kept even if the step fails afterwards.

    Web searches the call ran (Anthropic's server tool) are added at `WEB_SEARCH_USD` each.
    """
    usage = response.usage
    searches = usage.server_tool_use.web_search_requests if usage.server_tool_use is not None else 0
    token_cost = cost_usd(model=model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
    row = models.LlmCall(
        user_id=context.user_id,
        source_id=context.source_id,
        job_id=context.job_id,
        step=str(context.step),
        provider=PROVIDER,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=token_cost + WEB_SEARCH_USD * searches,
        stop_reason=response.stop_reason,
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.add(row)
        db.commit()


def record_embedding_call(engine: sqlalchemy.Engine, *, context: CallContext, tokens: int) -> None:
    """Record one OpenAI embeddings request, billed by its input tokens."""
    row = models.LlmCall(
        user_id=context.user_id,
        source_id=context.source_id,
        job_id=context.job_id,
        step=str(context.step),
        provider=OPENAI_PROVIDER,
        model=EMBEDDING_MODEL,
        input_tokens=tokens,
        output_tokens=0,
        cost_usd=cost_usd(model=EMBEDDING_MODEL, input_tokens=tokens, output_tokens=0),
        stop_reason=None,
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.add(row)
        db.commit()


def _is_service_failure(error: anthropic.APIStatusError | anthropic.APIConnectionError) -> bool:
    if isinstance(error, anthropic.APIConnectionError):
        return True
    return error.status_code >= _FIRST_SERVER_ERROR_STATUS


def _text_of(response: anthropic.types.Message) -> str:
    return "".join(block.text for block in response.content if block.type == "text")
