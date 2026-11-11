"""Books: a source's `author`, and a card's `available_at` (not reviewable before it).

Both are nullable with no backfill: existing sources have no author and existing cards are reviewable at once.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-10
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add `sources.author` and `cards.available_at`."""
    op.add_column("sources", sqlalchemy.Column("author", sqlalchemy.String(length=300), nullable=True))
    op.add_column("cards", sqlalchemy.Column("available_at", sqlalchemy.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop both."""
    op.drop_column("cards", "available_at")
    op.drop_column("sources", "author")
