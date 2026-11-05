"""Queued primers: a source's primer can sit in the queue as its own entry; Prep me is gone.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def upgrade() -> None:
    """Drop `prep_me` and add the queued primer's position and snooze."""
    op.drop_column("sources", "prep_me")
    op.add_column("sources", sqlalchemy.Column("primer_queue_position", sqlalchemy.Double(), nullable=True))
    op.add_column("sources", sqlalchemy.Column("primer_snoozed_until", _TIMESTAMP, nullable=True))


def downgrade() -> None:
    """Undo everything `upgrade` did, in reverse."""
    op.drop_column("sources", "primer_snoozed_until")
    op.drop_column("sources", "primer_queue_position")
    op.add_column(
        "sources", sqlalchemy.Column("prep_me", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False)
    )
