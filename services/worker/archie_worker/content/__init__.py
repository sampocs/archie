"""Turning a source's page, capture or post into the plain text the pipeline reads."""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Longest text kept from one source, however it was fetched.
MAX_TEXT_LENGTH = 200_000

# Keys of a `text` artifact's content.
TEXT_KEY = "text"
SEGMENTS_KEY = "segments"


def midnight_utc(day: datetime.date | None) -> datetime.datetime | None:
    """A publication day as the moment it began in UTC, for `sources.published_at`; None stays None."""
    return datetime.datetime.combine(day, datetime.time(), tzinfo=datetime.UTC) if day is not None else None


# Postgres text and jsonb values reject NUL, so a string containing one would fail the job forever.
_NUL = "\x00"


@dataclass(frozen=True)
class ExtractedText:
    """A source's readable text and, when one was found, its title, artwork and publication date."""

    title: str | None
    text: str
    image_url: str | None = None
    published_at: datetime.datetime | None = None


# Longest caption kept for a saved post; a long X thread's first post can run to thousands of characters.
MAX_PREVIEW_TITLE_LENGTH = 1000


@dataclass(frozen=True)
class LinkPreview:
    """What a saved post shows: its caption or title, who posted it, a thumbnail, and a video's length."""

    title: str | None
    author: str | None
    image_url: str | None
    duration_seconds: int | None


@dataclass(frozen=True)
class Segment:
    """One timed stretch of speech; `start` is in seconds from the beginning of the source."""

    start: float
    text: str


def timed_text_content(*, segments: Sequence[Segment], extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A `text` artifact's content for timed text: the joined text plus the segments, NUL-free, with `extra` merged."""
    cleaned = [Segment(start=segment.start, text=strip_nul(segment.text)) for segment in segments]
    return {
        TEXT_KEY: " ".join(segment.text for segment in cleaned),
        SEGMENTS_KEY: [{"start": round(segment.start, 2), "text": segment.text} for segment in cleaned],
        **_strip_nul_deep(dict(extra or {})),
    }


def segments_of(text_content: Mapping[str, Any]) -> list[Segment]:
    """The timed segments of a `text` artifact's content; empty when it has none."""
    return [Segment(start=float(raw["start"]), text=raw["text"]) for raw in text_content.get(SEGMENTS_KEY, [])]


def strip_nul(value: str) -> str:
    """`value` without NUL characters."""
    return value.replace(_NUL, "")


def _strip_nul_deep(value: Any) -> Any:
    if isinstance(value, str):
        return strip_nul(value)
    if isinstance(value, dict):
        return {strip_nul(key): _strip_nul_deep(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_strip_nul_deep(item) for item in value]
    return value
