"""Cards' `detail`: the lines shown after the short graded answer, joined by newlines, on cards and their versions.

Existing cards and versions get "" (no detail), which shows exactly as before.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-10
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None

_TABLES = ("cards", "card_versions")


def upgrade() -> None:
    """Add `detail` to `cards` and `card_versions`."""
    for table in _TABLES:
        op.add_column(table, sqlalchemy.Column("detail", sqlalchemy.Text(), server_default="", nullable=False))


def downgrade() -> None:
    """Drop `detail` from both."""
    for table in _TABLES:
        op.drop_column(table, "detail")
