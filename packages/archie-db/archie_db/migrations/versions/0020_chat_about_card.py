"""A chat can be about a review card: `conversations.about_card_id`, counted in the one-about check.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None

CHECK_NAME = "ck_conversations_one_about"


def upgrade() -> None:
    """Add the column and widen the check to four ids."""
    op.add_column(
        "conversations",
        sqlalchemy.Column(
            "about_card_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.drop_constraint(CHECK_NAME, "conversations", type_="check")
    op.create_check_constraint(
        CHECK_NAME,
        "conversations",
        "num_nonnulls(about_source_id, about_topic_primer_id, about_take_id, about_card_id) <= 1",
    )


def downgrade() -> None:
    """Narrow the check back and drop the column."""
    op.drop_constraint(CHECK_NAME, "conversations", type_="check")
    op.create_check_constraint(
        CHECK_NAME, "conversations", "num_nonnulls(about_source_id, about_topic_primer_id, about_take_id) <= 1"
    )
    op.drop_column("conversations", "about_card_id")
