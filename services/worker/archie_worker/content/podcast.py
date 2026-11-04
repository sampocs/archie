"""Resolving a shared podcast episode (Spotify or Apple link) to its RSS item, audio and published transcripts.

Follows `spikes/podcast_resolve/resolve_episodes.py`. Spotify: the public episode page gives title, date and show name;
the show's feed comes from the show registry or iTunes Search. Apple: iTunes Lookup gives the feed and the episode.
Either way the episode is then matched in the RSS feed, which supplies the audio URL and any transcripts.
"""

from __future__ import annotations

import datetime
import difflib
import email.utils
import html
import json
import re
import xml.etree.ElementTree
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import defusedxml.ElementTree
import httpx
import sqlalchemy
import sqlalchemy.dialects.postgresql
import sqlalchemy.orm
from archie_db import models
from archie_shared import logging, urls

from archie_worker import errors
from archie_worker.content import episode as episode_content
from archie_worker.handlers import fetch_title

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
SPOTIFY_EPISODE_URL = "https://open.spotify.com/episode/{episode_id}"

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
_HEADERS = {"User-Agent": _USER_AGENT}
_SPOTIFY_TIMEOUT_SECONDS = 15
_SPOTIFY_MAX_BYTES = 5_000_000
_FEED_TIMEOUT_SECONDS = 30
_FEED_MAX_BYTES = 50_000_000
_API_TIMEOUT_SECONDS = 15
_API_MAX_BYTES = 5_000_000
_SEARCH_CANDIDATE_COUNT = 5
_LOOKUP_EPISODE_LIMIT = 200
_MIN_TITLE_SIMILARITY = 0.6
_MAX_DAYS_APART = 3
_MAX_DESCRIPTION_LENGTH = 2000
# Page statuses that mean the episode is gone; a retry cannot fix them.
_GONE_STATUSES = frozenset({404, 410})

_PODCAST_NAMESPACES = ("{https://podcastindex.org/namespace/1.0}", "{http://podcastindex.org/namespace/1.0}")
_ITUNES_NAMESPACE = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
_CONTENT_NAMESPACE = "{http://purl.org/rss/1.0/modules/content/}"
_LD_JSON_PATTERN = re.compile(r'<script type="application/ld\+json">(.+?)</script>', re.DOTALL)
_SHOW_NAME_PATTERN = re.compile(r"^Listen to this episode from (.+?) on Spotify\.")
_TAG_PATTERN = re.compile(r"<[^>]*>")
_NON_WORD_PATTERN = re.compile(r"[^a-z0-9 ]")

_logger = logging.get_logger(logging.LoggerName.WORKER, "podcast")


@dataclass(frozen=True)
class TranscriptLink:
    """One `<podcast:transcript>` of a feed item."""

    url: str
    mime_type: str


@dataclass(frozen=True)
class ResolvedEpisode:
    """The episode found in its feed, and the transcripts that item publishes (possibly none)."""

    episode: episode_content.PodcastEpisode
    transcripts: list[TranscriptLink]


@dataclass(frozen=True)
class SpotifyEpisode:
    """What a Spotify episode page says about the episode."""

    title: str
    show_name: str
    published: datetime.date


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


@dataclass(frozen=True)
class _Show:
    """A show's feed and the name to record the episode under."""

    name: str
    feed_url: str
    itunes_id: int | None


@dataclass(frozen=True)
class _Match:
    """The feed item that is the episode, and the show feed it was found in."""

    show: _Show
    item: FeedItem


def resolve(engine: sqlalchemy.Engine, *, link: urls.PodcastLink) -> ResolvedEpisode:
    """Find the linked episode in its show's RSS feed.

    Raises `PermanentJobError` with `SPOTIFY_ONLY` when iTunes knows no feed for a Spotify show, and with
    `EPISODE_NOT_FOUND` when the episode isn't in the feed (or Apple's lookup lacks it).
    """
    if link.platform == urls.PodcastPlatform.SPOTIFY:
        return _resolve_spotify(engine, episode_id=link.episode_id)

    assert link.show_id is not None
    return _resolve_apple(show_id=link.show_id, episode_id=int(link.episode_id))


def spotify_episode_from_page(page: str) -> SpotifyEpisode:
    """Read an episode page's ld+json; ValueError when it or the "Listen to this episode from" prefix is missing."""
    found = _LD_JSON_PATTERN.search(page)
    if found is None:
        raise ValueError("Spotify page has no ld+json")

    document = json.loads(found.group(1))
    if not isinstance(document, dict):
        raise ValueError("Spotify page ld+json is not an object")

    show = _SHOW_NAME_PATTERN.match(document.get("description", ""))
    if show is None:
        raise ValueError("Spotify page description has no show name")

    name = document.get("name")
    date_published = document.get("datePublished")
    if not isinstance(name, str) or not isinstance(date_published, str):
        raise ValueError("Spotify page ld+json lacks name or datePublished")

    return SpotifyEpisode(
        title=html.unescape(name),
        show_name=html.unescape(show.group(1)),
        published=datetime.date.fromisoformat(date_published[:10]),
    )


