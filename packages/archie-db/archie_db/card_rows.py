"""Card rows shared by the API and the worker: ownership, a card's stored detail, retiring cards, the user's card
preferences, done briefs.

Every function that writes expects the caller to hold `changes.lock_user_writes` for the user.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, models

MAX_PREFERENCE_NOTES = 20
QUIZ_LIFETIME = datetime.timedelta(days=7)
QUIZ_BRIEF_WINDOW = datetime.timedelta(days=7)
# The `news_quiz` job payload key naming the week (the phone's local Sunday, "YYYY-MM-DD") it was asked for.
WEEK_START_KEY = "week_start"
# A card's detail lines are stored as one text, joined by this.
DETAIL_SEPARATOR = "\n"
# The most the card rules let a writer give a card, when the owner asks for more detail (0-3 lines is the default).
MAX_DETAIL_LINES = 5


@dataclass(frozen=True)
class PreferenceNote:
    """One thing the user told Archie about cards: what they care about, or the question of a card they dropped."""

    kind: models.CardPreferenceKind
    note: str


def owned_live_card(db: sqlalchemy.orm.Session, *, user_id: int, card_id: uuid.UUID) -> models.Card | None:
    """The user's card with this id; another user's or a deleted one is treated as missing."""
    card = db.get(models.Card, card_id)
    if card is None or card.user_id != user_id or card.deleted_at is not None:
        return None
    return card


def detail_lines(lines: Sequence[str]) -> list[str]:
    """A card's detail lines cleaned as a writer gave them: a newline inside a line becomes a space, blank lines go,
    and only the first `MAX_DETAIL_LINES` are kept."""
    cleaned = (" ".join(line.split()) for line in lines)
    return [line for line in cleaned if line][:MAX_DETAIL_LINES]


def joined_detail(lines: Sequence[str]) -> str:
    """A card's detail lines as stored on the card: cleaned (`detail_lines`) and joined by newlines."""
    return DETAIL_SEPARATOR.join(detail_lines(lines))


def retire_cards(db: sqlalchemy.orm.Session, *criteria: sqlalchemy.ColumnElement[bool]) -> None:
    """Soft-delete the live cards matching `criteria`, each with a fresh change position so phones drop them."""
    db.execute(
        sqlalchemy.update(models.Card)
        .where(models.Card.deleted_at.is_(None), *criteria)
        .values(
            deleted_at=sqlalchemy.func.now(),
            updated_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
    )


def recent_preferences(
    db: sqlalchemy.orm.Session, *, user_id: int, limit: int = MAX_PREFERENCE_NOTES
) -> list[PreferenceNote]:
    """The user's latest card preferences, newest first."""
    rows = db.scalars(
        sqlalchemy.select(models.CardPreference)
        .where(models.CardPreference.user_id == user_id)
        .order_by(models.CardPreference.created_at.desc(), models.CardPreference.id.desc())
        .limit(limit)
    )
    return [PreferenceNote(kind=models.CardPreferenceKind(row.kind), note=row.note) for row in rows]


def recently_done_briefs(
    db: sqlalchemy.orm.Session, *, user_id: int, window: datetime.timedelta = QUIZ_BRIEF_WINDOW
) -> list[models.Brief]:
    """The user's briefs marked Done within `window` of now (the database's clock), newest first."""
    return list(
        db.scalars(
            sqlalchemy.select(models.Brief)
            .where(
                models.Brief.user_id == user_id,
                models.Brief.status == models.BriefStatus.DONE.value,
                models.Brief.done_at >= sqlalchemy.func.now() - window,
            )
            .order_by(models.Brief.done_at.desc())
        )
    )
