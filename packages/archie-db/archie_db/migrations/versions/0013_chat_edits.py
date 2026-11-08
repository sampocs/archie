"""Edits through chat: who made each version, card versions, and the edits Ask proposes.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def upgrade() -> None:
    """Add `origin` to every versioned row, `cards.version`, and the `card_versions` and `edit_proposals` tables.

    Existing rows take the defaults: Archie wrote every artifact and topic primer, the owner every take version, and
    every card is at version 1 with no history rows yet.
    """
    op.add_column("source_artifacts", _origin_column(default="archie"))
    op.add_column("topic_primers", _origin_column(default="archie"))
    op.add_column("topic_primers", sqlalchemy.Column("derived_from_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "topic_primers_derived_from_id_fkey", "topic_primers", "topic_primers", ["derived_from_id"], ["id"]
    )
    op.add_column("topic_primers", sqlalchemy.Column("instruction", sqlalchemy.Text(), nullable=True))
    op.add_column("take_versions", _origin_column(default="owner"))
    op.add_column("cards", sqlalchemy.Column("version", sqlalchemy.Integer(), server_default="1", nullable=False))
    _create_card_versions()
    _create_edit_proposals()


def downgrade() -> None:
    """Drop the two tables and the added columns."""
    op.drop_table("edit_proposals")
    op.drop_table("card_versions")
    op.drop_column("cards", "version")
    op.drop_column("take_versions", "origin")
    op.drop_column("topic_primers", "instruction")
    op.drop_constraint("topic_primers_derived_from_id_fkey", "topic_primers", type_="foreignkey")
    op.drop_column("topic_primers", "derived_from_id")
    op.drop_column("topic_primers", "origin")
    op.drop_column("source_artifacts", "origin")


def _origin_column(*, default: str) -> sqlalchemy.Column[str]:
    return sqlalchemy.Column("origin", sqlalchemy.String(16), server_default=default, nullable=False)


def _user_column() -> sqlalchemy.Column[int]:
    return sqlalchemy.Column(
        "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def _create_card_versions() -> None:
    op.create_table(
        "card_versions",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_column(),
        sqlalchemy.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("question", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("answer", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("origin", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("instruction", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.UniqueConstraint("card_id", "version", name="uq_card_versions_version"),
    )
    op.create_index("ix_card_versions_user_id_change_seq", "card_versions", ["user_id", "change_seq"])


def _create_edit_proposals() -> None:
    op.create_table(
        "edit_proposals",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_column(),
        sqlalchemy.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("target_kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("description", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("base_version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("before", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("after", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("applied_version", sqlalchemy.Integer(), nullable=True),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_edit_proposals_user_id_change_seq", "edit_proposals", ["user_id", "change_seq"])
    op.create_index("ix_edit_proposals_conversation_id", "edit_proposals", ["conversation_id"])