def parse_feed(feed: bytes) -> list[FeedItem]:
    """The items of an RSS feed, in feed order; malformed or forbidden XML raises ParseError or ValueError."""
    channel = defusedxml.ElementTree.fromstring(feed).find("channel")
    if channel is None:
        raise ValueError("Feed has no channel")

    return [_feed_item(item) for item in channel.findall("item")]


def best_match(*, title: str, published: datetime.date, items: Sequence[FeedItem]) -> FeedItem | None:
    """The item published within 3 days with the closest title (ratio at least 0.6); items without audio never match."""
    candidates = [
        item
        for item in items
        if item.audio_url and item.published and abs((published - item.published).days) <= _MAX_DAYS_APART
    ]
    if not candidates:
        return None

    best = max(candidates, key=lambda item: _similarity(title, item.title))
    return best if _similarity(title, best.title) >= _MIN_TITLE_SIMILARITY else None


def name_key(name: str) -> str:
    """A show name as the registry keys it: lower-cased, whitespace collapsed."""
    return " ".join(name.lower().split())


def _resolve_spotify(engine: sqlalchemy.Engine, *, episode_id: str) -> ResolvedEpisode:
    spotify = _read_spotify_page(episode_id=episode_id)

    registered = _registered_show(engine, show_name=spotify.show_name)
    show = registered or _search_show(show_name=spotify.show_name)
    if show is None:
        _logger.info("No feed for Spotify show %r", spotify.show_name)
        raise errors.PermanentJobError(errors.FailureReason.SPOTIFY_ONLY)

    match = _match_spotify_episode(spotify, show=show)
    if match is None and registered is not None:
        # The remembered feed may be stale (the show moved hosts), so search once more before giving up.
        match = _match_in_searched_feed(spotify, registered=registered)

    if match is None:
        _logger.info("Episode %r not found in the feed of %r", spotify.title, spotify.show_name)
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND)

    # Only a matched feed is remembered, so a wrong top search hit never sticks; a changed feed replaces the old row.
    _remember_show(engine, show=match.show)
    return _resolved(item=match.item, show_name=match.show.name, feed_url=match.show.feed_url)


def _match_spotify_episode(spotify: SpotifyEpisode, *, show: _Show) -> _Match | None:
    item = best_match(title=spotify.title, published=spotify.published, items=_read_feed(show.feed_url))
    return _Match(show=show, item=item) if item else None


def _match_in_searched_feed(spotify: SpotifyEpisode, *, registered: _Show) -> _Match | None:
    """The episode in the searched feed, when search finds one other than the registered feed that lacked it."""
    searched = _search_show(show_name=spotify.show_name)
    if searched is None or searched.feed_url == registered.feed_url:
        return None

    return _match_spotify_episode(spotify, show=searched)


def _resolve_apple(*, show_id: str, episode_id: int) -> ResolvedEpisode:
    lookup = _fetch_json(url=f"{ITUNES_LOOKUP_URL}?id={show_id}&entity=podcastEpisode&limit={_LOOKUP_EPISODE_LIMIT}")
    results: list[dict[str, Any]] = lookup.get("results", [])
    show = next((result for result in results if result.get("wrapperType") == "track" and result.get("feedUrl")), None)
    apple_episode = next((result for result in results if result.get("trackId") == episode_id), None)
    if show is None or apple_episode is None:
        _logger.info("Apple lookup of show %s has no episode %d", show_id, episode_id)
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND)

    title = apple_episode.get("trackName")
    release_date = apple_episode.get("releaseDate")
    show_name = show.get("collectionName")
    if not isinstance(title, str) or not isinstance(release_date, str) or not isinstance(show_name, str):
        _logger.info("Apple lookup of show %s lacks trackName, releaseDate or collectionName", show_id)
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND)

    items = _read_feed(show["feedUrl"])
    item = _item_by_guid(items=items, guid=apple_episode.get("episodeGuid")) or best_match(
        title=title,
        published=_apple_date(release_date),
        items=items,
    )
    if item is None:
        _logger.info("Apple episode %r not found in the feed of show %s", title, show_id)
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND)

    return _resolved(item=item, show_name=show_name, feed_url=show["feedUrl"])


