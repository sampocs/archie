"""Turning the model's text blocks into labelled segments: each paragraph is labelled by its blocks' citations.

Citations split the model's text into many blocks, often mid-sentence, so labels are given per paragraph: a run of
consecutive text blocks that ends at a non-text block, at the end of a model round, or after a block whose text holds a
blank line ("\n\n"); a block starting with a blank line begins a new paragraph. A paragraph with a block citing a
library passage (a `search_result` this answer's searches returned) is `library`; else one with a block citing a web
result is `web`; else `background`. A heading paragraph instead takes the label of the paragraph after it in the same
round. Every block of the paragraph gets that label and keeps its own citations. Library passages go to the model as
`search_result` blocks whose `source` is `source_key(hit)`, so a citation's `source` leads back to the passage.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import anthropic.types
from archie_db import models, search

QUOTE_CHARACTERS = 300
PARAGRAPH_BREAK = "\n\n"
HEADING_CHARACTERS = 60
_SOURCE_PREFIX = "archie:chunk:"
_HEADING_LINE = re.compile(r"#{1,6}\s|\*\*.+\*\*$")


class AnswerLabel(StrEnum):
    """Where a segment of an answer came from."""

    LIBRARY = "library"
    WEB = "web"
    BACKGROUND = "background"


@dataclass(frozen=True)
class Segment:
    """One text block of an answer with its label and de-duplicated citations, in the stored wire shape."""

    label: AnswerLabel
    text: str
    citations: list[dict[str, Any]]

    def to_wire(self) -> dict[str, Any]:
        """The shape stored in `messages.segments` and sent in the `block` event."""
        return {"label": self.label.value, "text": self.text, "citations": self.citations}


@dataclass
class Paragraphs:
    """Text blocks gathered into the open paragraph; each closed paragraph comes back with its label on every block.

    A heading paragraph ("**What to pick:**") carries no citations, so it is held until the paragraph after it closes
    and takes that paragraph's label; otherwise it would split one library answer with a background section. Its
    blocks come back only once their label is final, so streaming never sends a label that later changes.
    """

    held: list[Segment] = field(default_factory=list)
    current: list[Segment] = field(default_factory=list)

    @property
    def open(self) -> list[Segment]:
        """Every block not returned yet: held headings, then the paragraph still being written."""
        return [*self.held, *self.current]

    def add(self, segment: Segment) -> list[Segment]:
        """Take the next text block of the run; returns the blocks of any paragraphs it closed, relabelled."""
        closed = self.close() if segment.text.startswith(PARAGRAPH_BREAK) else []
        self.current.append(segment)
        return [*closed, *self.close()] if PARAGRAPH_BREAK in segment.text else closed

    def close(self) -> list[Segment]:
        """End the open paragraph (a non-text block or a blank line) and return the blocks whose label is final."""
        paragraph, self.current = self.current, []
        if not paragraph:
            return []
        if _is_heading(paragraph):
            self.held.extend(paragraph)
            return []

        label = _paragraph_label(paragraph)
        released, self.held = [*self.held, *paragraph], []
        return [dataclasses.replace(segment, label=label) for segment in released]

    def finish(self) -> list[Segment]:
        """End the round (or the answer): close the open paragraph, and headings nothing followed keep their label."""
        closed = self.close()
        held, self.held = self.held, []
        return [*closed, *(dataclasses.replace(segment, label=_paragraph_label([segment])) for segment in held)]


def _paragraph_label(paragraph: list[Segment]) -> AnswerLabel:
    labels = {segment.label for segment in paragraph}
    if AnswerLabel.LIBRARY in labels:
        return AnswerLabel.LIBRARY
    return AnswerLabel.WEB if AnswerLabel.WEB in labels else AnswerLabel.BACKGROUND


def _is_heading(paragraph: list[Segment]) -> bool:
    """A one-line paragraph that only titles what follows: `# …`, a fully bold line, or a short line ending in ':'."""
    text = "".join(segment.text for segment in paragraph).strip()
    if not text or "\n" in text:
        return False
    return bool(_HEADING_LINE.match(text)) or (len(text) <= HEADING_CHARACTERS and text.endswith(":"))


def by_paragraph(segments: list[Segment]) -> list[Segment]:
    """One run of consecutive text blocks' segments, each relabelled with its paragraph's label."""
    paragraphs = Paragraphs()
    relabelled = [closed for segment in segments for closed in paragraphs.add(segment)]
    return [*relabelled, *paragraphs.finish()]


def uncited_paragraphs_dropped(segments: list[Segment]) -> list[bool]:
    """Per paragraph-relabelled segment: whether it belongs to a paragraph with no citation at all.

    Citations cut a paragraph into blocks, many uncited, so the rule is per paragraph: a background label (set by
    `by_paragraph`) means no block of the paragraph cited anything.
    """
    return [segment.label == AnswerLabel.BACKGROUND for segment in segments]


def source_key(hit: search.ChunkHit) -> str:
    """The `source` a passage's `search_result` block carries, which its citations echo back."""
    return f"{_SOURCE_PREFIX}{hit.chunk_id}"


