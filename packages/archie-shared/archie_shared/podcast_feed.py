"""Reading a podcast's RSS feed: its items, their audio, transcripts and descriptions.

Shared by the worker (resolving a shared episode) and the API (listing a show's episodes for "Wrong episode?").
"""

from __future__ import annotations

import datetime
import email.utils
import html
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import defusedxml.ElementTree
import httpx

EPISODE_KEY = "episode"  # Where the worker keeps a resolved `PodcastEpisode` on the `text` artifact.

FEED_TIMEOUT_SECONDS = 30
FEED_MAX_BYTES = 50_000_000
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"

_MAX_DESCRIPTION_LENGTH = 2000
_PODCAST_NAMESPACES = ("{https://podcastindex.org/namespace/1.0}", "{http://podcastindex.org/namespace/1.0}")
_ITUNES_NAMESPACE = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
_CONTENT_NAMESPACE = "{http://purl.org/rss/1.0/modules/content/}"
_TAG_PATTERN = re.compile(r"<[^>]*>")


@dataclass(frozen=True)
class TranscriptLink:
    """One `<podcast:transcript>` of a feed item."""

    url: str
    mime_type: str


@dataclass(frozen=True)
class FeedItem:
    """One `<item>` of a podcast RSS feed."""

    title: str
    published: datetime.date | None
    guid: str | None
    audio_url: str | None
    duration_s: int | None
    description: str
    transcripts: list[TranscriptLink]
    image_url: str | None = None


def parse_feed(feed: bytes) -> list[FeedItem]:
    """The items of an RSS feed, in feed order; malformed or forbidden XML raises ParseError or ValueError."""
    channel = defusedxml.ElementTree.fromstring(feed).find("channel")
    if channel is None:
        raise ValueError("Feed has no channel")

    channel_image_url = _channel_image_url(channel)
    return [_feed_item(item, channel_image_url=channel_image_url) for item in channel.findall("item")]


def item_by_guid(*, items: Sequence[FeedItem], guid: str | None) -> FeedItem | None:
    """The item with this guid that has audio; None when `guid` is empty or no such item exists."""
    if not guid:
        return None
    return next((item for item in items if item.guid == guid and item.audio_url), None)


def fetch_feed(feed_url: str) -> bytes:
    """Download a feed (at most 50 MB within 30 s in total); raises httpx errors on 4xx/5xx and TimeoutError past it."""
    deadline = time.monotonic() + FEED_TIMEOUT_SECONDS
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=FEED_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
        with client.stream("GET", feed_url) as response:
            response.raise_for_status()

            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Fetching {feed_url} took longer than {FEED_TIMEOUT_SECONDS}s")
                body.extend(chunk)
                if len(body) >= FEED_MAX_BYTES:
                    break
            return bytes(body[:FEED_MAX_BYTES])


def _channel_image_url(channel: Any) -> str | None:
    """The show's artwork: the channel's `itunes:image`, else its RSS `<image><url>`."""
    itunes_image = channel.find(f"{_ITUNES_NAMESPACE}image")
    href = itunes_image.get("href") if itunes_image is not None else None
    return href or (channel.findtext("image/url") or "").strip() or None


def _feed_item(item: Any, *, channel_image_url: str | None) -> FeedItem:
    enclosure = item.find("enclosure")
    guid = item.findtext("guid")
    item_image = item.find(f"{_ITUNES_NAMESPACE}image")
    return FeedItem(
        title=item.findtext("title", default="").strip(),
        published=_item_date(item.findtext("pubDate")),
        guid=guid.strip() if guid else None,
        audio_url=enclosure.get("url") if enclosure is not None else None,
        duration_s=_duration_seconds(item.findtext(f"{_ITUNES_NAMESPACE}duration")),
        description=_description(item),
        transcripts=[
            TranscriptLink(url=transcript.get("url"), mime_type=transcript.get("type", ""))
            for namespace in _PODCAST_NAMESPACES
            for transcript in item.findall(f"{namespace}transcript")
            if transcript.get("url")
        ],
        image_url=(item_image.get("href") if item_image is not None else None) or channel_image_url,
    )


def _item_date(pub_date: str | None) -> datetime.date | None:
    if not pub_date:
        return None
    try:
        return email.utils.parsedate_to_datetime(pub_date).date()
    except (TypeError, ValueError):
        return None


def _duration_seconds(raw: str | None) -> int | None:
    """`itunes:duration` as seconds: a bare number of seconds, or `[h:]mm:ss`."""
    if not raw:
        return None

    try:
        parts = [int(float(part)) for part in raw.strip().split(":")]
    except ValueError:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _description(item: Any) -> str:
    raw = (
        item.findtext("description")
        or item.findtext(f"{_ITUNES_NAMESPACE}summary")
        or item.findtext(f"{_CONTENT_NAMESPACE}encoded")
    )
    stripped = html.unescape(_TAG_PATTERN.sub(" ", raw or ""))
    return " ".join(stripped.split())[:_MAX_DESCRIPTION_LENGTH]