def _read_spotify_page(*, episode_id: str) -> SpotifyEpisode:
    try:
        page = fetch_title.fetch_page(
            url=SPOTIFY_EPISODE_URL.format(episode_id=episode_id),
            timeout_seconds=_SPOTIFY_TIMEOUT_SECONDS,
            max_bytes=_SPOTIFY_MAX_BYTES,
            headers=_HEADERS,
        )
        return spotify_episode_from_page(page)
    except httpx.HTTPStatusError as error:
        if error.response.status_code not in _GONE_STATUSES:
            raise
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND) from error
    except ValueError as error:
        _logger.info("Spotify page for %s unreadable: %s", episode_id, error)
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND) from error


def _registered_show(engine: sqlalchemy.Engine, *, show_name: str) -> _Show | None:
    with sqlalchemy.orm.Session(engine) as db:
        row = db.scalars(
            sqlalchemy.select(models.PodcastShow).where(models.PodcastShow.name_key == name_key(show_name))
        ).first()
        return _Show(name=row.name, feed_url=row.feed_url, itunes_id=row.itunes_id) if row else None


def _search_show(*, show_name: str) -> _Show | None:
    """The best iTunes Search hit (see `best_search_hit`) as a show, or None when there is none to use."""
    search = _fetch_json(
        url=str(
            httpx.URL(
                ITUNES_SEARCH_URL,
                params={
                    "media": "podcast",
                    "entity": "podcast",
                    "term": show_name,
                    "limit": _SEARCH_CANDIDATE_COUNT,
                },
            )
        )
    )
    hit = best_search_hit(show_name=show_name, results=search.get("results", []))
    if hit is None:
        return None

    return _Show(name=show_name, feed_url=hit["feedUrl"], itunes_id=hit.get("collectionId"))


def best_search_hit(*, show_name: str, results: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The feed-bearing hit named exactly (case-insensitive) like the show, else the top hit that has a feed.

    A hit named exactly like the show but without a feed means the show has none (Spotify-only), so no other
    show's feed is substituted for it.
    """
    exact = [hit for hit in results if hit.get("collectionName", "").casefold() == show_name.casefold()]
    if exact:
        return next((hit for hit in exact if hit.get("feedUrl")), None)

    return next((hit for hit in results if hit.get("feedUrl")), None)


def _remember_show(engine: sqlalchemy.Engine, *, show: _Show) -> None:
    statement = sqlalchemy.dialects.postgresql.insert(models.PodcastShow).values(
        name_key=name_key(show.name), name=show.name, feed_url=show.feed_url, itunes_id=show.itunes_id
    )
    statement = statement.on_conflict_do_update(
        index_elements=[models.PodcastShow.name_key],
        set_={
            "feed_url": statement.excluded.feed_url,
            "itunes_id": statement.excluded.itunes_id,
            "updated_at": sqlalchemy.func.now(),
        },
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.execute(statement)
        db.commit()


def _apple_date(release_date: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(release_date[:10])
    except ValueError as error:
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND) from error


def _read_feed(feed_url: str) -> list[FeedItem]:
    """Fetch and parse a feed; an unparseable or forbidden (DTD/entity) feed can't be fixed by a retry."""
    try:
        return parse_feed(_fetch_feed(feed_url))
    except (xml.etree.ElementTree.ParseError, ValueError) as error:
        _logger.info("Feed %s unreadable: %s", feed_url, error)
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND) from error


def _fetch_feed(feed_url: str) -> bytes:
    return fetch_title.fetch_bytes(
        url=feed_url, timeout_seconds=_FEED_TIMEOUT_SECONDS, max_bytes=_FEED_MAX_BYTES, headers=_HEADERS
    )


def _fetch_json(*, url: str) -> dict[str, Any]:
    body = fetch_title.fetch_bytes(
        url=url, timeout_seconds=_API_TIMEOUT_SECONDS, max_bytes=_API_MAX_BYTES, headers=_HEADERS
    )
    return json.loads(body)


def _item_by_guid(*, items: Sequence[FeedItem], guid: str | None) -> FeedItem | None:
    if not guid:
        return None
    return next((item for item in items if item.guid == guid and item.audio_url), None)


def _resolved(*, item: FeedItem, show_name: str, feed_url: str) -> ResolvedEpisode:
    assert item.audio_url is not None
    episode = episode_content.PodcastEpisode(
        show_name=show_name,
        title=item.title,
        description=item.description,
        feed_url=feed_url,
        guid=item.guid,
        audio_url=item.audio_url,
        duration_s=item.duration_s,
    )
    return ResolvedEpisode(episode=episode, transcripts=item.transcripts)


def _feed_item(item: Any) -> FeedItem:
    enclosure = item.find("enclosure")
    guid = item.findtext("guid")
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


def _similarity(first: str, second: str) -> float:
    return difflib.SequenceMatcher(a=_normalize(first), b=_normalize(second)).ratio()


def _normalize(text: str) -> str:
    return _NON_WORD_PATTERN.sub("", text.casefold())
