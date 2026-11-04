"""Podcast audio to timed text: download the enclosure, cut it into chunks with ffmpeg, and transcribe each chunk.

Groq's Whisper does the work; OpenAI redoes a chunk Groq rejects or under-transcribes (Whisper sometimes skips
long passages). Both are called over plain httpx. Every successful call records its cost in `llm_calls`.
"""

from __future__ import annotations

import pathlib
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import httpx
import sqlalchemy
from archie_db import models
from archie_shared import config, logging

from archie_worker import content, errors, llm

CHUNK_SECONDS = 600
OPENAI_PART_SECONDS = 300
DOWNLOAD_TIMEOUT_SECONDS = 600
MAX_AUDIO_BYTES = 600_000_000
MIN_WORDS_PER_MINUTE = 100
MIN_CHECKED_CHUNK_SECONDS = 30
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"

# Each read of the download may wait this long; the whole download is bounded by `DOWNLOAD_TIMEOUT_SECONDS`.
_READ_TIMEOUT_SECONDS = 60
_GROQ_DEFAULT_RETRY_AFTER_SECONDS = 60
_CHUNK_PREFIX = "chunk"
_AUDIO_MEDIA_TYPE = "audio/mpeg"
_LANGUAGE = "en"
_SECONDS_PER_MINUTE = 60
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_CLIENT_ERRORS = range(400, 500)

_logger = logging.get_logger(logging.LoggerName.WORKER, "transcription")


@dataclass(frozen=True)
class TranscriptionKeys:
    """The speech-to-text keys that pay for a user's transcription; at least one is set."""

    groq: str | None
    openai: str | None


@dataclass(frozen=True)
class AudioChunk:
    """One slice of an episode's audio; `start_seconds` is where it begins in the whole episode."""

    index: int
    path: pathlib.Path
    start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class ChunkTranscript:
    """A chunk's segments (absolute episode times) and the provider and model that produced them."""

    provider: models.TranscriptProvider
    model: str
    segments: list[content.Segment]


class GroqRejectedError(Exception):
    """Groq answered with a client error other than a rate limit, so retrying the same request won't help."""


def keys_for(user: models.User) -> TranscriptionKeys:
    """The owner's transcription keys for whitelisted users; raises `PermanentJobError` when there are none to use."""
    if not user.is_whitelisted:
        raise errors.PermanentJobError(errors.FailureReason.NEEDS_API_KEY)

    settings = config.Settings()
    keys = TranscriptionKeys(groq=settings.groq_api_key or None, openai=settings.openai_api_key or None)
    if keys.groq is None and keys.openai is None:
        raise errors.PermanentJobError(errors.FailureReason.TRANSCRIPTION_NOT_SET_UP)
    return keys


def download(*, url: str, directory: pathlib.Path) -> pathlib.Path:
    """Stream the audio at `url` into `directory`; raises `PermanentJobError` past `MAX_AUDIO_BYTES`.

    httpx's timeout applies to each read, so the total deadline is checked per chunk (as `fetch_title.fetch_page`
    does) to stop a trickling server from holding the worker; the loop retries the `TimeoutError`.
    """
    path = directory / "episode.audio"
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
    with httpx.Client(timeout=_READ_TIMEOUT_SECONDS, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()

            # A declared length over the cap fails before any of the audio is read.
            declared_bytes = int(response.headers.get("content-length") or 0)
            if declared_bytes > MAX_AUDIO_BYTES:
                raise errors.PermanentJobError(errors.FailureReason.EPISODE_TOO_LONG)

            received_bytes = 0
            with path.open("wb") as audio_file:
                for block in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Downloading {url} took longer than {DOWNLOAD_TIMEOUT_SECONDS}s")
                    received_bytes += len(block)
                    if received_bytes > MAX_AUDIO_BYTES:
                        raise errors.PermanentJobError(errors.FailureReason.EPISODE_TOO_LONG)
                    audio_file.write(block)
    return path


def split(
    *, audio: pathlib.Path, directory: pathlib.Path, chunk_seconds: float, prefix: str = _CHUNK_PREFIX
) -> list[AudioChunk]:
    """Re-encode `audio` as mono 16 kHz 32 kbps MP3 slices of `chunk_seconds`, named `<prefix>_000.mp3`, ...

    Each slice's start is the sum of the durations before it, so segment times can be made absolute.
    """
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(audio),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            str(directory / f"{prefix}_%03d.mp3"),
        ],
        check=True,
    )

    chunks: list[AudioChunk] = []
    start_seconds = 0.0
    for index, path in enumerate(sorted(directory.glob(f"{prefix}_[0-9][0-9][0-9].mp3"))):
        duration_seconds = _duration_seconds(path)
        chunks.append(
            AudioChunk(index=index, path=path, start_seconds=start_seconds, duration_seconds=duration_seconds)
        )
        start_seconds += duration_seconds
    return chunks


def needs_fallback(*, segments: Sequence[content.Segment], duration_seconds: float) -> bool:
    """Whether a chunk came back with too few words for its length (Whisper skipped speech).

    Chunks under `MIN_CHECKED_CHUNK_SECONDS` are exempt: a short trailing outro is often mostly music.
    """
    if duration_seconds < MIN_CHECKED_CHUNK_SECONDS:
        return False

    words = sum(len(segment.text.split()) for segment in segments)
    return words / (duration_seconds / _SECONDS_PER_MINUTE) < MIN_WORDS_PER_MINUTE


