"""Pure podcast parsing and matching, on real files copied out of the recorded cassettes (`fixtures/podcast/`).

`darknet_diaries_blackshades.vtt` is the real transcript of Darknet Diaries "182: Blackshades"; the feed is that show's
real feed cut to its first 5 items. The `.srt` and `.json` files were converted from the first 300 cues of the real VTT
(no public feed with a SubRip or Podcasting 2.0 JSON transcript was looked for), so they test our parsers on the
formats' shape, not on a particular publisher's quirks.
"""

from __future__ import annotations

import datetime
import pathlib
import re

import httpx
import pytest
from archie_shared import podcast_feed
from archie_worker import content, errors
from archie_worker.content import podcast, transcripts
from archie_worker.handlers import fetch_title

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "podcast"
MIN_WORDS = 200


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _item(
    *, title: str, published: datetime.date | None, audio_url: str | None = "https://example.test/a.mp3"
) -> podcast_feed.FeedItem:
    return podcast_feed.FeedItem(
        title=title,
        published=published,
        guid=None,
        audio_url=audio_url,
        duration_s=None,
        description="",
        transcripts=[],
    )


def test_vtt_cues_become_ordered_segments_without_tags() -> None:
    """The first cue starts at 0.435 s, starts never go backwards, and no markup is left."""
    segments = transcripts.parse_vtt(_read("darknet_diaries_blackshades.vtt"))

    assert segments[0].start == pytest.approx(0.435)
    assert segments[0].text == "JACK: Have you ever tried installing"
    starts = [segment.start for segment in segments]
    assert starts == sorted(starts)
    assert len(" ".join(segment.text for segment in segments).split()) >= MIN_WORDS
    assert not any("<" in segment.text or "-->" in segment.text for segment in segments)


def test_vtt_tags_and_hour_timestamps_are_handled() -> None:
    """A voice tag and a class tag are dropped, entities decoded, and `h:mm:ss` timings read."""
    vtt = "WEBVTT\n\nNOTE a comment\n\n1:02:03.500 --> 1:02:05.000\n<v Host>Fish &amp; <c.loud>chips</c>\n"

    (segment,) = transcripts.parse_vtt(vtt)

    assert (segment.start, segment.text) == (3723.5, "Fish & chips")


def test_srt_cues_become_segments() -> None:
    """SubRip cues keep their order and millisecond starts."""
    segments = transcripts.parse_srt(_read("darknet_diaries_blackshades.srt"))

    assert len(segments) == 300
    assert segments[0].start == pytest.approx(0.435)
    assert segments[1].start == pytest.approx(1.601)
    assert len(" ".join(segment.text for segment in segments).split()) >= MIN_WORDS


def test_podcasting_two_json_becomes_segments() -> None:
    """Podcasting 2.0 JSON segments map `startTime` and `body`."""
    segments = transcripts.parse_json(_read("darknet_diaries_blackshades.json"))

    assert len(segments) == 300
    assert segments[0] == content.Segment(start=0.435, text="JACK: Have you ever tried installing")


def test_json_without_segments_is_rejected() -> None:
    """JSON with no `segments` is a parse failure, so `fetch_best` moves on."""
    with pytest.raises(ValueError):
        transcripts.parse_json('{"version": "1.0.0"}')


def test_html_becomes_visible_text_only() -> None:
    """Scripts, styles and the head are dropped; whitespace is collapsed."""
    page = (
        "<html><head><title>x</title><style>p{}</style></head>"
        "<body><p>Hello</p><script>var a;</script><p>there  world</p></body></html>"
    )

    assert transcripts.html_to_text(page) == "Hello there world"


def test_the_feed_gives_titles_dates_enclosures_durations_and_transcripts() -> None:
    """The real feed's first item carries every field the resolver needs."""
    items = podcast_feed.parse_feed((FIXTURES / "darknet_diaries_feed.xml").read_bytes())

    assert [item.title for item in items][:2] == ["182: Blackshades", "181: Ricky"]
    assert len(items) == 5
    blackshades = items[0]
    assert blackshades.published is not None
    assert blackshades.audio_url and blackshades.audio_url.startswith("http")
    assert blackshades.guid
    assert blackshades.duration_s and blackshades.duration_s > 600
    assert [(link.mime_type, link.url.endswith(".vtt")) for link in blackshades.transcripts] == [("text/vtt", True)]
    assert 0 < len(blackshades.description) <= 2000
    assert "<" not in blackshades.description


