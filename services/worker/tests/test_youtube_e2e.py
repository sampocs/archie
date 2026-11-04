"""YouTube captions through `fetch_content`: real jobs in Postgres, captions and the watch page replayed from cassettes.

Re-record `youtube_powell.yaml` from a residential IP (YouTube blocks cloud ranges): delete it, then
`uv run pytest services/worker/tests/test_youtube_e2e.py --record-mode=once -m postgres` with `TEST_DATABASE_URL` set.
The Supadata branch has no cassette yet (no key); see the M3 spec's follow-ups.
"""

from __future__ import annotations

import pathlib
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, jobs, models, pipeline, session
from archie_testing import media, recording
from archie_worker import errors, handlers, loop

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
MIN_WORDS = 100


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> vcr_module.VCR:
    """The recorder: replay-only unless pytest is given `--record-mode`."""
    return recording.vcr_for(request, cassette_dir=CASSETTE_DIR)


def test_captions_become_timed_text_titled_from_the_watch_page(
    engine: sqlalchemy.Engine, replay: vcr_module.VCR
) -> None:
    """A video's captions are stored as a text artifact with ordered segments; analyze and primer are queued."""
    source_id = _add_youtube_source(engine, url=media.YOUTUBE_VIDEO_URL)

    with replay.use_cassette("youtube_powell.yaml", allow_playback_repeats=True):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        artifact = db.scalars(
            sqlalchemy.select(models.SourceArtifact).where(models.SourceArtifact.source_id == source_id)
        ).one()
        queued_jobs = db.scalars(sqlalchemy.select(models.Job).where(models.Job.status == models.JobStatus.QUEUED))
        queued = sorted(job.kind for job in queued_jobs)

    assert (artifact.kind, artifact.is_current) == (models.ArtifactKind.TEXT, True)
    assert len(artifact.content["text"].split()) >= MIN_WORDS
    starts = [segment["start"] for segment in artifact.content["segments"]]
    assert len(starts) > 5
    assert starts == sorted(starts)
    assert source.title and source.title != media.YOUTUBE_VIDEO_URL
    assert source.processing == models.ProcessingStatus.PROCESSING
    assert queued == sorted([models.JobKind.ANALYZE, models.JobKind.PRIMER])


def test_a_video_url_without_an_id_fails_for_good_without_a_request(
    engine: sqlalchemy.Engine, replay: vcr_module.VCR
) -> None:
    """A channel link has no video to read: one attempt, the video-unavailable reason, no artifact."""
    source_id = _add_youtube_source(engine, url="https://www.youtube.com/@somechannel")

    with replay.use_cassette("no_requests.yaml") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 0
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        job = db.scalars(sqlalchemy.select(models.Job)).one()
    assert source.processing_error == errors.FailureReason.VIDEO_UNAVAILABLE
    assert (job.attempts, job.status) == (1, models.JobStatus.FAILED)


def _add_youtube_source(engine: sqlalchemy.Engine, *, url: str) -> uuid.UUID:
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        db.add(
            models.Source(
                id=source_id,
                user_id=user.id,
                url=url,
                normalized_url=url,
                kind=models.SourceKind.YOUTUBE.value,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        jobs.enqueue(
            db,
            kind=models.JobKind.FETCH_CONTENT,
            user_id=user.id,
            payload={pipeline.SOURCE_ID_KEY: str(source_id)},
        )
        db.commit()
    return source_id
