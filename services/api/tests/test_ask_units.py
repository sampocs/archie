"""Ask's pure logic: a paragraph's label comes from its blocks' citations; history keeps only finished pairs."""

from __future__ import annotations

import dataclasses
import datetime
import uuid
import zoneinfo

import anthropic.types
from archie_api.ask import answer, citations, context, prompts
from archie_db import models, search

HIT = search.ChunkHit(
    chunk_id=7,
    item=search.ItemRef(kind=models.SearchItemKind.SOURCE, id=uuid.UUID(int=1)),
    title="Odd Lots",
    url="https://open.spotify.com/episode/1",
    sender=None,
    saved_at=datetime.datetime(2026, 11, 2, 9, tzinfo=datetime.UTC),
    published_at=None,
    owner_kind=models.ChunkOwner.SOURCE_TEXT,
    text="The Fed pays with reserves.",
    start_seconds=1880.0,
    score=1.0,
    keyword_match=True,
)
PASSAGES = {citations.source_key(HIT): HIT}
NEW_YORK = zoneinfo.ZoneInfo("America/New_York")


def _library(cited: str = "The Fed pays with reserves.") -> anthropic.types.CitationsSearchResultLocation:
    return anthropic.types.CitationsSearchResultLocation(
        type="search_result_location",
        source=citations.source_key(HIT),
        title="Odd Lots",
        cited_text=cited,
        search_result_index=0,
        start_block_index=0,
        end_block_index=1,
    )


def _web(url: str = "https://www.federalreserve.gov/x") -> anthropic.types.CitationsWebSearchResultLocation:
    return anthropic.types.CitationsWebSearchResultLocation(
        type="web_search_result_location", url=url, title="The Fed", cited_text="$6.6T", encrypted_index="e"
    )


def _block(text: str, cited: list[anthropic.types.TextCitation] | None) -> anthropic.types.TextBlock:
    return anthropic.types.TextBlock(type="text", text=text, citations=cited)


def test_a_block_citing_the_library_is_library_even_with_a_web_citation_too() -> None:
    """Library wins; both kinds of chip are kept, each once."""
    segment = citations.segment_of(
        _block("It pays with reserves.", [_library(), _library(), _web()]), passages=PASSAGES
    )

    assert segment.label == citations.AnswerLabel.LIBRARY
    assert [citation["kind"] for citation in segment.citations] == ["library", "web"]
    assert segment.citations[0] == {
        "kind": "library",
        "title": "Odd Lots",
        "source_id": str(uuid.UUID(int=1)),
        "topic_primer_id": None,
        "take_id": None,
        "owner_kind": "source_text",
        "start_seconds": 1880.0,
        "quote": "The Fed pays with reserves.",
    }


def test_web_only_is_web_and_no_citations_is_background() -> None:
    """An unknown library source (not from this answer's searches) is ignored."""
    stray = _library().model_copy(update={"source": "archie:chunk:999"})

    assert (
        citations.segment_of(_block("Balance sheet.", [_web()]), passages=PASSAGES).label == citations.AnswerLabel.WEB
    )
    assert citations.segment_of(_block("Printing is shorthand.", None), passages=PASSAGES).label == (
        citations.AnswerLabel.BACKGROUND
    )
    assert citations.segment_of(_block("Hm.", [stray]), passages=PASSAGES).label == citations.AnswerLabel.BACKGROUND


def test_a_paragraph_split_by_citations_takes_one_label_and_a_blank_line_starts_the_next() -> None:
    """The recorded `ask_library` answer: citations cut one paragraph into four blocks, then a background paragraph."""
    fragments = [
        _block("According to your saved article, the Fed creates money by ", None),
        _block("buying bonds from banks and paying with newly created reserves.", [_library()]),
        _block(" Those reserves are digital balances, and the article notes that ", None),
        _block("they sit in the banks' accounts at the Fed.", [_library(), _library()]),
        _block("\n\nThat's all your library says about it.", None),
    ]
    segments = [citations.segment_of(fragment, passages=PASSAGES) for fragment in fragments]

    relabelled = citations.by_paragraph(segments)

    assert [segment.label for segment in relabelled] == [citations.AnswerLabel.LIBRARY] * 4 + [
        citations.AnswerLabel.BACKGROUND
    ]
    assert [segment.text for segment in relabelled] == [fragment.text for fragment in fragments]
    assert [len(segment.citations) for segment in relabelled] == [0, 1, 0, 1, 0]


