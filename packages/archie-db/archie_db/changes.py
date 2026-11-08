"""Change positions that phones pull from.

Every insert or update of a synced row takes the next value of one Postgres sequence. A phone pulls
rows with a position above its last one. The trap is that two transactions can take positions 5 and 6
and commit as 6 then 5: a phone pulling in between would advance past 5 and never see it. Serializing
each user's writes with a transaction-scoped advisory lock makes one user's positions commit in order.
Write volume per user is tiny, so the lock costs nothing.
"""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm

from archie_db import models


def lock_user_writes(db: sqlalchemy.orm.Session, user_id: int) -> None:
    """Block until this transaction is the only one writing synced rows for `user_id`; released at commit."""
    db.execute(sqlalchemy.select(sqlalchemy.func.pg_advisory_xact_lock(user_id)))


def next_change_seq() -> sqlalchemy.ColumnElement[int]:
    """The next change position. Call only after `lock_user_writes` in the same transaction."""
    return sqlalchemy.func.nextval(models.CHANGE_SEQ_NAME)


def touch(
    row: models.Source
    | models.Topic
    | models.Collection
    | models.CollectionItem
    | models.Take
    | models.NewsletterSender,
) -> None:
    """Mark a changed row so phones pull it again. Call only after `lock_user_writes` in the same transaction."""
    row.updated_at = sqlalchemy.func.now()
    row.change_seq = next_change_seq()
