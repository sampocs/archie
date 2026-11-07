"""Ask's pure logic: a paragraph's label comes from its blocks' citations; history keeps only finished pairs."""

from __future__ import annotations

import uuid

import anthropic.types
from archie_api.ask import citations, context
from archie_db import models, search

HIT = search.ChunkHit(
    chunk_id=7,
    item=search.ItemRef(kind=models.SearchItemKind.SOURCE, id=uuid.UUID(int=1)),
    title="Odd Lots",
    owner_kind=models.ChunkOwner.SOURCE_TEXT,
    text="The Fed pays with reserves.",
    start_seconds=1880.0,
    score=1.0,
    keyword_match=True,
)
PASSAGES = {citations.source_key(HIT): HIT}


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
