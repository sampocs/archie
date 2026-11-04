"""The transcription fallback decision and where name corrections land: logic with edge cases, no network."""

from __future__ import annotations

import pytest
from archie_worker import content, corrections, transcription


def _words(count: int) -> str:
    return " ".join(["word"] * count)


def test_a_chunk_at_normal_speaking_pace_keeps_groq() -> None:
    """1,500 words in ten minutes is 150 words per minute, above the 100 that triggers the fallback."""
    segments = [content.Segment(start=0.0, text=_words(750)), content.Segment(start=300.0, text=_words(750))]

    assert transcription.needs_fallback(segments=segments, duration_seconds=600) is False


def test_a_sparse_chunk_needs_the_fallback() -> None:
    """900 words in ten minutes (90 per minute) means Whisper skipped speech."""
    segments = [content.Segment(start=0.0, text=_words(900))]

    assert transcription.needs_fallback(segments=segments, duration_seconds=600) is True


def test_a_short_trailing_chunk_is_exempt() -> None:
    """A 20-second outro with 3 words is under the 30 seconds the check applies to."""
    segments = [content.Segment(start=0.0, text="thanks for listening")]

    assert transcription.needs_fallback(segments=segments, duration_seconds=20) is False


def _texts(segments: list[content.Segment]) -> list[str]:
    return [segment.text for segment in segments]


def test_a_correction_changes_only_the_match_inside_its_context() -> None:
    """Three "Gary"s, one correction whose context holds the second: only that one becomes "Gabby"."""
    segments = [
        content.Segment(start=0.0, text="Gary opened the show."),
        content.Segment(start=5.0, text="and then Gary said the Fed would cut."),
        content.Segment(start=9.0, text="Gary disagreed."),
    ]
    correction = corrections.Correction(heard="Gary", correct="Gabby", context="and then Gary said the Fed")

    corrected = corrections.apply(segments, [correction])

    assert _texts(corrected) == ["Gary opened the show.", "and then Gabby said the Fed would cut.", "Gary disagreed."]
    assert [segment.start for segment in corrected] == [0.0, 5.0, 9.0]


def test_a_context_not_in_the_text_changes_nothing() -> None:
    """The model's snippet must be found in the transcript, or its correction is not applied at all."""
    segments = [content.Segment(start=0.0, text="Gary said the Fed would cut.")]
    correction = corrections.Correction(heard="Gary", correct="Gabby", context="then Gary said the ECB")

    assert _texts(corrections.apply(segments, [correction])) == ["Gary said the Fed would cut."]


def test_only_whole_words_are_replaced() -> None:
    """ "Ty" inside "Tyler" is left alone; the standalone "Ty" in the same context is fixed."""
    segments = [content.Segment(start=0.0, text="Tyler asked Ty about it.")]
    correction = corrections.Correction(heard="Ty", correct="Tai", context="Tyler asked Ty about")

    assert _texts(corrections.apply(segments, [correction])) == ["Tyler asked Tai about it."]


def test_a_context_ending_mid_word_does_not_match_the_word_start() -> None:
    """A context cut off at "Ty" in "Tyler" must not let "Ty" count as a whole word there."""
    segments = [content.Segment(start=0.0, text="and then Tyler spoke.")]
    correction = corrections.Correction(heard="Ty", correct="Tai", context="and then Ty")

    assert _texts(corrections.apply(segments, [correction])) == ["and then Tyler spoke."]


def test_matching_ignores_case_and_keeps_the_rest_of_the_text() -> None:
    """A lower-cased context and heard still find the capitalized words; the surrounding text is untouched."""
    segments = [content.Segment(start=0.0, text="We talked to Vitalic Butterin today, about Ethereum.")]
    correction = corrections.Correction(
        heard="vitalic butterin", correct="Vitalik Buterin", context="to vitalic butterin today"
    )

    assert _texts(corrections.apply(segments, [correction])) == ["We talked to Vitalik Buterin today, about Ethereum."]


def test_a_match_spanning_two_segments_is_skipped() -> None:
    """A misheard name split across segments can't be placed in one segment's text, so it's left as is."""
    segments = [
        content.Segment(start=0.0, text="we spoke with Vitalic"),
        content.Segment(start=3.0, text="Butterin today"),
    ]
    correction = corrections.Correction(
        heard="Vitalic Butterin", correct="Vitalik Buterin", context="with Vitalic Butterin today"
    )

    assert _texts(corrections.apply(segments, [correction])) == ["we spoke with Vitalic", "Butterin today"]


def test_two_corrections_in_one_context_both_apply() -> None:
    """Two different mishearings in the same snippet are both fixed, each at its own offset."""
    segments = [content.Segment(start=0.0, text="Then Sailor said Micro Strategy bought more.")]
    context = "Sailor said Micro Strategy bought"
    fixes = [
        corrections.Correction(heard="Sailor", correct="Saylor", context=context),
        corrections.Correction(heard="Micro Strategy", correct="MicroStrategy", context=context),
    ]

    assert _texts(corrections.apply(segments, fixes)) == ["Then Saylor said MicroStrategy bought more."]


@pytest.mark.parametrize("context", ["Gary", "gary."])
def test_a_context_with_no_word_beyond_heard_changes_nothing(context: str) -> None:
    """Such a context would match every "Gary", which is a global replace; the correction is skipped instead."""
    segments = [
        content.Segment(start=0.0, text="Gary opened the show."),
        content.Segment(start=5.0, text="and then Gary said the Fed would cut."),
        content.Segment(start=9.0, text="Gary disagreed."),
    ]
    correction = corrections.Correction(heard="Gary", correct="Gabby", context=context)

    assert _texts(corrections.apply(segments, [correction])) == _texts(segments)
