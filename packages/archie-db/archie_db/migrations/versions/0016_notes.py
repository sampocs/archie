"""Notes: Bear id, markdown, tags, edit and refresh timestamps on `sources`, and one Bear id per user.

Existing sources keep null note columns (and `refreshed_from_queue` false).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the note columns and the per-user Bear id index."""
    op.add_column("sources", sqlalchemy.Column("bear_id", sqlalchemy.String(length=64), nullable=True))
    op.add_column("sources", sqlalchemy.Column("note_markdown", sqlalchemy.Text(), nullable=True))
    op.add_column("sources", sqlalchemy.Column("note_tags", postgresql.ARRAY(sqlalchemy.Text()), nullable=True))
    op.add_column("sources", sqlalchemy.Column("note_edited_at", sqlalchemy.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sqlalchemy.Column("refreshed_at", sqlalchemy.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sources",
        sqlalchemy.Column(
            "refreshed_from_queue", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False
        ),
    )
    op.add_column("sources", sqlalchemy.Column("refresh_skipped_at", sqlalchemy.DateTime(timezone=True), nullable=True))
    op.create_index("uq_sources_user_id_bear_id", "sources", ["user_id", "bear_id"], unique=True)


def downgrade() -> None:
    """Drop the index and the note columns."""
    op.drop_index("uq_sources_user_id_bear_id", table_name="sources")
    for column in (
        "refresh_skipped_at",
        "refreshed_from_queue",
        "refreshed_at",
        "note_edited_at",
        "note_tags",
        "note_markdown",
        "bear_id",
    ):
        op.drop_column("sources", column)
