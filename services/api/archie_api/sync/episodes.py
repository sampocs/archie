"""The `choose_episode` action: replace a podcast source's matched episode with another from the same feed."""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import changes, models, pipeline
from sqlalchemy import orm

from archie_api.sync import rows

MAX_GUID_LENGTH = 1_024

_NOT_PODCAST = "source is not a podcast"
_STILL_PROCESSING = "source is still processing"
_BUSY = frozenset({models.ProcessingStatus.PENDING, models.ProcessingStatus.PROCESSING})


class _ChooseEpisodePayload(pydantic.BaseModel):
    id: uuid.UUID
    guid: str = pydantic.Field(min_length=1, max_length=MAX_GUID_LENGTH)


def choose_episode(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Replace the matched episode: retire the source's text, summary, primer and cards, drop its transcript chunks,
    and fetch again with the chosen feed guid. The source is also unfiled and its primer unread, so the new episode
    is filed from its own summary."""
    parsed = rows.parse(_ChooseEpisodePayload, payload)
    if parsed is None:
        return rows.MALFORMED

    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.kind != models.SourceKind.PODCAST:
        return _NOT_PODCAST
    if source.processing in _BUSY:
        return _STILL_PROCESSING

    _retire_outputs(db, source=source)
    db.execute(sqlalchemy.delete(models.TranscriptChunk).where(models.TranscriptChunk.source_id == source.id))

    # Cleared so the new episode's title and artwork replace them (the pipeline only fills empty ones).
    source.episode_guid = parsed.guid
    source.title = None
    source.image_url = None

    # Analyze queues `file_topic` only while `domain` is null, and the new primer hasn't been read.
    source.domain = None
    source.topic_id = None
    source.primer_opened_at = None
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.FETCH_CONTENT])
    return None


def _retire_outputs(db: orm.Session, *, source: models.Source) -> None:
    """Make the current text, summary and primer non-current and soft-delete the cards, each with a new position."""
    for kind in (models.ArtifactKind.TEXT, models.ArtifactKind.SUMMARY, models.ArtifactKind.PRIMER):
        artifact = pipeline.current_artifact(db, source_id=source.id, kind=kind)
        if artifact is None:
            continue

        artifact.is_current = False
        artifact.change_seq = changes.next_change_seq()

    db.execute(
        sqlalchemy.update(models.Card)
        .where(models.Card.source_id == source.id, models.Card.deleted_at.is_(None))
        .values(
            deleted_at=sqlalchemy.func.now(),
            updated_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
    )
