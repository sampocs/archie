"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def upgrade() -> None:
    """Create the initial tables."""
    # SCAFFOLD: sample table matching the sample model; replaced by the real schema (plan Task 2).
    op.create_table(
        "sources",
        sqlalchemy.Column("id", sqlalchemy.Uuid(), primary_key=True),
        sqlalchemy.Column("url", sqlalchemy.String(2048), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("state", sqlalchemy.String(16), server_default="queued", nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
    )


def downgrade() -> None:
    """Drop the initial tables."""
    op.drop_table("sources")
