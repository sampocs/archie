"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def _now_column(name: str) -> sqlalchemy.Column:
    return sqlalchemy.Column(name, _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False)


def _user_id_column() -> sqlalchemy.Column:
    return sqlalchemy.Column(
        "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    """Create the extension, the change-position sequence, and the tables."""
    # pgvector is not used yet; enabling it now spares milestone 6 a migration on a populated database.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SEQUENCE change_seq")

    op.create_table(
        "users",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column("apple_sub", sqlalchemy.String(255), nullable=False, unique=True),
        sqlalchemy.Column("email", sqlalchemy.String(320), nullable=True),
        sqlalchemy.Column("is_whitelisted", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False),
        _now_column("created_at"),
    )

    op.create_table(
        "sessions",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        _user_id_column(),
        sqlalchemy.Column("key_hash", sqlalchemy.String(64), nullable=False),
        _now_column("created_at"),
        _now_column("last_used_at"),
        sqlalchemy.Column("revoked_at", _TIMESTAMP, nullable=True),
    )
    op.create_index("ix_sessions_key_hash", "sessions", ["key_hash"], unique=True)

    op.create_table(
        "sources",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id_column(),
        sqlalchemy.Column("url", sqlalchemy.String(2048), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("state", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("intent", sqlalchemy.String(16), nullable=False),
        _now_column("created_at"),
        _now_column("updated_at"),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_sources_user_id_change_seq", "sources", ["user_id", "change_seq"])

    op.create_table(
        "applied_actions",
        sqlalchemy.Column("action_id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id_column(),
        _now_column("applied_at"),
        sqlalchemy.Column("result", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("reason", sqlalchemy.Text(), nullable=True),
    )

    op.create_table(
        "jobs",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column("kind", sqlalchemy.String(32), nullable=False),
        sqlalchemy.Column("payload", postgresql.JSONB(), nullable=False),
        _user_id_column(),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("attempts", sqlalchemy.Integer(), server_default="0", nullable=False),
        sqlalchemy.Column("max_attempts", sqlalchemy.Integer(), server_default="3", nullable=False),
        _now_column("next_run_at"),
        sqlalchemy.Column("last_error", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("started_at", _TIMESTAMP, nullable=True),
        _now_column("created_at"),
    )
    op.create_index("ix_jobs_status_next_run_at", "jobs", ["status", "next_run_at"])


def downgrade() -> None:
    """Drop the tables and the sequence; the vector extension stays."""
    op.drop_table("jobs")
    op.drop_table("applied_actions")
    op.drop_table("sources")
    op.drop_table("sessions")
    op.drop_table("users")
    op.execute("DROP SEQUENCE change_seq")
