"""Pull: everything that changed for a user after a position, one page at a time."""

from __future__ import annotations

import dataclasses
import datetime
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Protocol

import sqlalchemy
from archie_db import models
from sqlalchemy import orm

from archie_api.sync import schemas

PULL_PAGE_SIZE = 500

# Done briefs older than this are not sent: the phone shows only the open brief and recent ones.
DONE_BRIEF_WINDOW = datetime.timedelta(days=7)


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
    BRIEFS = "briefs"
    COLLECTIONS = "collections"
    COLLECTION_ITEMS = "collection_items"
    TAKES = "takes"
    TAKE_VERSIONS = "take_versions"
    CONVERSATIONS = "conversations"
    MESSAGES = "messages"
    CARD_VERSIONS = "card_versions"
    EDIT_PROPOSALS = "edit_proposals"
    NEWSLETTER_SENDERS = "newsletter_senders"


@dataclasses.dataclass(frozen=True)
class MergedPage[RowT: _Positioned]:
    """The rows one pull page keeps from each table, and where the phone should resume."""

    rows: dict[str, list[RowT]]
    position: int
    more: bool


def pull_changes(db: orm.Session, *, user_id: int, since: int, limit: int = PULL_PAGE_SIZE) -> schemas.PullResponse:
    """Rows (deleted ones included) from the fifteen synced tables with a position above `since`, oldest first.

    Of the briefs, only the open one and those done in the last 7 days are sent.
    """
    artifact_kinds = models.SourceArtifact.kind.in_([kind.value for kind in models.SYNCED_ARTIFACT_KINDS])
    recent_brief = sqlalchemy.or_(
        models.Brief.status == models.BriefStatus.OPEN.value,
        models.Brief.done_at >= sqlalchemy.func.now() - DONE_BRIEF_WINDOW,
    )
    tables: dict[str, Sequence[_Positioned]] = {
        PulledTable.SOURCES: _changed_rows(db, models.Source, user_id=user_id, since=since, limit=limit),
        PulledTable.ARTIFACTS: _changed_rows(
            db, models.SourceArtifact, artifact_kinds, user_id=user_id, since=since, limit=limit
        ),
        PulledTable.CARDS: _changed_rows(db, models.Card, user_id=user_id, since=since, limit=limit),
        PulledTable.TOPICS: _changed_rows(db, models.Topic, user_id=user_id, since=since, limit=limit),
        PulledTable.TOPIC_PRIMERS: _changed_rows(db, models.TopicPrimer, user_id=user_id, since=since, limit=limit),
        PulledTable.BRIEFS: _changed_rows(db, models.Brief, recent_brief, user_id=user_id, since=since, limit=limit),
        PulledTable.COLLECTIONS: _changed_rows(db, models.Collection, user_id=user_id, since=since, limit=limit),
        PulledTable.COLLECTION_ITEMS: _changed_rows(
            db, models.CollectionItem, user_id=user_id, since=since, limit=limit
        ),
        PulledTable.TAKES: _changed_rows(db, models.Take, user_id=user_id, since=since, limit=limit),
        PulledTable.TAKE_VERSIONS: _changed_rows(db, models.TakeVersion, user_id=user_id, since=since, limit=limit),
        PulledTable.CONVERSATIONS: _changed_rows(db, models.Conversation, user_id=user_id, since=since, limit=limit),
        PulledTable.MESSAGES: _changed_rows(db, models.Message, user_id=user_id, since=since, limit=limit),
        PulledTable.CARD_VERSIONS: _changed_rows(db, models.CardVersion, user_id=user_id, since=since, limit=limit),
        PulledTable.EDIT_PROPOSALS: _changed_rows(db, models.EditProposal, user_id=user_id, since=since, limit=limit),
        PulledTable.NEWSLETTER_SENDERS: _changed_rows(
            db, models.NewsletterSender, user_id=user_id, since=since, limit=limit
        ),
    }
    page = merge_page(tables=tables, since=since, limit=limit)

    return schemas.PullResponse(
        rows=schemas.PulledRows(
            sources=[schemas.SourceOut.model_validate(row) for row in page.rows[PulledTable.SOURCES]],
            artifacts=[schemas.ArtifactOut.model_validate(row) for row in page.rows[PulledTable.ARTIFACTS]],
            cards=[schemas.CardOut.model_validate(row) for row in page.rows[PulledTable.CARDS]],
            topics=[schemas.TopicOut.model_validate(row) for row in page.rows[PulledTable.TOPICS]],
            topic_primers=[schemas.TopicPrimerOut.model_validate(row) for row in page.rows[PulledTable.TOPIC_PRIMERS]],
            briefs=[schemas.BriefOut.model_validate(row) for row in page.rows[PulledTable.BRIEFS]],
            collections=[schemas.CollectionOut.model_validate(row) for row in page.rows[PulledTable.COLLECTIONS]],
            collection_items=[
                schemas.CollectionItemOut.model_validate(row) for row in page.rows[PulledTable.COLLECTION_ITEMS]
            ],
            takes=[schemas.TakeOut.model_validate(row) for row in page.rows[PulledTable.TAKES]],
            take_versions=[schemas.TakeVersionOut.model_validate(row) for row in page.rows[PulledTable.TAKE_VERSIONS]],
            conversations=[schemas.ConversationOut.model_validate(row) for row in page.rows[PulledTable.CONVERSATIONS]],
            messages=[schemas.MessageOut.model_validate(row) for row in page.rows[PulledTable.MESSAGES]],
            card_versions=[schemas.CardVersionOut.model_validate(row) for row in page.rows[PulledTable.CARD_VERSIONS]],
            edit_proposals=[
                schemas.EditProposalOut.model_validate(row) for row in page.rows[PulledTable.EDIT_PROPOSALS]
            ],
            newsletter_senders=[
                schemas.NewsletterSenderOut.model_validate(row) for row in page.rows[PulledTable.NEWSLETTER_SENDERS]
            ],
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


def _changed_rows[
    RowT: (
        models.Source,
        models.SourceArtifact,
        models.Card,
        models.Topic,
        models.TopicPrimer,
        models.Brief,
        models.Collection,
        models.CollectionItem,
        models.Take,
        models.TakeVersion,
        models.Conversation,
        models.Message,
        models.CardVersion,
        models.EditProposal,
        models.NewsletterSender,
    )
](
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