def test_a_block_holding_a_blank_line_ends_its_paragraph_and_web_beats_background() -> None:
    """A cited web block labels its paragraph web; the uncited paragraph after the break stays background."""
    segments = [
        citations.segment_of(_block("Rates sit at 4.25%.", [_web()]), passages=PASSAGES),
        citations.segment_of(_block(" That is high.\n\nRates", None), passages=PASSAGES),
        citations.segment_of(_block(" move slowly.", None), passages=PASSAGES),
    ]

    assert [segment.label for segment in citations.by_paragraph(segments)] == [
        citations.AnswerLabel.WEB,
        citations.AnswerLabel.WEB,
        citations.AnswerLabel.BACKGROUND,
    ]


def test_history_keeps_finished_pairs_only_and_the_last_twenty_messages() -> None:
    """A failed answer drops with its question; the history alternates user / assistant from the oldest kept pair."""

    def message(
        role: models.MessageRole, text: str, status: models.MessageStatus = models.MessageStatus.COMPLETE
    ) -> context.HistoryMessage:
        return context.HistoryMessage(role=role, text=text, status=status)

    rows = [
        message(models.MessageRole.USER, "q0"),
        message(models.MessageRole.ASSISTANT, "a0", models.MessageStatus.FAILED),
    ]
    for index in range(1, 13):
        rows += [message(models.MessageRole.USER, f"q{index}"), message(models.MessageRole.ASSISTANT, f"a{index}")]

    history = context.history_messages(rows)

    assert len(history) == context.HISTORY_MESSAGES
    assert history[0] == {"role": "user", "content": "q3"} and history[-1] == {"role": "assistant", "content": "a12"}


def test_only_a_paragraph_with_no_citation_at_all_is_dropped_before_a_tool_call() -> None:
    """Citations cut a cited paragraph into uncited fragments; those stay, while an uncited paragraph is dropped."""
    fragments = [
        _block("According to your article, ", None),
        _block("rates rose.", [_library()]),
        _block(" That mattered a lot.", None),
        _block("\n\nLet me search your library.", None),
    ]
    segments = [citations.segment_of(fragment, passages=PASSAGES) for fragment in fragments]

    relabelled = citations.by_paragraph(segments)

    assert citations.uncited_paragraphs_dropped(relabelled) == [False, False, False, True]


def test_a_heading_paragraph_takes_the_label_of_the_paragraph_after_it() -> None:
    """A bold title line has no citations; it joins the library paragraph it introduces instead of splitting it."""
    fragments = [
        _block("**What to pick:**\n\n", None),
        _block("Something you have an aptitude for, ", None),
        _block("and a deep interest in.", [_library()]),
        _block("\n\n## How to find it", None),
        _block("\n\nBy working on it.", [_library()]),
    ]
    segments = [citations.segment_of(fragment, passages=PASSAGES) for fragment in fragments]

    assert [segment.label for segment in citations.by_paragraph(segments)] == [citations.AnswerLabel.LIBRARY] * 5


def test_a_heading_with_nothing_after_it_stays_background_and_waits_to_be_sent() -> None:
    """Streaming sends a heading's block only once its label is final: when a paragraph follows, or the round ends."""
    paragraphs = citations.Paragraphs()
    heading = citations.segment_of(_block("Short answer:", None), passages=PASSAGES)

    assert paragraphs.add(heading) == []
    assert paragraphs.close() == []
    assert paragraphs.open == [heading]
    assert [segment.label for segment in paragraphs.finish()] == [citations.AnswerLabel.BACKGROUND]
    assert paragraphs.open == []


def test_a_library_result_is_titled_with_who_its_from_its_dates_and_where_it_sits() -> None:
    """A newsletter shows its sender and the day it came; a timed passage keeps its timestamp after the date.

    The day is the owner's: an issue that came at 10pm in New York is Wednesday there and already Thursday in UTC.
    """
    newsletter = dataclasses.replace(
        HIT,
        title="☕ Panicky vibes",
        url="https://example.invalid/tracked",
        sender="Morning Brew",
        saved_at=datetime.datetime(2026, 11, 5, 3, tzinfo=datetime.UTC),
        owner_kind=models.ChunkOwner.SOURCE_SUMMARY,
        start_seconds=None,
    )

    assert citations.search_result_block(newsletter, day_zone=NEW_YORK)["title"] == (
        "☕ Panicky vibes · Morning Brew · Wed 4 Nov 2026 (Archie's summary)"
    )
    assert citations.search_result_block(newsletter, day_zone=datetime.UTC)["title"] == (
        "☕ Panicky vibes · Morning Brew · Thu 5 Nov 2026 (Archie's summary)"
    )
    assert citations.search_result_block(HIT, day_zone=NEW_YORK)["title"] == (
        "Odd Lots · open.spotify.com · Mon 2 Nov 2026 (at 31:20)"
    )


