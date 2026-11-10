"""Cards from a chat: the chat a `chat` source was saved from, and the card sets Ask proposes.

Existing sources keep a null `chat_conversation_id`.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-09
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)
_CHAT_FOREIGN_KEY = "sources_chat_conversation_id_fkey"


def upgrade() -> None:
    """Add `sources.chat_conversation_id` (one item per chat) and the `card_set_proposals` table."""
    op.add_column("sources", sqlalchemy.Column("chat_conversation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        _CHAT_FOREIGN_KEY, "sources", "conversations", ["chat_conversation_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(
        "uq_sources_chat_conversation_id",
        "sources",
        ["chat_conversation_id"],
        unique=True,
        postgresql_where=sqlalchemy.text("chat_conversation_id IS NOT NULL"),
    )
    _create_card_set_proposals()


def downgrade() -> None:
    """Drop the table, the index and the column."""
    op.drop_table("card_set_proposals")
    op.drop_index("uq_sources_chat_conversation_id", table_name="sources")
    op.drop_constraint(_CHAT_FOREIGN_KEY, "sources", type_="foreignkey")
    op.drop_column("sources", "chat_conversation_id")


def _create_card_set_proposals() -> None:
    op.create_table(
        "card_set_proposals",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
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
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("cheat_sheet", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("cards", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column(
            "saved_source_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column("kept", postgresql.JSONB(), nullable=True),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_card_set_proposals_user_id_change_seq", "card_set_proposals", ["user_id", "change_seq"])
    op.create_index("ix_card_set_proposals_conversation_id", "card_set_proposals", ["conversation_id"])
