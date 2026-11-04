"""Capture pipeline: processing columns on sources, captures, artifacts, cards, llm_calls.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def _now_column(name: str) -> sqlalchemy.Column:
    return sqlalchemy.Column(name, _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False)


def _user_id_column() -> sqlalchemy.Column:
    return sqlalchemy.Column(
        "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def _source_id_column() -> sqlalchemy.Column:
    return sqlalchemy.Column(
        "source_id",
        postgresql.UUID(as_uuid=True),
        sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    """Extend `sources` (backfilling M1 rows) and create the pipeline tables."""
    _upgrade_sources()
    _create_pipeline_tables()


def _upgrade_sources() -> None:
    op.add_column(
        "sources",
        sqlalchemy.Column("processing", sqlalchemy.String(16), server_default="pending", nullable=False),
    )
    op.add_column("sources", sqlalchemy.Column("processing_error", sqlalchemy.Text(), nullable=True))
    op.add_column("sources", sqlalchemy.Column("reaction", sqlalchemy.String(16), nullable=True))
    op.add_column("sources", sqlalchemy.Column("note", sqlalchemy.Text(), nullable=True))
    op.add_column(
        "sources", sqlalchemy.Column("prep_me", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False)
    )
    op.add_column("sources", sqlalchemy.Column("normalized_url", sqlalchemy.String(2048), nullable=True))
    op.add_column(
        "sources",
        sqlalchemy.Column(
            "merged_into_id", postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id"), nullable=True
        ),
    )

    # Existing rows are M1 `link` captures the pipeline can't process; their url was never normalized. A fresh
    # change_seq makes phones that already pulled them re-pull, so they replace their local default of 'pending'.
    op.execute("UPDATE sources SET normalized_url = url")
    op.execute("UPDATE sources SET processing = 'unsupported', change_seq = nextval('change_seq')")
    op.alter_column("sources", "normalized_url", nullable=False)
    op.create_index("ix_sources_user_id_normalized_url", "sources", ["user_id", "normalized_url"])


def _create_pipeline_tables() -> None:
    op.create_table(
        "source_captures",
        sqlalchemy.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("text", sqlalchemy.Text(), nullable=False),
        _now_column("created_at"),
    )

    op.create_table(
        "source_artifacts",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id_column(),
        _source_id_column(),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("content", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("is_current", sqlalchemy.Boolean(), nullable=False),
        sqlalchemy.Column("model", sqlalchemy.String(64), nullable=True),
        sqlalchemy.Column("prompt_version", sqlalchemy.String(32), nullable=True),
        sqlalchemy.Column(
            "derived_from_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("source_artifacts.id"),
            nullable=True,
        ),
        sqlalchemy.Column("instruction", sqlalchemy.Text(), nullable=True),
        _now_column("created_at"),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.UniqueConstraint("source_id", "kind", "version", name="uq_source_artifacts_version"),
    )
    op.create_index(
        "uq_source_artifacts_current",
        "source_artifacts",
        ["source_id", "kind"],
        unique=True,
        postgresql_where=sqlalchemy.text("is_current"),
    )
    op.create_index("ix_source_artifacts_user_id_change_seq", "source_artifacts", ["user_id", "change_seq"])

    op.create_table(
        "cards",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id_column(),
        _source_id_column(),
        sqlalchemy.Column(
            "artifact_id", postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("source_artifacts.id"), nullable=False
        ),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("question", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("answer", sqlalchemy.Text(), nullable=False),
        _now_column("created_at"),
        _now_column("updated_at"),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_cards_user_id_change_seq", "cards", ["user_id", "change_seq"])

    op.create_table(
        "llm_calls",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        _user_id_column(),
        sqlalchemy.Column(
            "source_id", postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="SET NULL")
        ),
        sqlalchemy.Column("job_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("jobs.id", ondelete="SET NULL")),
        sqlalchemy.Column("step", sqlalchemy.String(32), nullable=False),
        sqlalchemy.Column("provider", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("model", sqlalchemy.String(64), nullable=False),
        sqlalchemy.Column("input_tokens", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("output_tokens", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("cost_usd", sqlalchemy.Numeric(12, 6), nullable=False),
        sqlalchemy.Column("stop_reason", sqlalchemy.String(32), nullable=True),
        _now_column("created_at"),
    )
    op.create_index("ix_llm_calls_user_id_created_at", "llm_calls", ["user_id", "created_at"])


def downgrade() -> None:
    """Drop the pipeline tables and the columns added to `sources`."""
    op.drop_table("llm_calls")
    op.drop_table("cards")
    op.drop_table("source_artifacts")
    op.drop_table("source_captures")

    op.drop_index("ix_sources_user_id_normalized_url", table_name="sources")
    for column in (
        "merged_into_id",
        "normalized_url",
        "prep_me",
        "note",
        "reaction",
        "processing_error",
        "processing",
    ):
        op.drop_column("sources", column)
