"""All sources: newsletters, transcript chunks, the podcast show registry, ingest tokens.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def _now_column(name: str) -> sqlalchemy.Column:
    return sqlalchemy.Column(name, _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False)


def upgrade() -> None:
    """Add ingest tokens and newsletter columns, then create the show registry and transcript chunks."""
    _add_ingest_tokens()

    op.add_column("sources", sqlalchemy.Column("sender", sqlalchemy.Text(), nullable=True))
    op.add_column("sources", sqlalchemy.Column("newsletter_message_id", sqlalchemy.String(998), nullable=True))
    op.create_index(
        "uq_sources_user_id_newsletter_message_id",
        "sources",
        ["user_id", "newsletter_message_id"],
        unique=True,
    )

    op.add_column("llm_calls", sqlalchemy.Column("audio_seconds", sqlalchemy.Numeric(10, 3), nullable=True))

    op.create_table(
        "podcast_shows",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column("name_key", sqlalchemy.String(512), nullable=False, unique=True),
        sqlalchemy.Column("name", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("feed_url", sqlalchemy.String(2048), nullable=False),
        sqlalchemy.Column("itunes_id", sqlalchemy.BigInteger(), nullable=True),
        _now_column("created_at"),
        _now_column("updated_at"),
    )

    op.create_table(
        "transcript_chunks",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("chunk_index", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("provider", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("model", sqlalchemy.String(64), nullable=False),
        sqlalchemy.Column("segments", postgresql.JSONB(), nullable=False),
        _now_column("created_at"),
        sqlalchemy.UniqueConstraint("source_id", "chunk_index", name="uq_transcript_chunks_source_id_chunk_index"),
    )


def _add_ingest_tokens() -> None:
    """Existing users get a random 10-character token (md5 hex is lowercase letters and digits)."""
    op.add_column("users", sqlalchemy.Column("ingest_token", sqlalchemy.String(16), nullable=True))
    op.execute("UPDATE users SET ingest_token = substr(md5(random()::text || id::text), 1, 10)")
    op.alter_column("users", "ingest_token", nullable=False)
    op.create_unique_constraint("users_ingest_token_key", "users", ["ingest_token"])


def downgrade() -> None:
    """Undo everything `upgrade` added, in reverse."""
    op.drop_table("transcript_chunks")
    op.drop_table("podcast_shows")
    op.drop_column("llm_calls", "audio_seconds")
    op.drop_index("uq_sources_user_id_newsletter_message_id", table_name="sources")
    op.drop_column("sources", "newsletter_message_id")
    op.drop_column("sources", "sender")
    op.drop_constraint("users_ingest_token_key", "users", type_="unique")
    op.drop_column("users", "ingest_token")
