"""SQLAlchemy engines for the Archie Postgres database."""

from __future__ import annotations

import sqlalchemy

_DRIVER_SCHEME = "postgresql+psycopg://"
_BARE_SCHEMES = ("postgresql://", "postgres://")


def normalize_url(database_url: str) -> str:
    """Return `database_url` using the psycopg 3 driver (Railway hands out bare `postgresql://` URLs)."""
    if database_url.startswith(_DRIVER_SCHEME):
        return database_url
    for scheme in _BARE_SCHEMES:
        if database_url.startswith(scheme):
            return _DRIVER_SCHEME + database_url.removeprefix(scheme)
    raise ValueError("DATABASE_URL must be a Postgres URL (postgresql://...)")


def engine_for(database_url: str) -> sqlalchemy.Engine:
    """A pooled engine for `database_url`, checking connections before use."""
    return sqlalchemy.create_engine(normalize_url(database_url), pool_pre_ping=True)
