"""Spike: can each show I listen to be resolved to a public RSS feed, and do feeds publish transcripts?

Run: python3 -I spikes/podcast_resolve/resolve_shows.py
"""

import concurrent.futures
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree
from dataclasses import dataclass

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
SEARCH_CANDIDATE_COUNT = 5
PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
USER_AGENT = "second-brain-spike/0.1"
RECENT_EPISODE_COUNT = 10
REQUEST_TIMEOUT_SECONDS = 30

# Search terms tuned so the top iTunes hit is the intended show
SHOW_QUERIES = [
    "Dwarkesh Podcast",
    "All-In with Chamath Jason Sacks Friedberg",
    "New Heights Jason Travis Kelce",
    "Pardon My Take",
    "Bussin' With The Boys",
    "Empire Blockworks",
    "Bell Curve Blockworks",
    "The Rollup",
    "Milk Road Crypto",
    "Bankless",
    "My First Million",
    "This Week in Startups",
    "Darknet Diaries",
    "Acquired",
    "Lenny's Podcast",
    "Lex Fridman Podcast",
    "When Shift Happens Podcast",
    "Invest Like the Best with Patrick O'Shaughnessy",
    "Real Survival Stories",
    "Huberman Lab",
    "The Joe Rogan Experience",
    "Honestly with Bari Weiss",
    "a16z Podcast",
    "Money Stuff: The Podcast",
    "Business Breakdowns",
    "Freakonomics Radio",
    "0xResearch",
    "The Tim Ferriss Show",
]


@dataclass
class ShowResult:
    query: str
    matched_name: str | None
    feed_url: str | None
    recent_episodes: int
    episodes_with_transcript: int
    transcript_types: set[str]
    latest_title: str | None
    latest_duration: str | None
    has_audio_enclosure: bool
    error: str | None


def main() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_resolve_show, SHOW_QUERIES))

    _print_table(results=results)
    _print_summary(results=results)


def _resolve_show(query: str) -> ShowResult:
    search_hit = _search_itunes(query=query)
    if search_hit is None or "feedUrl" not in search_hit:
        return _failed_result(
            query=query,
            matched_name=(search_hit or {}).get("collectionName"),
            error="no feed url",
        )

    feed_url = search_hit["feedUrl"]
    try:
        feed_xml = _fetch(url=feed_url)
    except (
        Exception
    ) as error:  # Spike: record any fetch failure per show rather than abort the run
        return _failed_result(
            query=query,
            matched_name=search_hit["collectionName"],
            error=f"feed fetch: {error}",
        )

    return _summarize_feed(
        query=query,
        matched_name=search_hit["collectionName"],
        feed_url=feed_url,
        feed_xml=feed_xml,
    )


def _search_itunes(query: str) -> dict | None:
    params = urllib.parse.urlencode({"media": "podcast", "term": query, "limit": SEARCH_CANDIDATE_COUNT})
    candidates = json.loads(_fetch(url=f"{ITUNES_SEARCH_URL}?{params}"))["results"]
    if not candidates:
        return None

    # The top hit is sometimes a spin-off or stale listing, so prefer an exact title match
    exact_matches = [hit for hit in candidates if hit["collectionName"].casefold() == query.casefold()]
    return exact_matches[0] if exact_matches else candidates[0]


def _summarize_feed(
    query: str, matched_name: str, feed_url: str, feed_xml: bytes
) -> ShowResult:
    channel = xml.etree.ElementTree.fromstring(feed_xml).find("channel")
    recent_items = channel.findall("item")[:RECENT_EPISODE_COUNT]

    # Podcasting 2.0 transcript tags: one per format (vtt, srt, json, html) on each episode
    transcript_tags = [
        item.findall(f"{{{PODCAST_NAMESPACE}}}transcript") for item in recent_items
    ]
    transcript_types = {
        tag.get("type", "?") for tags in transcript_tags for tag in tags
    }

    latest = recent_items[0] if recent_items else None
    enclosure = latest.find("enclosure") if latest is not None else None
    return ShowResult(
        query=query,
        matched_name=matched_name,
        feed_url=feed_url,
        recent_episodes=len(recent_items),
        episodes_with_transcript=sum(1 for tags in transcript_tags if tags),
        transcript_types=transcript_types,
        latest_title=latest.findtext("title") if latest is not None else None,
        latest_duration=latest.findtext(f"{{{ITUNES_NAMESPACE}}}duration")
        if latest is not None
        else None,
        has_audio_enclosure=enclosure is not None
        and "audio" in enclosure.get("type", "audio"),
        error=None,
    )


def _failed_result(query: str, matched_name: str | None, error: str) -> ShowResult:
    return ShowResult(
        query=query,
        matched_name=matched_name,
        feed_url=None,
        recent_episodes=0,
        episodes_with_transcript=0,
        transcript_types=set(),
        latest_title=None,
        latest_duration=None,
        has_audio_enclosure=False,
        error=error,
    )


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


def _print_table(results: list[ShowResult]) -> None:
    for result in results:
        if result.error:
            print(
                f"FAIL  {result.query!r:45} -> {result.matched_name} ({result.error})"
            )
            continue

        transcripts = f"{result.episodes_with_transcript}/{result.recent_episodes}"
        types = ",".join(sorted(result.transcript_types)) or "-"
        print(
            f"OK    {result.query!r:45} -> {result.matched_name!r:50} "
            f"audio={result.has_audio_enclosure} transcripts={transcripts:5} types={types}"
        )
        print(f"        latest: {result.latest_title!r} ({result.latest_duration})")


def _print_summary(results: list[ShowResult]) -> None:
    resolved = [result for result in results if not result.error]
    with_transcripts = [
        result for result in resolved if result.episodes_with_transcript
    ]
    print()
    print(f"Resolved to RSS:          {len(resolved)}/{len(results)}")
    print(f"Publish RSS transcripts:  {len(with_transcripts)}/{len(resolved)}")
    print("  " + ", ".join(result.matched_name for result in with_transcripts))


if __name__ == "__main__":
    main()
