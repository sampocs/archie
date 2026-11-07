"""Search and Ask: search passages (chunks), saved chats and their messages, and chat cards as a fifth card origin.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06
"""

from __future__ import annotations

import uuid

import sqlalchemy
from alembic import op
from archie_db import vector
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)
_FOUR_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id) = 1"
_FIVE_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id, conversation_id) = 1"
_EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    """Create `chunks`, `conversations` and `messages`, add the cards' chat columns, and widen the one-origin CHECK."""
    _create_chunks()
    _create_conversations()
    _create_messages()

    op.add_column("cards", sqlalchemy.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "cards_conversation_id_fkey", "cards", "conversations", ["conversation_id"], ["id"], ondelete="CASCADE"
    )
    op.add_column("cards", sqlalchemy.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("cards_message_id_fkey", "cards", "messages", ["message_id"], ["id"], ondelete="CASCADE")

    # Existing cards have exactly one of the first four origins, so they satisfy the wider check as they are.
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.create_check_constraint("ck_cards_one_origin", "cards", _FIVE_ORIGINS)


def _owner_column(name: str, table: str) -> sqlalchemy.Column[uuid.UUID]:
    return sqlalchemy.Column(
        name, postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=True
    )


def _create_chunks() -> None:
    op.create_table(
        "chunks",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("owner_kind", sqlalchemy.String(16), nullable=False),
        _owner_column("source_id", "sources"),
        _owner_column("topic_primer_id", "topic_primers"),
        _owner_column("take_id", "takes"),
        sqlalchemy.Column("chunk_index", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("text", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("start_seconds", sqlalchemy.Double(), nullable=True),
        sqlalchemy.Column("embedding", vector.Vector(_EMBEDDING_DIMENSIONS), nullable=True),
        sqlalchemy.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sqlalchemy.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.CheckConstraint("num_nonnulls(source_id, topic_primer_id, take_id) = 1", name="ck_chunks_one_owner"),
    )
    for name, column in (
        ("uq_chunks_source", "source_id"),
        ("uq_chunks_topic_primer", "topic_primer_id"),
        ("uq_chunks_take", "take_id"),
    ):
        op.create_index(
            name,
            "chunks",
            [column, "owner_kind", "chunk_index"],
            unique=True,
            postgresql_where=sqlalchemy.text(f"{column} IS NOT NULL"),
        )
    op.create_index("ix_chunks_user_id", "chunks", ["user_id"])
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")


def _create_conversations() -> None:
    op.create_table(
        "conversations",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("title", sqlalchemy.String(200), nullable=False),
        sqlalchemy.Column("about_kind", sqlalchemy.String(16), nullable=True),
        sqlalchemy.Column(
            "about_source_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column(
            "about_topic_primer_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("topic_primers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column(
            "about_take_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("takes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.CheckConstraint(
            "num_nonnulls(about_source_id, about_topic_primer_id, about_take_id) <= 1",
            name="ck_conversations_one_about",
        ),
    )
    op.create_index("ix_conversations_user_id_change_seq", "conversations", ["user_id", "change_seq"])


def _create_messages() -> None:
    op.create_table(
        "messages",
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
        sqlalchemy.Column("role", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("text", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("segments", postgresql.JSONB(), nullable=True),
        sqlalchemy.Column("web_search", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_messages_user_id_change_seq", "messages", ["user_id", "change_seq"])
    op.create_index("ix_messages_conversation_id_created_at", "messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    """Undo `upgrade`; chat cards go first so the four-origin CHECK holds again, then the three tables."""
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.execute("DELETE FROM cards WHERE conversation_id IS NOT NULL")
    op.drop_constraint("cards_message_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "message_id")
    op.drop_constraint("cards_conversation_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "conversation_id")
    op.create_check_constraint("ck_cards_one_origin", "cards", _FOUR_ORIGINS)

    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("chunks")
