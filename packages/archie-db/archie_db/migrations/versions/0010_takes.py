"""Takes: the owner's own opinions and talking points, their dated versions, and take cards as a fourth card origin.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)
_THREE_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id) = 1"
_FOUR_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id) = 1"


def upgrade() -> None:
    """Create `takes` and `take_versions`, add the cards' take columns, and widen the one-origin CHECK."""
    _create_takes()
    _create_take_versions()

    op.add_column("cards", sqlalchemy.Column("take_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("cards_take_id_fkey", "cards", "takes", ["take_id"], ["id"], ondelete="CASCADE")
    op.add_column("cards", sqlalchemy.Column("take_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "cards_take_version_id_fkey", "cards", "take_versions", ["take_version_id"], ["id"], ondelete="CASCADE"
    )

    # Existing cards all have exactly one of the first three origins, so they satisfy the wider check as they are.
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.create_check_constraint("ck_cards_one_origin", "cards", _FOUR_ORIGINS)


def _create_takes() -> None:
    op.create_table(
        "takes",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.String(200), nullable=False),
        sqlalchemy.Column("current_version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_takes_user_id_change_seq", "takes", ["user_id", "change_seq"])


def _create_take_versions() -> None:
    op.create_table(
        "take_versions",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column(
            "take_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("body", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("raw_body", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("cleaned", sqlalchemy.Boolean(), nullable=False),
        sqlalchemy.Column("clean_failed", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.UniqueConstraint("take_id", "version", name="uq_take_versions_version"),
    )
    op.create_index("ix_take_versions_user_id_change_seq", "take_versions", ["user_id", "change_seq"])


def downgrade() -> None:
    """Undo `upgrade`; take cards go first so the three-origin CHECK holds again, then takes and their versions."""
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.execute("DELETE FROM cards WHERE take_id IS NOT NULL")
    op.drop_constraint("cards_take_version_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "take_version_id")
    op.drop_constraint("cards_take_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "take_id")
    op.create_check_constraint("ck_cards_one_origin", "cards", _THREE_ORIGINS)

    op.drop_table("take_versions")
    op.drop_table("takes")
