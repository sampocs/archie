"""URL normalizing and kind detection.

Capture dedupes by normalized URL, so the same page shared from different apps (tracking params,
`www.`, a mobile host, a Twitter vs X link) must collapse to one string. The phone and the server
both rely on these rules, which come from the product spec.
"""

from __future__ import annotations

import re
import urllib.parse
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
