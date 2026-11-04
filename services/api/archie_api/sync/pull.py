"""Pull: everything that changed for a user after a position, one page at a time."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Protocol

import sqlalchemy
from archie_db import models
from sqlalchemy import orm

from archie_api.sync import schemas

PULL_PAGE_SIZE = 500


class _Positioned(Protocol):
    @property
    def change_seq(self) -> int: ...


class PulledTable(StrEnum):
    """The synced tables a pull page carries, keyed as on the wire."""

    SOURCES = "sources"
    ARTIFACTS = "artifacts"
    CARDS = "cards"
    TOPICS = "topics"
    TOPIC_PRIMERS = "topic_primers"


@dataclasses.dataclass(frozen=True)
class MergedPage[RowT: _Positioned]:
    """The rows one pull page keeps from each table, and where the phone should resume."""

    rows: dict[str, list[RowT]]
    position: int
    more: bool


def pull_changes(db: orm.Session, *, user_id: int, since: int, limit: int = PULL_PAGE_SIZE) -> schemas.PullResponse:
    """Rows (deleted ones included) from the five synced tables with a position above `since`, oldest first."""
    artifact_kinds = models.SourceArtifact.kind.in_([kind.value for kind in models.SYNCED_ARTIFACT_KINDS])
    tables: dict[str, Sequence[_Positioned]] = {
        PulledTable.SOURCES: _changed_rows(db, models.Source, user_id=user_id, since=since, limit=limit),
        PulledTable.ARTIFACTS: _changed_rows(
            db, models.SourceArtifact, artifact_kinds, user_id=user_id, since=since, limit=limit
        ),
        PulledTable.CARDS: _changed_rows(db, models.Card, user_id=user_id, since=since, limit=limit),
        PulledTable.TOPICS: _changed_rows(db, models.Topic, user_id=user_id, since=since, limit=limit),
        PulledTable.TOPIC_PRIMERS: _changed_rows(db, models.TopicPrimer, user_id=user_id, since=since, limit=limit),
    }
    page = merge_page(tables=tables, since=since, limit=limit)

    return schemas.PullResponse(
        rows=schemas.PulledRows(
            sources=[schemas.SourceOut.model_validate(row) for row in page.rows[PulledTable.SOURCES]],
            artifacts=[schemas.ArtifactOut.model_validate(row) for row in page.rows[PulledTable.ARTIFACTS]],
            cards=[schemas.CardOut.model_validate(row) for row in page.rows[PulledTable.CARDS]],
            topics=[schemas.TopicOut.model_validate(row) for row in page.rows[PulledTable.TOPICS]],
            topic_primers=[schemas.TopicPrimerOut.model_validate(row) for row in page.rows[PulledTable.TOPIC_PRIMERS]],
        ),
        position=page.position,
        more=page.more,
    )


def merge_page[RowT: _Positioned](*, tables: Mapping[str, Sequence[RowT]], since: int, limit: int) -> MergedPage[RowT]:
    """Keep the `limit` lowest positions across the tables' rows (each table already holds its own lowest).

    Positions come from one sequence, so they are unique across tables. The phone resumes from the last kept
    position, so every cut row sits above it and is returned by the next pull. `more` is set when rows were cut
    or a table filled its own query, since that table may hold further rows the others' positions hide.
    """
    all_rows = [row for rows in tables.values() for row in rows]
    kept_positions = sorted(row.change_seq for row in all_rows)[:limit]
    position = kept_positions[-1] if kept_positions else since

    return MergedPage(
        rows={name: [row for row in rows if row.change_seq <= position] for name, rows in tables.items()},
        position=position,
        more=len(all_rows) > limit or any(len(rows) == limit for rows in tables.values()),
    )


def _changed_rows[RowT: (models.Source, models.SourceArtifact, models.Card, models.Topic, models.TopicPrimer)](
    db: orm.Session, model: type[RowT], *criteria: sqlalchemy.ColumnElement[bool], user_id: int, since: int, limit: int
) -> list[RowT]:
    """The user's `limit` oldest `model` rows above `since` that match `criteria`."""
    return list(
        db.scalars(
            sqlalchemy.select(model)
            .where(model.user_id == user_id, model.change_seq > since, *criteria)
            .order_by(model.change_seq)
            .limit(limit)
        )
    )