def transcribe_groq(*, chunk: AudioChunk, api_key: str, prompt: str) -> list[content.Segment]:
    """Groq Whisper's timed segments for `chunk`, shifted to episode time.

    A 429 raises `RetryLaterError` after Groq's `retry-after`; another 4xx raises `GroqRejectedError`; a 5xx raises
    `httpx.HTTPStatusError` (the loop retries it).
    """
    response = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        data={
            "model": llm.GROQ_WHISPER,
            "response_format": "verbose_json",
            "language": _LANGUAGE,
            "temperature": "0",
            "prompt": prompt,
        },
        files={"file": (chunk.path.name, chunk.path.read_bytes(), _AUDIO_MEDIA_TYPE)},
        timeout=llm.REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == _HTTP_TOO_MANY_REQUESTS:
        retry_after = float(response.headers.get("retry-after") or _GROQ_DEFAULT_RETRY_AFTER_SECONDS)
        raise errors.RetryLaterError(reason="Groq rate limit", after_seconds=retry_after)
    if response.status_code in _HTTP_CLIENT_ERRORS:
        raise GroqRejectedError(f"Groq answered {response.status_code}: {response.text[:200]}")
    response.raise_for_status()

    raw_segments = response.json().get("segments") or []
    timed = (
        content.Segment(start=chunk.start_seconds + float(raw["start"]), text=raw["text"].strip())
        for raw in raw_segments
    )
    return [segment for segment in timed if segment.text]


def transcribe_openai(
    *, chunk: AudioChunk, api_key: str, prompt: str, directory: pathlib.Path
) -> list[content.Segment]:
    """OpenAI's text for `chunk`, one segment per `OPENAI_PART_SECONDS` part (it truncates long requests)."""
    parts = split(
        audio=chunk.path, directory=directory, chunk_seconds=OPENAI_PART_SECONDS, prefix=f"{chunk.path.stem}_part"
    )

    segments: list[content.Segment] = []
    for part in parts:
        response = httpx.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "model": llm.OPENAI_TRANSCRIBE,
                "response_format": "json",
                "language": _LANGUAGE,
                "prompt": prompt,
            },
            files={"file": (part.path.name, part.path.read_bytes(), _AUDIO_MEDIA_TYPE)},
            timeout=llm.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        segments.append(
            content.Segment(start=chunk.start_seconds + part.start_seconds, text=response.json()["text"].strip())
        )
    return segments


def transcribe_chunk(
    engine: sqlalchemy.Engine,
    *,
    chunk: AudioChunk,
    keys: TranscriptionKeys,
    prompt: str,
    context: llm.CallContext,
    directory: pathlib.Path,
) -> ChunkTranscript:
    """Transcribe one chunk with Groq, redoing it with OpenAI when Groq rejects it or comes back too sparse.

    Without an OpenAI key a sparse Groq result is kept, and a Groq rejection is re-raised. Without a Groq key the
    chunk goes straight to OpenAI. Each successful provider call records its cost.
    """
    if keys.groq is None:
        assert keys.openai is not None, "keys_for guarantees one key"
        return _transcribe_with_openai(
            engine, chunk=chunk, api_key=keys.openai, prompt=prompt, context=context, directory=directory
        )

    try:
        segments = transcribe_groq(chunk=chunk, api_key=keys.groq, prompt=prompt)
    except GroqRejectedError as error:
        if keys.openai is None:
            raise
        _logger.warning("Groq rejected chunk %d of source %s, using OpenAI: %s", chunk.index, context.source_id, error)
        return _transcribe_with_openai(
            engine, chunk=chunk, api_key=keys.openai, prompt=prompt, context=context, directory=directory
        )

    _record(engine, context=context, provider=models.TranscriptProvider.GROQ, model=llm.GROQ_WHISPER, chunk=chunk)
    if keys.openai is None or not needs_fallback(segments=segments, duration_seconds=chunk.duration_seconds):
        return ChunkTranscript(provider=models.TranscriptProvider.GROQ, model=llm.GROQ_WHISPER, segments=segments)

    _logger.warning("Groq transcript of chunk %d of source %s is sparse, using OpenAI", chunk.index, context.source_id)
    return _transcribe_with_openai(
        engine, chunk=chunk, api_key=keys.openai, prompt=prompt, context=context, directory=directory
    )


def _transcribe_with_openai(
    engine: sqlalchemy.Engine,
    *,
    chunk: AudioChunk,
    api_key: str,
    prompt: str,
    context: llm.CallContext,
    directory: pathlib.Path,
) -> ChunkTranscript:
    segments = transcribe_openai(chunk=chunk, api_key=api_key, prompt=prompt, directory=directory)
    _record(
        engine, context=context, provider=models.TranscriptProvider.OPENAI, model=llm.OPENAI_TRANSCRIBE, chunk=chunk
    )
    return ChunkTranscript(provider=models.TranscriptProvider.OPENAI, model=llm.OPENAI_TRANSCRIBE, segments=segments)


def _record(
    engine: sqlalchemy.Engine,
    *,
    context: llm.CallContext,
    provider: models.TranscriptProvider,
    model: str,
    chunk: AudioChunk,
) -> None:
    llm.record_audio_call(
        engine,
        context=context,
        provider=provider,
        model=model,
        audio_seconds=Decimal(f"{chunk.duration_seconds:.3f}"),
    )


def _duration_seconds(path: pathlib.Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(probe.stdout)
