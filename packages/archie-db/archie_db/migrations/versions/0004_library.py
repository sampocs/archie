"""Library: topics, topic primers, and the source columns for filing, artwork, the queue and reading state.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def _now_column(name: str) -> sqlalchemy.Column:
    return sqlalchemy.Column(name, _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False)


def _user_id_column() -> sqlalchemy.Column:
    return sqlalchemy.Column(
        "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    """Add the topic tables and the new source columns, then backfill queue positions and read markers."""
    op.add_column("users", sqlalchemy.Column("topics_chosen_at", _TIMESTAMP, nullable=True))
    _create_topics()
    _create_topic_primers()
    _add_source_columns()
    _backfill_sources()


def _create_topics() -> None:
    op.create_table(
        "topics",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id_column(),
        sqlalchemy.Column("domain", sqlalchemy.String(32), nullable=False),
        sqlalchemy.Column("name", sqlalchemy.String(200), nullable=False),
        sqlalchemy.Column("origin", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("removed_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column(
            "merged_into_id", postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topics.id"), nullable=True
        ),
        _now_column("created_at"),
        _now_column("updated_at"),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_topics_user_id_change_seq", "topics", ["user_id", "change_seq"])

    # Live and removed topics keep their names unique; a merged topic gives its name up.
    op.create_index(
        "uq_topics_user_id_lower_name",
        "topics",
        ["user_id", sqlalchemy.text("lower(name)")],
        unique=True,
        postgresql_where=sqlalchemy.text("merged_into_id IS NULL"),
    )


def _create_topic_primers() -> None:
    op.create_table(
        "topic_primers",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id_column(),
        sqlalchemy.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("is_current", sqlalchemy.Boolean(), nullable=False),
        sqlalchemy.Column("content", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("model", sqlalchemy.String(64), nullable=True),
        sqlalchemy.Column("prompt_version", sqlalchemy.String(32), nullable=True),
        sqlalchemy.Column("opened_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("snoozed_until", _TIMESTAMP, nullable=True),
        _now_column("created_at"),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.UniqueConstraint("topic_id", "version", name="uq_topic_primers_version"),
    )
    op.create_index(
        "uq_topic_primers_current",
        "topic_primers",
        ["topic_id"],
        unique=True,
        postgresql_where=sqlalchemy.text("is_current"),
    )
    op.create_index("ix_topic_primers_user_id_change_seq", "topic_primers", ["user_id", "change_seq"])


def _add_source_columns() -> None:
    op.add_column("sources", sqlalchemy.Column("domain", sqlalchemy.String(32), nullable=True))
    op.add_column("sources", sqlalchemy.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("sources_topic_id_fkey", "sources", "topics", ["topic_id"], ["id"], ondelete="SET NULL")
    op.add_column("sources", sqlalchemy.Column("image_url", sqlalchemy.String(2048), nullable=True))
    op.add_column("sources", sqlalchemy.Column("queue_position", sqlalchemy.Double(), nullable=True))
    op.add_column("sources", sqlalchemy.Column("read_at", _TIMESTAMP, nullable=True))
    op.add_column("sources", sqlalchemy.Column("snoozed_until", _TIMESTAMP, nullable=True))
    op.add_column("sources", sqlalchemy.Column("primer_opened_at", _TIMESTAMP, nullable=True))
    op.add_column("sources", sqlalchemy.Column("newsletter_kind", sqlalchemy.String(16), nullable=True))
    op.add_column("sources", sqlalchemy.Column("episode_guid", sqlalchemy.String(1024), nullable=True))


def _backfill_sources() -> None:
    """Order today's queue oldest first, and treat every existing primer as opened and every newsletter as read.

    The phone pulls only rows whose position moved, so every source gets a new `change_seq`.
    """
    op.execute(
        "UPDATE sources SET queue_position = ranked.position FROM ("
        " SELECT id, -row_number() OVER (PARTITION BY user_id ORDER BY created_at, change_seq) AS position"
        " FROM sources WHERE state = 'queued' AND deleted_at IS NULL"
        ") AS ranked WHERE sources.id = ranked.id"
    )
    op.execute(
        "UPDATE sources SET primer_opened_at = now(),"
        " read_at = CASE WHEN kind = 'newsletter' THEN now() END,"
        " change_seq = nextval('change_seq')"
    )


def downgrade() -> None:
    """Undo everything `upgrade` added, in reverse."""
    for column in (
        "episode_guid",
        "newsletter_kind",
        "primer_opened_at",
        "snoozed_until",
        "read_at",
        "queue_position",
        "image_url",
    ):
        op.drop_column("sources", column)
    op.drop_constraint("sources_topic_id_fkey", "sources", type_="foreignkey")
    op.drop_column("sources", "topic_id")
    op.drop_column("sources", "domain")

    op.drop_table("topic_primers")
    op.drop_table("topics")
    op.drop_column("users", "topics_chosen_at")
