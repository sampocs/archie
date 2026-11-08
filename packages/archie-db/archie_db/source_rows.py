"""Changes to a source row that more than one caller makes."""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, models


def soft_delete_source(db: sqlalchemy.orm.Session, *, source: models.Source) -> None:
    """Soft-delete a source and its cards, so phones drop both. The caller holds the user's write lock."""
    source.deleted_at = sqlalchemy.func.now()
    changes.touch(source)
    db.execute(
        sqlalchemy.update(models.Card)
        .where(models.Card.source_id == source.id, models.Card.deleted_at.is_(None))
        .values(
            deleted_at=sqlalchemy.func.now(),
            updated_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
    )
