"""Audio stripping and chunk matching: the logic that keeps transcription cassettes small and replayable."""

from __future__ import annotations

import httpx
from archie_testing import recording
from vcr import request as vcr_request

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _upload(*, filename: str, url: str = GROQ_URL) -> vcr_request.Request:
    request = httpx.Request(
        "POST",
        url,
        data={"model": "whisper-large-v3-turbo", "language": "en"},
        files={"file": (filename, b"\xff\xfb" * 5000, "audio/mpeg")},
    )
    return vcr_request.Request(request.method, str(request.url), request.read(), dict(request.headers))


def test_strip_audio_upload_keeps_fields_and_drops_audio() -> None:
    """Only the file part's bytes are replaced; the form fields and filename stay."""
    stripped = recording._strip_audio_upload(_upload(filename="chunk_001.mp3"))

    assert len(stripped.body) < 1024
    assert recording.OMITTED_AUDIO in stripped.body
    assert b"\xff\xfb" not in stripped.body
    assert b'filename="chunk_001.mp3"' in stripped.body
    assert b"whisper-large-v3-turbo" in stripped.body
    assert b'name="language"\r\n\r\nen' in stripped.body


def test_strip_audio_upload_leaves_other_requests_alone() -> None:
    """A non-transcription request is returned unchanged."""
    body = b'{"model": "claude"}'
    other = vcr_request.Request("POST", ANTHROPIC_URL, body, {"content-type": "application/json"})

    assert recording._strip_audio_upload(other).body == body


def test_chunk_matcher_tells_chunks_apart_and_matches_stripped_to_full() -> None:
    """Chunk uploads replay by filename, whether the recorded body is stripped or full."""
    full = _upload(filename="chunk_001.mp3")
    stripped = recording._strip_audio_upload(_upload(filename="chunk_001.mp3"))
    other_chunk = _upload(filename="chunk_002.mp3")

    assert recording._transcription_chunks_match(stripped, full)
    assert not recording._transcription_chunks_match(stripped, other_chunk)


def test_chunk_matcher_leaves_other_hosts_to_their_own_matcher() -> None:
    """Requests to other hosts compare equal here."""
    first = vcr_request.Request("POST", ANTHROPIC_URL, b"{}", {})
    second = vcr_request.Request("POST", ANTHROPIC_URL, b'{"a": 1}', {})

    assert recording._transcription_chunks_match(first, second)
