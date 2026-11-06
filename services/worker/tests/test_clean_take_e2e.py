"""`clean_take` end to end: real jobs in a real Postgres, Anthropic replayed from a recorded real response.

Re-record `clean_take_crypto` by deleting it and running
`uv run pytest services/worker/tests/test_clean_take_e2e.py --record-mode=once -m postgres` (a few cents of Sonnet;
needs ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session, takes
from archie_llm import llm
from archie_testing import recording
from archie_worker import errors, handlers, loop

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
RAMBLE = (
    "ok so the main thing is people think it's all speculation and like most of it is, fine, but the actual use "
    "that's working is moving dollars. stablecoins did something like 10 trillion last year which is basically visa. "
    "and people in argentina or turkey want dollars and this is the easiest way. and the other thing is anyone can "
    "build on it, you don't need a bank partner"
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class TakeIds:
    """The rows `_add_take` made."""

    take_id: uuid.UUID
    version_ids: list[uuid.UUID]


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> Replay:
    """Returns `use_cassette(name)`: the recorded Anthropic HTTP for one test, replayable any number of times."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def _add_user(engine: sqlalchemy.Engine, *, is_whitelisted: bool = True) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.commit()
        return user.id


def _add_take(engine: sqlalchemy.Engine, *, user_id: int, raw_body: str, versions: int = 1) -> TakeIds:
    """A talking point with `versions` uncleaned versions and a `clean_take` job for the first."""
    take_id = uuid.uuid4()
    version_ids = [uuid.uuid4() for _ in range(versions)]
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Take(
                id=take_id,
                user_id=user_id,
                kind=models.TakeKind.TALKING_POINT.value,
                title="The argument for crypto",
                current_version=versions,
                created_at=datetime.datetime.now(datetime.UTC),
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        for number, version_id in enumerate(version_ids, start=1):
            db.add(
                models.TakeVersion(
                    id=version_id,
                    user_id=user_id,
                    take_id=take_id,
                    version=number,
                    body=None,
                    raw_body=raw_body,
                    cleaned=True,
                    change_seq=changes.next_change_seq(),
                )
            )
        db.flush()
        first = db.get_one(models.TakeVersion, version_ids[0])
        takes.enqueue_step(db, version=first, kind=models.JobKind.CLEAN_TAKE)
        db.commit()
    return TakeIds(take_id=take_id, version_ids=version_ids)


def _version(engine: sqlalchemy.Engine, version_id: uuid.UUID) -> models.TakeVersion:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.TakeVersion, version_id)


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))


def _kinds_and_statuses(engine: sqlalchemy.Engine) -> list[tuple[str, str]]:
    return [(job.kind, job.status) for job in _jobs(engine)]


def test_a_rambling_dictation_becomes_a_short_take_in_its_own_words(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The body is short markdown that keeps the owner's claims and numbers, and the take's cards are queued."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, raw_body=RAMBLE)
    version_id = ids.version_ids[0]
    seq_before = _version(engine, version_id).change_seq

    with replay("clean_take_crypto"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    version = _version(engine, version_id)
    assert version.body is not None
    assert "## Main points" in version.body
    assert len([line for line in version.body.splitlines() if line.startswith("- ")]) >= 2
    assert "stablecoin" in version.body.lower()
    assert "bank" in version.body.lower()
    # Nothing invented: every number in the take is one the owner said.
    assert set(NUMBER.findall(version.body)) <= set(NUMBER.findall(RAMBLE))
    assert not version.clean_failed
    assert version.change_seq > seq_before

    assert _kinds_and_statuses(engine) == [
        (models.JobKind.CLEAN_TAKE, models.JobStatus.DONE),
        (models.JobKind.TAKE_CARDS, models.JobStatus.QUEUED),
    ]
    assert _jobs(engine)[1].payload == {jobs.TAKE_VERSION_ID_KEY: str(version_id)}

    [call] = _llm_calls(engine)
    assert (call.step, call.model, call.source_id) == (models.JobKind.CLEAN_TAKE, llm.SONNET, None)


def test_a_version_replaced_meanwhile_is_still_cleaned_but_gets_no_cards(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """Version 1 is cleaned for the record while version 2 is current; the newer save queued its own steps."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, raw_body=RAMBLE, versions=2)

    with replay("clean_take_crypto"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _version(engine, ids.version_ids[0]).body is not None
    assert _version(engine, ids.version_ids[1]).body is None
    assert _kinds_and_statuses(engine) == [(models.JobKind.CLEAN_TAKE, models.JobStatus.DONE)]


def test_without_a_key_the_raw_text_stands_in_and_the_cards_still_come(engine: sqlalchemy.Engine) -> None:
    """A user without a key fails before any call; the failure hook shows the raw text and queues the cards."""
    user_id = _add_user(engine, is_whitelisted=False)
    ids = _add_take(engine, user_id=user_id, raw_body=RAMBLE)
    version_id = ids.version_ids[0]

    loop.run_one(engine, handlers=handlers.HANDLERS)

    clean_job, cards_job = _jobs(engine)
    assert (clean_job.status, clean_job.last_error) == (models.JobStatus.FAILED, errors.FailureReason.NEEDS_API_KEY)
    assert (cards_job.kind, cards_job.status) == (models.JobKind.TAKE_CARDS, models.JobStatus.QUEUED)
    assert cards_job.payload == {jobs.TAKE_VERSION_ID_KEY: str(version_id)}

    version = _version(engine, version_id)
    assert version.body == RAMBLE
    assert version.clean_failed
    assert _llm_calls(engine) == []


def test_a_failed_cleanup_of_a_replaced_version_queues_no_cards(engine: sqlalchemy.Engine) -> None:
    """The failure hook still shows the raw text, but a stale version gets no cards."""
    user_id = _add_user(engine, is_whitelisted=False)
    ids = _add_take(engine, user_id=user_id, raw_body=RAMBLE, versions=2)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    version = _version(engine, ids.version_ids[0])
    assert (version.body, version.clean_failed) == (RAMBLE, True)
    assert _kinds_and_statuses(engine) == [(models.JobKind.CLEAN_TAKE, models.JobStatus.FAILED)]


def test_a_deleted_take_is_left_alone(engine: sqlalchemy.Engine) -> None:
    """No call, the job is done, the body stays empty and no cards are queued."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, raw_body=RAMBLE)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Take, ids.take_id).deleted_at = datetime.datetime.now(datetime.UTC)
        db.commit()

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _version(engine, ids.version_ids[0]).body is None
    assert _kinds_and_statuses(engine) == [(models.JobKind.CLEAN_TAKE, models.JobStatus.DONE)]
    assert _llm_calls(engine) == []


def test_a_version_that_already_has_a_body_is_left_alone(engine: sqlalchemy.Engine) -> None:
    """A duplicate job makes no call and changes nothing."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, raw_body=RAMBLE)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.TakeVersion, ids.version_ids[0]).body = "Already written."
        db.commit()
    before = _version(engine, ids.version_ids[0])

    loop.run_one(engine, handlers=handlers.HANDLERS)

    after = _version(engine, ids.version_ids[0])
    assert (after.body, after.change_seq) == ("Already written.", before.change_seq)
    assert _kinds_and_statuses(engine) == [(models.JobKind.CLEAN_TAKE, models.JobStatus.DONE)]
    assert _llm_calls(engine) == []
