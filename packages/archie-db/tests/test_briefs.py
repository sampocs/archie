"""Which newsletters a brief covers, and when a ready newsletter queues the brief's rewrite, against a real Postgres."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import briefs, changes, models, pipeline, session

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


def test_a_ready_inbox_newsletter_queues_one_rewrite_until_it_starts_running(
    db: sqlalchemy.orm.Session, user: models.User
) -> None:
    """A second newsletter adds nothing while the rewrite is queued; once it runs, the next one queues a follow-up."""
    _finish(db, _summarized(db, user=user))
    _finish(db, _summarized(db, user=user))

    [first] = _brief_jobs(db, user_id=user.id)
    assert (first.status, first.payload) == (models.JobStatus.QUEUED.value, {briefs.USER_ID_KEY: user.id})

    first.status = models.JobStatus.RUNNING.value
    _finish(db, _summarized(db, user=user))

    assert [job.status for job in _brief_jobs(db, user_id=user.id)] == [
        models.JobStatus.RUNNING.value,
        models.JobStatus.QUEUED.value,
    ]


def test_another_users_queued_rewrite_does_not_block_this_users(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """The one-queued rule is per user."""
    other = models.User(apple_sub=f"sub-{uuid.uuid4()}")
    db.add(other)
    db.flush()
    briefs.enqueue_update(db, user_id=other.id)

    _finish(db, _summarized(db, user=user))

    assert len(_brief_jobs(db, user_id=user.id)) == 1


@pytest.mark.parametrize(
    ("kind", "state"),
    [
        (models.SourceKind.ARTICLE, models.SourceState.INBOX),
        (models.SourceKind.NEWSLETTER, models.SourceState.QUEUED),
        (models.SourceKind.NEWSLETTER, models.SourceState.CONSUMED),
    ],
)
def test_only_an_inbox_newsletter_queues_a_rewrite(
    db: sqlalchemy.orm.Session, user: models.User, kind: models.SourceKind, state: models.SourceState
) -> None:
    """An article, or a newsletter already queued or read, is never in a brief, so it queues nothing."""
    source = _summarized(db, user=user, kind=kind, state=state)
    if kind != models.SourceKind.NEWSLETTER:
        _write(db, source, kind=models.ArtifactKind.PRIMER)

    _finish(db, source)

    assert source.processing == models.ProcessingStatus.READY.value
    assert _brief_jobs(db, user_id=user.id) == []


def test_a_newsletter_still_missing_its_summary_queues_nothing(db: sqlalchemy.orm.Session, user: models.User) -> None:
    """Not ready yet, so not covered yet."""
    source = _source(db, user=user)

    _finish(db, source)

    assert _brief_jobs(db, user_id=user.id) == []


def test_covered_newsletters_are_every_ready_live_inbox_newsletter_however_old(
    db: sqlalchemy.orm.Session, user: models.User
) -> None:
    """A month-old one is covered; queued, processing, deleted, non-newsletter and other users' sources are not."""
    old = _ready(db, user=user, created_at=_ago(days=30))
    recent = _ready(db, user=user, created_at=_ago(hours=1))
    _ready(db, user=user, state=models.SourceState.QUEUED)
    _ready(db, user=user, state=models.SourceState.BRIEFED)
    _ready(db, user=user, kind=models.SourceKind.ARTICLE)
    _ready(db, user=user, processing=models.ProcessingStatus.PROCESSING)
    deleted = _ready(db, user=user)
    deleted.deleted_at = sqlalchemy.func.now()
    other = models.User(apple_sub=f"sub-{uuid.uuid4()}")
    db.add(other)
    db.flush()
    _ready(db, user=other)

    assert [source.id for source in briefs.covered_newsletters(db, user_id=user.id)] == [old.id, recent.id]


def _ago(*, days: int = 0, hours: int = 0) -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days, hours=hours)


def _source(
    db: sqlalchemy.orm.Session,
    *,
    user: models.User,
    kind: models.SourceKind = models.SourceKind.NEWSLETTER,
    state: models.SourceState = models.SourceState.INBOX,
    processing: models.ProcessingStatus = models.ProcessingStatus.PROCESSING,
    created_at: datetime.datetime | None = None,
) -> models.Source:
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url=f"https://example.com/{uuid.uuid4()}",
        normalized_url=f"https://example.com/{uuid.uuid4()}",
        kind=kind.value,
        state=state.value,
        intent=models.SourceIntent.QUEUE.value,
        processing=processing.value,
        change_seq=changes.next_change_seq(),
    )
    if created_at is not None:
        source.created_at = created_at
    db.add(source)
    db.flush()
    return source


def _summarized(
    db: sqlalchemy.orm.Session,
    *,
    user: models.User,
    kind: models.SourceKind = models.SourceKind.NEWSLETTER,
    state: models.SourceState = models.SourceState.INBOX,
) -> models.Source:
    source = _source(db, user=user, kind=kind, state=state)
    _write(db, source, kind=models.ArtifactKind.SUMMARY)
    return source


def _ready(
    db: sqlalchemy.orm.Session,
    *,
    user: models.User,
    kind: models.SourceKind = models.SourceKind.NEWSLETTER,
    state: models.SourceState = models.SourceState.INBOX,
    processing: models.ProcessingStatus = models.ProcessingStatus.READY,
    created_at: datetime.datetime | None = None,
) -> models.Source:
    return _source(db, user=user, kind=kind, state=state, processing=processing, created_at=created_at)


def _write(db: sqlalchemy.orm.Session, source: models.Source, *, kind: models.ArtifactKind) -> None:
    pipeline.write_artifact(db, source=source, kind=kind, content={}, model=None, prompt_version=None)


def _finish(db: sqlalchemy.orm.Session, source: models.Source) -> None:
    pipeline.finish_step(db, source=source)
    db.flush()


def _brief_jobs(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Job]:
    return list(
        db.scalars(
            sqlalchemy.select(models.Job)
            .where(models.Job.kind == models.JobKind.UPDATE_BRIEF.value, models.Job.user_id == user_id)
            .order_by(models.Job.id)
        )
    )
