"""YouTube captions as timed segments: Supadata when a key is configured, else the caption library directly.

Cloud hosts are blocked by YouTube, so production uses Supadata; a residential IP (a dev Mac) can go direct.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
import youtube_transcript_api
from archie_shared import logging

from archie_worker import content, errors
from archie_worker.content import Segment
from archie_worker.handlers import fetch_title as title_page

# Supadata's generic transcript endpoint takes the video URL (its docs no longer list a videoId parameter).
SUPADATA_URL = "https://api.supadata.ai/v1/transcript"
SUPADATA_JOB_URL = "https://api.supadata.ai/v1/transcript/{job_id}"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
OEMBED_URL = "https://www.youtube.com/oembed"
THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

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
_OEMBED_TIMEOUT_SECONDS = 5
_OEMBED_MAX_BYTES = 20_000
_MAX_TITLE_LENGTH = 500
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


def thumbnail_url(video_id: str) -> str:
    """The video's standard thumbnail, which exists for every public video."""
    return THUMBNAIL_URL.format(video_id=video_id)


def fetch_title(*, video_id: str) -> str | None:
    """The video's title from oEmbed, else the watch page; None when both fail (the source keeps its URL as title)."""
    oembed = _fetch_oembed(video_id=video_id)
    if oembed is not None and oembed.title:
        return oembed.title

    try:
        page = title_page.fetch_page(
            url=WATCH_URL.format(video_id=video_id), timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES
        )
    except (httpx.HTTPError, TimeoutError):
        _logger.info("No title for video %s", video_id)
        return None

    return title_page.extract_title(page=page)


# The watch page embeds its player response as JSON; the first match is the video's own (later ones are suggestions).
_LENGTH_SECONDS = re.compile(r'"lengthSeconds":"(\d+)"')
_OWNER_CHANNEL_NAME = re.compile(r'"ownerChannelName":"((?:[^"\\]|\\.)*)"')


def fetch_preview(*, video_id: str) -> content.LinkPreview:
    """The video's title, channel and length, with the standard thumbnail; raises if neither lookup works.

    The watch page is the only source of the length, but it is the lookup YouTube refuses from cloud hosts, so
    oEmbed's title and channel stand in for it (without a length) rather than failing the preview.
    """
    try:
        page = title_page.fetch_page(
            url=WATCH_URL.format(video_id=video_id), timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES
        )
    except (httpx.HTTPError, TimeoutError):
        oembed = _fetch_oembed(video_id=video_id)
        if oembed is None:
            raise
        return content.LinkPreview(
            title=oembed.title, author=oembed.author, image_url=thumbnail_url(video_id), duration_seconds=None
        )

    length = _LENGTH_SECONDS.search(page)
    owner = _OWNER_CHANNEL_NAME.search(page)
    return content.LinkPreview(
        title=title_page.extract_title(page=page),
        # The channel name is a JSON string, so its escapes (&, \") decode as JSON does.
        author=content.strip_nul(json.loads(f'"{owner.group(1)}"')) if owner else None,
        image_url=thumbnail_url(video_id),
        duration_seconds=int(length.group(1)) if length else None,
    )


@dataclass(frozen=True)
class _OEmbed:
    title: str | None
    author: str | None


def _fetch_oembed(*, video_id: str) -> _OEmbed | None:
    """The video's title and channel from YouTube's tiny oEmbed endpoint; None when it can't be read."""
    try:
        body = title_page.fetch_bytes(
            url=OEMBED_URL,
            params={"url": WATCH_URL.format(video_id=video_id), "format": "json"},
            timeout_seconds=_OEMBED_TIMEOUT_SECONDS,
            max_bytes=_OEMBED_MAX_BYTES,
        )
        data = json.loads(body)
    except (httpx.HTTPError, TimeoutError, ValueError):
        _logger.info("No oEmbed for video %s", video_id)
        return None

    return _OEmbed(title=_clean_text(data.get("title")), author=_clean_text(data.get("author_name")))


def _clean_text(value: Any) -> str | None:
    """`value` as NUL-free text with whitespace collapsed, or None when it is not text or is blank."""
    if not isinstance(value, str):
        return None
    return " ".join(content.strip_nul(value).split())[:_MAX_TITLE_LENGTH] or None


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
