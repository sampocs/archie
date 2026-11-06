"""Take actions: write or edit a take, change its kind, delete it, restore a version, and retry a failed cleanup.

A take's title and kind live on `takes`; only the body is versioned in `take_versions`. A save makes the next version
when it is the first, the body changed, or Clean it up is asked for on a version that wasn't cleaned, and queues that
version's next step: `clean_take` when it has no body yet, otherwise `take_cards`. Each handler returns the rejection
reason or None; the caller holds the user's write lock and every check runs before the first write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pydantic
import sqlalchemy
from archie_db import card_rows, changes, models, takes
from sqlalchemy import orm

from archie_api.sync import rows

MAX_TAKE_TITLE_LENGTH = 200
MAX_TAKE_BODY_LENGTH = 20_000

NO_TAKE = "take not found"
_NO_VERSION = "take version not found"
_EMPTY_TITLE = "take title is empty"
_LONG_TITLE = f"take title is longer than {MAX_TAKE_TITLE_LENGTH} characters"
_EMPTY_BODY = "take is empty"
_LONG_BODY = f"take is longer than {MAX_TAKE_BODY_LENGTH} characters"
_ID_EXISTS = "id already exists"


class _SaveTakePayload(pydantic.BaseModel):
    id: uuid.UUID
    # Made on the phone so the new version shows offline; unused when the save makes no version.
    version_id: uuid.UUID
    kind: models.TakeKind
    title: str
    body: str
    clean: bool = False


class _UpdateTakePayload(pydantic.BaseModel):
    id: uuid.UUID
    kind: models.TakeKind | None = None
    title: str | None = None
    # There is no undelete: false is accepted and ignored.
    deleted: bool = False


class _RestoreTakeVersionPayload(pydantic.BaseModel):
    id: uuid.UUID
    version: int = pydantic.Field(ge=1)
    version_id: uuid.UUID


class _RetryTakeCleanupPayload(pydantic.BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID


@dataclass(frozen=True)
class _VersionText:
    """A new version's text: the shown body (None until `clean_take` writes it), the owner's raw text, the flag."""

    body: str | None
    raw_body: str
    cleaned: bool


def save_take(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Write a new take or save an edit; a version-making save also starts its cleanup or its cards."""
    parsed = rows.parse(_SaveTakePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    title = _clean_title(parsed.title)
    body = parsed.body.strip()
    reason = _title_reason(title) or _body_reason(body)
    if reason is not None:
        return reason
    take = db.get(models.Take, parsed.id)
    if take is not None and not _is_owned_live(take, user=user):
        return NO_TAKE
    current = takes.current_version(db, take=take) if take is not None else None
    makes_version = _save_makes_version(current, body=body, clean=parsed.clean)
    if makes_version and db.get(models.TakeVersion, parsed.version_id) is not None:
        return _ID_EXISTS

    if take is None:
        take = models.Take(
            id=parsed.id,
            user_id=user.id,
            kind=parsed.kind.value,
            title=title,
            current_version=0,
            change_seq=changes.next_change_seq(),
        )
        db.add(take)
        db.flush()

    take.kind = parsed.kind.value
    take.title = title
    if makes_version:
        text = _VersionText(body=None if parsed.clean else body, raw_body=body, cleaned=parsed.clean)
        _add_version(db, take=take, version_id=parsed.version_id, text=text)
    changes.touch(take)
    return None


def update_take(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Rename a take, change its kind, or delete it (its cards leave review with it); none of these makes a version."""
    parsed = rows.parse(_UpdateTakePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    take = _owned_take(db, user=user, take_id=parsed.id)
    if take is None:
        return NO_TAKE
    title = _clean_title(parsed.title) if parsed.title is not None else None
    reason = _title_reason(title) if title is not None else None
    if reason is not None:
        return reason

    if title is not None:
        take.title = title
    if parsed.kind is not None:
        take.kind = parsed.kind.value
    if parsed.deleted:
        take.deleted_at = sqlalchemy.func.now()
        card_rows.retire_cards(db, models.Card.take_id == take.id)
    changes.touch(take)
    return None


def restore_take_version(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Save an earlier version again as the newest one, exactly as it was (no new cleanup), and rewrite the cards."""
    parsed = rows.parse(_RestoreTakeVersionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    take = _owned_take(db, user=user, take_id=parsed.id)
    if take is None:
        return NO_TAKE
    earlier = db.scalar(
        sqlalchemy.select(models.TakeVersion).where(
            models.TakeVersion.take_id == take.id, models.TakeVersion.version == parsed.version
        )
    )
    if earlier is None:
        return _NO_VERSION
    if db.get(models.TakeVersion, parsed.version_id) is not None:
        return _ID_EXISTS

    # A version replaced while its own cleanup was still running may have no body yet; its raw text stands in.
    body = earlier.body if earlier.body is not None else earlier.raw_body
    text = _VersionText(body=body, raw_body=earlier.raw_body, cleaned=earlier.cleaned)
    _add_version(db, take=take, version_id=parsed.version_id, text=text)
    changes.touch(take)
    return None


def retry_take_cleanup(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Try again after Clean it up gave up: the version waits for `clean_take` again, its raw text shown meanwhile."""
    parsed = rows.parse(_RetryTakeCleanupPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    take = _owned_take(db, user=user, take_id=parsed.id)
    if take is None:
        return NO_TAKE
    version = db.get(models.TakeVersion, parsed.version_id)
    if version is None or version.take_id != take.id:
        return _NO_VERSION

    # Always bumped: a phone that skipped this version while the action was unsent pulls it again.
    takes.mark_changed(version)
    if not (version.cleaned and version.clean_failed):
        return None

    version.body = None
    version.clean_failed = False
    takes.enqueue_step(db, version=version, kind=models.JobKind.CLEAN_TAKE)
    return None


def _add_version(db: orm.Session, *, take: models.Take, version_id: uuid.UUID, text: _VersionText) -> None:
    """Make `text` the take's next version and queue its next step: the cleanup when it has no body, else its cards."""
    take.current_version += 1
    version = models.TakeVersion(
        id=version_id,
        user_id=take.user_id,
        take_id=take.id,
        version=take.current_version,
        body=text.body,
        raw_body=text.raw_body,
        cleaned=text.cleaned,
        change_seq=changes.next_change_seq(),
    )
    db.add(version)
    db.flush()

    step = models.JobKind.CLEAN_TAKE if text.body is None else models.JobKind.TAKE_CARDS
    takes.enqueue_step(db, version=version, kind=step)


def _save_makes_version(current: models.TakeVersion | None, *, body: str, clean: bool) -> bool:
    """A first save, a changed body, or Clean it up asked for on a version that wasn't cleaned (the phone agrees)."""
    if current is None:
        return True
    shown = current.body if current.body is not None else current.raw_body
    return body != shown or (clean and not current.cleaned)


def _is_owned_live(take: models.Take, *, user: models.User) -> bool:
    return take.user_id == user.id and take.deleted_at is None


def _owned_take(db: orm.Session, *, user: models.User, take_id: uuid.UUID) -> models.Take | None:
    """The user's live take with this id; another user's or a deleted one is treated as missing."""
    take = db.get(models.Take, take_id)
    return take if take is not None and _is_owned_live(take, user=user) else None


def _clean_title(title: str) -> str:
    return " ".join(title.split())


def _title_reason(title: str) -> str | None:
    if not title:
        return _EMPTY_TITLE
    if len(title) > MAX_TAKE_TITLE_LENGTH:
        return _LONG_TITLE
    return None


def _body_reason(body: str) -> str | None:
    if not body:
        return _EMPTY_BODY
    if len(body) > MAX_TAKE_BODY_LENGTH:
        return _LONG_BODY
    return None
