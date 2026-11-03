"""Every model call goes through `complete`: it falls back to a second model and records each call's cost."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import anthropic
import sqlalchemy
import sqlalchemy.orm
from archie_db import models
from archie_shared import config, logging

from archie_worker import errors

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"

PROVIDER = "anthropic"
REQUEST_TIMEOUT_SECONDS = 300

# Stop reasons that mean the model did not deliver a usable answer, so the fallback model gets a turn.
_UNUSABLE_STOP_REASONS = frozenset({"refusal", "max_tokens"})

_TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)

_logger = logging.get_logger(logging.LoggerName.WORKER, "llm")


@dataclass(frozen=True)
class ModelPair:
    """A step's model and the stronger one to try when the first gives no usable answer."""

    primary: str
    fallback: str


ANALYZE_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
PRIMER_MODELS = ModelPair(primary=SONNET, fallback=OPUS)


@dataclass(frozen=True)
class _Price:
    input_per_million: Decimal
    output_per_million: Decimal


# USD per million tokens.
_PRICES: dict[str, _Price] = {
    HAIKU: _Price(input_per_million=Decimal("0.10"), output_per_million=Decimal("0.50")),
    SONNET: _Price(input_per_million=Decimal("2"), output_per_million=Decimal("10")),
    OPUS: _Price(input_per_million=Decimal("4"), output_per_million=Decimal("20")),
}


@dataclass(frozen=True)
class CallContext:
    """Whom and what a call is for, stored on its cost record."""

    user_id: int
    source_id: uuid.UUID
    job_id: int
    step: models.JobKind


@dataclass(frozen=True)
class Completion:
    """The model that produced the answer and its text (the JSON string for schema calls)."""

    model: str
    text: str


class ModelOutputError(Exception):
    """Both models stopped on a refusal or the output cap, so there is no usable answer."""


def cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Dollar cost of one call; raises `KeyError` for a model without a known price."""
    price = _PRICES[model]
    return (price.input_per_million * input_tokens + price.output_per_million * output_tokens) / _TOKENS_PER_PRICE_UNIT


def api_key_for(user: models.User) -> str:
    """The key that pays for this user's calls: the owner's for whitelisted users, otherwise they need their own."""
    if not user.is_whitelisted:
        raise errors.PermanentJobError(errors.FailureReason.NEEDS_API_KEY)

    return config.Settings().require_anthropic_api_key()


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
) -> Completion:
    """Ask `models.primary`, then `models.fallback` if it refused or ran out of tokens; record every call."""
    # No SDK retries: the worker loop owns retrying, so a failed call is not silently billed twice.
    client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)
    output_options: dict[str, Any] = (
        {"output_config": {"format": {"type": "json_schema", "schema": json_schema}}} if json_schema else {}
    )

    for model in (models.primary, models.fallback):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
            **output_options,
        )
        _record_call(engine, context=context, model=model, response=response)

        if response.stop_reason not in _UNUSABLE_STOP_REASONS:
            return Completion(model=model, text=_text_of(response))

        _logger.warning("%s stopped on %s for job %d", model, response.stop_reason, context.job_id)

    raise ModelOutputError(f"{models.primary} and {models.fallback} both gave no usable answer")


def _record_call(
    engine: sqlalchemy.Engine, *, context: CallContext, model: str, response: anthropic.types.Message
) -> None:
    # Committed on its own so the spend is kept even if the step fails afterwards.
    usage = response.usage
    row = models.LlmCall(
        user_id=context.user_id,
        source_id=context.source_id,
        job_id=context.job_id,
        step=context.step.value,
        provider=PROVIDER,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost_usd(model=model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens),
        stop_reason=response.stop_reason,
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.add(row)
        db.commit()


def _text_of(response: anthropic.types.Message) -> str:
    return "".join(block.text for block in response.content if block.type == "text")