def search_result_block(hit: search.ChunkHit, *, day_zone: datetime.tzinfo) -> dict[str, Any]:
    """A library passage as the model sees it: citable, titled with its item, its day in `day_zone`, and where in the
    item it sits."""
    return {
        "type": "search_result",
        "source": source_key(hit),
        "title": _result_title(hit, day_zone=day_zone),
        "content": [{"type": "text", "text": hit.text}],
        "citations": {"enabled": True},
    }


def segment_of(block: anthropic.types.TextBlock, *, passages: Mapping[str, search.ChunkHit]) -> Segment:
    """The block's segment: its own label from its citations (before `Paragraphs` relabels it), each citation once."""
    library: list[dict[str, Any]] = []
    web: list[dict[str, Any]] = []
    for citation in block.citations or []:
        if citation.type == "search_result_location":
            hit = passages.get(citation.source)
            if hit is not None:
                library.append(_library_citation(hit, quote=citation.cited_text))
        elif citation.type == "web_search_result_location":
            web.append(
                {
                    "kind": "web",
                    "title": citation.title or citation.url,
                    "url": citation.url,
                    "quote": citation.cited_text[:QUOTE_CHARACTERS],
                }
            )

    label = AnswerLabel.LIBRARY if library else AnswerLabel.WEB if web else AnswerLabel.BACKGROUND
    return Segment(label=label, text=block.text, citations=_unique([*library, *web]))


def _library_citation(hit: search.ChunkHit, *, quote: str) -> dict[str, Any]:
    item_id = str(hit.item.id)
    return {
        "kind": "library",
        "title": hit.title,
        "source_id": item_id if hit.item.kind == models.SearchItemKind.SOURCE else None,
        "topic_primer_id": item_id if hit.item.kind == models.SearchItemKind.TOPIC_PRIMER else None,
        "take_id": item_id if hit.item.kind == models.SearchItemKind.TAKE else None,
        "owner_kind": hit.owner_kind.value,
        "start_seconds": hit.start_seconds,
        "quote": quote[:QUOTE_CHARACTERS],
    }


def _unique(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[object, ...]] = set()
    kept = []
    for citation in found:
        key = (
            (citation["source_id"], citation["topic_primer_id"], citation["take_id"], citation["start_seconds"])
            if citation["kind"] == "library"
            else (citation["url"],)
        )
        if key not in seen:
            seen.add(key)
            kept.append(citation)
    return kept


_OWNER_NAMES = {
    models.ChunkOwner.SOURCE_SUMMARY: "Archie's summary",
    models.ChunkOwner.SOURCE_PRIMER: "Archie's primer",
    models.ChunkOwner.TOPIC_PRIMER: "topic primer",
    models.ChunkOwner.TAKE: "the owner's own take",
}


def _result_title(hit: search.ChunkHit, *, day_zone: datetime.tzinfo) -> str:
    """The item's title, who it's from and its dates, then where in the item the passage sits.

    e.g. "☕ Panicky vibes · Morning Brew · Wed 5 Nov 2026" (a newsletter is sent and saved the same day), or
    "How to Do Great Work · paulgraham.com · published 2023 · saved Wed 5 Nov 2026".
    """
    named = " · ".join(part for part in (hit.title, _byline(hit), _dates(hit, day_zone=day_zone)) if part)
    if hit.owner_kind == models.ChunkOwner.SOURCE_TEXT and hit.start_seconds is not None:
        minutes, seconds = divmod(int(hit.start_seconds), 60)
        return f"{named} (at {minutes}:{seconds:02d})"
    name = _OWNER_NAMES.get(hit.owner_kind)
    return f"{named} ({name})" if name else named


def _byline(hit: search.ChunkHit) -> str | None:
    """A newsletter's sender, else a web source's site; None for topic primers, takes and other sources."""
    if hit.sender:
        return hit.sender
    site = urllib.parse.urlsplit(hit.url).hostname if hit.url else None
    return site.removeprefix("www.") if site else None


def _dates(hit: search.ChunkHit, *, day_zone: datetime.tzinfo) -> str:
    """The saved day, with the published date in front when that fell on another day."""
    saved = hit.saved_at.astimezone(day_zone)
    saved_text = f"{saved:%a} {saved.day} {saved:%b %Y}"
    published = hit.published_at.astimezone(day_zone) if hit.published_at is not None else None
    if published is None or published.date() == saved.date():
        return saved_text

    # A page that gives only a year comes back as 1 January, so that day is shown as the year alone.
    is_year_only = (published.month, published.day) == (1, 1)
    published_text = f"{published:%Y}" if is_year_only else f"{published.day} {published:%b %Y}"
    return f"published {published_text} · saved {saved_text}"
