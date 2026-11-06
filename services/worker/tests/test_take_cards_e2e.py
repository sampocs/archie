"""`take_cards` end to end: real jobs in a real Postgres, Anthropic replayed from a recorded real response.

Re-record `take_cards_crypto` by deleting it and running
`uv run pytest services/worker/tests/test_take_cards_e2e.py --record-mode=once -m postgres` with `TEST_DATABASE_URL`
set (a fraction of a cent of Haiku; needs ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import pathlib
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session
from archie_llm import llm
from archie_testing import recording
from archie_worker import errors, handlers, loop
from archie_worker.handlers import take_cards

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

CLEANED = (
    "Crypto's lasting use isn't speculation. It's moving dollars, and it already works.\n\n"
    "## Main points\n\n"
    "- Stablecoins settle ~$10T a year, already Visa scale, with no bank in the middle.\n"
    "- Dollar demand abroad: people in high-inflation countries want dollars, and stablecoins are the easiest way to "
    "hold them.\n"
    "- Open rails: anyone can build payments on them without a bank partnership.\n\n"
    '## When they say "it\'s just a casino"\n\n'
    "Most volume is speculation, agreed. But the payment use is growing whatever happens to prices."
)


@dataclass(frozen=True)
class TakeIds:
    """A test take and its versions, oldest first."""

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


def test_a_take_gets_two_to_four_cards_in_its_own_words(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The recorded answer cites only numbers the take has, and each card names the version it came from."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, bodies=[CLEANED])
    _enqueue(engine, ids.version_ids[0])

    with replay("take_cards_crypto"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    cards = _live_cards(engine)
    assert 2 <= len(cards) <= take_cards.MAX_TAKE_CARDS
    for card in cards:
        assert card.kind == models.CardKind.TAKE.value
        assert (card.take_id, card.take_version_id) == (ids.take_id, ids.version_ids[0])
        assert (card.source_id, card.artifact_id, card.topic_primer_id, card.brief_id) == (None, None, None, None)
        assert card.fsrs_state == models.FsrsState.NEW.value
        assert card.question.strip() and card.answer.strip()
        assert set(re.findall(r"\d+(?:\.\d+)?", card.answer)) <= set(re.findall(r"\d+(?:\.\d+)?", CLEANED))
    assert len({card.change_seq for card in cards}) == len(cards)

    [call] = _llm_calls(engine)
    assert (call.step, call.model, call.source_id) == (models.JobKind.TAKE_CARDS.value, llm.HAIKU, None)
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_new_version_retires_the_previous_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The old card stays as a soft-deleted row with a newer position, so phones drop it."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, bodies=["Old take.", CLEANED])
    old_card_id = _add_old_card(engine, take_id=ids.take_id, version_id=ids.version_ids[0])
    old_seq = _card(engine, old_card_id).change_seq
    _enqueue(engine, ids.version_ids[1])

    with replay("take_cards_crypto"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    old = _card(engine, old_card_id)
    assert old.deleted_at is not None and old.change_seq > old_seq
    new_cards = _live_cards(engine)
    assert new_cards and all(card.take_version_id == ids.version_ids[1] for card in new_cards)


def test_a_version_that_is_no_longer_current_gets_no_cards(engine: sqlalchemy.Engine) -> None:
    """No cassette: a request would fail the job, so finishing proves no call was made."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, bodies=[CLEANED, "Newer."])
    _enqueue(engine, ids.version_ids[0])

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _live_cards(engine) == []
    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_deleted_take_gets_no_cards(engine: sqlalchemy.Engine) -> None:
    """A take deleted before its job runs wants no cards and makes no call."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, bodies=[CLEANED])
    _delete_take(engine, ids.take_id)
    _enqueue(engine, ids.version_ids[0])

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _live_cards(engine) == []
    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_version_still_being_cleaned_gets_no_cards(engine: sqlalchemy.Engine) -> None:
    """Its body is null until `clean_take` lands, which queues this job again."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, bodies=[None])
    _enqueue(engine, ids.version_ids[0])

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _live_cards(engine) == []
    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_save_during_the_call_wins(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A version added mid-call is re-checked under the lock: nothing is written and the old card stays live."""
    user_id = _add_user(engine)
    ids = _add_take(engine, user_id=user_id, bodies=[CLEANED])
    old_card_id = _add_old_card(engine, take_id=ids.take_id, version_id=ids.version_ids[0])
    _enqueue(engine, ids.version_ids[0])
    real_complete = llm.complete

    def complete_then_save(*args: Any, **kwargs: Any) -> Any:
        completion = real_complete(*args, **kwargs)
        with sqlalchemy.orm.Session(engine) as db:
            changes.lock_user_writes(db, user_id)
            _add_version(db, user_id=user_id, take_id=ids.take_id, version=2, body="Newer.")
            db.get_one(models.Take, ids.take_id).current_version = 2
            db.commit()
        return completion

    monkeypatch.setattr(llm, "complete", complete_then_save)

    with replay("take_cards_crypto"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert [card.id for card in _live_cards(engine)] == [old_card_id]
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_without_a_key_the_job_fails_and_nothing_is_written(engine: sqlalchemy.Engine) -> None:
    """No cassette and no changes: the job fails before any call, leaving the old card alone."""
    user_id = _add_user(engine, is_whitelisted=False)
    ids = _add_take(engine, user_id=user_id, bodies=[CLEANED])
    old_card_id = _add_old_card(engine, take_id=ids.take_id, version_id=ids.version_ids[0])
    _enqueue(engine, ids.version_ids[0])

    loop.run_one(engine, handlers=handlers.HANDLERS)

    [job] = _jobs(engine)
    assert (job.status, job.last_error) == (models.JobStatus.FAILED.value, errors.FailureReason.NEEDS_API_KEY)
    assert [card.id for card in _live_cards(engine)] == [old_card_id]
    assert _llm_calls(engine) == []


def _add_user(engine: sqlalchemy.Engine, *, is_whitelisted: bool = True) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.commit()
        return user.id


def _add_version(
    db: sqlalchemy.orm.Session, *, user_id: int, take_id: uuid.UUID, version: int, body: str | None
) -> uuid.UUID:
    version_id = uuid.uuid4()
    db.add(
        models.TakeVersion(
            id=version_id,
            user_id=user_id,
            take_id=take_id,
            version=version,
            body=body,
            raw_body=body or "raw",
            cleaned=False,
            change_seq=changes.next_change_seq(),
        )
    )
    return version_id


def _add_take(engine: sqlalchemy.Engine, *, user_id: int, bodies: list[str | None]) -> TakeIds:
    """A talking point with one version per body (version n is index + 1), the last being current."""
    take_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Take(
                id=take_id,
                user_id=user_id,
                kind=models.TakeKind.TALKING_POINT.value,
                title="The argument for crypto",
                current_version=len(bodies),
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        version_ids = [
            _add_version(db, user_id=user_id, take_id=take_id, version=index + 1, body=body)
            for index, body in enumerate(bodies)
        ]
        db.commit()
    return TakeIds(take_id=take_id, version_ids=version_ids)


def _enqueue(engine: sqlalchemy.Engine, version_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        user_id = db.get_one(models.TakeVersion, version_id).user_id
        jobs.enqueue(
            db, kind=models.JobKind.TAKE_CARDS, user_id=user_id, payload={jobs.TAKE_VERSION_ID_KEY: str(version_id)}
        )
        db.commit()


def _add_old_card(engine: sqlalchemy.Engine, *, take_id: uuid.UUID, version_id: uuid.UUID) -> uuid.UUID:
    """A live take card from an earlier run."""
    card_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user_id = db.get_one(models.Take, take_id).user_id
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Card(
                id=card_id,
                user_id=user_id,
                take_id=take_id,
                take_version_id=version_id,
                kind=models.CardKind.TAKE.value,
                question="Old question?",
                answer="Old answer.",
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    return card_id


def _delete_take(engine: sqlalchemy.Engine, take_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Take, take_id).deleted_at = sqlalchemy.func.now()
        db.commit()


def _card(engine: sqlalchemy.Engine, card_id: uuid.UUID) -> models.Card:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Card, card_id)


def _cards(engine: sqlalchemy.Engine) -> list[models.Card]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Card).order_by(models.Card.change_seq)))


def _live_cards(engine: sqlalchemy.Engine) -> list[models.Card]:
    return [card for card in _cards(engine) if card.deleted_at is None]


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
