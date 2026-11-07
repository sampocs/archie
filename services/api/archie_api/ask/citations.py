"""Turning the model's text blocks into labelled segments: the label is read off the block's citations.

A block citing a library passage (a `search_result` this answer's searches returned) is `library`; else one citing a
web result is `web`; else `background`. Library passages go to the model as `search_result` blocks whose `source` is
`source_key(hit)`, so a citation's `source` leads back to the passage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import anthropic.types
from archie_db import models, search

QUOTE_CHARACTERS = 300
_SOURCE_PREFIX = "archie:chunk:"


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


def source_key(hit: search.ChunkHit) -> str:
    """The `source` a passage's `search_result` block carries, which its citations echo back."""
    return f"{_SOURCE_PREFIX}{hit.chunk_id}"


def search_result_block(hit: search.ChunkHit) -> dict[str, Any]:
    """A library passage as the model sees it: citable, titled with its item and where in the item it sits."""
    return {
        "type": "search_result",
        "source": source_key(hit),
        "title": _result_title(hit),
        "content": [{"type": "text", "text": hit.text}],
        "citations": {"enabled": True},
    }


def segment_of(block: anthropic.types.TextBlock, *, passages: Mapping[str, search.ChunkHit]) -> Segment:
    """The block's segment: its label from its citations, and each cited item or link once."""
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


def _result_title(hit: search.ChunkHit) -> str:
    if hit.owner_kind == models.ChunkOwner.SOURCE_TEXT and hit.start_seconds is not None:
        minutes, seconds = divmod(int(hit.start_seconds), 60)
        return f"{hit.title} (at {minutes}:{seconds:02d})"
    name = _OWNER_NAMES.get(hit.owner_kind)
    return f"{hit.title} ({name})" if name else hit.title
