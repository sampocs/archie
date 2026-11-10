"""Topic primers end to end: real jobs in a real Postgres, Anthropic replayed from a recorded real response.

Re-record `topic_primer_fed` with `uv run pytest services/worker/tests/test_topic_primer_e2e.py --record-mode=once
-m postgres` after deleting the cassette (a couple of cents; needs ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator, Sequence

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session, topic_primers, user_topics
from archie_llm import llm
from archie_testing import recording
from archie_worker import handlers, loop, prompts

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
TOPIC_NAME = "Fed & monetary policy"
SOURCE_TITLES = ["Powell's Jackson Hole speech", "Why the yield curve inverted"]
MIN_FOUNDATION_CARDS = 2
# The card rules' ceiling on an answer.
MAX_ANSWER_WORDS = 15


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
    """Returns `use_cassette(name)`: the recorded Anthropic HTTP for one test."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def test_topic_primer_writes_the_first_version(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A user topic with two sources gets a current v1 primer from Sonnet, and a costed call tied to no source."""
    topic_id = _add_topic(engine, source_titles=SOURCE_TITLES)
    _enqueue(engine, topic_id)

    with replay("topic_primer_fed"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [primer] = _primers(engine, topic_id)
    assert primer.is_current
    assert primer.version == 1
    assert primer.content["markdown"].startswith("#")
    assert primer.model == llm.SONNET
    assert primer.prompt_version == prompts.TOPIC_PRIMER_PROMPT_VERSION == "topic-primer-v3"
    assert "<foundation_cards>" not in primer.content["markdown"]
    with sqlalchemy.orm.Session(engine) as db:
        [embed] = db.scalars(sqlalchemy.select(models.Job).where(models.Job.kind == models.JobKind.EMBED.value))
    assert embed.status == models.JobStatus.QUEUED.value
    assert embed.payload[jobs.ITEM_KIND_KEY] == "topic_primer"
    assert embed.payload[jobs.ITEM_ID_KEY] == str(primer.id)
    [call] = _llm_calls(engine)
    assert call.step == models.JobKind.TOPIC_PRIMER.value
    assert call.source_id is None
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_topic_primer_writes_foundation_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The primer's foundation cards belong to the topic primer, not to any source."""
    topic_id = _add_topic(engine, source_titles=SOURCE_TITLES)
    _enqueue(engine, topic_id)

    with replay("topic_primer_fed"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [primer] = _primers(engine, topic_id)
    cards = _cards(engine, topic_id)
    assert MIN_FOUNDATION_CARDS <= len(cards) <= prompts.MAX_FOUNDATION_CARDS
    assert all(card.topic_primer_id == primer.id and card.source_id is None for card in cards)
    assert all(card.kind == models.CardKind.FOUNDATION.value and card.deleted_at is None for card in cards)
    assert all(card.question.strip() and card.answer.strip() for card in cards)
    # The card rules: a short answer, with the why in the detail lines.
    assert all(len(card.answer.split()) <= MAX_ANSWER_WORDS for card in cards)
    assert any(card.detail for card in cards)


def test_a_new_topic_primer_version_retires_the_older_versions_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Writing a newer version retires the foundation cards of every older one and keeps its own."""
    topic_id = _add_topic(engine, source_titles=SOURCE_TITLES)
    _write(engine, topic_id, "# Older")
    older_card_seqs = _add_foundation_cards(engine, topic_id)
    _enqueue(engine, topic_id)

    with replay("topic_primer_fed"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    older, newer = _primers(engine, topic_id)
    cards = _cards(engine, topic_id)
    retired = [card for card in cards if card.topic_primer_id == older.id]
    assert {card.id for card in retired} == set(older_card_seqs)
    assert all(card.deleted_at is not None and card.change_seq > older_card_seqs[card.id] for card in retired)
    live = [card for card in cards if card.topic_primer_id == newer.id]
    assert MIN_FOUNDATION_CARDS <= len(live) <= prompts.MAX_FOUNDATION_CARDS
    assert all(card.deleted_at is None for card in live)


def test_removed_topic_gets_no_primer_and_no_call(engine: sqlalchemy.Engine) -> None:
    """A topic the user removed before the job ran is skipped without calling the model."""
    topic_id = _add_topic(engine, removed=True)
    _enqueue(engine, topic_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _primers(engine, topic_id) == []
    assert _llm_calls(engine) == []
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_topic_with_a_current_primer_is_left_alone(engine: sqlalchemy.Engine) -> None:
    """A repeated request does not write a second version or spend a call."""
    topic_id = _add_topic(engine)
    _write(engine, topic_id, "# Existing")
    _enqueue(engine, topic_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    [primer] = _primers(engine, topic_id)
    assert primer.content["markdown"] == "# Existing"
    assert _llm_calls(engine) == []


def test_writing_twice_keeps_the_old_version_not_current(engine: sqlalchemy.Engine) -> None:
    """v2 becomes current, v1 stays as history, and both get fresh change positions."""
    topic_id = _add_topic(engine)

    first_seq = _write(engine, topic_id, "# One")
    second_seq = _write(engine, topic_id, "# Two")

    first, second = _primers(engine, topic_id)
    assert (first.version, first.is_current) == (1, False)
    assert (second.version, second.is_current) == (2, True)
    assert first.change_seq > first_seq
    assert second.change_seq == second_seq > first.change_seq


def _add_topic(engine: sqlalchemy.Engine, *, source_titles: Sequence[str] = (), removed: bool = False) -> uuid.UUID:
    """A whitelisted user with one topic and a live source per title."""
    topic_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=True)
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        db.add(
            models.Topic(
                id=topic_id,
                user_id=user.id,
                domain="Macro",
                name=TOPIC_NAME,
                origin=models.TopicOrigin.USER.value,
                removed_at=sqlalchemy.func.now() if removed else None,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        for title in source_titles:
            url = f"https://example.com/{uuid.uuid4()}"
            db.add(
                models.Source(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    url=url,
                    normalized_url=url,
                    title=title,
                    kind=models.SourceKind.ARTICLE.value,
                    state=models.SourceState.INBOX.value,
                    intent=models.SourceIntent.QUEUE.value,
                    domain="Macro",
                    topic_id=topic_id,
                    change_seq=changes.next_change_seq(),
                )
            )
        db.commit()
    return topic_id


def _enqueue(engine: sqlalchemy.Engine, topic_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        topic = db.get_one(models.Topic, topic_id)
        jobs.enqueue(
            db,
            kind=models.JobKind.TOPIC_PRIMER,
            user_id=topic.user_id,
            payload={user_topics.TOPIC_ID_KEY: str(topic_id)},
        )
        db.commit()


def _write(engine: sqlalchemy.Engine, topic_id: uuid.UUID, markdown: str) -> int:
    """Write a primer version under the user's lock; returns its change position."""
    with sqlalchemy.orm.Session(engine) as db:
        topic = db.get_one(models.Topic, topic_id)
        changes.lock_user_writes(db, topic.user_id)
        primer = topic_primers.write(
            db, topic=topic, markdown=markdown, model=llm.SONNET, prompt_version=prompts.TOPIC_PRIMER_PROMPT_VERSION
        )
        db.commit()
        return primer.change_seq


def _add_foundation_cards(engine: sqlalchemy.Engine, topic_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Two foundation cards on the topic's current primer, which is then left not current so a new one is written.

    Returns each card's change position.
    """
    with sqlalchemy.orm.Session(engine) as db:
        primer = db.scalars(
            sqlalchemy.select(models.TopicPrimer).where(
                models.TopicPrimer.topic_id == topic_id, models.TopicPrimer.is_current
            )
        ).one()
        changes.lock_user_writes(db, primer.user_id)
        cards = [
            models.Card(
                id=uuid.uuid4(),
                user_id=primer.user_id,
                topic_primer_id=primer.id,
                kind=models.CardKind.FOUNDATION.value,
                question=f"Older question {index}?",
                answer="Older answer.",
                change_seq=changes.next_change_seq(),
            )
            for index in range(2)
        ]
        db.add_all(cards)
        primer.is_current = False
        db.commit()
        return {card.id: card.change_seq for card in cards}


def _primers(engine: sqlalchemy.Engine, topic_id: uuid.UUID) -> list[models.TopicPrimer]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.TopicPrimer)
                .where(models.TopicPrimer.topic_id == topic_id)
                .order_by(models.TopicPrimer.version)
            )
        )


def _cards(engine: sqlalchemy.Engine, topic_id: uuid.UUID) -> list[models.Card]:
    """Every card, live or retired, on any version of the topic's primer."""
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.Card)
                .join(models.TopicPrimer, models.Card.topic_primer_id == models.TopicPrimer.id)
                .where(models.TopicPrimer.topic_id == topic_id)
            )
        )


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))


def _only_job(engine: sqlalchemy.Engine) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        # The search passages job the new primer queues is not what these tests look at.
        return db.scalars(sqlalchemy.select(models.Job).where(models.Job.kind != models.JobKind.EMBED.value)).one()
