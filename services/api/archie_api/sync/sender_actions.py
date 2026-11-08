"""The `set_sender_status` action: allow or block a newsletter sender, or un-block one.

The caller holds the user's write lock and every check runs before the first write (see `actions.apply_actions`).
"""

from __future__ import annotations

import uuid
from typing import Self

import pydantic
from archie_db import models, senders
from sqlalchemy import orm

from archie_api.sync import rows

NO_SENDER = "sender not found"
_NOT_NEWSLETTER = "source is not a newsletter"
_NO_IDENTIFIERS = "source has no sender to record"


class _SetSenderStatusPayload(pydantic.BaseModel):
    status: models.SenderStatus
    source_id: uuid.UUID | None = None
    sender_id: uuid.UUID | None = None

    @pydantic.model_validator(mode="after")
    def _exactly_one_id(self) -> Self:
        if (self.source_id is None) == (self.sender_id is None):
            raise ValueError("exactly one of source_id and sender_id")
        return self


def set_sender_status(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Record a decision about the sender of one of the user's newsletters (`source_id`), or set a known sender's
    status (`sender_id`, for Unblock). Pending newsletters are then released or deleted; repeating it changes nothing.
    """
    parsed = rows.parse(_SetSenderStatusPayload, payload)
    if parsed is None:
        return rows.MALFORMED

    if parsed.sender_id is not None:
        return _set_known_sender(db, user=user, sender_id=parsed.sender_id, status=parsed.status)
    assert parsed.source_id is not None
    return _record_source_sender(db, user=user, source_id=parsed.source_id, status=parsed.status)


def _set_known_sender(
    db: orm.Session, *, user: models.User, sender_id: uuid.UUID, status: models.SenderStatus
) -> str | None:
    sender = db.get(models.NewsletterSender, sender_id)
    if sender is None or sender.user_id != user.id:
        return NO_SENDER

    senders.set_status(db, sender=sender, status=status)
    return None


def _record_source_sender(
    db: orm.Session, *, user: models.User, source_id: uuid.UUID, status: models.SenderStatus
) -> str | None:
    # Live or not: an action queued just before the source was deleted must still work.
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user.id:
        return rows.NO_SOURCE
    if source.kind != models.SourceKind.NEWSLETTER:
        return _NOT_NEWSLETTER

    identifiers = senders.identifiers_for(address=source.sender_address, list_id=source.list_id, name=source.sender)
    if not identifiers:
        return _NO_IDENTIFIERS

    senders.record(
        db, user_id=user.id, identifiers=identifiers, status=status, label=source.sender or source.sender_address or ""
    )
    return None
