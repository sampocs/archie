"""Review routes: grade a recalled answer, transcribe a spoken one, and rewrite a card around a learner's note.

Each costs the owner's keys, so only whitelisted users may call them. None holds a transaction open across an outside
call: the card is read into locals and committed first, as the worker's handlers do.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, TypeVar

import anthropic
import fastapi
import httpx
import pydantic
import sqlalchemy
from archie_db import card_rows, changes, models
from archie_llm import llm, speech
from archie_shared import config, logging
from fastapi.routing import APIRoute
from sqlalchemy import orm

from archie_api import deps
from archie_api.review import prompts
from archie_api.sync import schemas

GRADE_MAX_TOKENS = 1500
GRADE_TIMEOUT_SECONDS = 10
CARE_MAX_TOKENS = 1500
MAX_AUDIO_BYTES = 5_000_000
MULTIPART_OVERHEAD_BYTES = 64_000
MAX_AUDIO_MS = 125_000
MAX_PROMPT_CHARACTERS = 800

_AUDIO_FILENAME = "answer.m4a"
_AUDIO_MEDIA_TYPE = "audio/m4a"
_NEEDS_KEY = "needs your own API key"
_MILLISECONDS_PER_SECOND = 1000


class _BoundedUploadRoute(APIRoute):
    """A route that refuses a request whose declared size is missing or too big before its body is parsed.

    Starlette spools a whole multipart body to disk while parsing it, and does so before any dependency runs, so the
    size has to be judged from `Content-Length` here, ahead of the form parsing, not from the bytes read afterwards.
    """

    def get_route_handler(self) -> Callable[[fastapi.Request], Coroutine[Any, Any, fastapi.Response]]:
        """Wrap the stock handler with the size check."""
        handle = super().get_route_handler()

        async def handle_bounded(request: fastapi.Request) -> fastapi.Response:
            declared = request.headers.get("content-length", "")
            if not declared.isdigit() or int(declared) > MAX_AUDIO_BYTES + MULTIPART_OVERHEAD_BYTES:
                raise fastapi.HTTPException(status_code=413, detail="recording too large")
            return await handle(request)

        return handle_bounded


_Output = TypeVar("_Output", bound=pydantic.BaseModel)

router = fastapi.APIRouter(prefix="/review", tags=["review"])
_upload_router = fastapi.APIRouter(tags=["review"], route_class=_BoundedUploadRoute)
_logger = logging.get_logger(logging.LoggerName.API, "review")


class GradeRequest(pydantic.BaseModel):
    """The learner's typed or dictated answer to a card."""

    card_id: uuid.UUID
    answer: str = pydantic.Field(min_length=1, max_length=4000)


class GradeView(pydantic.BaseModel):
    """The verdict; `missing` is empty for got_it."""

    grade: models.ReviewGrade
    missing: str


class CareRequest(pydantic.BaseModel):
    """What the learner says matters to them about a card."""

    note: str = pydantic.Field(min_length=1, max_length=500)


class TranscriptView(pydantic.BaseModel):
    """What the learner said."""

    text: str


class _Verdict(pydantic.BaseModel):
    """The model's grading JSON."""

    grade: models.ReviewGrade
    missing: str
    confident: bool


class _CareAnswer(pydantic.BaseModel):
    """The model's rewritten accepted answer."""

    answer: str = pydantic.Field(min_length=1)


@dataclass(frozen=True)
class _SpeechKeys:
    """The owner's transcription keys; at least one is set."""

    groq: str | None
    openai: str | None


