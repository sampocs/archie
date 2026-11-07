"""Writing a source's text (or handing it to `transcribe`) under the user's lock, shared by the steps that find text."""

from __future__ import annotations

from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline

from archie_worker import content
from archie_worker.content import episode as episode_content

_MAX_TITLE_LENGTH = 500
_MAX_IMAGE_URL_LENGTH = 2048


def store_text(
    db: sqlalchemy.orm.Session,
    *,
    source: models.Source,
    text_content: dict[str, Any],
    title: str | None,
    image_url: str | None = None,
) -> None:
    """Store `text_content` as the current `text` artifact, fill an empty title and image, and queue its next steps
    and its search passages.

    Takes the user's write lock and re-reads the source first: the user may have deleted it during the outside call,
    in which case nothing is written.
    """
    if not _lock_live(db, source=source):
        return

    pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.TEXT, content=text_content, model=None, prompt_version=None
    )
    _set_title_if_empty(source, title=title)
    _set_image_if_empty(source, image_url=image_url)
    jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)
    pipeline.enqueue_steps(db, source=source, steps=pipeline.steps_after_text(models.SourceKind(source.kind)))


def enqueue_transcribe(
    db: sqlalchemy.orm.Session, *, source: models.Source, episode: episode_content.PodcastEpisode
) -> None:
    """Queue a `transcribe` job for the resolved episode and fill an empty title and image; it stays `processing`."""
    if not _lock_live(db, source=source):
        return

    _set_title_if_empty(source, title=episode.title)
    _set_image_if_empty(source, image_url=episode.image_url)
    jobs.enqueue(
        db,
        kind=models.JobKind.TRANSCRIBE,
        user_id=source.user_id,
        payload={pipeline.SOURCE_ID_KEY: str(source.id), episode_content.EPISODE_KEY: episode.to_payload()},
        max_attempts=pipeline.MAX_ATTEMPTS[models.JobKind.TRANSCRIBE],
    )


def _lock_live(db: sqlalchemy.orm.Session, *, source: models.Source) -> bool:
    """Take the user's write lock and refresh the source; False when it was deleted."""
    changes.lock_user_writes(db, source.user_id)
    db.refresh(source)
    return source.deleted_at is None


def _set_title_if_empty(source: models.Source, *, title: str | None) -> None:
    cleaned = " ".join(content.strip_nul(title or "").split())[:_MAX_TITLE_LENGTH]
    if source.title or not cleaned:
        return

    source.title = cleaned
    changes.touch(source)


def _set_image_if_empty(source: models.Source, *, image_url: str | None) -> None:
    # A cut-off URL would point nowhere, so an overlong one means no image.
    if source.image_url or not image_url or len(image_url) > _MAX_IMAGE_URL_LENGTH:
        return

    source.image_url = image_url
    changes.touch(source)
