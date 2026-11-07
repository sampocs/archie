"""Sources' `published_at`: when the item was published or sent, so Ask can find "Tuesday's newsletter".

Existing newsletters are backfilled from `created_at` (they arrived within moments of being sent); other sources
stay null until their next fetch reads a date.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add `sources.published_at` and fill it for existing newsletters."""
    op.add_column("sources", sqlalchemy.Column("published_at", sqlalchemy.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE sources SET published_at = created_at WHERE kind = 'newsletter'")


def downgrade() -> None:
    """Drop `sources.published_at`."""
    op.drop_column("sources", "published_at")
