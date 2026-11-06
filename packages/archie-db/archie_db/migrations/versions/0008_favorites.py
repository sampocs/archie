"""Favorites: when a source was starred.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add `sources.favorited_at` (null = not starred)."""
    op.add_column("sources", sqlalchemy.Column("favorited_at", sqlalchemy.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop `sources.favorited_at`; stars are lost."""
    op.drop_column("sources", "favorited_at")
