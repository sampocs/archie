"""Ask's pure logic: a block's label comes from its citations; history keeps only finished question-answer pairs."""

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
