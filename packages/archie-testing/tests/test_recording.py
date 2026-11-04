"""Audio stripping and chunk matching: the logic that keeps transcription cassettes small and replayable."""

from __future__ import annotations

import _socket  # The real primitives the root conftest's network guard leaves untouched.
import http.server
import pathlib
import socket
import threading
from collections.abc import Iterator

import httpx
import pytest
import vcr.record_mode
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


def test_prompt_matcher_skips_bodies_of_other_hosts() -> None:
    """An Anthropic call compared with a recorded multipart upload doesn't try to parse the upload as JSON."""
    anthropic_call = vcr_request.Request("POST", ANTHROPIC_URL, b'{"model": "claude", "system": "s"}', {})

    assert recording._anthropic_prompts_match(_upload(filename="chunk_001.mp3"), anthropic_call)
    assert recording._anthropic_prompts_match(anthropic_call, _upload(filename="chunk_001.mp3"))


def test_chunk_matcher_rejects_unparseable_transcription_bodies() -> None:
    """Transcription requests without a model or filename never match, even each other."""
    first = vcr_request.Request("POST", GROQ_URL, b"not multipart", {})
    second = vcr_request.Request("POST", GROQ_URL, b"also not multipart", {})

    assert not recording._transcription_chunks_match(first, second)
    assert not recording._transcription_chunks_match(first, _upload(filename="chunk_001.mp3"))


def test_use_recording_api_key_names_unknown_variable(request: pytest.FixtureRequest) -> None:
    """An env name without a replay placeholder fails naming only the variable."""
    with pytest.raises(pytest.fail.Exception, match="No replay placeholder for UNKNOWN_KEY"):
        recording.use_recording_api_key(request, pytest.MonkeyPatch(), env_names=("UNKNOWN_KEY",))


class _ChunkEchoHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server's required hook name
        body = self.rfile.read(int(self.headers["Content-Length"]))
        filename = recording._FILENAME_PATTERN.search(body)
        reply = b"heard " + (filename.group(1) if filename else b"nothing")
        self.send_response(200)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture
def chunk_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A loopback server for the recorder to talk to; the root network guard is lifted for loopback only here."""
    monkeypatch.setattr(socket, "getaddrinfo", _socket.getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", _socket.socket.connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _socket.socket.connect_ex)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ChunkEchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1/audio/transcriptions"
    server.shutdown()
    server.server_close()


def test_same_path_chunks_replay_out_of_order_from_audio_free_cassette(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
    chunk_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two chunk uploads to one path record once and replay by filename, in any order, with no audio or auth."""
    monkeypatch.setattr(recording, "TRANSCRIPTION_HOSTS", frozenset({"127.0.0.1"}))
    recorder = recording.vcr_for(request, cassette_dir=tmp_path)
    cassette_path = tmp_path / "chunks.yaml"
    headers = {"Authorization": "Bearer secret-token"}

    def upload(filename: str) -> str:
        files = {"file": (filename, b"\xff\xfb" * 5000, "audio/mpeg")}
        return httpx.post(chunk_server, data={"model": "whisper"}, files=files, headers=headers).text

    with recorder.use_cassette(str(cassette_path), record_mode=vcr.record_mode.RecordMode.ONCE):
        assert upload("chunk_001.mp3") == "heard chunk_001.mp3"
        assert upload("chunk_002.mp3") == "heard chunk_002.mp3"

    saved = cassette_path.read_bytes()
    assert b"\xff\xfb" not in saved
    assert b"authorization" not in saved.lower()

    with recorder.use_cassette(str(cassette_path), record_mode=vcr.record_mode.RecordMode.NONE):
        assert upload("chunk_002.mp3") == "heard chunk_002.mp3"
        assert upload("chunk_001.mp3") == "heard chunk_001.mp3"
