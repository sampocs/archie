"""Session keys: random bearer tokens, stored only as hashes.

The caller owns the transaction: these functions change the session but never commit.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

import sqlalchemy
from archie_db import models
from sqlalchemy import orm

SESSION_TOUCH_INTERVAL = datetime.timedelta(hours=1)
_KEY_BYTES = 32


def create_session(db: orm.Session, *, user_id: int) -> str:
    """Start a session for `user_id` and return its raw key, which is never stored."""
    raw_key = secrets.token_urlsafe(_KEY_BYTES)
    db.add(models.Session(user_id=user_id, key_hash=_hash_key(raw_key)))
    db.flush()
    return raw_key


def resolve_session(db: orm.Session, *, raw_key: str) -> models.User | None:
    """The user behind a live session key, or `None` if it is unknown or revoked."""
    row = db.execute(
        sqlalchemy.select(models.Session, models.User)
        .join(models.User, models.User.id == models.Session.user_id)
        .where(models.Session.key_hash == _hash_key(raw_key), models.Session.revoked_at.is_(None))
    ).first()
    if row is None:
        return None

    session, user = row

    # Throttled so an ordinary read isn't a database write on every request. Left dirty, not flushed, so
    # the caller can tell a touch happened (`db.dirty`) and commit only then.
    now = datetime.datetime.now(tz=datetime.UTC)
    if now - session.last_used_at > SESSION_TOUCH_INTERVAL:
        session.last_used_at = now
    return user


def revoke_session(db: orm.Session, *, raw_key: str) -> None:
    """Revoke the session; revoking an unknown or already-revoked key does nothing."""
    db.execute(
        sqlalchemy.update(models.Session)
        .where(models.Session.key_hash == _hash_key(raw_key), models.Session.revoked_at.is_(None))
        .values(revoked_at=sqlalchemy.func.now())
    )


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
