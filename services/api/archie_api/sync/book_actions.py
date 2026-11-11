"""The `add_book` action, and finishing a book (shared with `finish_source`).

A book is one source for its whole life: added as reading (its spoiler-free primer is written and queued in Up next)
or as finished (its refresher is written), and finishing a reading book later moves the same source to finished. The
caller holds the user's write lock; every check runs before the first write (see `actions.apply_actions`).
"""

from __future__ import annotations

import uuid
from enum import StrEnum

import pydantic
import sqlalchemy
from archie_db import changes, models, pipeline
from archie_shared import urls
from sqlalchemy import orm

from archie_api.sync import capture, rows

MAX_TITLE_LENGTH = 500
MAX_AUTHOR_LENGTH = 300

_NOTE_NEEDS_FINISHED = "note needs state finished"
_SOURCE_ID_EXISTS = "source id already exists"


class BookState(StrEnum):
    """Where the owner is with a book they add: reading it now, or already finished."""

    READING = "reading"
    FINISHED = "finished"


class _AddBookPayload(pydantic.BaseModel):
    id: uuid.UUID
    url: str
    title: str = pydantic.Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    author: str | None = pydantic.Field(default=None, max_length=MAX_AUTHOR_LENGTH)
    image_url: str | None = None
    state: BookState
    # The owner's thoughts on finishing it.
    note: str | None = pydantic.Field(default=None, max_length=capture.MAX_NOTE_LENGTH)


def add_book(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Add a book, or fold it into the user's book with the same URL (finishing that one when it was being read)."""
    parsed = rows.parse(_AddBookPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    reason = _validate(db, payload=parsed)
    if reason is not None:
        return reason

    normalized_url = urls.normalize_url(parsed.url)
    existing = db.scalars(
        sqlalchemy.select(models.Source)
        .where(
            models.Source.user_id == user.id,
            models.Source.kind == models.SourceKind.BOOK.value,
            models.Source.normalized_url == normalized_url,
            models.Source.deleted_at.is_(None),
        )
        .order_by(models.Source.created_at, models.Source.change_seq)
        .limit(1)
    ).one_or_none()

    if existing is None:
        _insert_book(db, user=user, payload=parsed, normalized_url=normalized_url)
        return None

    _insert_merged_book(db, user=user, payload=parsed, normalized_url=normalized_url, existing=existing)
    if existing.state == models.SourceState.READING and parsed.state == BookState.FINISHED:
        finish_book(db, source=existing, note=parsed.note)
    return None


def finish_book(db: orm.Session, *, source: models.Source, note: str | None) -> None:
    """Move a book being read to finished, keeping the owner's thoughts, and have its refresher written.

    A primer in the queue stays there. The caller has checked that the book is being read.
    """
    source.state = models.SourceState.CONSUMED.value
    if note:
        source.note = note
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.WRITE_BOOK])


def _validate(db: orm.Session, *, payload: _AddBookPayload) -> str | None:
    """The reason this add_book can't be applied, or None."""
    url_reason = capture.validate_url(payload.url)
    if url_reason is not None:
        return url_reason
    image_reason = capture.validate_url(payload.image_url) if payload.image_url is not None else None
    if image_reason is not None:
        return f"image_url: {image_reason}"
    if payload.note is not None and payload.state != BookState.FINISHED:
        return _NOTE_NEEDS_FINISHED

    # As for add_source: a retry carries the same action id, so a new action reusing a source id is a client bug.
    if db.get(models.Source, payload.id) is not None:
        return _SOURCE_ID_EXISTS
    return None


def _insert_book(db: orm.Session, *, user: models.User, payload: _AddBookPayload, normalized_url: str) -> None:
    """Insert the book and start its first step: a reading book's primer (queued in Up next), else its refresher."""
    book = _build_book(
        user=user, payload=payload, normalized_url=normalized_url, processing=models.ProcessingStatus.PROCESSING
    )
    db.add(book)
    db.flush()

    if payload.state == BookState.FINISHED:
        pipeline.enqueue_steps(db, source=book, steps=[models.JobKind.WRITE_BOOK])
        return
    pipeline.enqueue_steps(db, source=book, steps=[models.JobKind.PRIMER])
    rows.queue_primer(db, source=book)


def _insert_merged_book(
    db: orm.Session,
    *,
    user: models.User,
    payload: _AddBookPayload,
    normalized_url: str,
    existing: models.Source,
) -> None:
    """Record the phone's row as deleted and pointing at `existing`, so the phone learns which book won."""
    merged = _build_book(
        user=user,
        payload=payload,
        normalized_url=normalized_url,
        processing=models.ProcessingStatus(existing.processing),
    )
    merged.deleted_at = sqlalchemy.func.now()
    merged.merged_into_id = existing.id
    db.add(merged)
    db.flush()


def _build_book(
    *, user: models.User, payload: _AddBookPayload, normalized_url: str, processing: models.ProcessingStatus
) -> models.Source:
    is_reading = payload.state == BookState.READING
    return models.Source(
        id=payload.id,
        user_id=user.id,
        url=payload.url,
        normalized_url=normalized_url,
        title=payload.title,
        author=payload.author,
        image_url=payload.image_url,
        kind=models.SourceKind.BOOK.value,
        state=(models.SourceState.READING if is_reading else models.SourceState.CONSUMED).value,
        # Unused for books; both states store `finished`.
        intent=models.SourceIntent.FINISHED.value,
        processing=processing.value,
        note=payload.note,
        change_seq=changes.next_change_seq(),
    )
