"""SQLAlchemy ORM models for Archie's Postgres database.

The phone keeps a full copy of each user's rows, so every synced table carries a `change_seq`
from one shared Postgres sequence: a pull asks for everything past the last position it saw.
The migrations in `migrations/versions/` must match these exactly (a test compares them).
"""

from __future__ import annotations

import datetime
import uuid
from enum import StrEnum
from typing import Any

import sqlalchemy
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TIMESTAMP = sqlalchemy.DateTime(timezone=True)
CHANGE_SEQ_NAME = "change_seq"


class Base(DeclarativeBase):
    """Declarative base whose metadata Alembic compares against."""


# Declared on the metadata so autogenerate and `create_all` know the sequence exists.
CHANGE_SEQ = sqlalchemy.Sequence(CHANGE_SEQ_NAME, metadata=Base.metadata)


class SourceKind(StrEnum):
    """What a source points at."""

    LINK = "link"


class SourceState(StrEnum):
    """Where a source stands in the user's reading and in processing."""

    QUEUED = "queued"
    INBOX = "inbox"
    BRIEFED = "briefed"
    CONSUMED = "consumed"
    PROCESSING = "processing"
    FAILED = "failed"


class SourceIntent(StrEnum):
    """Why the user captured a source: already read it, or saving it for later."""

    FINISHED = "finished"
    QUEUE = "queue"


class JobKind(StrEnum):
    """The kinds of background work the worker knows how to run."""

    FETCH_TITLE = "fetch_title"


class JobStatus(StrEnum):
    """Where a job is in its lifecycle."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ActionResult(StrEnum):
    """How the server answered a phone's action."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class User(Base):
    """A person who signed in with Apple; `is_whitelisted` means the owner's API keys pay for their processing."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    apple_sub: Mapped[str] = mapped_column(sqlalchemy.String(255), unique=True)
    email: Mapped[str | None] = mapped_column(sqlalchemy.String(320))
    is_whitelisted: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class Session(Base):
    """A signed-in device; only the hash of its API key is stored, so a database leak reveals no usable key."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    key_hash: Mapped[str] = mapped_column(sqlalchemy.String(64), unique=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    last_used_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)


class Source(Base):
    """One captured item. The id is generated on the phone so an offline-created row keeps its identity."""

    __tablename__ = "sources"
    __table_args__ = (sqlalchemy.Index("ix_sources_user_id_change_seq", "user_id", "change_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(sqlalchemy.String(2048))
    title: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    state: Mapped[str] = mapped_column(sqlalchemy.String(16))
    intent: Mapped[str] = mapped_column(sqlalchemy.String(16))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    # Always assigned via changes.next_change_seq() under changes.lock_user_writes(); see changes.py for why.
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class AppliedAction(Base):
    """A phone action the server has already answered, so a retried upload is recognized and not applied twice."""

    __tablename__ = "applied_actions"

    action_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    applied_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    result: Mapped[str] = mapped_column(sqlalchemy.String(16))
    reason: Mapped[str | None] = mapped_column(sqlalchemy.Text)


class Job(Base):
    """One unit of background work for the worker, enqueued in the same transaction as the change that needs it."""

    __tablename__ = "jobs"
    __table_args__ = (sqlalchemy.Index("ix_jobs_status_next_run_at", "status", "next_run_at"),)

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(sqlalchemy.String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(sqlalchemy.String(16))
    attempts: Mapped[int] = mapped_column(sqlalchemy.Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(sqlalchemy.Integer, server_default="3")
    next_run_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    last_error: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    started_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
