"""A user's topics against a real Postgres: owner seeding, name lookups, the unique-name rule, analyzed sources."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session, user_topics
from archie_shared import topics
from archie_shared.domains import Domain

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
    new_user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
    db.add(new_user)
    db.flush()
    changes.lock_user_writes(db, new_user.id)
    return new_user


def test_seed_owner_topics_adds_the_picks_live_and_the_extras_removed_once(
    db: sqlalchemy.orm.Session, user: models.User
) -> None:
    """Every owner pick is a live starter topic, the 3 extras removed, the user counts as chosen; a rerun adds none."""
    user_topics.seed_owner_topics(db, user=user)
    user_topics.seed_owner_topics(db, user=user)
    db.refresh(user)

    live = user_topics.live_topics(db, user_id=user.id)
    removed = user_topics.removed_topics(db, user_id=user.id)
    assert len(live) == sum(len(names) for names in topics.OWNER_TOPICS.values())
    assert {topic.origin for topic in live + removed} == {models.TopicOrigin.STARTER.value}
    assert {topic.name for topic in removed} == {"Personal finance & taxes", "Insurance", "College football"}
    assert user.topics_chosen_at is not None


def test_seeding_files_the_owners_analyzed_sources_once(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """One analyzed source queues exactly one `file_topic` job; seeding again queues nothing more."""
    source = _source(db, user=user)
    pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.SUMMARY, content={}, model=None, prompt_version=None
    )

    user_topics.seed_owner_topics(db, user=user)
    user_topics.seed_owner_topics(db, user=user)

    jobs = list(db.scalars(sqlalchemy.select(models.Job)))
    assert [(job.kind, job.payload[pipeline.SOURCE_ID_KEY]) for job in jobs] == [("file_topic", str(source.id))]


def test_named_topic_matches_normalized_live_and_removed_topics_but_not_merged_ones(
    db: sqlalchemy.orm.Session, user: models.User
) -> None:
    """Lookups ignore case and `&`; a removed topic still holds its name, a merged one gave it up."""
    fed = _create(db, user=user, name="Fed & monetary policy")
    removed = _create(db, user=user, name="Insurance", removed=True)
    merged = _create(db, user=user, name="Monetary history")
    merged.merged_into_id = fed.id
    db.flush()

    assert user_topics.named_topic(db, user_id=user.id, name="fed and monetary policy") is fed
    assert user_topics.named_topic(db, user_id=user.id, name="INSURANCE") is removed
    assert user_topics.named_topic(db, user_id=user.id, name="Monetary history") is None


def test_topic_names_are_unique_per_user_until_one_is_merged(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """A name differing only in case collides; once the first topic is merged away, its name is free again."""
    first = _create(db, user=user, name="Bitcoin")
    with pytest.raises(sqlalchemy.exc.IntegrityError), db.begin_nested():
        _create(db, user=user, name="BITCOIN")

    winner = _create(db, user=user, name="Crypto investing")
    first.merged_into_id = winner.id
    db.flush()
    again = _create(db, user=user, name="bitcoin")

    assert again.merged_into_id is None


def test_analyzed_sources_are_the_live_sources_with_a_current_summary(
    db: sqlalchemy.orm.Session, user: models.User
) -> None:
    """A source without a summary, or deleted, is not filed."""
    analyzed = _source(db, user=user)
    deleted = _source(db, user=user)
    _source(db, user=user)
    for source in (analyzed, deleted):
        pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY, content={}, model=None, prompt_version=None
        )
    deleted.deleted_at = sqlalchemy.func.now()
    db.flush()

    assert user_topics.analyzed_sources(db, user_id=user.id) == [analyzed]


def _create(db: sqlalchemy.orm.Session, *, user: models.User, name: str, removed: bool = False) -> models.Topic:
    return user_topics.create_topic(
        db, user_id=user.id, domain=Domain.CRYPTO, name=name, origin=models.TopicOrigin.USER, removed=removed
    )


def _source(db: sqlalchemy.orm.Session, *, user: models.User) -> models.Source:
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url="https://example.com/a",
        normalized_url="https://example.com/a",
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.QUEUE.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source
