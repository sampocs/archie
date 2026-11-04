"""URL normalizing and kind detection.

Capture dedupes by normalized URL, so the same page shared from different apps (tracking params,
`www.`, a mobile host, a Twitter vs X link) must collapse to one string. The phone and the server
both rely on these rules, which come from the product spec.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from enum import StrEnum

# Query parameters that only track where a link was shared from. `s` and `t` are X/YouTube share noise.
DROPPED_QUERY_PARAMS = frozenset({"si", "s", "t", "ref", "fbclid", "gclid"})
DROPPED_QUERY_PREFIX = "utm_"
DROPPED_HOST_PREFIXES = ("www.", "mobile.", "m.")

X_HOSTS = frozenset({"x.com", "twitter.com"})
YOUTUBE_HOSTS = frozenset({"youtube.com", "youtu.be"})
PODCAST_HOSTS = frozenset({"open.spotify.com", "podcasts.apple.com"})

# `/<handle>/status/<id>` or `/i/article/<id>` and so on; a profile (`/naval`) has no id.
_X_POST_PATH = re.compile(r"^/(?:[^/]+/)+(?:status|article)/(\d+)(?:/|$)")
_SPOTIFY_EPISODE_PATH = re.compile(r"^/(?:intl-[a-z]+/)?episode/([A-Za-z0-9]+)/?$")
_APPLE_PODCAST_PATH = re.compile(r"^/[a-z]{2}/podcast/[^/]+/id(\d+)/?$")
_APPLE_EPISODE_ID = re.compile(r"^\d+$")
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_YOUTUBE_ID_PATH = re.compile(r"^/(?:shorts|live)/([A-Za-z0-9_-]+)/?$")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_X_CANONICAL_URL = "https://x.com/i/status/{post_id}"


class UrlKind(StrEnum):
    """What a URL points at, as far as its host reveals (models' `SourceKind` adds `LINK`)."""

    ARTICLE = "article"
    X = "x"
    YOUTUBE = "youtube"
    PODCAST = "podcast"


def normalize_url(url: str) -> str:
    """Return the canonical form of `url` used to recognize the same page captured twice."""
    parts = urllib.parse.urlsplit(url.strip())
    host = _bare_host(parts.netloc, scheme=parts.scheme)

    post_id = _x_post_id_for(host=host, path=parts.path)
    if post_id is not None:
        return _X_CANONICAL_URL.format(post_id=post_id)

    kept_params = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if name.lower() not in DROPPED_QUERY_PARAMS and not name.lower().startswith(DROPPED_QUERY_PREFIX)
    ]
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), host, parts.path.rstrip("/"), urllib.parse.urlencode(kept_params), "")
    )


def detect_kind(url: str) -> UrlKind:
    """Classify `url` by host; an X host without a post id (a profile) is an ordinary article."""
    parts = urllib.parse.urlsplit(url.strip())
    host = _bare_host(parts.netloc, scheme=parts.scheme)

    if _x_post_id_for(host=host, path=parts.path) is not None:
        return UrlKind.X
    if host in YOUTUBE_HOSTS:
        return UrlKind.YOUTUBE
    if host in PODCAST_HOSTS:
        return UrlKind.PODCAST
    return UrlKind.ARTICLE


def x_post_id(url: str) -> str | None:
    """The numeric post id of an X status or article URL, or None for any other URL."""
    parts = urllib.parse.urlsplit(url.strip())
    return _x_post_id_for(host=_bare_host(parts.netloc, scheme=parts.scheme), path=parts.path)


def _bare_host(netloc: str, *, scheme: str = "") -> str:
    host = netloc.lower().rpartition("@")[2]
    default_port = _DEFAULT_PORTS.get(scheme.lower())
    if default_port is not None:
        host = host.removesuffix(f":{default_port}")
    for prefix in DROPPED_HOST_PREFIXES:
        if host.startswith(prefix):
            return host.removeprefix(prefix)
    return host


def _x_post_id_for(*, host: str, path: str) -> str | None:
    if host not in X_HOSTS:
        return None
    match = _X_POST_PATH.match(path)
    return match.group(1) if match else None


class PodcastPlatform(StrEnum):
    """Which podcast app a shared episode link came from."""

    SPOTIFY = "spotify"
    APPLE = "apple"


@dataclass(frozen=True)
class PodcastLink:
    """A podcast episode link: the platform's episode id, and the show id when the link carries one (Apple only)."""

    platform: PodcastPlatform
    episode_id: str
    show_id: str | None


def podcast_link(url: str) -> PodcastLink | None:
    """Parse a Spotify or Apple Podcasts episode link; show links and everything else give None."""
    parts = urllib.parse.urlsplit(url.strip())
    host = _bare_host(parts.netloc, scheme=parts.scheme)

    if host == "open.spotify.com":
        match = _SPOTIFY_EPISODE_PATH.match(parts.path)
        return PodcastLink(PodcastPlatform.SPOTIFY, match.group(1), None) if match else None

    if host == "podcasts.apple.com":
        match = _APPLE_PODCAST_PATH.match(parts.path)
        episode_ids = urllib.parse.parse_qs(parts.query).get("i", [])
        if not match or not episode_ids or not _APPLE_EPISODE_ID.match(episode_ids[0]):
            return None
        return PodcastLink(PodcastPlatform.APPLE, episode_ids[0], match.group(1))

    return None


def youtube_video_id(url: str) -> str | None:
    """The video id of a watch, youtu.be, shorts or live link; channels, playlists and other URLs give None."""
    parts = urllib.parse.urlsplit(url.strip())
    host = _bare_host(parts.netloc, scheme=parts.scheme)

    if host == "youtu.be":
        video_id = parts.path.strip("/")
        return video_id if _YOUTUBE_ID.match(video_id) else None

    if host != "youtube.com":
        return None
    if parts.path == "/watch":
        video_ids = urllib.parse.parse_qs(parts.query).get("v", [])
        return video_ids[0] if video_ids and _YOUTUBE_ID.match(video_ids[0]) else None

    match = _YOUTUBE_ID_PATH.match(parts.path)
    return match.group(1) if match else None
