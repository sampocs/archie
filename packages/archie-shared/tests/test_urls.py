"""Unit tests for URL normalizing and kind detection (pure functions, no database)."""

from __future__ import annotations

import pytest
from archie_shared import urls

X_POST_URL = "https://x.com/i/status/2107691261776052633"


def test_normalize_lowercases_and_strips_tracking_fragment_and_trailing_slash() -> None:
    """Scheme/host lowercase, `www.` gone, `utm_*` and fragment dropped, trailing slash removed."""
    assert urls.normalize_url("https://WWW.Example.com/a/?utm_source=x&id=3#frag") == "https://example.com/a?id=3"


def test_normalize_drops_spotify_share_noise() -> None:
    """Spotify's `si` and `utm_*` share parameters do not make a different episode."""
    shared = "https://open.spotify.com/episode/abc?si=123&utm_source=native-share-menu"

    assert urls.normalize_url(shared) == "https://open.spotify.com/episode/abc"


@pytest.mark.parametrize(
    "url",
    [
        "https://twitter.com/sama/status/2107691261776052633?s=20",
        "https://mobile.x.com/sama/status/2107691261776052633",
        "http://www.twitter.com/sama/status/2107691261776052633/",
        "https://x.com/i/status/2107691261776052633",
    ],
)
def test_normalize_collapses_x_status_urls(url: str) -> None:
    """Every spelling of one X post normalizes to the canonical `x.com/i/status/<id>` form."""
    assert urls.normalize_url(url) == X_POST_URL


def test_normalize_collapses_x_article_urls() -> None:
    """An X article URL becomes a status URL, because the canonical form has no `article` path."""
    expected = "https://x.com/i/status/2033603974675227095"

    assert urls.normalize_url("https://x.com/i/article/2033603974675227095") == expected


def test_normalize_leaves_x_profiles_as_ordinary_urls() -> None:
    """A profile has no post id, so only the generic rules apply."""
    assert urls.normalize_url("https://Twitter.com/naval/?s=20") == "https://twitter.com/naval"


def test_normalize_keeps_remaining_query_params_in_order() -> None:
    """Kept parameters stay in their original order; dropped ones vanish from between them."""
    assert urls.normalize_url("https://example.com/p?z=1&t=9&a=2&ref=x&m=3") == "https://example.com/p?z=1&a=2&m=3"


def test_normalize_drops_m_and_mobile_prefixes_and_keeps_other_subdomains() -> None:
    """Only `www.`, `mobile.` and `m.` are removed from the host."""
    assert urls.normalize_url("https://m.example.com/x") == "https://example.com/x"
    assert urls.normalize_url("https://blog.example.com/x") == "https://blog.example.com/x"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (X_POST_URL, urls.UrlKind.X),
        ("https://twitter.com/sama/status/2107691261776052633", urls.UrlKind.X),
        ("https://www.youtube.com/watch?v=abc", urls.UrlKind.YOUTUBE),
        ("https://youtu.be/xyz", urls.UrlKind.YOUTUBE),
        ("https://open.spotify.com/episode/abc", urls.UrlKind.PODCAST),
        ("https://podcasts.apple.com/us/podcast/x/id1", urls.UrlKind.PODCAST),
        ("https://example.com/post", urls.UrlKind.ARTICLE),
        ("https://x.com/naval", urls.UrlKind.ARTICLE),
    ],
)
def test_detect_kind(url: str, expected: urls.UrlKind) -> None:
    """Each host family maps to its kind; an X profile falls back to article."""
    assert urls.detect_kind(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://twitter.com/sama/status/2107691261776052633?s=20", "2107691261776052633"),
        ("https://x.com/i/article/2033603974675227095", "2033603974675227095"),
        ("https://x.com/naval", None),
        ("https://example.com/status/123", None),
    ],
)
def test_x_post_id(url: str, expected: str | None) -> None:
    """The id comes from status and article paths on X hosts only."""
    assert urls.x_post_id(url) == expected
