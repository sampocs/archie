"""Review: card scheduling state and new origins, the review log, card preferences, and cards off per source.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)
_ONE_ORIGIN = "num_nonnulls(source_id, topic_primer_id, brief_id) = 1"


def upgrade() -> None:
    """Add the cards' FSRS state and origins, `sources.cards_off`, and the `reviews` and `card_preferences` tables."""
    _extend_cards()
    op.add_column(
        "sources",
        sqlalchemy.Column("cards_off", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False),
    )
    _create_reviews()
    _create_card_preferences()


def _extend_cards() -> None:
    op.alter_column("cards", "source_id", nullable=True)
    op.alter_column("cards", "artifact_id", nullable=True)
    op.add_column("cards", sqlalchemy.Column("topic_primer_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "cards_topic_primer_id_fkey", "cards", "topic_primers", ["topic_primer_id"], ["id"], ondelete="CASCADE"
    )
    op.add_column("cards", sqlalchemy.Column("brief_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("cards_brief_id_fkey", "cards", "briefs", ["brief_id"], ["id"], ondelete="CASCADE")
    op.add_column("cards", sqlalchemy.Column("fsrs_state", sqlalchemy.String(16), server_default="new", nullable=False))
    op.add_column("cards", sqlalchemy.Column("stability", sqlalchemy.Double(), nullable=True))
    op.add_column("cards", sqlalchemy.Column("difficulty", sqlalchemy.Double(), nullable=True))
    op.add_column("cards", sqlalchemy.Column("due_at", _TIMESTAMP, nullable=True))
    op.add_column("cards", sqlalchemy.Column("last_review_at", _TIMESTAMP, nullable=True))
    op.add_column("cards", sqlalchemy.Column("reps", sqlalchemy.Integer(), server_default="0", nullable=False))
    op.add_column("cards", sqlalchemy.Column("lapses", sqlalchemy.Integer(), server_default="0", nullable=False))
    op.add_column("cards", sqlalchemy.Column("expires_at", _TIMESTAMP, nullable=True))
    op.create_check_constraint("ck_cards_one_origin", "cards", _ONE_ORIGIN)


def _create_reviews() -> None:
    op.create_table(
        "reviews",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("grade", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("graded_by", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("answer", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("missing", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("was_due", sqlalchemy.Boolean(), nullable=False),
        sqlalchemy.Column("reviewed_at", _TIMESTAMP, nullable=False),
        sqlalchemy.Column("state_before", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("state_after", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("replaces_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
    )
    op.create_index("ix_reviews_card_id_reviewed_at", "reviews", ["card_id", "reviewed_at"])


def _create_card_preferences() -> None:
    op.create_table(
        "card_preferences",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("note", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
    )
    op.create_index("ix_card_preferences_user_id_created_at", "card_preferences", ["user_id", "created_at"])


def downgrade() -> None:
    """Undo everything `upgrade` added; cards without a source (foundation cards of topic primers, quiz cards) go."""
    op.drop_table("card_preferences")
    op.drop_table("reviews")
    op.drop_column("sources", "cards_off")

    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.execute("DELETE FROM cards WHERE source_id IS NULL OR artifact_id IS NULL")
    for column in ("expires_at", "lapses", "reps", "last_review_at", "due_at", "difficulty", "stability", "fsrs_state"):
        op.drop_column("cards", column)
    op.drop_constraint("cards_brief_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "brief_id")
    op.drop_constraint("cards_topic_primer_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "topic_primer_id")
    op.alter_column("cards", "artifact_id", nullable=False)
    op.alter_column("cards", "source_id", nullable=False)
