"""FastAPI dependencies: the database session and the signed-in user."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Annotated

import fastapi
import sqlalchemy
from archie_db import models, session
from archie_shared import config
from sqlalchemy import orm

from archie_api.auth import sessions

_BEARER_SCHEME = "bearer"

# Built on first use, not at import, so tests can point each live stack at its own database.
_engine: sqlalchemy.Engine | None = None
_engine_lock = threading.Lock()


def get_engine() -> sqlalchemy.Engine:
    """The process-wide engine for `DATABASE_URL`, created on first use."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = session.engine_for(config.get_settings().require_database_url())
        return _engine


def reset_engine() -> None:
    """Dispose the engine so the next request builds one from the current environment."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def get_db() -> Iterator[orm.Session]:
    """A database session for one request; routes commit explicitly."""
    with orm.Session(get_engine()) as db:
        yield db


def current_session_key(authorization: Annotated[str | None, fastapi.Header()] = None) -> str:
    """The raw session key from `Authorization: Bearer <key>`, or 401."""
    if authorization is None:
        raise _unauthorized()

    # Auth schemes are case-insensitive (RFC 7235), so `bearer` is as valid as `Bearer`.
    scheme, _, raw_key = authorization.strip().partition(" ")
    if scheme.lower() != _BEARER_SCHEME or not raw_key.strip():
        raise _unauthorized()
    return raw_key.strip()


def current_user(
    db: Annotated[orm.Session, fastapi.Depends(get_db)],
    raw_key: Annotated[str, fastapi.Depends(current_session_key)],
) -> models.User:
    """The user the session key belongs to, or 401 when it is unknown or revoked."""
    user = sessions.resolve_session(db, raw_key=raw_key)
    if user is None:
        raise _unauthorized()

    # Resolving may refresh `last_used_at`; commit only then, so that write lands even on a read-only route
    # without every request paying a commit and the reload of the expired `user` that follows.
    if db.dirty:
        db.commit()
    return user


def _unauthorized() -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing session key",
        headers={"WWW-Authenticate": "Bearer"},
    )
