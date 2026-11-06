"""`fetch_collection_item`: fill a saved post's preview once, when it is saved.

A collection item is never a source: this reads only the post's URL and writes only its preview columns and
`metadata_status`. Following the loop's handler contract, it commits before the outside call and takes the user's
write lock only to write. When the job fails for good, `mark_failed` leaves the post with its URL (the phone shows a
neutral tile); there is nothing to retry by hand.
"""

from __future__ import annotations

import uuid

import sqlalchemy.orm
from archie_db import changes, jobs, models

from archie_worker.content import preview


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Fetch the post's preview and store it, bumping its change position so phones pull it."""
    item = db.get(models.CollectionItem, uuid.UUID(job.payload[jobs.COLLECTION_ITEM_ID_KEY]))
    if item is None or item.deleted_at is not None:
        return

    # Read what the fetch needs and end the transaction, so no connection is held during the outside calls.
    url, kind, user_id = item.url, models.CollectionItemKind(item.kind), item.user_id
    db.commit()
    fetched = preview.fetch(url=url, kind=kind)

    # The user may have removed the post during the fetch; the lock makes the refreshed state final.
    changes.lock_user_writes(db, user_id)
    db.refresh(item)
    if item.deleted_at is not None:
        return

    item.title = fetched.title
    item.author = fetched.author
    item.image_url = fetched.image_url
    item.duration_seconds = fetched.duration_seconds
    item.metadata_status = models.MetadataStatus.READY.value
    changes.touch(item)


def mark_failed(db: sqlalchemy.orm.Session, job: models.Job, reason: str) -> None:
    """Failure hook: mark the post's preview failed, unless the user removed it; `reason` stays on the job only."""
    del reason
    item = db.get(models.CollectionItem, uuid.UUID(job.payload[jobs.COLLECTION_ITEM_ID_KEY]))
    if item is None:
        return

    changes.lock_user_writes(db, item.user_id)
    db.refresh(item)
    if item.deleted_at is not None:
        return

    item.metadata_status = models.MetadataStatus.FAILED.value
    changes.touch(item)
