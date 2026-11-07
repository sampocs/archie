"""Cutting passages: ~300-word windows with a 50-word overlap at sentence ends, transcript start times, sections."""

from __future__ import annotations

from archie_db import models
from archie_worker import chunking, content

# Eight words each; ten per paragraph.
SENTENCES = [f"Sentence number {index} is about stablecoins and payments." for index in range(90)]
TEXT = "\n\n".join(" ".join(SENTENCES[start : start + 10]) for start in range(0, 90, 10))


def test_text_is_cut_into_windows_of_at_most_300_words_that_overlap_by_whole_sentences() -> None:
    """37 sentences, then 37 starting 6 back (48 overlapping words), then the last 28: every sentence is covered."""
    passages = chunking.text_passages(TEXT, owner_kind=models.ChunkOwner.SOURCE_TEXT)

    assert len(passages) == 3
    assert all(len(passage.text.split()) <= chunking.TARGET_WORDS for passage in passages)
    assert passages[0].text.endswith(SENTENCES[36]) and passages[1].text.startswith(SENTENCES[31])
    assert passages[2].text.startswith(SENTENCES[62]) and passages[2].text.endswith(SENTENCES[89])
    assert all(passage.start_seconds is None for passage in passages)


def test_a_transcript_passage_keeps_its_first_segments_start() -> None:
    """100 ten-word segments five seconds apart: 30 per window, 5 overlapping."""
    segments = [content.Segment(start=index * 5.0, text=" ".join(["word"] * 10)) for index in range(100)]

    passages = chunking.segment_passages(segments)

    assert [passage.start_seconds for passage in passages] == [0.0, 125.0, 250.0, 375.0]
    assert {passage.owner_kind for passage in passages} == {models.ChunkOwner.SOURCE_TEXT}


def test_markdown_is_cut_section_by_section() -> None:
    """Each heading starts a passage, even when the sections are short."""
    markdown = "Intro line.\n\n## Reserves\n\nBanks hold reserves.\n\n## Rates\n\nThe Fed sets a rate."

    passages = chunking.markdown_passages(markdown, owner_kind=models.ChunkOwner.TOPIC_PRIMER)

    assert [passage.text for passage in passages] == [
        "Intro line.",
        "## Reserves Banks hold reserves.",
        "## Rates The Fed sets a rate.",
    ]


def test_the_summary_becomes_gist_key_ideas_and_numbers_sections() -> None:
    """The analyze JSON reads as the source page shows it."""
    summary = {
        "gist": "The Fed creates reserves.",
        "key_ideas": [{"timestamp": "31:20", "idea": "It buys bonds."}],
        "numbers": [{"timestamp": None, "fact": "$6.6T balance sheet."}],
    }

    markdown = chunking.summary_markdown(summary)

    assert markdown == (
        "## Gist\n\nThe Fed creates reserves.\n\n"
        "## Key ideas\n\n- It buys bonds.\n\n"
        "## Numbers\n\n- $6.6T balance sheet."
    )


def test_a_sentence_or_segment_longer_than_a_passage_is_cut_at_word_counts() -> None:
    """700 words with no sentence end, as text and as a segment: no passage is over 300 words."""
    long_text = " ".join(["word"] * 700)

    text_result = chunking.text_passages(long_text, owner_kind=models.ChunkOwner.SOURCE_TEXT)
    segment_result = chunking.segment_passages(
        [content.Segment(start=12.0, text=long_text), content.Segment(start=99.0, text="A short one.")]
    )

    assert all(len(passage.text.split()) <= chunking.TARGET_WORDS for passage in [*text_result, *segment_result])
    assert segment_result[0].start_seconds == 12.0
    assert [passage.start_seconds for passage in segment_result[:3]] == [12.0, 12.0, 12.0]
