"""Newsletter sender allowlist: senders and their identifiers, and the sender columns on sources.

Existing sources only stored the display name, so each distinct display name of a user's live, non-confirmation
newsletters becomes an allowed sender with one `name` identifier: their subscriptions keep flowing. The SQL
normalisation equals `archie_db.senders.normalize_name`.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)

# One sender per (user, normalised display name), labelled with the oldest newsletter's original spelling. The CTE is
# read twice, so Postgres computes it once and both inserts share the generated ids.
_BACKFILL_SENDERS = """
WITH named AS (
    SELECT DISTINCT ON (user_id, name) gen_random_uuid() AS id, user_id, name, sender AS label
    FROM (
        SELECT user_id, sender, created_at, lower(regexp_replace(trim(sender), '\\s+', ' ', 'g')) AS name
        FROM sources
        WHERE kind = 'newsletter' AND deleted_at IS NULL AND confirm_url IS NULL AND sender IS NOT NULL
    ) AS normalised
    WHERE name <> ''
    ORDER BY user_id, name, created_at
), created AS (
    INSERT INTO newsletter_senders (id, user_id, label, status, change_seq)
    SELECT id, user_id, label, 'allowed', nextval('change_seq') FROM named
)
INSERT INTO newsletter_sender_identifiers (sender_id, user_id, kind, value)
SELECT id, user_id, 'name', name FROM named
"""


def upgrade() -> None:
    """Add the sender tables and source columns, then allow the senders of existing newsletters by display name."""
    op.add_column("sources", sqlalchemy.Column("sender_address", sqlalchemy.String(length=320), nullable=True))
    op.add_column("sources", sqlalchemy.Column("list_id", sqlalchemy.String(length=998), nullable=True))
    op.add_column(
        "sources",
        sqlalchemy.Column("sender_pending", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False),
    )

    op.create_table(
        "newsletter_senders",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("label", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_newsletter_senders_user_id_change_seq", "newsletter_senders", ["user_id", "change_seq"])

    op.create_table(
        "newsletter_sender_identifiers",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column(
            "sender_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("newsletter_senders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("value", sqlalchemy.String(998), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
    )
    op.create_index(
        "uq_newsletter_sender_identifiers_user_id_kind_value",
        "newsletter_sender_identifiers",
        ["user_id", "kind", "value"],
        unique=True,
    )

    op.execute(_BACKFILL_SENDERS)


def downgrade() -> None:
    """Drop the sender tables and source columns; every allow and block decision is lost."""
    op.drop_table("newsletter_sender_identifiers")
    op.drop_table("newsletter_senders")
    op.drop_column("sources", "sender_pending")
    op.drop_column("sources", "list_id")
    op.drop_column("sources", "sender_address")
