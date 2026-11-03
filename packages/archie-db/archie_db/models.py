"""SQLAlchemy ORM models for Archie's Postgres database.

The phone keeps a full copy of each user's rows, so every synced table carries a `change_seq`
from one shared Postgres sequence: a pull asks for everything past the last position it saw.
The migrations in `migrations/versions/` must match these exactly (a test compares them).
"""

from __future__ import annotations

import datetime
import uuid
from enum import StrEnum

import sqlalchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TIMESTAMP = sqlalchemy.DateTime(timezone=True)
URL = sqlalchemy.String(2048)


class Base(DeclarativeBase):
    """Declarative base whose metadata Alembic compares against."""


# SCAFFOLD: sample status enum; the real Source kind/state/intent enums land with the schema (plan Task 2).
class SourceState(StrEnum):
    """Where a source stands in the user's reading: waiting in the queue, or already consumed."""

    QUEUED = "queued"
    CONSUMED = "consumed"


# SCAFFOLD: sample table showing the column conventions; replaced by the real schema (plan Task 2).
class Source(Base):
    """One thing the user shared — a link to an article, podcast, video, or newsletter issue."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(sqlalchemy.Uuid, primary_key=True)
    url: Mapped[str] = mapped_column(URL)
    title: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    state: Mapped[str] = mapped_column(sqlalchemy.String(16), server_default=SourceState.QUEUED.value)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
