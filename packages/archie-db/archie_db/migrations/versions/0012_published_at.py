"""Sources' `published_at`: when an article or episode came out, beside `created_at` (when the owner saved it).

Newsletters keep it null: they are sent and saved the same day, so `created_at` already says when. Existing sources
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
    """Add `sources.published_at`."""
    op.add_column("sources", sqlalchemy.Column("published_at", sqlalchemy.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop `sources.published_at`."""
    op.drop_column("sources", "published_at")
