"""The brief's stored content and the server's pass over the model's stories before it is written.

The model groups, ranks and writes; the server decides what is kept. Source ids that aren't a covered news
newsletter are dropped, and a story or "also" line left without any is dropped. Domains are ordered by their most
important story and stories by importance, and only the top `MAX_STORIES` are shown in full: the rest become "also"
lines (their headline). The result is validated with pydantic before it is stored.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pydantic
from archie_shared import domains
from archie_shared.domains import Domain

MAX_STORIES = 10
MIN_IMPORTANCE = 1
MAX_IMPORTANCE = 10


class Story(pydantic.BaseModel):
    """One story shown in full: the headline, what happened, why it matters, and the longer story-page paragraph."""

    headline: str
    body: str
    why: str
    detail: str
    importance: int = pydantic.Field(ge=MIN_IMPORTANCE, le=MAX_IMPORTANCE)
    source_ids: list[uuid.UUID] = pydantic.Field(min_length=1)


class DomainStories(pydantic.BaseModel):
    """One domain's stories, most important first."""

    domain: Domain
    stories: list[Story] = pydantic.Field(min_length=1)


class AlsoItem(pydantic.BaseModel):
    """A one-line "also happening" item."""

    text: str
    source_ids: list[uuid.UUID] = pydantic.Field(min_length=1)


class Essay(pydantic.BaseModel):
    """An essay newsletter listed under "Worth reading", pitched by its summary's gist."""

    source_id: uuid.UUID
    pitch: str


class BriefContent(pydantic.BaseModel):
    """A brief's `content` column, already ordered for display."""

    domains: list[DomainStories]
    also: list[AlsoItem]
    essays: list[Essay]

    def to_json(self) -> dict[str, Any]:
        """The JSON stored in `briefs.content` (ids as strings, domains as their display names)."""
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class _FiledStory:
    domain: Domain
    story: Story


def assemble(
    model_output: Mapping[str, Any], *, news_ids: Collection[uuid.UUID], essays: Sequence[Essay]
) -> BriefContent:
    """The brief's content from the model's `{domains, also}` answer about the newsletters in `news_ids`.

    Ties in importance keep the model's order. An unknown domain becomes Other, and importance is clamped to 1-10.
    """
    known_ids = {str(source_id): source_id for source_id in news_ids}
    filed = [
        filed_story
        for raw_domain in model_output["domains"]
        for raw_story in raw_domain["stories"]
        if (filed_story := _filed_story(raw_story, domain=raw_domain["domain"], known_ids=known_ids)) is not None
    ]

    # Sorting is stable, so equal importance keeps the model's order.
    ranked = sorted(filed, key=lambda filed_story: -filed_story.story.importance)
    shown, overflow = ranked[:MAX_STORIES], ranked[MAX_STORIES:]

    # Grouping in rank order puts each domain at its top story's rank, with its stories already most important first.
    grouped: dict[Domain, list[Story]] = {}
    for filed_story in shown:
        grouped.setdefault(filed_story.domain, []).append(filed_story.story)

    overflow_lines = [AlsoItem(text=item.story.headline, source_ids=item.story.source_ids) for item in overflow]
    model_lines = [
        AlsoItem(text=raw["text"], source_ids=source_ids)
        for raw in model_output["also"]
        if (source_ids := _known(raw["source_ids"], known_ids=known_ids))
    ]
    return BriefContent(
        domains=[DomainStories(domain=domain, stories=stories) for domain, stories in grouped.items()],
        also=[*overflow_lines, *model_lines],
        essays=list(essays),
    )


def _filed_story(raw: Mapping[str, Any], *, domain: str, known_ids: Mapping[str, uuid.UUID]) -> _FiledStory | None:
    """The model's story with only known source ids; None when it has none left."""
    source_ids = _known(raw["source_ids"], known_ids=known_ids)
    if not source_ids:
        return None

    story = Story(
        headline=raw["headline"],
        body=raw["body"],
        why=raw["why"],
        detail=raw["detail"],
        importance=min(max(int(raw["importance"]), MIN_IMPORTANCE), MAX_IMPORTANCE),
        source_ids=source_ids,
    )
    return _FiledStory(domain=domains.parse_domain(domain), story=story)


def _known(raw_ids: Sequence[str], *, known_ids: Mapping[str, uuid.UUID]) -> list[uuid.UUID]:
    """The ids that name a covered newsletter, in order, each once."""
    cleaned = (raw_id.strip().lower() for raw_id in raw_ids)
    return list(dict.fromkeys(known_ids[raw_id] for raw_id in cleaned if raw_id in known_ids))
