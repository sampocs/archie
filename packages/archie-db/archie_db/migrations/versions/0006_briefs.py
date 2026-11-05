"""Briefs: the rolling newsletter brief, one open per user.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def upgrade() -> None:
    """Create `briefs` with its pull index and the one-open-brief-per-user index."""
    op.create_table(
        "briefs",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("content", postgresql.JSONB(), nullable=True),
        sqlalchemy.Column(
            "source_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sqlalchemy.text("'{}'"),
            nullable=False,
        ),
        sqlalchemy.Column("since", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("version", sqlalchemy.Integer(), server_default="0", nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("done_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_briefs_user_id_change_seq", "briefs", ["user_id", "change_seq"])
    op.create_index(
        "uq_briefs_user_id_open",
        "briefs",
        ["user_id"],
        unique=True,
        postgresql_where=sqlalchemy.text("status = 'open'"),
    )


def downgrade() -> None:
    """Drop `briefs` and its indexes."""
    op.drop_table("briefs")
