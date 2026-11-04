"""Minute markers and the model's view of timed text."""

from __future__ import annotations

import pytest
from archie_worker import content, prompts, timestamps


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (59.9, "00:59"), (734.2, "12:14"), (3599, "59:59"), (3600, "1:00:00"), (3723, "1:02:03")],
)
def test_format_timestamp(seconds: float, expected: str) -> None:
    """Under an hour is mm:ss; from an hour it is h:mm:ss."""
    assert timestamps.format_timestamp(seconds) == expected


def test_marked_text_marks_the_first_segment_past_each_minute() -> None:
    """Segments at 0, 20, 61, 62, 130 and 3700 s are marked only at 0, 61, 130 and 3700."""
    segments = [content.Segment(start=start, text=f"s{start}") for start in (0, 20, 61, 62, 130, 3700)]

    assert timestamps.marked_text(segments) == ("[00:00] s0 s20\n[01:01] s61 s62\n[02:10] s130\n[1:01:40] s3700")


def test_marked_text_inside_one_minute_has_one_marker() -> None:
    """Four segments in the first minute get just the opening marker."""
    segments = [content.Segment(start=start, text=f"s{start}") for start in (0, 10, 30, 59)]

    assert timestamps.marked_text(segments) == "[00:00] s0 s10 s30 s59"


def test_timed_text_content_round_trips_and_strips_nul() -> None:
    """Segments are rounded, NULs removed everywhere, and `segments_of` reads them back."""
    result = content.timed_text_content(
        segments=[content.Segment(start=1.234, text="a\x00b"), content.Segment(start=70, text="c")],
        extra={"note": "x\x00y"},
    )

    assert result == {
        "text": "ab c",
        "segments": [{"start": 1.23, "text": "ab"}, {"start": 70, "text": "c"}],
        "note": "xy",
    }
    assert content.segments_of(result) == [content.Segment(start=1.23, text="ab"), content.Segment(start=70, text="c")]
    assert content.segments_of({"text": "plain"}) == []


def test_model_text_caps_timed_text_at_600000_and_untimed_at_200000() -> None:
    """Timed text is marked and capped higher than plain text."""
    timed = {"text": "x", "segments": [{"start": 0, "text": "§" * 700_000}]}
    assert len(prompts.model_text(timed)) == 600_000
    assert prompts.model_text(timed).startswith("[00:00] §")

    assert len(prompts.model_text({"text": "§" * 300_000})) == 200_000


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[02:03]", "02:03"),
        ("02:03", "02:03"),
        ("[1:02:03]", "1:02:03"),
        ("around 2 min", None),
        ("[02:03", None),
        ("", None),
        (None, None),
    ],
)
def test_clean_model_timestamp(raw: str | None, expected: str | None) -> None:
    """Brackets are stripped; a valid time passes; anything else becomes None."""
    assert timestamps.clean_model_timestamp(raw) == expected
