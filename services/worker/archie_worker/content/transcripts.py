"""Transcripts a podcast's feed publishes (`<podcast:transcript>`): fetched, parsed to timed segments or plain text."""

from __future__ import annotations

import html
import html.parser
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from archie_shared import logging

from archie_worker import content
from archie_worker.content import podcast
from archie_worker.handlers import fetch_title

_FETCH_TIMEOUT_SECONDS = 30
_FETCH_MAX_BYTES = 10_000_000
# A shorter "transcript" is a stub or an error page; the episode is transcribed from its audio instead.
MIN_TRANSCRIPT_WORDS = 200

# Mime types by preference: timed formats first, then formats that only give plain text.
_MIME_PREFERENCE = (
    ("text/vtt",),
    ("application/x-subrip", "application/srt"),
    ("application/json",),
    ("text/html", "text/plain"),
)
_HTML_MIME_TYPES = frozenset({"text/html", "text/plain"})
_TIMING_PATTERN = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->")
_TAG_PATTERN = re.compile(r"<[^>]*>")
_SKIPPED_HTML_TAGS = frozenset({"script", "style", "head"})

_logger = logging.get_logger(logging.LoggerName.WORKER, "transcripts")


@dataclass(frozen=True)
class PublishedTranscript:
    """A fetched transcript: its text and, for timed formats, its segments (empty for HTML and plain text)."""

    text: str
    segments: list[content.Segment]


def fetch_best(links: Sequence[podcast.TranscriptLink]) -> PublishedTranscript | None:
    """The first link, in format preference order, that fetches and parses to at least 200 words; else None."""
    for link in _in_preference_order(links):
        transcript = _try_fetch(link)
        if transcript is not None and len(transcript.text.split()) >= MIN_TRANSCRIPT_WORDS:
            return transcript

    return None


def parse_vtt(text: str) -> list[content.Segment]:
    """The cues of a WebVTT file as segments; cue tags (`<v Name>`, `<c>`) are removed."""
    return _parse_cues(text)


def parse_srt(text: str) -> list[content.Segment]:
    """The cues of a SubRip file as segments."""
    return _parse_cues(text)


def parse_json(text: str) -> list[content.Segment]:
    """Segments of a Podcasting 2.0 JSON transcript (`segments[].startTime` and `body`); ValueError if malformed."""
    document: Any = json.loads(text)
    raw_segments = document.get("segments") if isinstance(document, dict) else None
    if not isinstance(raw_segments, list):
        raise ValueError("Transcript JSON has no segments")

    segments = []
    for raw in raw_segments:
        body = " ".join(str(raw["body"]).split())
        if body:
            segments.append(content.Segment(start=float(raw["startTime"]), text=body))
    return segments


def html_to_text(text: str) -> str:
    """The visible text of an HTML (or plain text) transcript, whitespace collapsed."""
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def _in_preference_order(links: Sequence[podcast.TranscriptLink]) -> list[podcast.TranscriptLink]:
    ranked = [
        (rank, link)
        for link in links
        for rank, mime_types in enumerate(_MIME_PREFERENCE)
        if _base_mime(link.mime_type) in mime_types
    ]
    return [link for _, link in sorted(ranked, key=lambda pair: pair[0])]


def _base_mime(mime_type: str) -> str:
    return mime_type.split(";")[0].strip().lower()


def _try_fetch(link: podcast.TranscriptLink) -> PublishedTranscript | None:
    """Fetch and parse one link; a fetch or parse failure is logged and gives None so the next link is tried."""
    try:
        raw = fetch_title.fetch_bytes(url=link.url, timeout_seconds=_FETCH_TIMEOUT_SECONDS, max_bytes=_FETCH_MAX_BYTES)
        return _parse(raw.decode("utf-8", errors="replace"), mime_type=_base_mime(link.mime_type))
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError) as error:
        _logger.info("Transcript %s failed: %s", link.url, error)
        return None


def _parse(text: str, *, mime_type: str) -> PublishedTranscript:
    if mime_type in _HTML_MIME_TYPES:
        return PublishedTranscript(text=html_to_text(text), segments=[])

    parsers = {"text/vtt": parse_vtt, "application/json": parse_json}
    segments = parsers.get(mime_type, parse_srt)(text)
    return PublishedTranscript(text=" ".join(segment.text for segment in segments), segments=segments)


def _parse_cues(text: str) -> list[content.Segment]:
    """Cues are blank-line separated blocks: the line with `-->` carries the start, the lines after it the text."""
    segments = []
    for block in re.split(r"\r?\n\s*\r?\n", text.lstrip("\ufeff")):
        lines = block.strip().splitlines()
        timing_index = next((index for index, line in enumerate(lines) if _TIMING_PATTERN.match(line.strip())), None)
        if timing_index is None:
            continue

        timing = _TIMING_PATTERN.match(lines[timing_index].strip())
        assert timing is not None
        hours, minutes, seconds, fraction = timing.groups()
        start = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(fraction) / 10 ** len(fraction)

        cue_text = " ".join(html.unescape(_TAG_PATTERN.sub("", " ".join(lines[timing_index + 1 :]))).split())
        if cue_text:
            segments.append(content.Segment(start=start, text=cue_text))
    return segments


class _TextExtractor(html.parser.HTMLParser):
    """Collects the text outside `<script>`, `<style>` and `<head>`."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Enter a skipped element."""
        if tag in _SKIPPED_HTML_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        """Leave a skipped element."""
        if tag in _SKIPPED_HTML_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        """Keep visible text."""
        if not self._skip_depth:
            self.parts.append(data)