def test_every_item_has_artwork_and_a_bare_item_falls_back_to_the_channels() -> None:
    """Items carry their own artwork; a bare one gets the channel's `itunes:image`, else its `<image><url>`."""
    feed = (FIXTURES / "darknet_diaries_feed.xml").read_text(encoding="utf-8")
    items = podcast_feed.parse_feed(feed.encode())
    assert all(item.image_url and item.image_url.startswith("https://") for item in items)

    item_image = re.compile(r'\s*<itunes:image href="[^"]*Ep182_BlackshadesSquare.jpg" />')
    assert item_image.search(feed)
    bare = podcast_feed.parse_feed(item_image.sub("", feed).encode())
    channel_href = re.search(r'<itunes:image href="([^"]+)"', feed)
    assert channel_href is not None
    assert bare[0].image_url == channel_href.group(1)
    assert bare[1].image_url != bare[0].image_url

    channel_url = re.search(r"<image>\s*<url>([^<]+)</url>", feed)
    assert channel_url is not None
    without_channel_itunes_image = re.sub(r'\n    <itunes:image href="[^"]*68ff[^"]*" />', "", item_image.sub("", feed))
    assert podcast_feed.parse_feed(without_channel_itunes_image.encode())[0].image_url == channel_url.group(1)


def test_durations_are_read_as_seconds_or_clock_times() -> None:
    """`itunes:duration` as seconds, `mm:ss` or `h:mm:ss`; anything else is None."""
    feed = b"""<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
      <item><title>a</title><itunes:duration>754</itunes:duration></item>
      <item><title>b</title><itunes:duration>12:34</itunes:duration></item>
      <item><title>c</title><itunes:duration>1:02:03</itunes:duration></item>
      <item><title>d</title><itunes:duration>soon</itunes:duration></item>
      <item><title>e</title></item></channel></rss>"""

    assert [item.duration_s for item in podcast_feed.parse_feed(feed)] == [754, 754, 3723, None, None]


DAY = datetime.date(2026, 10, 20)


def test_an_exact_title_two_days_apart_wins_over_a_similar_one() -> None:
    """The highest title ratio inside the date window wins, not the nearest date."""
    exact = _item(title="Episode 5: Foxes", published=DAY + datetime.timedelta(days=2))
    similar = _item(title="Episode 5: Foxes (rerun)", published=DAY)

    assert podcast.best_match(title="Episode 5: Foxes", published=DAY, items=[similar, exact]) is exact


def test_a_title_below_the_ratio_matches_nothing() -> None:
    """A title scoring just under 0.6 is no match."""
    # Ten shared leading characters out of 17 + 17: ratio 20 / 34 = 0.588, just under the 0.6 bar.
    items = [_item(title="abcdefghijuvwxyzz", published=DAY)]

    assert podcast.best_match(title="abcdefghijklmnopq", published=DAY, items=items) is None


def test_a_matching_title_four_days_apart_matches_nothing() -> None:
    """The date window is 3 days."""
    items = [_item(title="Episode 5", published=DAY + datetime.timedelta(days=4))]

    assert podcast.best_match(title="Episode 5", published=DAY, items=items) is None


def test_items_without_audio_or_a_date_are_skipped() -> None:
    """An item with no enclosure, or no parseable date, can never match."""
    items = [
        _item(title="Episode 5", published=DAY, audio_url=None),
        _item(title="Episode 5", published=None),
    ]

    assert podcast.best_match(title="Episode 5", published=DAY, items=items) is None


def test_a_guidless_apple_title_matches_the_feed_title_with_its_number() -> None:
    """The real pair from the Apple lookup and feed: "Blackshades" vs "182: Blackshades"."""
    items = podcast_feed.parse_feed((FIXTURES / "darknet_diaries_feed.xml").read_bytes())
    published = items[0].published
    assert published is not None

    match = podcast.best_match(title="Blackshades", published=published, items=items)

    assert match is items[0]


