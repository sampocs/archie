"""The transcription fallback decision and where name corrections land: logic with edge cases, no network."""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from archie_worker import content, corrections, errors, transcription

SHORT_CHUNK = pathlib.Path(__file__).parent / "fixtures" / "audio" / "short_chunk.mp3"


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


def test_audio_over_the_duration_cap_is_refused_before_splitting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 60-second fixture against a 10-second cap is too long, and says so permanently."""
    monkeypatch.setattr(transcription, "MAX_AUDIO_SECONDS", 10)

    with pytest.raises(errors.PermanentJobError) as raised:
        transcription.episode_seconds(SHORT_CHUNK)

    assert raised.value.reason == errors.FailureReason.EPISODE_TOO_LONG


def test_audio_under_the_duration_cap_reports_its_length() -> None:
    """The real 60-second fixture is accepted and measured."""
    assert transcription.episode_seconds(SHORT_CHUNK) == pytest.approx(60, abs=2)


def test_undecodable_audio_is_permanently_unreadable(tmp_path: pathlib.Path) -> None:
    """Garbage bytes fail ffprobe, which would fail every retry, so the job fails at once."""
    garbage = tmp_path / "episode.audio"
    garbage.write_bytes(b"this is not audio" * 100)

    with pytest.raises(errors.PermanentJobError) as probe_raised:
        transcription.episode_seconds(garbage)
    with pytest.raises(errors.PermanentJobError) as split_raised:
        transcription.split(audio=garbage, audio_seconds=60, directory=tmp_path, chunk_seconds=600)

    assert probe_raised.value.reason == errors.FailureReason.AUDIO_UNREADABLE
    assert split_raised.value.reason == errors.FailureReason.AUDIO_UNREADABLE


def test_ffprobe_output_that_is_not_a_number_is_unreadable(tmp_path: pathlib.Path) -> None:
    """A file ffprobe accepts but gives no duration for (empty output) is unreadable rather than a ValueError retry."""
    empty = tmp_path / "empty.audio"
    empty.write_bytes(b"")

    with pytest.raises(errors.PermanentJobError):
        transcription.episode_seconds(empty)


def test_a_split_that_exceeds_its_time_limit_stays_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A stuck ffmpeg raises TimeoutExpired, which is not permanent: the loop retries it."""
    monkeypatch.setattr(transcription, "_FFMPEG_MIN_TIMEOUT_SECONDS", 0.001)

    with pytest.raises(subprocess.TimeoutExpired):
        transcription.split(audio=SHORT_CHUNK, audio_seconds=0, directory=tmp_path, chunk_seconds=600)


@pytest.mark.parametrize(
    ("header", "expected"),
    [("17", 17.0), ("2.5", 2.5), (None, 60.0), ("", 60.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 60.0)],
)
def test_retry_after_uses_the_header_only_when_it_is_a_number_of_seconds(header: str | None, expected: float) -> None:
    """An HTTP-date `retry-after` falls back to the default instead of crashing the handler with a ValueError."""
    assert transcription.retry_after_seconds(header) == expected
