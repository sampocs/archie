"""Collections: just-for-fun scrapbooks and their saved posts, kept apart from sources.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def upgrade() -> None:
    """Create `collections` and `collection_items` with their pull indexes."""
    op.create_table(
        "collections",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("name", sqlalchemy.String(200), nullable=False),
        sqlalchemy.Column("position", sqlalchemy.Double(), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_collections_user_id_change_seq", "collections", ["user_id", "change_seq"])

    op.create_table(
        "collection_items",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("url", sqlalchemy.String(2048), nullable=False),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("author", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("image_url", sqlalchemy.String(2048), nullable=True),
        sqlalchemy.Column("duration_seconds", sqlalchemy.Integer(), nullable=True),
        sqlalchemy.Column("note", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("metadata_status", sqlalchemy.String(16), server_default="pending", nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_collection_items_user_id_change_seq", "collection_items", ["user_id", "change_seq"])
    op.create_index("ix_collection_items_collection_id", "collection_items", ["collection_id"])


def downgrade() -> None:
    """Drop both tables (items first, for the foreign key); collections are lost."""
    op.drop_table("collection_items")
    op.drop_table("collections")
