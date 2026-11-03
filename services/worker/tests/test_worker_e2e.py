"""The worker end to end: real jobs in a real Postgres, real handlers, HTTP replayed from recorded cassettes.

Re-record with `uv run pytest services/worker/tests --record-mode=once -m postgres` after deleting a cassette.
"""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, jobs, models, session
from archie_worker import handlers, loop

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

# Recorded pages: ogp.me has an og:title, example.com only a <title>, httpbin's /json has neither.
OG_PAGE_URL = "https://ogp.me/"
OG_PAGE_TITLE = "Open Graph protocol"
TITLE_PAGE_URL = "https://example.com/"
TITLE_PAGE_TITLE = "Example Domain"
NO_TITLE_PAGE_URL = "https://httpbin.org/json"
SERVER_ERROR_URL = "https://httpbin.org/status/500"


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> Replay:
    """Returns `use_cassette(name)`: the recorded HTTP for one page, shared across tests.

    Replay-only unless pytest is given `--record-mode`, so a normal run can never reach the network.
    """
    recorder = vcr_module.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode=request.config.getoption("--record-mode") or "none",
        # Keep recordings small, readable and free of per-request noise.
        filter_headers=["authorization", "cookie", "set-cookie"],
        decode_compressed_response=True,
    )
    # A recorded failure may replay on every retry of a job.
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def test_og_title_wins_over_the_title_tag(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A page's og:title becomes the source's title, the job finishes, and phones see a newer change position."""
    source_id = _add_source_and_job(engine, url=OG_PAGE_URL)
    seq_before = _source(engine, source_id).change_seq

    with replay("og_page"):
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    source = _source(engine, source_id)
    assert source.title == OG_PAGE_TITLE
    assert source.change_seq > seq_before
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_title_tag_is_the_fallback(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Without an og:title, the page's <title> is used."""
    source_id = _add_source_and_job(engine, url=TITLE_PAGE_URL)

    with replay("title_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).title == TITLE_PAGE_TITLE
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_page_without_a_title_still_finishes_the_job(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A missing title is a success, not a retry; the source keeps no title and no new change position."""
    source_id = _add_source_and_job(engine, url=NO_TITLE_PAGE_URL)
    seq_before = _source(engine, source_id).change_seq

    with replay("no_title_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.title is None
    assert source.change_seq == seq_before
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_a_source_deleted_before_the_job_runs_is_left_alone(engine: sqlalchemy.Engine) -> None:
    """No request is made (record mode "none" would raise) and the tombstone keeps its title and change position."""
    source_id = _add_source_and_job(engine, url=OG_PAGE_URL)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, source_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    seq_before = _source(engine, source_id).change_seq

    assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    source = _source(engine, source_id)
    assert source.title is None
    assert source.change_seq == seq_before
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_a_server_error_is_retried_with_backoff_then_fails_for_good(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A recorded 500 re-queues the job 10s out; after the last allowed attempt it is failed with its error kept."""
    source_id = _add_source_and_job(engine, url=SERVER_ERROR_URL)

    with replay("server_error"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

        job = _only_job(engine)
        assert (job.attempts, job.status) == (1, models.JobStatus.QUEUED.value)
        assert job.last_error is not None
        until_retry = job.next_run_at - datetime.datetime.now(datetime.UTC)
        assert datetime.timedelta(seconds=5) < until_retry < datetime.timedelta(seconds=15)

        _make_due(engine)
        loop.run_one(engine, handlers=handlers.HANDLERS)
        assert _only_job(engine).status == models.JobStatus.QUEUED.value

        _make_due(engine)
        loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _only_job(engine)
    assert (job.attempts, job.status) == (3, models.JobStatus.FAILED.value)
    assert job.last_error is not None
    assert _source(engine, source_id).title is None


def test_a_job_that_failed_once_succeeds_on_retry(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """After a 500, a later attempt that reaches a good page completes the job and clears the error."""
    source_id = _add_source_and_job(engine, url=SERVER_ERROR_URL)

    with replay("server_error"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    assert _only_job(engine).status == models.JobStatus.QUEUED.value

    # The link now points at a working page, standing in for the site recovering.
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, source_id).url = OG_PAGE_URL
        db.commit()
    _make_due(engine)
    with replay("og_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _only_job(engine)
    assert (job.attempts, job.status, job.last_error) == (2, models.JobStatus.DONE.value, None)
    assert _source(engine, source_id).title == OG_PAGE_TITLE


def test_only_jobs_running_too_long_are_requeued(engine: sqlalchemy.Engine) -> None:
    """A job orphaned by a crash (running for 11 minutes) is re-queued; one running 5 minutes is left alone."""
    now = datetime.datetime.now(datetime.UTC)
    user_id = _add_user(engine)
    with sqlalchemy.orm.Session(engine) as db:
        stale = _running_job(db, user_id=user_id, started_at=now - datetime.timedelta(minutes=11))
        fresh = _running_job(db, user_id=user_id, started_at=now - datetime.timedelta(minutes=5))
        db.commit()
        stale_id, fresh_id = stale.id, fresh.id

    with sqlalchemy.orm.Session(engine) as db:
        requeued = loop.requeue_stale(db, now=now)

    assert requeued == 1
    with sqlalchemy.orm.Session(engine) as db:
        assert db.get_one(models.Job, stale_id).status == models.JobStatus.QUEUED.value
        assert db.get_one(models.Job, fresh_id).status == models.JobStatus.RUNNING.value


def test_a_crashed_job_out_of_attempts_fails_instead_of_looping(engine: sqlalchemy.Engine) -> None:
    """A job that keeps killing its worker is failed by the stale sweep once its attempts are spent."""
    now = datetime.datetime.now(datetime.UTC)
    user_id = _add_user(engine)
    with sqlalchemy.orm.Session(engine) as db:
        job = _running_job(db, user_id=user_id, started_at=now - datetime.timedelta(minutes=11))
        job.attempts = job.max_attempts = 3
        db.commit()

    with sqlalchemy.orm.Session(engine) as db:
        loop.requeue_stale(db, now=now)

    assert _only_job(engine).status == models.JobStatus.FAILED.value


def test_an_idle_queue_runs_nothing(engine: sqlalchemy.Engine) -> None:
    """With no due job, `run_one` reports that nothing ran; a future-dated job isn't due yet."""
    _add_source_and_job(engine, url=OG_PAGE_URL)
    _make_due(engine, seconds_from_now=60)

    assert loop.run_one(engine, handlers=handlers.HANDLERS) is False


def _add_user(engine: sqlalchemy.Engine) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
        db.add(user)
        db.commit()
        return user.id


def _add_source_and_job(engine: sqlalchemy.Engine, *, url: str) -> uuid.UUID:
    """A user's link and its queued `fetch_title` job, as the sync push will create them."""
    user_id = _add_user(engine)
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Source(
                id=source_id,
                user_id=user_id,
                url=url,
                normalized_url=url,
                kind=models.SourceKind.LINK.value,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                change_seq=changes.next_change_seq(),
            )
        )
        jobs.enqueue(
            db,
            kind=models.JobKind.FETCH_TITLE,
            user_id=user_id,
            payload={"source_id": str(source_id)},
        )
        db.commit()
    return source_id


def _running_job(db: sqlalchemy.orm.Session, *, user_id: int, started_at: datetime.datetime) -> models.Job:
    job = jobs.enqueue(db, kind=models.JobKind.FETCH_TITLE, user_id=user_id, payload={})
    job.status = models.JobStatus.RUNNING.value
    job.attempts = 1
    job.started_at = started_at
    return job


def _make_due(engine: sqlalchemy.Engine, *, seconds_from_now: int = 0) -> None:
    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text("UPDATE jobs SET next_run_at = now() + make_interval(secs => :seconds)"),
            {"seconds": seconds_from_now},
        )


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _only_job(engine: sqlalchemy.Engine) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        return db.execute(sqlalchemy.select(models.Job)).scalar_one()
