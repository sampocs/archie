"""The podcast episode a `transcribe` job works on, carried in its payload and kept on the `text` artifact."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from archie_shared import podcast_feed

# The payload / artifact key holding a `PodcastEpisode`.
EPISODE_KEY = podcast_feed.EPISODE_KEY


@dataclass(frozen=True)
class PodcastEpisode:
    """A resolved podcast episode: where its audio is and what to call it."""

    show_name: str
    title: str
    description: str
    feed_url: str
    guid: str | None
    audio_url: str
    duration_s: int | None
    image_url: str | None = None
    # The feed item's publication day, when the feed gives one.
    published: datetime.date | None = None

    def to_payload(self) -> dict[str, Any]:
        """The episode as JSON-ready data."""
        return {
            "show_name": self.show_name,
            "title": self.title,
            "description": self.description,
            "feed_url": self.feed_url,
            "guid": self.guid,
            "audio_url": self.audio_url,
            "duration_s": self.duration_s,
            "image_url": self.image_url,
            "published": self.published.isoformat() if self.published is not None else None,
        }

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> PodcastEpisode:
        """The episode back from `to_payload` data; older payloads may lack `image_url` and `published`."""
        published = data.get("published")
        return cls(
            show_name=data["show_name"],
            title=data["title"],
            description=data["description"],
            feed_url=data["feed_url"],
            guid=data["guid"],
            audio_url=data["audio_url"],
            duration_s=data["duration_s"],
            image_url=data.get("image_url"),
            published=datetime.date.fromisoformat(published) if published else None,
        )
