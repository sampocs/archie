"""Pull: everything that changed for a user after a position, one page at a time."""

from __future__ import annotations

import sqlalchemy
from archie_db import models
from sqlalchemy import orm

from archie_api.sync import schemas

PULL_PAGE_SIZE = 500


def pull_changes(db: orm.Session, *, user_id: int, since: int, limit: int = PULL_PAGE_SIZE) -> schemas.PullResponse:
    """Rows (deleted ones included) with a position above `since`, oldest first."""
    rows = db.scalars(
        sqlalchemy.select(models.Source)
        .where(models.Source.user_id == user_id, models.Source.change_seq > since)
        .order_by(models.Source.change_seq)
        .limit(limit)
    ).all()

    # With no rows the phone stays where it was; a full page means there may be more behind it.
    return schemas.PullResponse(
        rows=schemas.PulledRows(sources=[schemas.SourceOut.model_validate(row) for row in rows]),
        position=rows[-1].change_seq if rows else since,
        more=len(rows) == limit,
    )
