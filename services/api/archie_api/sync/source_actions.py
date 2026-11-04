"""Reading-state actions on a source (and on topic primers for opened/snoozed): each returns a reason or None.

The caller holds the user's write lock; every check runs before the first write (see `actions.apply_actions`).
"""

from __future__ import annotations

import uuid
from enum import StrEnum

import pydantic
import sqlalchemy
from archie_db import changes, models, pipeline
from sqlalchemy import orm

from archie_api.sync import capture, rows

_NOT_QUEUED = "source is not queued"
_NOT_IN_INBOX = "source is not in the inbox"
_NOT_NEWSLETTER = "source is not a newsletter"
_NOT_READY = "source is not ready"
_NO_PRIMER = "topic primer not found"
_INBOX_STATES = frozenset({models.SourceState.INBOX, models.SourceState.BRIEFED})


class PrimerTarget(StrEnum):
    """What a primer-opened or snooze action points at."""

    SOURCE = "source"
    TOPIC_PRIMER = "topic_primer"


class _SourcePayload(pydantic.BaseModel):
    id: uuid.UUID


class _FinishPayload(_SourcePayload):
    reaction: models.Reaction | None = None
    note: str | None = pydantic.Field(default=None, max_length=capture.MAX_NOTE_LENGTH)


class _PrepMePayload(_SourcePayload):
    prep_me: bool


class _ReadPayload(_SourcePayload):
    read: bool


class _PrimerOpenedPayload(_SourcePayload):
    target: PrimerTarget
    opened: bool


class _SnoozePayload(_SourcePayload):
    target: PrimerTarget
    until: pydantic.AwareDatetime | None


class _QueuePositionPayload(_SourcePayload):
    position: float = pydantic.Field(allow_inf_nan=False)


def finish_source(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Mark a queued source consumed, with the optional reaction and note; "Parts lost me" also pushes its primer."""
    parsed = rows.parse(_FinishPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.state != models.SourceState.QUEUED:
        return _NOT_QUEUED

    source.state = models.SourceState.CONSUMED.value
    source.snoozed_until = None
    if parsed.reaction is not None:
        source.reaction = parsed.reaction.value
    if parsed.note:
        source.note = parsed.note
    if parsed.reaction == models.Reaction.LOST:
        source.prep_me = True
    changes.touch(source)
    return None


def snooze(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Hide a source or topic primer until `until` (None unsnoozes); a snoozed queued source returns at the top."""
    parsed = rows.parse(_SnoozePayload, payload)
    if parsed is None:
        return rows.MALFORMED

    if parsed.target == PrimerTarget.TOPIC_PRIMER:
        primer = rows.owned_topic_primer(db, user=user, primer_id=parsed.id)
        if primer is None:
            return _NO_PRIMER
        primer.snoozed_until = parsed.until
        primer.change_seq = changes.next_change_seq()
        return None

    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if parsed.until is not None and source.state == models.SourceState.QUEUED:
        source.queue_position = rows.top_queue_position(db, user_id=user.id)
    source.snoozed_until = parsed.until
    changes.touch(source)
    return None


def go_deeper(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Consume an inbox item for real: write its primer and re-analyze it, which now gives it cards."""
    parsed = rows.parse(_SourcePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.state not in _INBOX_STATES:
        return _NOT_IN_INBOX
    if source.processing != models.ProcessingStatus.READY:
        return _NOT_READY

    source.state = models.SourceState.CONSUMED.value
    source.snoozed_until = None
    source.read_at = source.read_at or sqlalchemy.func.now()
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.ANALYZE, models.JobKind.PRIMER])
    return None


def delete_source(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Soft-delete a source and its cards, so phones drop both."""
    parsed = rows.parse(_SourcePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE

    source.deleted_at = sqlalchemy.func.now()
    changes.touch(source)
    db.execute(
        sqlalchemy.update(models.Card)
        .where(models.Card.source_id == source.id, models.Card.deleted_at.is_(None))
        .values(
            deleted_at=sqlalchemy.func.now(),
            updated_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
    )
    return None


def set_prep_me(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Ask for (or drop) a primer on a queued source."""
    parsed = rows.parse(_PrepMePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.state != models.SourceState.QUEUED:
        return _NOT_QUEUED

    source.prep_me = parsed.prep_me
    changes.touch(source)
    return None


def set_read(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Mark an inbox newsletter read or unread."""
    parsed = rows.parse(_ReadPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.kind != models.SourceKind.NEWSLETTER:
        return _NOT_NEWSLETTER
    if source.state not in _INBOX_STATES:
        return _NOT_IN_INBOX

    source.read_at = sqlalchemy.func.now() if parsed.read else None
    changes.touch(source)
    return None


def set_primer_opened(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Record that a source's primer or a topic primer was opened (or clear it)."""
    parsed = rows.parse(_PrimerOpenedPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    opened_at = sqlalchemy.func.now() if parsed.opened else None

    if parsed.target == PrimerTarget.TOPIC_PRIMER:
        primer = rows.owned_topic_primer(db, user=user, primer_id=parsed.id)
        if primer is None:
            return _NO_PRIMER
        primer.opened_at = opened_at
        primer.change_seq = changes.next_change_seq()
        return None

    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    source.primer_opened_at = opened_at
    changes.touch(source)
    return None


def set_queue_position(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Move a queued source to the position the phone computed."""
    parsed = rows.parse(_QueuePositionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.state != models.SourceState.QUEUED:
        return _NOT_QUEUED

    source.queue_position = parsed.position
    changes.touch(source)
    return None


def read_later(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Move an inbox item to the top of the queue."""
    parsed = rows.parse(_SourcePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.state not in _INBOX_STATES:
        return _NOT_IN_INBOX

    source.queue_position = rows.top_queue_position(db, user_id=user.id)
    source.state = models.SourceState.QUEUED.value
    source.snoozed_until = None
    changes.touch(source)
    return None
