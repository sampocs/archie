"""Per-source reads the phone makes online: a newsletter's or chat item's full text and a podcast's nearby
episodes."""

from __future__ import annotations

import datetime
import uuid
import xml.etree.ElementTree
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

import fastapi
import httpx
import pydantic
import sqlalchemy
from archie_db import models, pipeline
from archie_shared import podcast_feed
from sqlalchemy import orm

from archie_api import deps

router = fastapi.APIRouter(prefix="/sources", tags=["sources"])

_TEXT_KEY = "text"  # The `text` artifact's content key (the worker's `content.TEXT_KEY`).
# The kinds whose stored text the phone shows: a newsletter's full email, a chat item's transcript (See original).
_TEXT_KINDS = frozenset({models.SourceKind.NEWSLETTER, models.SourceKind.CHAT})
EPISODE_WINDOW_DAYS = 30


class SourceTextView(pydantic.BaseModel):
    """A newsletter's stored text, for "Open the full email", or a chat item's transcript, for See original."""

    text: str


@router.get("/{source_id}/text")
def source_text(
    source_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> SourceTextView:
    """The caller's newsletter text or chat transcript; 404 for any other source, someone else's, or one without text.

    A signup confirmation, or a newsletter from a sender nobody has allowed yet, never gets a text artifact (that
    would embed it into Ask), so its capture is served instead.
    """
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user.id or source.deleted_at is not None:
        raise _not_found()
    if source.kind not in _TEXT_KINDS:
        raise _not_found()

    artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if artifact is not None:
        return SourceTextView(text=artifact.content[_TEXT_KEY])
    if source.confirm_url is None and not source.sender_pending:
        raise _not_found()

    capture = db.get(models.SourceCapture, source.id)
    if capture is None:
        raise _not_found()
    return SourceTextView(text=capture.text)


class EpisodeView(pydantic.BaseModel):
    """One feed episode offered for "Wrong episode?"."""

    guid: str
    title: str
    published: str | None
    duration_s: int | None
    is_current: bool


class EpisodesView(pydantic.BaseModel):
    """The show's episodes near the matched one, newest first."""

    episodes: list[EpisodeView]


@dataclass(frozen=True)
class _ResolvedEpisode:
    """Where a podcast source's matched episode lives: its feed, its guid, and when the source was saved."""

    feed_url: str
    guid: str | None
    saved_on: datetime.date


@router.get("/{source_id}/episodes")
def episodes(
    source_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> EpisodesView:
    """The show's episodes within 30 days of the matched one, newest first, for "Wrong episode?"."""
    resolved = _resolved_episode(db, user=user, source_id=source_id)
    # Nothing is held open while the feed downloads.
    db.commit()
    try:
        items = podcast_feed.parse_feed(podcast_feed.fetch_feed(resolved.feed_url))
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, xml.etree.ElementTree.ParseError, ValueError) as error:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_502_BAD_GATEWAY, detail="couldn't read the feed"
        ) from error

    return EpisodesView(
        episodes=episodes_near(items=items, current_guid=resolved.guid, fallback_date=resolved.saved_on)
    )


def episodes_near(
    *, items: Sequence[podcast_feed.FeedItem], current_guid: str | None, fallback_date: datetime.date
) -> list[EpisodeView]:
    """Playable items with a date within 30 days of the current item (else of `fallback_date`), newest first."""
    current = next((item for item in items if current_guid and item.guid == current_guid), None)
    centre = current.published if current is not None and current.published else fallback_date
    window = datetime.timedelta(days=EPISODE_WINDOW_DAYS)

    nearby = [
        item
        for item in items
        if item.guid and item.audio_url and item.published and abs(item.published - centre) <= window
    ]
    nearby.sort(key=lambda item: item.published or centre, reverse=True)
    return [
        EpisodeView(
            guid=item.guid or "",
            title=item.title,
            published=item.published.isoformat() if item.published else None,
            duration_s=item.duration_s,
            is_current=item.guid == current_guid,
        )
        for item in nearby
    ]


def _resolved_episode(db: orm.Session, *, user: models.User, source_id: uuid.UUID) -> _ResolvedEpisode:
    """The caller's podcast source's matched episode; 404 for anything else or one not resolved yet."""
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user.id or source.deleted_at is not None:
        raise _not_found()
    if source.kind != models.SourceKind.PODCAST:
        raise _not_found()

    episode = _episode_of(db, source=source)
    if episode is None:
        raise _not_found()

    return _ResolvedEpisode(feed_url=episode["feed_url"], guid=episode.get("guid"), saved_on=source.created_at.date())


def _episode_of(db: orm.Session, *, source: models.Source) -> dict[str, Any] | None:
    """The `episode` record of the current text, else of the newest text that has a feed url.

    Choosing another episode retires the current text, and a failed re-fetch never writes a new one; the older
    record keeps "Wrong episode?" usable then.
    """
    texts = db.scalars(
        sqlalchemy.select(models.SourceArtifact)
        .where(models.SourceArtifact.source_id == source.id, models.SourceArtifact.kind == models.ArtifactKind.TEXT)
        .order_by(models.SourceArtifact.is_current.desc(), models.SourceArtifact.version.desc())
    )
    for artifact in texts:
        episode = artifact.content.get(podcast_feed.EPISODE_KEY)
        if isinstance(episode, dict) and episode.get("feed_url"):
            return episode
    return None


def _not_found() -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail="source not found")
