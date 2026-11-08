"""Sources' `confirm_url`: the link that confirms a newsletter signup, set on a signup-confirmation email.

Existing sources stay null: confirmation emails already stored remain ordinary newsletters.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add `sources.confirm_url`."""
    op.add_column("sources", sqlalchemy.Column("confirm_url", sqlalchemy.String(length=2048), nullable=True))


def downgrade() -> None:
    """Drop `sources.confirm_url`."""
    op.drop_column("sources", "confirm_url")
