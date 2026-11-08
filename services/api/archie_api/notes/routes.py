"""Notes imported from Bear: the import endpoint and the write-up queue."""

from __future__ import annotations

import datetime
import uuid
from enum import StrEnum
from typing import Annotated

import fastapi
import pydantic
import sqlalchemy
from archie_db import changes, jobs, models, pipeline
from sqlalchemy import orm

from archie_api import deps
from archie_api.sync import rows

NOTE_URL_PREFIX = "bear:"
MAX_NOTES_PER_IMPORT = 50
MAX_NOTE_MARKDOWN_LENGTH = 200_000
# Write-ups run one a minute so a first backlog of hundreds trickles in instead of bursting the model's rate limit.
WRITE_UP_SPACING = datetime.timedelta(seconds=60)
_MAX_TAG_LENGTH = 200

router = fastapi.APIRouter(prefix="/notes", tags=["notes"])


class NoteMark(StrEnum):
    """What the owner chose for a note in the triage: searchable only, or also review cards via the refresher."""

    IMPORT = "import"
    CARDS = "cards"


class ImportStatus(StrEnum):
    """What one import did to a note."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


class NoteIn(pydantic.BaseModel):
    """One Bear note as the import script sends it."""

    bear_id: str = pydantic.Field(min_length=1, max_length=64)
    title: str = pydantic.Field(min_length=1, max_length=500)
    markdown: str = pydantic.Field(max_length=MAX_NOTE_MARKDOWN_LENGTH)
    tags: list[str] = pydantic.Field(default_factory=list, max_length=50)
    created_at: pydantic.AwareDatetime
    edited_at: pydantic.AwareDatetime
    mark: NoteMark

    @pydantic.field_validator("tags")
    @classmethod
    def _short_tags(cls, tags: list[str]) -> list[str]:
        if any(len(tag) > _MAX_TAG_LENGTH for tag in tags):
            raise ValueError(f"a tag is longer than {_MAX_TAG_LENGTH} characters")
        return tags


class ImportRequest(pydantic.BaseModel):
    """A batch of notes; a Bear id may appear once."""

    notes: list[NoteIn] = pydantic.Field(min_length=1, max_length=MAX_NOTES_PER_IMPORT)

    @pydantic.model_validator(mode="after")
    def _unique_bear_ids(self) -> ImportRequest:
        ids = [note.bear_id for note in self.notes]
        if len(set(ids)) != len(ids):
            raise ValueError("a bear_id appears more than once")
        return self


class ImportResult(pydantic.BaseModel):
    """What the import did to one note."""

    bear_id: str
    id: uuid.UUID
    status: ImportStatus


class ImportResponse(pydantic.BaseModel):
    """One result per imported note, in request order."""

    results: list[ImportResult]


class WriteUpsResponse(pydantic.BaseModel):
    """How many write-up jobs this call queued."""

    queued: int


@router.post("/import")
def import_notes(
    request: ImportRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> ImportResponse:
    """Create or update the user's note sources from Bear; nothing is generated (write-ups are queued separately)."""
    changes.lock_user_writes(db, user.id)

    results = [_import_one(db, user=user, note=note) for note in request.notes]

    db.commit()
    return ImportResponse(results=results)


@router.post("/write-ups")
def queue_write_ups(
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> WriteUpsResponse:
    """Queue one spaced `write_note` job for each of the user's notes whose write-up is missing or older than its text.

    Spends the owner's model keys, so only a whitelisted user may ask.
    """
    if not user.is_whitelisted:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail=deps.NEEDS_OWN_KEY)
    changes.lock_user_writes(db, user.id)

    notes = db.scalars(
        sqlalchemy.select(models.Source)
        .where(
            models.Source.user_id == user.id,
            models.Source.kind == models.SourceKind.NOTE.value,
            models.Source.deleted_at.is_(None),
        )
        .order_by(models.Source.note_edited_at.desc().nulls_last(), models.Source.id)
    ).all()
    needing = [note for note in notes if _needs_write_up(db, note=note)]

    for index, note in enumerate(needing):
        jobs.enqueue(
            db,
            kind=models.JobKind.WRITE_NOTE,
            user_id=user.id,
            payload={pipeline.SOURCE_ID_KEY: str(note.id)},
            max_attempts=pipeline.MAX_ATTEMPTS[models.JobKind.WRITE_NOTE],
            delay=WRITE_UP_SPACING * index,
        )

    db.commit()
    return WriteUpsResponse(queued=len(needing))


