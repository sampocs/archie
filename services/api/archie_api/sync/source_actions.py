"""Reading-state actions on a source, its queued primer, and topic primers: each returns a reason or None.

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
_PRIMER_NOT_QUEUED = "primer is not queued"
_HAS_PRIMER = "source already has a primer"
_PREP_ME_REMOVED = "prep me was removed"
_WRITING_PRIMER = "primer is being written"
_INBOX_STATES = frozenset({models.SourceState.INBOX, models.SourceState.BRIEFED})


class PrimerTarget(StrEnum):
    """What a primer-opened action points at."""

    SOURCE = "source"
    TOPIC_PRIMER = "topic_primer"


class SnoozeTarget(StrEnum):
    """What a snooze action hides: a source, a source's queued primer, or a topic primer."""

    SOURCE = "source"
    SOURCE_PRIMER = "source_primer"
    TOPIC_PRIMER = "topic_primer"


class QueueTarget(StrEnum):
    """Which queue entry a position applies to: a queued source, or a source's queued primer."""

    SOURCE = "source"
    SOURCE_PRIMER = "source_primer"


class _SourcePayload(pydantic.BaseModel):
    id: uuid.UUID


class _FinishPayload(_SourcePayload):
    reaction: models.Reaction | None = None
    note: str | None = pydantic.Field(default=None, max_length=capture.MAX_NOTE_LENGTH)
    queue_primer: bool = False


class _QueuePrimerPayload(_SourcePayload):
    queued: bool


class _ReadPayload(_SourcePayload):
    read: bool


class _FavoritePayload(_SourcePayload):
    favorited: bool


class _PrimerOpenedPayload(_SourcePayload):
    target: PrimerTarget
    opened: bool


class _SnoozePayload(_SourcePayload):
    target: SnoozeTarget
    until: pydantic.AwareDatetime | None


class _QueuePositionPayload(_SourcePayload):
    position: float = pydantic.Field(allow_inf_nan=False)
    target: QueueTarget = QueueTarget.SOURCE


def finish_source(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Mark a queued source consumed, with the optional reaction and note, and queue its primer when asked.

    A newsletter is analyzed again once consumed, which now gives it cards.
    """
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
    changes.touch(source)

    # Analyze goes first, so a newsletter's primer (if this queues one) is written after its cards. An analyze
    # already queued or running makes cards anyway (it checks the consumed state when it runs), and one without text
    # has nothing to analyze; every other newsletter needs another pass, including one only writing its primer.
    if source.kind == models.SourceKind.NEWSLETTER and _needs_reanalysis(db, source=source):
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
        pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.ANALYZE])
    if parsed.queue_primer:
        rows.queue_primer(db, source=source)
    return None


def _needs_reanalysis(db: orm.Session, *, source: models.Source) -> bool:
    has_text = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT) is not None
    return has_text and not rows.has_pending_job(db, source=source, kind=models.JobKind.ANALYZE)


def queue_primer(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Put a source's primer in the queue as its own entry (writing a newsletter's first), or take it out."""
    parsed = rows.parse(_QueuePrimerPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE

    if parsed.queued:
        rows.queue_primer(db, source=source)
        return None
    source.primer_queue_position = None
    changes.touch(source)
    return None


def request_primer(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Write a ready newsletter's primer, which newsletters only get on request.

    Rejected while a primer is already being written, so a second tap can't queue a second job.
    """
    parsed = rows.parse(_SourcePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.kind != models.SourceKind.NEWSLETTER:
        return _NOT_NEWSLETTER
    if source.processing != models.ProcessingStatus.READY:
        return _NOT_READY
    if pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.PRIMER) is not None:
        return _HAS_PRIMER
    if rows.has_or_is_writing_primer(db, source=source):
        return _WRITING_PRIMER

    rows.start_primer(db, source=source)
    return None


def set_prep_me(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Reject "Prep me", which was removed; kept so an old phone's pending action doesn't fail the whole push."""
    return _PREP_ME_REMOVED


def return_to_inbox(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Undo "Add to queue": a queued newsletter goes back to the inbox."""
    parsed = rows.parse(_SourcePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.kind != models.SourceKind.NEWSLETTER:
        return _NOT_NEWSLETTER
    if source.state != models.SourceState.QUEUED:
        return _NOT_QUEUED

    source.state = models.SourceState.INBOX.value
    source.queue_position = None
    changes.touch(source)
    return None


def snooze(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Hide a source, its queued primer or a topic primer until `until` (None unsnoozes).

    A snoozed queue entry (a queued source or a queued primer) returns at the top of the queue.
    """
    parsed = rows.parse(_SnoozePayload, payload)
    if parsed is None:
        return rows.MALFORMED

    if parsed.target == SnoozeTarget.TOPIC_PRIMER:
        primer = rows.owned_topic_primer(db, user=user, primer_id=parsed.id)
        if primer is None:
            return _NO_PRIMER
        primer.snoozed_until = parsed.until
        primer.change_seq = changes.next_change_seq()
        return None

    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE

    if parsed.target == SnoozeTarget.SOURCE_PRIMER:
        if parsed.until is not None and source.primer_queue_position is not None:
            source.primer_queue_position = rows.top_queue_position(db, user_id=user.id)
        source.primer_snoozed_until = parsed.until
        changes.touch(source)
        return None

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

    # Going deeper asks for cards, so it undoes "No cards for this".
    source.cards_off = False
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


def set_favorite(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Star a source or clear its star; asking for the state it is already in writes nothing.

    Starring again keeps the first star's time, so "newest star first" doesn't reshuffle when a phone resends.
    """
    parsed = rows.parse(_FavoritePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if parsed.favorited == (source.favorited_at is not None):
        return None

    source.favorited_at = sqlalchemy.func.now() if parsed.favorited else None
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
    """Move a queued source, or a source's queued primer, to the position the phone computed."""
    parsed = rows.parse(_QueuePositionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE

    if parsed.target == QueueTarget.SOURCE_PRIMER:
        if source.primer_queue_position is None:
            return _PRIMER_NOT_QUEUED
        source.primer_queue_position = parsed.position
        changes.touch(source)
        return None

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
