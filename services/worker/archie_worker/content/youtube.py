"""YouTube captions as timed segments: Supadata when a key is configured, else the caption library directly.

Cloud hosts are blocked by YouTube, so production uses Supadata; a residential IP (a dev Mac) can go direct.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import youtube_transcript_api
from archie_shared import logging

from archie_worker import errors
from archie_worker.content import Segment
from archie_worker.handlers import fetch_title as title_page

# Supadata's generic transcript endpoint takes the video URL (its docs no longer list a videoId parameter).
SUPADATA_URL = "https://api.supadata.ai/v1/transcript"
SUPADATA_JOB_URL = "https://api.supadata.ai/v1/transcript/{job_id}"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

_SUPADATA_TIMEOUT_SECONDS = 30
_SUPADATA_JOB_DEADLINE_SECONDS = 120
_SUPADATA_POLL_SECONDS = 1.0
_MILLISECONDS_PER_SECOND = 1000
_STATUS_ACCEPTED = 202
_STATUS_TRANSCRIPT_UNAVAILABLE = 206
# 404: video missing or private; 403: sign-in, members-only or restricted.
_UNAVAILABLE_STATUSES = frozenset({403, 404})
_PAGE_TIMEOUT_SECONDS = 15
_PAGE_MAX_BYTES = 5_000_000
_SOUND_ONLY_SNIPPETS = frozenset({"[music]", "[applause]", "[laughter]"})

_logger = logging.get_logger(logging.LoggerName.WORKER, "youtube")


def fetch_segments(*, video_id: str, supadata_api_key: str | None) -> list[Segment]:
    """The video's English captions as timed segments; raises PermanentJobError (Supadata) or the library's errors."""
    if supadata_api_key:
        return _fetch_supadata(video_id=video_id, api_key=supadata_api_key)

    fetched = youtube_transcript_api.YouTubeTranscriptApi().fetch(video_id, languages=["en"])
    return _clean_segments((snippet.start, snippet.text) for snippet in fetched)


def permanent_error_for(error: Exception) -> errors.PermanentJobError | None:
    """The permanent failure a caption-library error means, or None when a retry could still help."""
    if isinstance(error, youtube_transcript_api.RequestBlocked):
        # Includes IpBlocked. Only the library path raises it (with a Supadata key it is never called).
        return errors.PermanentJobError(errors.FailureReason.YOUTUBE_NEEDS_SETUP)
    if isinstance(error, youtube_transcript_api.TranscriptsDisabled | youtube_transcript_api.NoTranscriptFound):
        return errors.PermanentJobError(errors.FailureReason.NO_CAPTIONS)
    if isinstance(error, youtube_transcript_api.VideoUnavailable):
        return errors.PermanentJobError(errors.FailureReason.VIDEO_UNAVAILABLE)
    return None


def fetch_title(*, video_id: str) -> str | None:
    """The watch page's title; None when the page can't be fetched (the source keeps its URL as title)."""
    try:
        page = title_page.fetch_page(
            url=WATCH_URL.format(video_id=video_id), timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES
        )
    except (httpx.HTTPError, TimeoutError):
        _logger.info("No title for video %s", video_id)
        return None

    return title_page.extract_title(page=page)


def _fetch_supadata(*, video_id: str, api_key: str) -> list[Segment]:
    headers = {"x-api-key": api_key}
    # `native` only: the AI-generated mode is billed per minute and is never wanted here.
    params = {"url": WATCH_URL.format(video_id=video_id), "lang": "en", "text": "false", "mode": "native"}

    with httpx.Client(timeout=_SUPADATA_TIMEOUT_SECONDS, headers=headers) as client:
        response = client.get(SUPADATA_URL, params=params)
        body = _supadata_body(response)
        if response.status_code == _STATUS_ACCEPTED:
            body = _poll_supadata_job(client, job_id=body["jobId"])

    content = body.get("content") or []
    return _clean_segments((segment["offset"] / _MILLISECONDS_PER_SECOND, segment["text"]) for segment in content)


def _supadata_body(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == _STATUS_TRANSCRIPT_UNAVAILABLE:
        raise errors.PermanentJobError(errors.FailureReason.NO_CAPTIONS)
    if response.status_code in _UNAVAILABLE_STATUSES:
        raise errors.PermanentJobError(errors.FailureReason.VIDEO_UNAVAILABLE)

    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


def _poll_supadata_job(client: httpx.Client, *, job_id: str) -> dict[str, Any]:
    """Wait for a long video's async transcript; a timeout or failed job raises so the loop retries."""
    deadline = time.monotonic() + _SUPADATA_JOB_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        body = _supadata_body(client.get(SUPADATA_JOB_URL.format(job_id=job_id)))
        status = body.get("status")
        if status == "completed":
            return body
        if status == "failed":
            raise RuntimeError(f"Supadata job {job_id} failed: {body.get('error')}")
        time.sleep(_SUPADATA_POLL_SECONDS)

    raise TimeoutError(f"Supadata job {job_id} took longer than {_SUPADATA_JOB_DEADLINE_SECONDS}s")


def _clean_segments(raw_segments: Any) -> list[Segment]:
    """Segments with newlines collapsed to spaces, dropping empty and sound-only ones."""
    cleaned = [Segment(start=start, text=" ".join(text.split())) for start, text in raw_segments]
    return [segment for segment in cleaned if segment.text and segment.text.lower() not in _SOUND_ONLY_SNIPPETS]
