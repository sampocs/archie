"""The corrections pass: a model spots misheard names in a transcript, and code fixes them only where it pointed.

Each correction names the misheard words (`heard`), their spelling (`correct`) and a short snippet of the transcript
around them (`context`). A fix is applied only inside an occurrence of its context, never as a global replace, so a
common word that was misheard once doesn't change everywhere.
"""

from __future__ import annotations

import bisect
import dataclasses
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy
from archie_shared import logging

from archie_worker import content, llm
from archie_worker.content import episode as episode_content

MAX_OUTPUT_TOKENS = 16000

SYSTEM = """You fix misheard names and jargon in automatic podcast transcripts.

Speech-to-text gets ordinary words right but mangles rare proper nouns: people, companies, crypto protocols and tokens, malware and hacking groups, products, places, and technical terms. Your job is to find those and give the correct spelling.

Use the episode title and description first, since they usually spell the guests and topics correctly.

Rules:
- Only fix proper nouns and jargon. Never fix grammar, filler words, punctuation, or phrasing.
- "heard" must be copied exactly from the transcript, and should be as short as possible while still unambiguous: just the misheard word or phrase.
- "context" is 4 to 12 words copied exactly from the transcript around the mishearing, and it must contain "heard".
- Only include a correction you're confident in. A wrong "fix" is worse than leaving a mishearing alone.
- If the transcript already spells something correctly, leave it out.
- Return an empty list if nothing needs fixing."""  # noqa: E501

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heard": {"type": "string"},
                    "correct": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["heard", "correct", "context"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["corrections"],
    "additionalProperties": False,
}

_SEGMENT_SEPARATOR = " "

_logger = logging.get_logger(logging.LoggerName.WORKER, "corrections")


@dataclass(frozen=True)
class Correction:
    """A misheard word or phrase, its right spelling, and the transcript snippet it was heard in."""

    heard: str
    correct: str
    context: str


@dataclass(frozen=True)
class _Replacement:
    """`correct` in place of the characters [begin, end) of one segment's text."""

    segment_index: int
    begin: int
    end: int
    correct: str


def request(
    engine: sqlalchemy.Engine,
    *,
    api_key: str,
    context: llm.CallContext,
    episode: episode_content.PodcastEpisode,
    text: str,
) -> list[Correction]:
    """Ask the corrections model for misheard names in `text`; entries that change nothing are dropped.

    Raises `llm.ModelOutputError`, `anthropic.APIError` or `json.JSONDecodeError` when there is no usable answer.
    """
    completion = llm.complete(
        engine,
        api_key=api_key,
        context=dataclasses.replace(context, step=llm.CORRECTIONS_STEP),
        models=llm.CORRECTIONS_MODELS,
        system=SYSTEM,
        user_message=(
            f"Show: {episode.show_name}\nEpisode title: {episode.title}\nEpisode description: {episode.description}"
            f"\n\n<transcript>\n{text}\n</transcript>"
        ),
        json_schema=SCHEMA,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    raw_corrections = json.loads(completion.text)["corrections"]
    corrections = (
        Correction(heard=raw["heard"], correct=raw["correct"], context=raw["context"]) for raw in raw_corrections
    )
    return [correction for correction in corrections if correction.heard and correction.heard != correction.correct]


def apply(segments: Sequence[content.Segment], corrections: Sequence[Correction]) -> list[content.Segment]:
    """`segments` with each correction applied to whole-word matches of `heard` inside occurrences of its `context`.

    Matching ignores case. A match that would span two segments is skipped, as is one overlapping an earlier fix.
    """
    joined = _SEGMENT_SEPARATOR.join(segment.text for segment in segments)
    segment_starts = _segment_starts(segments)

    replacements: list[_Replacement] = []
    taken: list[tuple[int, int]] = []
    for correction in corrections:
        for begin, end in _matches(joined, correction=correction):
            replacement = _replacement_at(
                begin=begin, end=end, correct=correction.correct, segments=segments, segment_starts=segment_starts
            )
            if replacement is None:
                _logger.info("Skipped %r -> %r: it spans two segments", correction.heard, correction.correct)
                continue
            if any(begin < taken_end and taken_begin < end for taken_begin, taken_end in taken):
                continue
            taken.append((begin, end))
            replacements.append(replacement)

    return [
        content.Segment(
            start=segment.start,
            text=_replaced(segment.text, [item for item in replacements if item.segment_index == index]),
        )
        for index, segment in enumerate(segments)
    ]


def _segment_starts(segments: Sequence[content.Segment]) -> list[int]:
    """Where each segment's text begins in the joined string."""
    starts: list[int] = []
    position = 0
    for segment in segments:
        starts.append(position)
        position += len(segment.text) + len(_SEGMENT_SEPARATOR)
    return starts


def _matches(joined: str, *, correction: Correction) -> list[tuple[int, int]]:
    """The [begin, end) spans in `joined` of whole-word `heard` matches inside each occurrence of `context`."""
    heard_pattern = re.compile(rf"(?<!\w){re.escape(correction.heard)}(?!\w)", re.IGNORECASE)
    context_pattern = re.compile(re.escape(correction.context), re.IGNORECASE)
    # One character past the context lets `(?!\w)` see what really follows, so a context ending mid-word doesn't
    # turn the start of that word into a whole-word match; lookbehind already sees before `pos`.
    return [
        (heard.start(), heard.end())
        for occurrence in context_pattern.finditer(joined)
        for heard in heard_pattern.finditer(joined, occurrence.start(), occurrence.end() + 1)
        if heard.end() <= occurrence.end()
    ]


def _replacement_at(
    *, begin: int, end: int, correct: str, segments: Sequence[content.Segment], segment_starts: Sequence[int]
) -> _Replacement | None:
    """The replacement in segment-local offsets; None when [begin, end) runs past its segment's text."""
    index = bisect.bisect_right(segment_starts, begin) - 1
    local_begin = begin - segment_starts[index]
    local_end = end - segment_starts[index]
    if local_end > len(segments[index].text):
        return None
    return _Replacement(segment_index=index, begin=local_begin, end=local_end, correct=correct)


def _replaced(text: str, replacements: Sequence[_Replacement]) -> str:
    # From the end backwards, so earlier offsets stay valid.
    for replacement in sorted(replacements, key=lambda item: item.begin, reverse=True):
        text = text[: replacement.begin] + replacement.correct + text[replacement.end :]
    return text
