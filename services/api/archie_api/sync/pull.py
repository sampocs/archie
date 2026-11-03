"""Pull: everything that changed for a user after a position, one page at a time."""

from __future__ import annotations

import dataclasses
from typing import Protocol, TypeVar

import sqlalchemy
from archie_db import models
from sqlalchemy import orm

from archie_api.sync import schemas

PULL_PAGE_SIZE = 500


class _Positioned(Protocol):
    @property
    def change_seq(self) -> int: ...


_RowT = TypeVar("_RowT", models.Source, models.SourceArtifact, models.Card)


@dataclasses.dataclass(frozen=True)
class MergedPage[SourceT: _Positioned, ArtifactT: _Positioned, CardT: _Positioned]:
    """The rows one pull page keeps from each table, and where the phone should resume."""

    sources: list[SourceT]
    artifacts: list[ArtifactT]
    cards: list[CardT]
    position: int
    more: bool


def pull_changes(db: orm.Session, *, user_id: int, since: int, limit: int = PULL_PAGE_SIZE) -> schemas.PullResponse:
    """Rows (deleted ones included) from sources, artifacts and cards with a position above `since`, oldest first."""
    page = merge_page(
        sources=_changed_rows(db, models.Source, user_id=user_id, since=since, limit=limit),
        artifacts=_changed_rows(
            db,
            models.SourceArtifact,
            models.SourceArtifact.kind.in_([kind.value for kind in models.SYNCED_ARTIFACT_KINDS]),
            user_id=user_id,
            since=since,
            limit=limit,
        ),
        cards=_changed_rows(db, models.Card, user_id=user_id, since=since, limit=limit),
        since=since,
        limit=limit,
    )

    return schemas.PullResponse(
        rows=schemas.PulledRows(
            sources=[schemas.SourceOut.model_validate(row) for row in page.sources],
            artifacts=[schemas.ArtifactOut.model_validate(row) for row in page.artifacts],
            cards=[schemas.CardOut.model_validate(row) for row in page.cards],
        ),
        position=page.position,
        more=page.more,
    )


def merge_page[SourceT: _Positioned, ArtifactT: _Positioned, CardT: _Positioned](
    *, sources: list[SourceT], artifacts: list[ArtifactT], cards: list[CardT], since: int, limit: int
) -> MergedPage[SourceT, ArtifactT, CardT]:
    """Keep the `limit` lowest positions across the three tables' rows (each table already holds its own lowest).

    Positions come from one sequence, so they are unique across tables. The phone resumes from the last kept
    position, so every cut row sits above it and is returned by the next pull. `more` is set when rows were cut
    or a table filled its own query, since that table may hold further rows the others' positions hide.
    """
    all_rows: list[_Positioned] = [*sources, *artifacts, *cards]
    kept_positions = sorted(row.change_seq for row in all_rows)[:limit]
    position = kept_positions[-1] if kept_positions else since

    return MergedPage(
        sources=[row for row in sources if row.change_seq <= position],
        artifacts=[row for row in artifacts if row.change_seq <= position],
        cards=[row for row in cards if row.change_seq <= position],
        position=position,
        more=len(all_rows) > limit or limit in (len(sources), len(artifacts), len(cards)),
    )


def _changed_rows(
    db: orm.Session, model: type[_RowT], *criteria: sqlalchemy.ColumnElement[bool], user_id: int, since: int, limit: int
) -> list[_RowT]:
    """The user's `limit` oldest `model` rows above `since` that match `criteria`."""
    return list(
        db.scalars(
            sqlalchemy.select(model)
            .where(model.user_id == user_id, model.change_seq > since, *criteria)
            .order_by(model.change_seq)
            .limit(limit)
        )
    )
