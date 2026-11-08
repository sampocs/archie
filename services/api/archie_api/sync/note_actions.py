"""Refresher actions on a note: Done (refresh) and skip, each returning a reason or None.

The caller holds the user's write lock; every check runs before the first write (see `actions.apply_actions`).
"""

from __future__ import annotations

import datetime
import uuid

import pydantic
from archie_db import changes, jobs, models, pipeline
from sqlalchemy import orm

from archie_api.sync import rows

_NOT_A_NOTE = "source is not a note"
_ALREADY_REFRESHED = "note is already refreshed"
_CARDS_OFF = "note has cards off"
_NO_WRITE_UP = "note has no write-up yet"


class _RefreshPayload(pydantic.BaseModel):
    id: uuid.UUID
    counted: bool
    at: pydantic.AwareDatetime


class _SkipPayload(pydantic.BaseModel):
    id: uuid.UUID
    at: pydantic.AwareDatetime


def refresh_note(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Done on a note: it becomes a Done item refreshed at the phone's tap time, and its review cards are queued."""
    parsed = rows.parse(_RefreshPayload, payload)
    if parsed is None:
        return rows.MALFORMED

    source = rows.owned_source(db, user=user, source_id=parsed.id)
    reason = _refreshable_reason(db, source=source)
    if reason is not None:
        return reason
    assert source is not None

    source.refreshed_at = _not_after_now(parsed.at)
    source.refreshed_from_queue = parsed.counted
    source.state = models.SourceState.CONSUMED.value
    changes.touch(source)
    jobs.enqueue(db, kind=models.JobKind.NOTE_CARDS, user_id=user.id, payload={pipeline.SOURCE_ID_KEY: str(source.id)})
    return None


def skip_note(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Skip a note in the refresher: it goes to the back of the queue."""
    parsed = rows.parse(_SkipPayload, payload)
    if parsed is None:
        return rows.MALFORMED

    source = rows.owned_source(db, user=user, source_id=parsed.id)
    reason = _note_reason(source=source)
    if reason is not None:
        return reason
    assert source is not None

    source.refresh_skipped_at = _not_after_now(parsed.at)
    changes.touch(source)
    return None


def _note_reason(*, source: models.Source | None) -> str | None:
    """Why the row can't be refreshed or skipped: missing, not a note, or already refreshed."""
    if source is None:
        return rows.NO_SOURCE
    if source.kind != models.SourceKind.NOTE:
        return _NOT_A_NOTE
    if source.refreshed_at is not None:
        return _ALREADY_REFRESHED
    return None


def _refreshable_reason(db: orm.Session, *, source: models.Source | None) -> str | None:
    """Refreshing also needs cards on and the write-up the refresher shows."""
    reason = _note_reason(source=source)
    if reason is not None:
        return reason
    assert source is not None
    if source.cards_off:
        return _CARDS_OFF
    if pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY) is None:
        return _NO_WRITE_UP
    return None


def _not_after_now(at: datetime.datetime) -> datetime.datetime:
    """A phone clock ahead of the server's must not write a future time."""
    return min(at, datetime.datetime.now(datetime.UTC))
