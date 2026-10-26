"""Spike: can a shared Spotify episode link be matched to the same episode in the show's public RSS feed?

Run: python3 -I spikes/podcast_resolve/resolve_episodes.py
"""

import concurrent.futures
import datetime
import difflib
import email.utils
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree
from dataclasses import dataclass

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"
SEARCH_CANDIDATE_COUNT = 5
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
REQUEST_TIMEOUT_SECONDS = 30
MIN_TITLE_SIMILARITY = 0.6
MAX_PUBLISH_DAYS_APART = 3

LD_JSON_PATTERN = re.compile(
    r'<script type="application/ld\+json">(.+?)</script>', re.DOTALL
)
SHOW_NAME_PATTERN = re.compile(r"^Listen to this episode from (.+?) on Spotify\.")

# Links shared from my phone on 2026-10-26
SPOTIFY_EPISODE_URLS = [
    "https://open.spotify.com/episode/78EhEFfadLHjjHI2u2jzQk",
    "https://open.spotify.com/episode/2VYJJiqQHsodk6kt00ex3z",
    "https://open.spotify.com/episode/7KitoirgJYocvFl1mOfuzm",
    "https://open.spotify.com/episode/0oCDDAKM5HOLDTmVg7kBzW",
    "https://open.spotify.com/episode/5NQFPblNw8ewxKolIDpiYN",
    "https://open.spotify.com/episode/4njsXIKuAL8SxFJgO312bS",
    "https://open.spotify.com/episode/5a1Mz3dkWPjhWzskMqFi0y",
    "https://open.spotify.com/episode/7bmemSbcIsoySwai0hoXzm",
    "https://open.spotify.com/episode/2ZNrpVSrgZMlDwQinl20Ay",
    "https://open.spotify.com/episode/2gvsQxvrqyPMCNVRFmeQDY",
    "https://open.spotify.com/episode/381MqxuiIutkTG0dbKrQU1",
    "https://open.spotify.com/episode/75VXqCGAV1igZViPFO8LIE",
    "https://open.spotify.com/episode/5NH5DolRk68wShCamCIFSJ",
]


@dataclass
class SpotifyEpisode:
    title: str
    show_name: str
    published: datetime.date


@dataclass
class FeedMatch:
    title: str
    published: datetime.date | None
    similarity: float
    audio_url: str | None
    has_transcript: bool


@dataclass
class EpisodeResult:
    url: str
    spotify: SpotifyEpisode | None
    feed_show_name: str | None
    match: FeedMatch | None
    error: str | None


def main() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(_resolve_episode, SPOTIFY_EPISODE_URLS))

    for result in results:
        _print_result(result=result)
    _print_summary(results=results)


def _resolve_episode(url: str) -> EpisodeResult:
    try:
        spotify = _read_spotify_page(url=url)
    except (
        Exception
    ) as error:  # Spike: record any per-link failure rather than abort the run
        return EpisodeResult(
            url=url,
            spotify=None,
            feed_show_name=None,
            match=None,
            error=f"spotify page: {error}",
        )

    show = _search_itunes(show_name=spotify.show_name)
    if show is None or "feedUrl" not in show:
        return EpisodeResult(
            url=url,
            spotify=spotify,
            feed_show_name=None,
            match=None,
            error="show not found",
        )

    channel = xml.etree.ElementTree.fromstring(_fetch(url=show["feedUrl"])).find(
        "channel"
    )
    match = _best_feed_match(spotify=spotify, items=channel.findall("item"))
    return EpisodeResult(
        url=url,
        spotify=spotify,
        feed_show_name=show["collectionName"],
        match=match,
        error=None,
    )


def _read_spotify_page(url: str) -> SpotifyEpisode:
    page = _fetch(url=url).decode()
    episode = json.loads(LD_JSON_PATTERN.search(page).group(1))

    # The show name is only exposed inside the boilerplate first sentence of the description
    show_name = SHOW_NAME_PATTERN.match(episode["description"]).group(1)
    return SpotifyEpisode(
        title=html.unescape(episode["name"]),
        show_name=html.unescape(show_name),
        published=datetime.date.fromisoformat(episode["datePublished"]),
    )


def _search_itunes(show_name: str) -> dict | None:
    params = urllib.parse.urlencode(
        {"media": "podcast", "term": show_name, "limit": SEARCH_CANDIDATE_COUNT}
    )
    candidates = json.loads(_fetch(url=f"{ITUNES_SEARCH_URL}?{params}"))["results"]
    exact_matches = [
        hit
        for hit in candidates
        if hit["collectionName"].casefold() == show_name.casefold()
    ]
    return (
        exact_matches[0] if exact_matches else (candidates[0] if candidates else None)
    )


def _best_feed_match(
    spotify: SpotifyEpisode, items: list[xml.etree.ElementTree.Element]
) -> FeedMatch | None:
    # Only consider episodes published within a few days of the Spotify date, then pick the closest title
    candidates = [
        _to_feed_match(spotify=spotify, item=item)
        for item in items
        if _days_apart(first=spotify.published, second=_item_date(item=item))
        <= MAX_PUBLISH_DAYS_APART
    ]
    if not candidates:
        return None

    best = max(candidates, key=lambda candidate: candidate.similarity)
    return best if best.similarity >= MIN_TITLE_SIMILARITY else None


def _to_feed_match(
    spotify: SpotifyEpisode, item: xml.etree.ElementTree.Element
) -> FeedMatch:
    title = html.unescape(item.findtext("title", default="")).strip()
    enclosure = item.find("enclosure")
    return FeedMatch(
        title=title,
        published=_item_date(item=item),
        similarity=difflib.SequenceMatcher(
            a=_normalize(text=spotify.title), b=_normalize(text=title)
        ).ratio(),
        audio_url=enclosure.get("url") if enclosure is not None else None,
        has_transcript=item.find(f"{{{PODCAST_NAMESPACE}}}transcript") is not None,
    )


def _item_date(item: xml.etree.ElementTree.Element) -> datetime.date | None:
    pub_date = item.findtext("pubDate")
    return email.utils.parsedate_to_datetime(pub_date).date() if pub_date else None


def _days_apart(first: datetime.date, second: datetime.date | None) -> int:
    return abs((first - second).days) if second else 10**6


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.casefold())


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


def _print_result(result: EpisodeResult) -> None:
    if result.error:
        print(f"FAIL   {result.url}\n       {result.error} ({result.spotify})")
        return

    spotify = result.spotify
    print(
        f"{'MATCH' if result.match else 'MISS '}  [{spotify.show_name} -> {result.feed_show_name}]"
    )
    print(f"       spotify: {spotify.title!r} ({spotify.published})")
    if result.match:
        match = result.match
        print(
            f"       rss:     {match.title!r} ({match.published}) sim={match.similarity:.2f} transcript={match.has_transcript}"
        )


def _print_summary(results: list[EpisodeResult]) -> None:
    matched = [result for result in results if result.match]
    with_transcript = [result for result in matched if result.match.has_transcript]
    print()
    print(f"Matched to RSS episode:  {len(matched)}/{len(results)}")
    print(f"With RSS transcript:     {len(with_transcript)}/{len(matched)}")


if __name__ == "__main__":
    main()
