"""Review actions from the phone: a graded answer, dropping a card, cards off for a source, the weekly quiz.

Each returns a reason or None. The caller holds the user's write lock; every check runs before the first write (see
`actions.apply_actions`). The phone is the scheduler: the server stores each review and the state the phone computed.
"""

from __future__ import annotations

import datetime
import uuid

import pydantic
import sqlalchemy
from archie_db import briefs, card_rows, changes, jobs, models, pipeline
from sqlalchemy import orm

from archie_api.sync import rows

NO_CARD = "card not found"
_REVIEW_ID_USED = "review id already used"
_NO_REPLACED_REVIEW = "replaced review not found"
MAX_ANSWER_LENGTH = 4000
MAX_MISSING_LENGTH = 1000


class _FsrsStatePayload(pydantic.BaseModel):
    fsrs_state: models.FsrsState
    stability: float | None = pydantic.Field(allow_inf_nan=False)
    difficulty: float | None = pydantic.Field(allow_inf_nan=False)
    due_at: pydantic.AwareDatetime | None
    last_review_at: pydantic.AwareDatetime | None
    reps: int = pydantic.Field(ge=0)
    lapses: int = pydantic.Field(ge=0)


class _ReviewCardPayload(pydantic.BaseModel):
    id: uuid.UUID
    review_id: uuid.UUID
    grade: models.ReviewGrade
    graded_by: models.GradedBy
    answer: str | None = pydantic.Field(default=None, max_length=MAX_ANSWER_LENGTH)
    missing: str | None = pydantic.Field(default=None, max_length=MAX_MISSING_LENGTH)
    was_due: bool
    reviewed_at: pydantic.AwareDatetime
    state_before: _FsrsStatePayload
    state_after: _FsrsStatePayload
    replaces_review_id: uuid.UUID | None = None


class _CardPayload(pydantic.BaseModel):
    id: uuid.UUID


class _CardsOffPayload(pydantic.BaseModel):
    id: uuid.UUID
    off: bool


class _NewsQuizPayload(pydantic.BaseModel):
    week_start: datetime.date


def review_card(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Log a graded answer and store the card's new FSRS state, unless a later review of the card already arrived.

    A review id seen before (the same answer sent again under a new action id) is a no-op. The latest review by
    `reviewed_at` decides the card's state, so a late upload from another phone can't roll the schedule back.
    """
    parsed = rows.parse(_ReviewCardPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    card = card_rows.owned_live_card(db, user_id=user.id, card_id=parsed.id)
    if card is None:
        return NO_CARD

    existing = db.get(models.Review, parsed.review_id)
    if existing is not None:
        return None if existing.user_id == user.id and existing.card_id == card.id else _REVIEW_ID_USED
    if parsed.replaces_review_id is not None and not _is_review_of(db, review_id=parsed.replaces_review_id, card=card):
        return _NO_REPLACED_REVIEW

    has_later_review = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(models.Review.card_id == card.id, models.Review.reviewed_at > parsed.reviewed_at)
        )
    )
    db.add(
        models.Review(
            id=parsed.review_id,
            user_id=user.id,
            card_id=card.id,
            grade=parsed.grade.value,
            graded_by=parsed.graded_by.value,
            answer=parsed.answer,
            missing=parsed.missing,
            was_due=parsed.was_due,
            reviewed_at=parsed.reviewed_at,
            state_before=parsed.state_before.model_dump(mode="json"),
            state_after=parsed.state_after.model_dump(mode="json"),
            replaces_review_id=parsed.replaces_review_id,
        )
    )
    if not has_later_review:
        _write_state(card, state=parsed.state_after)
    return None


def drop_card(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Retire a card the user doesn't want, and remember its question as a "not this" preference."""
    parsed = rows.parse(_CardPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    card = card_rows.owned_live_card(db, user_id=user.id, card_id=parsed.id)
    if card is None:
        return NO_CARD

    card_rows.retire_cards(db, models.Card.id == card.id)
    db.add(
        models.CardPreference(
            user_id=user.id, card_id=card.id, kind=models.CardPreferenceKind.DROP.value, note=card.question
        )
    )
    return None


def set_cards_off(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Cards off retires the source's cards (foundation cards too) and stops new ones; cards on re-runs analyze.

    A note is never analyzed: cards on for a refreshed note re-queues its `note_cards` job, and for an unrefreshed
    one only flips the flag (the refresher writes its cards when it is refreshed).
    """
    parsed = rows.parse(_CardsOffPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE

    source.cards_off = parsed.off
    changes.touch(source)
    if parsed.off:
        card_rows.retire_cards(db, models.Card.source_id == source.id)
        return None

    if source.kind == models.SourceKind.NOTE:
        _requeue_note_cards(db, source=source)
        return None

    # Only a source with text can be analyzed again; one still fetching gets its cards when its analyze runs.
    has_text = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT) is not None
    if has_text and not rows.has_pending_job(db, source=source, kind=models.JobKind.ANALYZE):
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
        pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.ANALYZE])
    return None


def _requeue_note_cards(db: orm.Session, *, source: models.Source) -> None:
    if source.refreshed_at is None or rows.has_pending_job(db, source=source, kind=models.JobKind.NOTE_CARDS):
        return
    jobs.enqueue(
        db,
        kind=models.JobKind.NOTE_CARDS,
        user_id=source.user_id,
        payload={pipeline.SOURCE_ID_KEY: str(source.id)},
    )


def request_news_quiz(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Queue this week's news quiz once, and only when a brief was Done in the last 7 days.

    Applied either way: the phone asks on every Sunday Today open, so "already made" and "nothing to quiz" are answers,
    not errors.
    """
    parsed = rows.parse(_NewsQuizPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    week_start = parsed.week_start.isoformat()
    if _quiz_requested(db, user_id=user.id, week_start=week_start):
        return None
    if not card_rows.recently_done_briefs(db, user_id=user.id):
        return None

    jobs.enqueue(
        db,
        kind=models.JobKind.NEWS_QUIZ,
        user_id=user.id,
        payload={briefs.USER_ID_KEY: user.id, card_rows.WEEK_START_KEY: week_start},
    )
    return None


def _is_review_of(db: orm.Session, *, review_id: uuid.UUID, card: models.Card) -> bool:
    review = db.get(models.Review, review_id)
    return review is not None and review.card_id == card.id


def _write_state(card: models.Card, *, state: _FsrsStatePayload) -> None:
    card.fsrs_state = state.fsrs_state.value
    card.stability = state.stability
    card.difficulty = state.difficulty
    card.due_at = state.due_at
    card.last_review_at = state.last_review_at
    card.reps = state.reps
    card.lapses = state.lapses
    card.updated_at = sqlalchemy.func.now()
    card.change_seq = changes.next_change_seq()


def _quiz_requested(db: orm.Session, *, user_id: int, week_start: str) -> bool:
    """Whether a news quiz for this week is queued, running or done; a failed one may be asked for again."""
    requested = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.kind == models.JobKind.NEWS_QUIZ.value,
                models.Job.user_id == user_id,
                models.Job.status != models.JobStatus.FAILED.value,
                models.Job.payload[card_rows.WEEK_START_KEY].astext == week_start,
            )
        )
    )
    return bool(requested)
