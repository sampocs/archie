"""Shared cassette configuration, so every service's tests record and replay outside calls the same way."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import dotenv
import pytest
import vcr
from archie_shared import config
from vcr import request as vcr_request

ANTHROPIC_HOST = "api.anthropic.com"
REPLAY_API_KEY = "sk-ant-replay-only"
RECORD_MODE_OPTION = "--record-mode"
DEFAULT_RECORD_MODE = "none"

# Enough of the system prompt to tell steps apart without tying a cassette to its full wording.
# This is a replay contract: the first 60 characters of ANALYZE_SYSTEM must stay stable, because the recorded analyze
# cassettes still hold the v1 request and response bodies. Wording past character 60 is not covered by any recording
# until a timed-source analyze cassette is recorded.
_SYSTEM_PREFIX_LENGTH = 60
_ANTHROPIC_PROMPT_MATCHER = "anthropic_prompt"

# Credentials and per-account identifiers that must never reach a cassette.
_FILTERED_HEADERS = [
    "authorization",
    "x-api-key",
    "cookie",
    "set-cookie",
    "anthropic-organization-id",
    "anthropic-workspace-id",
    "request-id",
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
        match_on=["method", "scheme", "host", "path", _ANTHROPIC_PROMPT_MATCHER],
    )
    recorder.register_matcher(_ANTHROPIC_PROMPT_MATCHER, _anthropic_prompts_match)
    return recorder


def use_recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose the real Anthropic key only while recording; replays get a placeholder that is never sent."""
    if _record_mode(request) == DEFAULT_RECORD_MODE:
        monkeypatch.setenv(config.ANTHROPIC_API_KEY_ENV, REPLAY_API_KEY)
        return

    api_key = dotenv.dotenv_values(_REPO_ROOT / ".env").get(config.ANTHROPIC_API_KEY_ENV)
    if not api_key:
        pytest.fail(f"Recording needs {config.ANTHROPIC_API_KEY_ENV} in the repo root .env")
    monkeypatch.setenv(config.ANTHROPIC_API_KEY_ENV, api_key)


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
