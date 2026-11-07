"""`store_text` and `enqueue_transcribe`: what each writes and queues, and that a deleted source is left alone."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session
from archie_worker.content import episode as episode_content
from archie_worker.handlers import _text

pytestmark = pytest.mark.postgres

EPISODE = episode_content.PodcastEpisode(
    show_name="Show",
    title="Episode One",
    description="d",
    feed_url="https://example.com/feed",
    guid=None,
    audio_url="https://example.com/a.mp3",
    duration_s=None,
)


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session whose changes are rolled back."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as database:
        yield database
        database.rollback()
    engine.dispose()


def _source(db: sqlalchemy.orm.Session, *, kind: models.SourceKind) -> models.Source:
    user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
    db.add(user)
    db.flush()
    changes.lock_user_writes(db, user.id)
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url="https://example.com/a",
        normalized_url="https://example.com/a",
        kind=kind.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.QUEUE.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source


def _queued_kinds(db: sqlalchemy.orm.Session, source: models.Source) -> list[str]:
    query = sqlalchemy.select(models.Job).where(models.Job.user_id == source.user_id).order_by(models.Job.id)
    return [job.kind for job in db.scalars(query)]


@pytest.mark.parametrize(
    ("kind", "expected_steps"),
    [
        (models.SourceKind.ARTICLE, [models.JobKind.ANALYZE, models.JobKind.PRIMER]),
        (models.SourceKind.NEWSLETTER, [models.JobKind.CLEAN_TEXT, models.JobKind.ANALYZE]),
    ],
)
def test_store_text_writes_the_artifact_titles_and_queues_the_kinds_steps(
    db: sqlalchemy.orm.Session, kind: models.SourceKind, expected_steps: list[models.JobKind]
) -> None:
    """The text artifact is current, an untitled source gets the title, and `embed` plus the kind's steps are queued."""
    source = _source(db, kind=kind)

    _text.store_text(db, source=source, text_content={"text": "hello"}, title="  A  Title ")

    artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    assert artifact is not None
    assert artifact.content == {"text": "hello"}
    assert source.title == "A Title"
    assert _queued_kinds(db, source) == [models.JobKind.EMBED.value, *[step.value for step in expected_steps]]


def test_store_text_does_nothing_for_a_deleted_source(db: sqlalchemy.orm.Session) -> None:
    """A source deleted during the fetch gets no artifact and no jobs."""
    source = _source(db, kind=models.SourceKind.ARTICLE)
    source.deleted_at = sqlalchemy.func.now()
    db.flush()

    _text.store_text(db, source=source, text_content={"text": "hello"}, title="T")

    assert pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT) is None
    assert _queued_kinds(db, source) == []


def test_enqueue_transcribe_queues_one_job_with_the_episode_and_titles_the_source(db: sqlalchemy.orm.Session) -> None:
    """The job carries the episode and the transcribe attempt budget; the source gets its title."""
    source = _source(db, kind=models.SourceKind.PODCAST)

    _text.enqueue_transcribe(db, source=source, episode=EPISODE)

    job = db.scalars(sqlalchemy.select(models.Job).where(models.Job.user_id == source.user_id)).one()
    assert job.kind == models.JobKind.TRANSCRIBE.value
    assert job.payload == {pipeline.SOURCE_ID_KEY: str(source.id), "episode": EPISODE.to_payload()}
    assert job.max_attempts == pipeline.MAX_ATTEMPTS[models.JobKind.TRANSCRIBE]
    assert episode_content.PodcastEpisode.from_payload(job.payload["episode"]) == EPISODE
    assert source.title == "Episode One"


def test_store_text_fills_an_empty_image_and_keeps_an_existing_one(db: sqlalchemy.orm.Session) -> None:
    """The fetcher's artwork lands on an image-less source and bumps its change_seq; a source with one keeps both."""
    empty = _source(db, kind=models.SourceKind.ARTICLE)
    kept = _source(db, kind=models.SourceKind.ARTICLE)
    kept.image_url = "https://img.example/kept.jpg"
    kept.title = "Titled"
    db.flush()
    db.refresh(kept)
    kept_seq = kept.change_seq
    db.refresh(empty)
    empty_seq = empty.change_seq

    for source in (empty, kept):
        _text.store_text(
            db, source=source, text_content={"text": "hello"}, title=None, image_url="https://img.example/a.jpg"
        )
    db.flush()
    db.refresh(empty)
    db.refresh(kept)

    assert empty.image_url == "https://img.example/a.jpg"
    assert empty.change_seq > empty_seq
    assert (kept.image_url, kept.change_seq) == ("https://img.example/kept.jpg", kept_seq)


def test_episode_payloads_queued_before_artwork_still_load() -> None:
    """A transcribe job queued by M3 has no `image_url` key; it loads with no image."""
    payload = EPISODE.to_payload()
    del payload["image_url"]

    assert episode_content.PodcastEpisode.from_payload(payload) == EPISODE
