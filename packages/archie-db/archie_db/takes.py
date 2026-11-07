"""Take rows shared by the API and the worker: the current version, marking a version changed, queueing its next step.

Every function that writes expects the caller to hold `changes.lock_user_writes` for the take's user.
"""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, jobs, models

# How prompts name each kind.
KIND_NAMES: dict[models.TakeKind, str] = {
    models.TakeKind.OPINION: "opinion",
    models.TakeKind.TALKING_POINT: "talking point",
}


def current_version(db: sqlalchemy.orm.Session, *, take: models.Take) -> models.TakeVersion | None:
    """The version the take page shows; every take the server stores has one."""
    return db.scalar(
        sqlalchemy.select(models.TakeVersion).where(
            models.TakeVersion.take_id == take.id, models.TakeVersion.version == take.current_version
        )
    )


def is_current(take: models.Take, version: models.TakeVersion) -> bool:
    """Whether `version` is what the live take shows now (a later save or a delete makes it stale)."""
    return take.deleted_at is None and take.current_version == version.version


def mark_changed(version: models.TakeVersion) -> None:
    """Give the version a fresh change position so phones pull it again (versions have no `updated_at`)."""
    version.change_seq = changes.next_change_seq()


def enqueue_step(db: sqlalchemy.orm.Session, *, version: models.TakeVersion, kind: models.JobKind) -> None:
    """Queue `clean_take` or `take_cards` for this version and, once it has its body, the take's search passages."""
    jobs.enqueue(db, kind=kind, user_id=version.user_id, payload={jobs.TAKE_VERSION_ID_KEY: str(version.id)})
    # Every path that gives a version its body queues `take_cards`, so this is the one place to index it.
    if kind == models.JobKind.TAKE_CARDS:
        jobs.enqueue_embed(db, user_id=version.user_id, item_kind=models.SearchItemKind.TAKE, item_id=version.take_id)
