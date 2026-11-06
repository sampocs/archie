"""Card ownership, retiring a source's cards, the latest card preferences and recently done briefs, on real Postgres."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, models, pipeline, session

pytestmark = pytest.mark.postgres


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session on the migrated test database, rolled back at the end."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as database:
        yield database
        database.rollback()
    engine.dispose()


@pytest.fixture
def user(db: sqlalchemy.orm.Session) -> models.User:
    """A user whose write lock this transaction already holds."""
    return _user(db)


def test_recent_preferences_are_the_latest_notes_newest_first(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """Ordered by when the note was made (not insertion order), capped at `limit`; other users' notes are left out."""
    now = datetime.datetime.now(datetime.UTC)
    for age_days, kind, note in [
        (1, models.CardPreferenceKind.CARE, "newest"),
        (3, models.CardPreferenceKind.DROP, "oldest"),
        (2, models.CardPreferenceKind.DROP, "middle"),
    ]:
        _preference(db, user=user, kind=kind, note=note, created_at=now - datetime.timedelta(days=age_days))
    _preference(db, user=_user(db), kind=models.CardPreferenceKind.CARE, note="someone else's", created_at=now)

    assert card_rows.recent_preferences(db, user_id=user.id, limit=2) == [
        card_rows.PreferenceNote(kind=models.CardPreferenceKind.CARE, note="newest"),
        card_rows.PreferenceNote(kind=models.CardPreferenceKind.DROP, note="middle"),
    ]


def test_retire_cards_soft_deletes_only_the_matching_live_cards(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """Each retired card gets its own newer change position; deleted cards and other sources' cards are untouched."""
    source = _source(db, user=user)
    live = [_card(db, source=source), _card(db, source=source)]
    already_deleted = _card(db, source=source, deleted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    other_source_card = _card(db, source=_source(db, user=user))
    before = {card.id: (card.deleted_at, card.change_seq) for card in [*live, already_deleted, other_source_card]}

    card_rows.retire_cards(db, models.Card.source_id == source.id)
    for card in [*live, already_deleted, other_source_card]:
        db.refresh(card)

    for card in live:
        assert card.deleted_at is not None
        assert card.change_seq > before[card.id][1]
    assert live[0].change_seq != live[1].change_seq
    assert (already_deleted.deleted_at, already_deleted.change_seq) == before[already_deleted.id]
    assert (other_source_card.deleted_at, other_source_card.change_seq) == before[other_source_card.id]


def test_recently_done_briefs_are_those_done_within_the_window(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """Done six days ago counts, eight days ago doesn't, and an open brief never does; newest done first."""
    six_days = _brief(db, user=user, done_days_ago=6)
    one_day = _brief(db, user=user, done_days_ago=1)
    _brief(db, user=user, done_days_ago=8)
    _brief(db, user=user, done_days_ago=None)
    _brief(db, user=_user(db), done_days_ago=1)

    assert [brief.id for brief in card_rows.recently_done_briefs(db, user_id=user.id)] == [one_day.id, six_days.id]


def test_owned_live_card_hides_other_users_and_deleted_cards(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """The caller's live card is found; another user's card, a deleted card and an unknown id read as missing."""
    source = _source(db, user=user)
    own = _card(db, source=source)
    deleted = _card(db, source=source, deleted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    someone_elses = _card(db, source=_source(db, user=_user(db)))

    assert card_rows.owned_live_card(db, user_id=user.id, card_id=own.id) is own
    assert card_rows.owned_live_card(db, user_id=user.id, card_id=deleted.id) is None
    assert card_rows.owned_live_card(db, user_id=user.id, card_id=someone_elses.id) is None
    assert card_rows.owned_live_card(db, user_id=user.id, card_id=uuid.uuid4()) is None


def _user(db: sqlalchemy.orm.Session) -> models.User:
    new_user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
    db.add(new_user)
    db.flush()
    changes.lock_user_writes(db, new_user.id)
    return new_user


def _source(db: sqlalchemy.orm.Session, *, user: models.User) -> models.Source:
    url = f"https://example.com/{uuid.uuid4()}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url=url,
        normalized_url=url,
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.CONSUMED.value,
        intent=models.SourceIntent.FINISHED.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source


def _card(
    db: sqlalchemy.orm.Session, *, source: models.Source, deleted_at: datetime.datetime | None = None
) -> models.Card:
    artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    if artifact is None:
        artifact = pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY, content={}, model=None, prompt_version=None
        )
    card = models.Card(
        id=uuid.uuid4(),
        user_id=source.user_id,
        source_id=source.id,
        artifact_id=artifact.id,
        kind=models.CardKind.CONCEPT.value,
        question="Q?",
        answer="A.",
        deleted_at=deleted_at,
        change_seq=changes.next_change_seq(),
    )
    db.add(card)
    db.flush()
    db.refresh(card)
    return card


def _preference(
    db: sqlalchemy.orm.Session,
    *,
    user: models.User,
    kind: models.CardPreferenceKind,
    note: str,
    created_at: datetime.datetime,
) -> None:
    db.add(models.CardPreference(user_id=user.id, kind=kind.value, note=note, created_at=created_at))
    db.flush()


def _brief(db: sqlalchemy.orm.Session, *, user: models.User, done_days_ago: int | None) -> models.Brief:
    status = models.BriefStatus.OPEN if done_days_ago is None else models.BriefStatus.DONE
    brief = models.Brief(
        id=uuid.uuid4(),
        user_id=user.id,
        status=status.value,
        done_at=None if done_days_ago is None else sqlalchemy.func.now() - datetime.timedelta(days=done_days_ago),
        change_seq=changes.next_change_seq(),
    )
    db.add(brief)
    db.flush()
    return brief
