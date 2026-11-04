"""Shared cassette configuration, so every service's tests record and replay outside calls the same way."""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Sequence
from typing import Any

import dotenv
import pytest
import vcr
from archie_shared import config
from vcr import request as vcr_request

ANTHROPIC_HOST = "api.anthropic.com"
REPLAY_API_KEYS = {
    config.ANTHROPIC_API_KEY_ENV: "sk-ant-replay-only",
    config.GROQ_API_KEY_ENV: "gsk-replay-only",
    config.OPENAI_API_KEY_ENV: "sk-openai-replay-only",
}
REPLAY_API_KEY = REPLAY_API_KEYS[config.ANTHROPIC_API_KEY_ENV]
TRANSCRIPTION_HOSTS = frozenset({"api.groq.com", "api.openai.com"})
OMITTED_AUDIO = b"<audio omitted>"
RECORD_MODE_OPTION = "--record-mode"
DEFAULT_RECORD_MODE = "none"

# Enough of the system prompt to tell steps apart without tying a cassette to its full wording.
# This is a replay contract: the first 60 characters of ANALYZE_SYSTEM must stay stable, because the recorded analyze
# cassettes still hold the v1 request and response bodies. Wording past character 60 is not covered by any recording
# until a timed-source analyze cassette is recorded.
_SYSTEM_PREFIX_LENGTH = 60
_ANTHROPIC_PROMPT_MATCHER = "anthropic_prompt"
_TRANSCRIPTION_CHUNK_MATCHER = "transcription_chunk"
_BOUNDARY_PATTERN = re.compile(r"boundary=([^;\s]+)")
_MODEL_PATTERN = re.compile(rb'name="model"\r\n\r\n([^\r]+)')
_FILENAME_PATTERN = re.compile(rb'filename="([^"]+)"')

# Credentials and per-account identifiers that must never reach a cassette.
_FILTERED_HEADERS = [
    "authorization",
    "x-api-key",
    "cookie",
    "set-cookie",
    "anthropic-organization-id",
    "anthropic-workspace-id",
    "request-id",
    "openai-organization",
    "openai-project",
    "x-request-id",
]

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def vcr_for(request: pytest.FixtureRequest, *, cassette_dir: pathlib.Path) -> vcr.VCR:
    """A recorder over `cassette_dir`: replay-only unless pytest is given `--record-mode`."""
    recorder = vcr.VCR(
        cassette_library_dir=str(cassette_dir),
        record_mode=_record_mode(request),
        filter_headers=_FILTERED_HEADERS,
        decode_compressed_response=True,
        before_record_response=_drop_identifying_response_headers,
        before_record_request=_strip_audio_upload,
        match_on=["method", "scheme", "host", "path", _ANTHROPIC_PROMPT_MATCHER, _TRANSCRIPTION_CHUNK_MATCHER],
    )
    recorder.register_matcher(_ANTHROPIC_PROMPT_MATCHER, _anthropic_prompts_match)
    recorder.register_matcher(_TRANSCRIPTION_CHUNK_MATCHER, _transcription_chunks_match)
    return recorder


def use_recording_api_key(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    *,
    env_names: Sequence[str] = (config.ANTHROPIC_API_KEY_ENV,),
) -> None:
    """Expose real keys only while recording; replays get placeholders that are never sent."""
    if _record_mode(request) == DEFAULT_RECORD_MODE:
        for env_name in env_names:
            monkeypatch.setenv(env_name, REPLAY_API_KEYS[env_name])
        return

    env_values = dotenv.dotenv_values(_REPO_ROOT / ".env")
    for env_name in env_names:
        api_key = env_values.get(env_name)
        if not api_key:
            pytest.fail(f"Recording needs {env_name} in the repo root .env")
        monkeypatch.setenv(env_name, api_key)


def _drop_identifying_response_headers(response: dict[str, Any]) -> dict[str, Any]:
    # `filter_headers` only covers request headers, but Anthropic echoes the account and request ids back.
    response["headers"] = {
        name: value for name, value in response["headers"].items() if name.lower() not in _FILTERED_HEADERS
    }
    return response


def _record_mode(request: pytest.FixtureRequest) -> str:
    return request.config.getoption(RECORD_MODE_OPTION) or DEFAULT_RECORD_MODE


def _anthropic_prompts_match(recorded: vcr_request.Request, incoming: vcr_request.Request) -> bool:
    """Anthropic calls match on model and system prompt; every other host matches unconditionally."""
    if ANTHROPIC_HOST not in (recorded.host, incoming.host):
        return True

    return _prompt_identity(recorded) == _prompt_identity(incoming)


def _prompt_identity(request: vcr_request.Request) -> tuple[str, str]:
    body = json.loads(request.body or b"{}")
    return body.get("model", ""), str(body.get("system", ""))[:_SYSTEM_PREFIX_LENGTH]


def _strip_audio_upload(request: vcr_request.Request) -> vcr_request.Request:
    """Replace the audio in a transcription upload with a marker, so cassettes never carry the uploaded chunks."""
    if request.host not in TRANSCRIPTION_HOSTS:
        return request

    content_type = request.headers.get("content-type", "")
    boundary_match = _BOUNDARY_PATTERN.search(content_type)
    if not content_type.startswith("multipart/form-data") or boundary_match is None or not request.body:
        return request

    delimiter = b"--" + boundary_match.group(1).strip('"').encode()
    parts = request.body.split(delimiter)
    request.body = delimiter.join(_omit_file_content(part) for part in parts)
    return request


def _omit_file_content(part: bytes) -> bytes:
    headers, separator, _content = part.partition(b"\r\n\r\n")
    if not separator or b"filename=" not in headers:
        return part

    return headers + separator + OMITTED_AUDIO + b"\r\n"


def _transcription_chunks_match(recorded: vcr_request.Request, incoming: vcr_request.Request) -> bool:
    """Transcription uploads match on model and chunk filename; every other host matches unconditionally."""
    if recorded.host not in TRANSCRIPTION_HOSTS and incoming.host not in TRANSCRIPTION_HOSTS:
        return True

    return _chunk_identity(recorded) == _chunk_identity(incoming)


def _chunk_identity(request: vcr_request.Request) -> tuple[bytes | None, bytes | None]:
    body = request.body or b""
    model = _MODEL_PATTERN.search(body)
    filename = _FILENAME_PATTERN.search(body)
    return (model.group(1) if model else None, filename.group(1) if filename else None)
