"""Cutting an item's words into search passages of about 300 words with a 50-word overlap.

Passages break at sentence ends (paragraph ends are sentence ends too); a sentence or transcript segment longer than a
passage is cut at word counts. A transcript is cut from its timed segments and each passage keeps its first segment's
start. Summaries and primers are cut section by section, so a heading always starts a passage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from archie_db import models

from archie_worker import content

TARGET_WORDS = 300
OVERLAP_WORDS = 50

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)


@dataclass(frozen=True)
class Passage:
    """One search passage before it is stored: what it was cut from, its text, and a transcript passage's start."""

    owner_kind: models.ChunkOwner
    text: str
    start_seconds: float | None


@dataclass(frozen=True)
class _Unit:
    """The smallest piece a passage is built from: a sentence, or one timed segment."""

    text: str
    start: float | None
    words: int


def text_passages(text: str, *, owner_kind: models.ChunkOwner) -> list[Passage]:
    """Plain text cut at sentence ends."""
    return [
        Passage(owner_kind=owner_kind, text=window_text, start_seconds=None)
        for window_text, _ in _pack(_sentence_units(text))
    ]


def segment_passages(segments: Sequence[content.Segment]) -> list[Passage]:
    """A transcript cut at segment ends; each passage starts when its first segment does."""
    units = [unit for segment in segments for unit in _word_units(segment.text.split(), start=segment.start)]
    return [
        Passage(owner_kind=models.ChunkOwner.SOURCE_TEXT, text=window_text, start_seconds=start)
        for window_text, start in _pack(units)
    ]


def markdown_passages(markdown: str, *, owner_kind: models.ChunkOwner) -> list[Passage]:
    """Markdown cut at its headings first, then each section at sentence ends."""
    return [passage for section in _sections(markdown) for passage in text_passages(section, owner_kind=owner_kind)]


def summary_markdown(summary: Mapping[str, Any]) -> str:
    """The analyze summary (gist, key ideas, numbers) as markdown sections, the way the source page shows it."""
    ideas = "\n".join(f"- {item['idea']}" for item in summary.get("key_ideas", []))
    numbers = "\n".join(f"- {item['fact']}" for item in summary.get("numbers", []))
    sections = [
        f"## Gist\n\n{summary.get('gist', '')}",
        f"## Key ideas\n\n{ideas}" if ideas else "",
        f"## Numbers\n\n{numbers}" if numbers else "",
    ]
    return "\n\n".join(section for section in sections if section)


def _sections(markdown: str) -> list[str]:
    starts = [match.start() for match in _HEADING.finditer(markdown) if match.start() > 0]
    bounds = [0, *starts, len(markdown)]
    sections = (markdown[start:end].strip() for start, end in zip(bounds, bounds[1:], strict=False))
    return [section for section in sections if section]


def _sentence_units(text: str) -> list[_Unit]:
    units = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        flat = " ".join(paragraph.split())
        for sentence in _SENTENCE_END.split(flat) if flat else []:
            units.extend(_word_units(sentence.split(), start=None))
    return units


def _word_units(words: Sequence[str], *, start: float | None) -> list[_Unit]:
    """One unit per TARGET_WORDS words, for a sentence or segment longer than a passage; each keeps the start."""
    return [
        _Unit(text=" ".join(piece), start=start, words=len(piece))
        for piece in (words[offset : offset + TARGET_WORDS] for offset in range(0, len(words), TARGET_WORDS))
    ]


def _pack(units: Sequence[_Unit]) -> list[tuple[str, float | None]]:
    """Whole units, greedily, up to TARGET_WORDS per window.

    Each new window opens with the previous window's last units (at most OVERLAP_WORDS of them), so the sentence that
    spans a boundary is whole in one of the two passages.
    """
    windows: list[list[_Unit]] = []
    current: list[_Unit] = []
    for unit in units:
        if current and _words(current) + unit.words > TARGET_WORDS:
            windows.append(current)
            current = _overlap(current)
            # Carried-over words that would themselves overflow the window are dropped.
            if _words(current) + unit.words > TARGET_WORDS:
                current = []
        current.append(unit)
    if current:
        windows.append(current)
    return [(" ".join(unit.text for unit in window), window[0].start) for window in windows]


def _overlap(window: Sequence[_Unit]) -> list[_Unit]:
    kept: list[_Unit] = []
    for unit in reversed(window):
        if _words(kept) + unit.words > OVERLAP_WORDS:
            break
        kept.insert(0, unit)
    return kept


def _words(units: Sequence[_Unit]) -> int:
    return sum(unit.words for unit in units)