def test_an_article_published_on_another_day_shows_both_dates_and_a_year_only_date_as_its_year() -> None:
    """Published on the day it was saved shows one date; a 1 January date (a page giving only a year) shows the year."""
    article = dataclasses.replace(
        HIT,
        title="How to Do Great Work",
        url="https://www.paulgraham.com/greatwork.html",
        saved_at=datetime.datetime(2026, 11, 5, 15, tzinfo=datetime.UTC),
        owner_kind=models.ChunkOwner.SOURCE_TEXT,
        start_seconds=None,
    )
    titles = [
        citations.search_result_block(dataclasses.replace(article, published_at=published), day_zone=NEW_YORK)["title"]
        for published in (
            datetime.datetime(2023, 1, 1, 12, tzinfo=datetime.UTC),
            datetime.datetime(2026, 10, 30, 12, tzinfo=datetime.UTC),
            datetime.datetime(2026, 11, 5, 12, tzinfo=datetime.UTC),
        )
    ]

    assert titles == [
        "How to Do Great Work · paulgraham.com · published 2023 · saved Thu 5 Nov 2026",
        "How to Do Great Work · paulgraham.com · published 30 Oct 2026 · saved Thu 5 Nov 2026",
        "How to Do Great Work · paulgraham.com · Thu 5 Nov 2026",
    ]


def test_the_system_prompt_keeps_its_replay_prefix_and_states_the_owners_today() -> None:
    """Cassettes replay by the first 60 characters, so the date must come after them; the day is the owner's."""
    # 02:00 UTC on Sunday is still Saturday evening in New York.
    sunday_utc = datetime.datetime(2026, 11, 8, 2, tzinfo=datetime.UTC)
    in_new_york = prompts.system_prompt(about=None, web_required=False, now=sunday_utc.astimezone(NEW_YORK))
    in_utc = prompts.system_prompt(about=None, web_required=False, now=sunday_utc)

    assert in_new_york[:60] == in_utc[:60] == prompts.ASK_SYSTEM[:60]
    assert "Today is Saturday 7 November 2026 (America/New_York)." in in_new_york
    assert "Today is Sunday 8 November 2026 (UTC)." in in_utc


def test_the_owners_zone_is_the_phones_or_utc_when_it_is_missing_or_unknown() -> None:
    """A name zoneinfo doesn't know, or a malformed one, falls back to UTC rather than failing the question."""
    assert context.owner_zone("America/New_York") == NEW_YORK
    assert [context.owner_zone(name) for name in (None, "", "Mars/Olympus_Mons", "../../etc/passwd")] == [
        datetime.UTC
    ] * 4


def test_search_library_takes_optional_saved_and_published_day_bounds_in_the_owners_zone() -> None:
    """Only the query is required; a bound that isn't a YYYY-MM-DD date goes back to the model as an error."""
    schema = prompts.SEARCH_LIBRARY_TOOL["input_schema"]
    assert schema["required"] == ["query"]
    assert set(schema["properties"]) == {"query", "saved_after", "saved_before", "published_after", "published_before"}

    bounds = {"query": "x", "saved_after": "2026-11-02", "published_before": "2026-11-06"}
    assert answer._dates_of(bounds, day_zone=NEW_YORK) == search.DateFilter(
        saved_after=datetime.date(2026, 11, 2), published_before=datetime.date(2026, 11, 6), day_zone=NEW_YORK
    )
    assert answer._dates_of({"query": "x"}, day_zone=NEW_YORK) == search.DateFilter(day_zone=NEW_YORK)
    assert answer._dates_of({"query": "x", "saved_before": "last Tuesday"}, day_zone=NEW_YORK) is None
    assert answer._dates_of({"query": "x", "published_after": 20261102}, day_zone=NEW_YORK) is None