def test_the_spotify_page_gives_title_show_and_date() -> None:
    """The real Spotify page's ld+json gives the episode, its show and its date."""
    episode = podcast.spotify_episode_from_page(_read("spotify_episode_page.html"))

    assert episode == podcast.SpotifyEpisode(
        title="Alligator in a bagel shop, largest rubber band ball",
        show_name="UPI Odd News Minute",
        published=datetime.date(2026, 11, 3),
    )


def test_a_spotify_page_listing_its_ld_json_reads_the_episode_entry() -> None:
    """Spotify now wraps the ld+json in a list; the PodcastEpisode entry in it gives the episode."""
    page = (
        '<script type="application/ld+json">[{"@type": "BreadcrumbList"}, {"@type": "PodcastEpisode",'
        ' "name": "An invented episode", "description": "Listen to this episode from Example Show on Spotify. More.",'
        ' "datePublished": "2026-11-03"}]</script>'
    )

    assert podcast.spotify_episode_from_page(page) == podcast.SpotifyEpisode(
        title="An invented episode", show_name="Example Show", published=datetime.date(2026, 11, 3)
    )


@pytest.mark.parametrize(
    "page",
    [
        "<html>no data</html>",
        '<script type="application/ld+json">{"name": "x", "description": "Other", "datePublished": "2026-11-03"}'
        "</script>",
        '<script type="application/ld+json">{"description": "Listen to this episode from Show on Spotify.",'
        ' "datePublished": "2026-11-03"}</script>',
        '<script type="application/ld+json">[1]</script>',
    ],
)
def test_a_page_without_the_expected_data_is_rejected(page: str) -> None:
    """A page with no ld+json, or a description without the show prefix, raises ValueError."""
    with pytest.raises(ValueError):
        podcast.spotify_episode_from_page(page)


def test_a_feed_with_a_doctype_entity_fails_permanently(monkeypatch: pytest.MonkeyPatch) -> None:
    """defusedxml refuses entity declarations; that surfaces as EPISODE_NOT_FOUND, not a retryable error."""
    feed = (
        b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY boom "x">]>'
        b"<rss><channel><item><title>&boom;</title></item></channel></rss>"
    )
    monkeypatch.setattr(podcast, "_fetch_feed", lambda feed_url: feed)

    with pytest.raises(errors.PermanentJobError) as raised:
        podcast._read_feed("https://example.test/feed.xml")

    assert raised.value.reason == errors.FailureReason.EPISODE_NOT_FOUND


def test_name_key_lowercases_and_collapses_whitespace() -> None:
    """Registry keys ignore case and spacing."""
    assert podcast.name_key("  The  Daily ") == "the daily"


# fetch_best serves the real fixture files in place of the network.