def _import_one(db: orm.Session, *, user: models.User, note: NoteIn) -> ImportResult:
    source = db.scalars(
        sqlalchemy.select(models.Source).where(models.Source.user_id == user.id, models.Source.bear_id == note.bear_id)
    ).one_or_none()
    if source is None:
        source = _create_note(db, user=user, note=note)
        return ImportResult(bear_id=note.bear_id, id=source.id, status=ImportStatus.CREATED)

    # A note the owner deleted on the phone stays deleted, however often Bear still has it.
    if source.deleted_at is not None:
        return ImportResult(bear_id=note.bear_id, id=source.id, status=ImportStatus.DELETED)
    return ImportResult(bear_id=note.bear_id, id=source.id, status=_update_note(db, source=source, note=note))


def _state_for(mark: NoteMark) -> models.SourceState:
    return models.SourceState.CONSUMED if mark == NoteMark.IMPORT else models.SourceState.INBOX


def _create_note(db: orm.Session, *, user: models.User, note: NoteIn) -> models.Source:
    url = f"{NOTE_URL_PREFIX}{note.bear_id}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url=url,
        normalized_url=url,
        title=note.title,
        kind=models.SourceKind.NOTE.value,
        state=_state_for(note.mark).value,
        intent=models.SourceIntent.FINISHED.value,
        created_at=note.created_at,
        processing=models.ProcessingStatus.READY.value,
        cards_off=note.mark == NoteMark.IMPORT,
        bear_id=note.bear_id,
        note_markdown=note.markdown,
        note_tags=note.tags,
        note_edited_at=note.edited_at,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()

    _store_text(db, source=source)
    return source


def _store_text(db: orm.Session, *, source: models.Source) -> None:
    """Write the note's markdown as its current text and queue it for search."""
    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.TEXT,
        content={"text": source.note_markdown},
        model=None,
        prompt_version=None,
    )
    jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)


def _update_note(db: orm.Session, *, source: models.Source, note: NoteIn) -> ImportStatus:
    markdown_changed = source.note_markdown != note.markdown
    # Once refreshed the phone owns the note's state and cards, so a later mark change no longer applies.
    mark_applies = source.refreshed_at is None and source.cards_off != (note.mark == NoteMark.IMPORT)
    unchanged = (
        not markdown_changed
        and not mark_applies
        and source.title == note.title
        and source.note_tags == note.tags
        and source.note_edited_at == note.edited_at
    )
    if unchanged:
        return ImportStatus.UNCHANGED

    source.title = note.title
    source.note_markdown = note.markdown
    source.note_tags = note.tags
    source.note_edited_at = note.edited_at
    if mark_applies:
        source.cards_off = note.mark == NoteMark.IMPORT
        source.state = _state_for(note.mark).value
    if markdown_changed:
        _store_text(db, source=source)
    changes.touch(source)
    return ImportStatus.UPDATED


def _needs_write_up(db: orm.Session, *, note: models.Source) -> bool:
    """Whether the note has text but no write-up newer than it, and none is already queued or running."""
    text = pipeline.current_artifact(db, source_id=note.id, kind=models.ArtifactKind.TEXT)
    if text is None:
        return False

    summary = pipeline.current_artifact(db, source_id=note.id, kind=models.ArtifactKind.SUMMARY)
    if summary is not None and summary.created_at >= text.created_at:
        return False
    return not rows.has_pending_job(db, source=note, kind=models.JobKind.WRITE_NOTE)
