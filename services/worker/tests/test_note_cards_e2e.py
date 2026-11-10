"""`note_cards` end to end: real jobs in a real Postgres, Anthropic replayed from a recorded real response.

Re-record `note_cards_staking` by deleting it and running
`uv run pytest services/worker/tests/test_note_cards_e2e.py --record-mode=once -m postgres` with `TEST_DATABASE_URL`
set (a fraction of a cent of Haiku; needs ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, session
from archie_llm import llm
from archie_testing import recording
from archie_worker import handlers, loop, prompts

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
# The card rules' ceiling on an answer.
MAX_ANSWER_WORDS = 15

NOTE_MARKDOWN = (
    "# Proof of stake\n\n"
    "- validators lock up coins instead of burning power\n"
    "- cheating gets the stake slashed\n"
    "- Ethereum needs 32 ETH per validator\n"
    "- energy use fell about 99.95% after the merge\n"
)

WRITE_UP = {
    "summary": {
        "gist": "Proof of stake secures a blockchain with locked-up coins instead of computing work.",
        "key_ideas": [
            {"timestamp": None, "idea": "Validators lock coins as a stake, and are chosen to propose blocks."},
            {"timestamp": None, "idea": "A validator who signs conflicting blocks has part of its stake slashed."},
            {
                "timestamp": None,
                "idea": "Attacking the chain means buying a large share of the coins, which is costly.",
            },
            {"timestamp": None, "idea": "Without mining hardware, energy use is a tiny fraction of proof of work."},
        ],
        "numbers": [
            {"timestamp": None, "fact": "Ethereum requires 32 ETH per validator."},
            {"timestamp": None, "fact": "Energy use fell about 99.95% after the switch to proof of stake."},
        ],
    },
    "domain": "technology",
    "topic": "Proof of stake",
    "tags": ["blockchain"],
    "concepts": ["slashing"],
    "is_educational": True,
    "cards": [],
    "sources": [],
}


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


def test_a_refreshed_note_gets_three_to_five_cards_from_its_write_up(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Each card belongs to the note and its current summary, and the call is one Haiku step."""
    source_id = _add_note(engine)
    summary_id = _summary_id(engine, source_id)
    _enqueue(engine, source_id)

    with replay("note_cards_staking"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    cards = _live_cards(engine)
    assert 3 <= len(cards) <= 5
    for card in cards:
        assert (card.source_id, card.artifact_id) == (source_id, summary_id)
        assert card.kind in prompts.CARD_KINDS
        assert card.question.strip() and card.answer.strip()
        assert len(card.answer.split()) <= MAX_ANSWER_WORDS
    assert len({card.change_seq for card in cards}) == len(cards)
    assert any(card.detail for card in cards)

    [call] = _llm_calls(engine)
    assert (call.step, call.model, call.source_id) == (models.JobKind.NOTE_CARDS.value, llm.HAIKU, source_id)
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_retry_never_doubles_the_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The second run retires the first run's cards, so the note never shows six to ten."""
    source_id = _add_note(engine)
    _enqueue(engine, source_id)
    _enqueue(engine, source_id)

    with replay("note_cards_staking"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert 3 <= len(_live_cards(engine)) <= 5
    assert len(_cards(engine)) > len(_live_cards(engine))


def test_a_note_with_cards_off_gets_none(engine: sqlalchemy.Engine) -> None:
    """No cassette: finishing proves no call was made."""
    source_id = _add_note(engine, cards_off=True)
    _enqueue(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _cards(engine) == []
    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_an_unrefreshed_note_gets_none(engine: sqlalchemy.Engine) -> None:
    """A note not marked Done has no cards yet, and makes no call."""
    source_id = _add_note(engine, refreshed=False)
    _enqueue(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _cards(engine) == []
    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def _add_note(engine: sqlalchemy.Engine, *, refreshed: bool = True, cards_off: bool = False) -> uuid.UUID:
    """A whitelisted user's note, consumed once refreshed, with a current summary artifact."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=True)
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        source = models.Source(
            id=source_id,
            user_id=user.id,
            url=f"note://{source_id}",
            normalized_url=f"note://{source_id}",
            title="Proof of stake",
            kind=models.SourceKind.NOTE.value,
            state=(models.SourceState.CONSUMED if refreshed else models.SourceState.INBOX).value,
            intent=models.SourceIntent.QUEUE.value,
            note_markdown=NOTE_MARKDOWN,
            refreshed_at=datetime.now(UTC) if refreshed else None,
            cards_off=cards_off,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY, content=WRITE_UP, model=None, prompt_version=None
        )
        db.commit()
    return source_id


def _enqueue(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        user_id = db.get_one(models.Source, source_id).user_id
        jobs.enqueue(
            db, kind=models.JobKind.NOTE_CARDS, user_id=user_id, payload={pipeline.SOURCE_ID_KEY: str(source_id)}
        )
        db.commit()


def _summary_id(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> uuid.UUID:
    with sqlalchemy.orm.Session(engine) as db:
        summary = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.SUMMARY)
        assert summary is not None
        return summary.id


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
