"""Minute markers for timed text, so the model can cite where in an episode an idea comes up."""

from __future__ import annotations

from collections.abc import Sequence

from archie_worker import content

_SECONDS_PER_HOUR = 3600


def format_timestamp(seconds: float) -> str:
    """`mm:ss` under an hour, `h:mm:ss` from an hour on; fractions are dropped."""
    whole = int(seconds)
    hours, remainder = divmod(whole, _SECONDS_PER_HOUR)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def marked_text(segments: Sequence[content.Segment], *, every_seconds: float = 60.0) -> str:
    """The segments joined by spaces, with a `[timestamp]` line start roughly every `every_seconds`.

    The first segment always gets a marker; after that, the first segment at or past the next boundary does, and the
    boundary moves to the next multiple of `every_seconds` after it.
    """
    lines: list[list[str]] = []
    next_boundary = 0.0
    for segment in segments:
        if lines and segment.start < next_boundary:
            lines[-1].append(segment.text)
            continue

        lines.append([f"[{format_timestamp(segment.start)}]", segment.text])
        next_boundary = (segment.start // every_seconds + 1) * every_seconds

    return "\n".join(" ".join(line) for line in lines)