VTT_URL = "https://example.test/ep.vtt"
SRT_URL = "https://example.test/ep.srt"
JSON_URL = "https://example.test/ep.json"
HTML_URL = "https://example.test/ep.html"
GONE_URL = "https://example.test/gone.vtt"


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Route `fetch_bytes` to fixture files, recording the URLs asked for; `GONE_URL` answers 404."""
    files = {
        VTT_URL: "darknet_diaries_blackshades.vtt",
        SRT_URL: "darknet_diaries_blackshades.srt",
        JSON_URL: "darknet_diaries_blackshades.json",
        HTML_URL: "spotify_episode_page.html",
    }
    asked: list[str] = []

    def fetch_bytes(*, url: str, **_: object) -> bytes:
        asked.append(url)
        if url not in files:
            raise httpx.HTTPStatusError("gone", request=httpx.Request("GET", url), response=httpx.Response(404))
        return (FIXTURES / files[url]).read_bytes()

    monkeypatch.setattr(fetch_title, "fetch_bytes", fetch_bytes)
    return asked


def _link(url: str, mime_type: str) -> podcast_feed.TranscriptLink:
    return podcast_feed.TranscriptLink(url=url, mime_type=mime_type)


def test_the_vtt_is_tried_before_srt_json_and_html(served: list[str]) -> None:
    """Preference is by format, not by the order the feed lists them; the first good one stops the search."""
    links = [
        _link(HTML_URL, "text/html"),
        _link(JSON_URL, "application/json"),
        _link(SRT_URL, "application/x-subrip"),
        _link(VTT_URL, "text/vtt; charset=utf-8"),
    ]

    published = transcripts.fetch_best(links)

    assert published is not None and len(published.segments) > 300
    assert served == [VTT_URL]


def test_a_failed_link_falls_back_to_the_next_format(served: list[str]) -> None:
    """A 404 on the VTT moves on to the JSON."""
    links = [_link(GONE_URL, "text/vtt"), _link(JSON_URL, "application/json")]

    published = transcripts.fetch_best(links)

    assert published is not None and len(published.segments) == 300
    assert served == [GONE_URL, JSON_URL]


def test_an_unparseable_link_falls_back_to_the_next_format(served: list[str]) -> None:
    """A page that is not JSON, and an SRT-labelled page with no cues, both move on to the next link."""
    links = [
        _link(HTML_URL, "application/srt"),
        _link(HTML_URL, "application/json"),
        _link(SRT_URL, "text/plain"),
    ]

    published = transcripts.fetch_best(links)

    assert published is not None and published.segments == []
    assert served == [HTML_URL, HTML_URL, SRT_URL]


def test_an_html_transcript_has_text_and_no_segments(served: list[str]) -> None:
    """Plain text and HTML give text only, with no segments."""
    published = transcripts.fetch_best([_link(VTT_URL, "text/plain")])

    assert published is not None
    assert published.segments == []
    assert len(published.text.split()) >= MIN_WORDS


def test_unknown_formats_and_no_links_give_nothing(served: list[str]) -> None:
    """A format outside the list is never fetched."""
    assert transcripts.fetch_best([_link(VTT_URL, "application/pdf")]) is None
    assert transcripts.fetch_best([]) is None
    assert served == []


def test_a_transcript_under_200_words_is_ignored(served: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A stub transcript is ignored so the episode gets transcribed."""

    def fetch_short(**_: object) -> bytes:
        return b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nOnly a few words here\n"

    monkeypatch.setattr(fetch_title, "fetch_bytes", fetch_short)

    assert transcripts.fetch_best([_link(VTT_URL, "text/vtt")]) is None


def test_a_top_hit_without_a_feed_is_skipped_for_the_next_one_that_has_one() -> None:
    """With no exact name match, the first hit that has a feedUrl is used, not a feedless top hit."""
    results = [
        {"collectionName": "The Show: Live", "collectionId": 1},
        {"collectionName": "The Show Extra", "collectionId": 2, "feedUrl": "https://example.test/extra.xml"},
    ]

    hit = podcast.best_search_hit(show_name="The Show", results=results)

    assert hit is not None
    assert hit["collectionId"] == 2


def test_an_exact_name_match_wins_over_the_top_hit() -> None:
    """The hit named exactly (any case) beats a higher-ranked near match."""
    results = [
        {"collectionName": "The Show Extra", "collectionId": 2, "feedUrl": "https://example.test/extra.xml"},
        {"collectionName": "the show", "collectionId": 3, "feedUrl": "https://example.test/show.xml"},
    ]

    hit = podcast.best_search_hit(show_name="The Show", results=results)

    assert hit is not None
    assert hit["collectionId"] == 3


def test_an_exact_name_match_without_a_feed_does_not_borrow_another_shows_feed() -> None:
    """A feedless exact match means the show is Spotify-only; the other shows named alike are not it."""
    results = [
        {"collectionName": "The Show", "collectionId": 1},
        {"collectionName": "The Show Extra", "collectionId": 2, "feedUrl": "https://example.test/extra.xml"},
    ]

    assert podcast.best_search_hit(show_name="The Show", results=results) is None


def test_no_search_results_means_no_show() -> None:
    """An empty result gives nothing."""
    assert podcast.best_search_hit(show_name="The Show", results=[]) is None