@router.post("/grade")
def grade(
    body: GradeRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> GradeView:
    """Grade an answer on the idea, not the wording; one Haiku call (the phone's timeout is the fallback)."""
    card = _card_or_404(db, user=user, card_id=body.card_id)
    api_key = _owner_anthropic_key(user)
    context = llm.CallContext(user_id=user.id, source_id=card.source_id, job_id=None, step=llm.GRADE_STEP)
    user_message = prompts.grade_message(question=card.question, accepted=card.answer, answer=body.answer)
    engine = _engine(db)

    # No transaction is held during the model call.
    db.commit()

    verdict = _complete_or_502(
        engine,
        output=_Verdict,
        api_key=api_key,
        context=context,
        models=llm.GRADE_MODELS,
        system=prompts.GRADE_SYSTEM,
        user_message=user_message,
        max_tokens=GRADE_MAX_TOKENS,
        json_schema=prompts.GRADE_SCHEMA,
        thinking=llm.THINKING_DISABLED,
        timeout_seconds=GRADE_TIMEOUT_SECONDS,
        failure="grading failed",
    )
    missing = "" if verdict.grade == models.ReviewGrade.GOT_IT else verdict.missing
    return GradeView(grade=verdict.grade, missing=missing)


@_upload_router.post("/transcribe")
def transcribe(
    card_id: Annotated[uuid.UUID, fastapi.Form()],
    duration_ms: Annotated[int, fastapi.Form(ge=1)],
    audio: fastapi.UploadFile,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> TranscriptView:
    """Turn a spoken answer into text, primed with the card's own words so terms of art come out right."""
    if duration_ms > MAX_AUDIO_MS:
        raise fastapi.HTTPException(status_code=413, detail="recording too long")

    # A backstop: the route class already judged the declared size, which a client can understate.
    audio_bytes = audio.file.read(MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise fastapi.HTTPException(status_code=413, detail="recording too large")

    card = _card_or_404(db, user=user, card_id=card_id)
    _require_whitelisted(user)
    keys = _speech_keys()
    context = llm.CallContext(
        user_id=user.id, source_id=card.source_id, job_id=None, step=llm.ANSWER_TRANSCRIPTION_STEP
    )
    prompt = f"{card.question} {card.answer}"[:MAX_PROMPT_CHARACTERS]
    engine = _engine(db)

    # No transaction is held during the provider calls.
    db.commit()

    text = _transcribe(
        engine,
        audio=audio_bytes,
        keys=keys,
        prompt=prompt,
        context=context,
        audio_seconds=Decimal(duration_ms) / _MILLISECONDS_PER_SECOND,
    )
    return TranscriptView(text=text)


# Included once the route is declared (include copies the routes present now); the prefix applies here.
router.include_router(_upload_router)


@router.post("/cards/{card_id}/care")
def care(
    card_id: uuid.UUID,
    body: CareRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.CardOut:
    """Rewrite the card's answer around what the learner cares about, and remember the note for future cards."""
    card = _card_or_404(db, user=user, card_id=card_id)
    api_key = _owner_anthropic_key(user)
    context = llm.CallContext(user_id=user.id, source_id=card.source_id, job_id=None, step=llm.CARE_STEP)
    user_message = prompts.care_message(question=card.question, accepted=card.answer, note=body.note)
    engine = _engine(db)

    # No transaction is held during the model call.
    db.commit()

    rewritten = _complete_or_502(
        engine,
        output=_CareAnswer,
        api_key=api_key,
        context=context,
        models=llm.CARE_MODELS,
        system=prompts.CARE_SYSTEM,
        user_message=user_message,
        max_tokens=CARE_MAX_TOKENS,
        json_schema=prompts.CARE_SCHEMA,
        failure="rewrite failed",
    )

    # The card may have been dropped while the model worked, so it is read again under the user's write lock.
    changes.lock_user_writes(db, user.id)
    live_card = _card_or_404(db, user=user, card_id=card_id)
    live_card.answer = rewritten.answer
    live_card.updated_at = sqlalchemy.func.now()
    live_card.change_seq = changes.next_change_seq()
    db.add(
        models.CardPreference(
            user_id=user.id, card_id=live_card.id, kind=models.CardPreferenceKind.CARE, note=body.note
        )
    )
    db.commit()
    db.refresh(live_card)
    return schemas.CardOut.model_validate(live_card)


def _card_or_404(db: orm.Session, *, user: models.User, card_id: uuid.UUID) -> models.Card:
    card = card_rows.owned_live_card(db, user_id=user.id, card_id=card_id)
    if card is None:
        raise fastapi.HTTPException(status_code=404, detail="card not found")
    return card


def _owner_anthropic_key(user: models.User) -> str:
    """The owner's Anthropic key, for whitelisted users only: grading and rewriting spend it."""
    _require_whitelisted(user)
    return config.Settings().require_anthropic_api_key()


def _require_whitelisted(user: models.User) -> None:
    """Refuse (403) a user without the owner's blessing: every route here spends the owner's keys."""
    if not user.is_whitelisted:
        raise fastapi.HTTPException(status_code=403, detail=_NEEDS_KEY)


def _speech_keys() -> _SpeechKeys:
    settings = config.Settings()
    keys = _SpeechKeys(groq=settings.groq_api_key or None, openai=settings.openai_api_key or None)
    if keys.groq is None and keys.openai is None:
        raise fastapi.HTTPException(status_code=503, detail="transcription isn't set up")
    return keys


def _engine(db: orm.Session) -> sqlalchemy.Engine:
    """The engine behind `db`, so a model call can record its cost on its own connection."""
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    return engine


def _complete_or_502(engine: sqlalchemy.Engine, *, output: type[_Output], failure: str, **options: Any) -> _Output:
    """`llm.complete` parsed as `output`, with any provider, output or validation failure turned into a 502.

    The phone falls back on any failure, so output the schema didn't hold to is the same 502 as a provider error.
    """
    try:
        completion = llm.complete(engine, **options)
        return output.model_validate_json(completion.text)
    except (anthropic.APIError, llm.ModelOutputError, pydantic.ValidationError) as error:
        _logger.warning("%s: %r", failure, error)
        raise fastapi.HTTPException(status_code=502, detail=failure) from error


def _transcribe(
    engine: sqlalchemy.Engine,
    *,
    audio: bytes,
    keys: _SpeechKeys,
    prompt: str,
    context: llm.CallContext,
    audio_seconds: Decimal,
) -> str:
    """Groq Whisper first; OpenAI when Groq refuses, fails or isn't configured. Each answered call is recorded."""
    if keys.groq is not None:
        groq_text = _groq_text(audio=audio, api_key=keys.groq, prompt=prompt)
        if groq_text is not None:
            llm.record_audio_call(
                engine,
                context=context,
                provider=models.TranscriptProvider.GROQ,
                model=llm.GROQ_WHISPER,
                audio_seconds=audio_seconds,
            )
            return groq_text

    if keys.openai is None:
        raise fastapi.HTTPException(status_code=502, detail="transcription failed")

    try:
        response = speech.post_openai(
            audio=audio, filename=_AUDIO_FILENAME, media_type=_AUDIO_MEDIA_TYPE, api_key=keys.openai, prompt=prompt
        )
    except httpx.HTTPError as error:
        _logger.warning("OpenAI transcription failed: %r", error)
        raise fastapi.HTTPException(status_code=502, detail="transcription failed") from error

    openai_text = _response_text(response) if response.is_success else None
    if openai_text is None:
        raise fastapi.HTTPException(status_code=502, detail="transcription failed")

    llm.record_audio_call(
        engine,
        context=context,
        provider=models.TranscriptProvider.OPENAI,
        model=llm.OPENAI_TRANSCRIBE,
        audio_seconds=audio_seconds,
    )
    return openai_text


def _response_text(response: httpx.Response) -> str | None:
    """The `text` of a provider's JSON answer, or None when the body isn't that."""
    try:
        return str(response.json()["text"]).strip()
    except (ValueError, KeyError, TypeError) as error:
        _logger.warning("Transcription answer had no text: %r", error)
        return None


def _groq_text(*, audio: bytes, api_key: str, prompt: str) -> str | None:
    """Groq's transcript, or None when it refuses or can't be reached: OpenAI is the fallback, as in the pipeline."""
    try:
        response = speech.post_groq(
            audio=audio,
            filename=_AUDIO_FILENAME,
            media_type=_AUDIO_MEDIA_TYPE,
            api_key=api_key,
            prompt=prompt,
            response_format="json",
        )
    except httpx.HTTPError as error:
        _logger.warning("Groq transcription failed, falling back to OpenAI: %r", error)
        return None

    if not response.is_success:
        _logger.warning("Groq answered %s, falling back to OpenAI", response.status_code)
        return None
    return _response_text(response)
