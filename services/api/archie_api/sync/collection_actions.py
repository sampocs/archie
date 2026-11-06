"""Collection actions: make, rename, reorder and delete a collection; save, edit, move and remove a post.

Collections are scrapbooks kept apart from the learning side: nothing here reads or writes sources, cards or the
pipeline, and the only job queued is `fetch_collection_item`, which fills in a post's preview. Each handler returns the
rejection reason or None; the caller holds the user's write lock and every check runs before the first write.
"""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import changes, jobs, models
from archie_shared import urls
from sqlalchemy import orm

from archie_api.sync import capture, rows

MAX_COLLECTION_NAME_LENGTH = 100

NO_COLLECTION = "collection not found"
NO_COLLECTION_ITEM = "collection item not found"
_EMPTY_NAME = "collection name is empty"
_LONG_NAME = f"collection name is longer than {MAX_COLLECTION_NAME_LENGTH} characters"
_LONG_NOTE = f"note is longer than {capture.MAX_NOTE_LENGTH} characters"
_ID_EXISTS = "id already exists"

# Only X and YouTube get their own preview lookups; every other URL is a plain link.
_ITEM_KIND_BY_URL_KIND = {
    urls.UrlKind.X: models.CollectionItemKind.X,
    urls.UrlKind.YOUTUBE: models.CollectionItemKind.YOUTUBE,
}


class _CreateCollectionPayload(pydantic.BaseModel):
    id: uuid.UUID
    name: str


class _UpdateCollectionPayload(pydantic.BaseModel):
    id: uuid.UUID
    name: str | None = None
    position: float | None = pydantic.Field(default=None, allow_inf_nan=False)
    # There is no undelete: false is accepted and ignored.
    deleted: bool = False


class _AddCollectionItemPayload(pydantic.BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    url: str
    note: str | None = None


class _UpdateCollectionItemPayload(pydantic.BaseModel):
    id: uuid.UUID
    # Only applied when the key is present (see `model_fields_set`); null or blank clears the note.
    note: str | None = None
    collection_id: uuid.UUID | None = None
    deleted: bool = False


def create_collection(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Make an empty collection after the user's last one."""
    parsed = rows.parse(_CreateCollectionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    name = _clean_name(parsed.name)
    reason = _name_reason(name)
    if reason is not None:
        return reason
    if db.get(models.Collection, parsed.id) is not None:
        return _ID_EXISTS

    db.add(
        models.Collection(
            id=parsed.id,
            user_id=user.id,
            name=name,
            position=_end_position(db, user_id=user.id),
            change_seq=changes.next_change_seq(),
        )
    )
    db.flush()
    return None


def update_collection(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Rename, move or delete a collection; deleting it removes every post in it too."""
    parsed = rows.parse(_UpdateCollectionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    collection = _owned_collection(db, user=user, collection_id=parsed.id)
    if collection is None:
        return NO_COLLECTION
    name = _clean_name(parsed.name) if parsed.name is not None else None
    reason = _name_reason(name) if name is not None else None
    if reason is not None:
        return reason

    if name is not None:
        collection.name = name
    if parsed.position is not None:
        collection.position = parsed.position
    if parsed.deleted:
        _delete_with_items(db, collection=collection)
    changes.touch(collection)
    return None


def add_collection_item(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Save a link into one of the user's collections and queue its preview; it never becomes a source."""
    parsed = rows.parse(_AddCollectionItemPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    url_reason = capture.validate_url(parsed.url)
    if url_reason is not None:
        return url_reason
    note = _clean_note(parsed.note)
    if note is not None and len(note) > capture.MAX_NOTE_LENGTH:
        return _LONG_NOTE
    if _owned_collection(db, user=user, collection_id=parsed.collection_id) is None:
        return NO_COLLECTION
    if db.get(models.CollectionItem, parsed.id) is not None:
        return _ID_EXISTS

    kind = _ITEM_KIND_BY_URL_KIND.get(urls.detect_kind(parsed.url), models.CollectionItemKind.LINK)
    item = models.CollectionItem(
        id=parsed.id,
        user_id=user.id,
        collection_id=parsed.collection_id,
        url=parsed.url,
        kind=kind.value,
        note=note,
        change_seq=changes.next_change_seq(),
    )
    db.add(item)
    db.flush()
    jobs.enqueue(
        db,
        kind=models.JobKind.FETCH_COLLECTION_ITEM,
        user_id=user.id,
        payload={jobs.COLLECTION_ITEM_ID_KEY: str(item.id)},
    )
    return None


def update_collection_item(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Edit a post's note, move it to another of the user's collections, or remove it."""
    parsed = rows.parse(_UpdateCollectionItemPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    item = _owned_item(db, user=user, item_id=parsed.id)
    if item is None:
        return NO_COLLECTION_ITEM
    note = _clean_note(parsed.note)
    if note is not None and len(note) > capture.MAX_NOTE_LENGTH:
        return _LONG_NOTE
    target_id = parsed.collection_id
    if target_id is not None and _owned_collection(db, user=user, collection_id=target_id) is None:
        return NO_COLLECTION

    if "note" in parsed.model_fields_set:
        item.note = note
    if target_id is not None:
        item.collection_id = target_id
    if parsed.deleted:
        item.deleted_at = sqlalchemy.func.now()
    changes.touch(item)
    return None


def _owned_collection(db: orm.Session, *, user: models.User, collection_id: uuid.UUID) -> models.Collection | None:
    """The user's live collection with this id; another user's or a deleted one is treated as missing."""
    collection = db.get(models.Collection, collection_id)
    if collection is None or collection.user_id != user.id or collection.deleted_at is not None:
        return None
    return collection


def _owned_item(db: orm.Session, *, user: models.User, item_id: uuid.UUID) -> models.CollectionItem | None:
    """The user's live post with this id (a deleted collection's posts are deleted with it)."""
    item = db.get(models.CollectionItem, item_id)
    if item is None or item.user_id != user.id or item.deleted_at is not None:
        return None
    return item


def _clean_name(name: str) -> str:
    return " ".join(name.split())


def _name_reason(name: str) -> str | None:
    if not name:
        return _EMPTY_NAME
    if len(name) > MAX_COLLECTION_NAME_LENGTH:
        return _LONG_NAME
    return None


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    return note.strip() or None


def _end_position(db: orm.Session, *, user_id: int) -> float:
    """One past the user's last live collection, or 0 for the first."""
    last = db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(models.Collection.position)).where(
            models.Collection.user_id == user_id, models.Collection.deleted_at.is_(None)
        )
    )
    return 0.0 if last is None else last + 1


def _delete_with_items(db: orm.Session, *, collection: models.Collection) -> None:
    """Soft-delete the collection and its live posts, each with a fresh change position so phones pull the deletion."""
    collection.deleted_at = sqlalchemy.func.now()
    live_items = db.scalars(
        sqlalchemy.select(models.CollectionItem).where(
            models.CollectionItem.collection_id == collection.id, models.CollectionItem.deleted_at.is_(None)
        )
    )
    for item in live_items:
        item.deleted_at = sqlalchemy.func.now()
        changes.touch(item)
