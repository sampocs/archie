"""Speech-to-text requests to Groq and OpenAI, shared by the worker (episodes) and the API (spoken answers).

The responses come back unchecked: the worker retries and falls back on particular statuses, the API turns them into
its own answers.
"""

from __future__ import annotations

import httpx

from archie_llm import llm

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
LANGUAGE = "en"


def post_groq(
    *,
    audio: bytes,
    filename: str,
    media_type: str,
    api_key: str,
    prompt: str,
    response_format: str,
    timeout_seconds: float = llm.REQUEST_TIMEOUT_SECONDS,
) -> httpx.Response:
    """Transcribe `audio` with Groq Whisper; `prompt` primes it with the words it is likely to hear."""
    return httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        data={
            "model": llm.GROQ_WHISPER,
            "response_format": response_format,
            "language": LANGUAGE,
            "temperature": "0",
            "prompt": prompt,
        },
        files={"file": (filename, audio, media_type)},
        timeout=timeout_seconds,
    )


def post_openai(
    *,
    audio: bytes,
    filename: str,
    media_type: str,
    api_key: str,
    prompt: str,
    timeout_seconds: float = llm.REQUEST_TIMEOUT_SECONDS,
) -> httpx.Response:
    """Transcribe `audio` with OpenAI's transcription model; the response is JSON with a single `text`."""
    return httpx.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        data={
            "model": llm.OPENAI_TRANSCRIBE,
            "response_format": "json",
            "language": LANGUAGE,
            "prompt": prompt,
        },
        files={"file": (filename, audio, media_type)},
        timeout=timeout_seconds,
    )
