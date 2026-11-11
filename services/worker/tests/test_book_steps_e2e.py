"""Books end to end in the worker: the spoiler-free primer, the refresher (`write_book`) and the cards (`book_cards`).

Real jobs in a real Postgres, Anthropic replayed from recorded real responses (the primer and the refresher search the
web inside the call). Re-record a cassette by deleting it and running
`uv run pytest services/worker/tests/test_book_steps_e2e.py --record-mode=once -m postgres` with `TEST_DATABASE_URL` set
(a few cents of Sonnet and web searches; needs ANTHROPIC_API_KEY in the repo root .env).
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
from archie_db import changes, jobs, models, pipeline, session, user_topics
from archie_llm import llm
from archie_testing import recording
from archie_worker import handlers, loop, prompts
from archie_worker.handlers import book_cards

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
TITLE = "Thinking, Fast and Slow"
AUTHOR = "Daniel Kahneman"
THOUGHTS = "Anchoring stuck with me most, and how confident System 1 feels even when it is wrong."
OWNER_WORDS = ("your notes", "your thoughts", "the reader", "you noted")
# Each kind's lower bound in the prompt; the upper bound is the handler's cap.
BOOK_CARD_FLOORS = {prompts.BookKind.HOW_TO: 4, prompts.BookKind.IDEA: 6, prompts.BookKind.TEXTBOOK: 10}

REFRESHER = {
    "summary": {
        "gist": "Kahneman describes two modes of thought: fast, intuitive System 1 and slow, effortful System 2.",
        "key_ideas": [
            {"timestamp": None, "idea": "**Two systems.** System 1 is automatic; System 2 is deliberate and lazy."},
            {"timestamp": None, "idea": "**Anchoring.** An arbitrary number shifts later estimates toward it."},
            {"timestamp": None, "idea": "**Loss aversion.** Losses weigh about twice as much as equal gains."},
            {"timestamp": None, "idea": "**WYSIATI.** System 1 builds a story only from the evidence at hand."},
            {"timestamp": None, "idea": "**Availability.** What comes to mind easily feels more common."},
            {"timestamp": None, "idea": "**Planning fallacy.** Plans ignore base rates and run over."},
        ],
        "numbers": [{"timestamp": None, "fact": "Losses feel roughly twice as strong as gains of the same size."}],
    },
    "domain": "science",
    "topic": "Behavioral economics",
    "tags": ["psychology"],
    "concepts": ["System 1", "anchoring"],
    "is_educational": True,
    "cards": [],
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


def test_a_reading_books_primer_is_markdown_with_no_foundation_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The book primer lands as the primer artifact; the reading book is then READY and has no cards."""
    source_id = _add_book(engine, state=models.SourceState.READING)
    _enqueue(engine, source_id, kind=models.JobKind.PRIMER)

    with replay("book_primer_thinking_fast"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    primer = _current(engine, source_id, kind=models.ArtifactKind.PRIMER)
    assert primer.prompt_version == "book-primer-v1"
    # Only the text after the last search: the primer itself, opening with its title.
    assert primer.content["markdown"].startswith("#")
    assert "Kahneman" in primer.content["markdown"]
    assert _cards(engine) == []
    assert _source(engine, source_id).processing == models.ProcessingStatus.READY.value

    [call] = _llm_calls(engine)
    assert (call.step, call.model, call.source_id) == (models.JobKind.PRIMER.value, llm.SONNET, source_id)
    assert models.JobKind.EMBED.value in _queued_kinds(engine)


def test_a_finished_book_gets_its_refresher_as_summary_and_text_then_its_cards_queued(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """The refresher has no cards and no timestamps; its text is indexed; search, filing and cards follow."""
    source_id = _add_book(engine, state=models.SourceState.CONSUMED, note=THOUGHTS)
    _enqueue(engine, source_id, kind=models.JobKind.WRITE_BOOK)

    with replay("write_book_thinking_fast"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    summary = _current(engine, source_id, kind=models.ArtifactKind.SUMMARY)
    content = summary.content
    assert summary.prompt_version == "book-write-up-v1"
    assert content["cards"] == []
    assert len(content["summary"]["key_ideas"]) >= 4
    assert all(item["timestamp"] is None for item in content["summary"]["key_ideas"])
    prose = " ".join([content["summary"]["gist"], *(item["idea"] for item in content["summary"]["key_ideas"])])
    assert not [words for words in OWNER_WORDS if words in prose.lower()]

    text = _current(engine, source_id, kind=models.ArtifactKind.TEXT)
    assert text.content == {"text": prompts.summary_text(content)}
    assert _source(engine, source_id).processing == models.ProcessingStatus.READY.value

    [call] = _llm_calls(engine)
    assert (call.step, call.model, call.source_id) == (models.JobKind.WRITE_BOOK.value, llm.SONNET, source_id)
    queued = _queued_kinds(engine)
    assert {models.JobKind.EMBED.value, models.JobKind.FILE_TOPIC.value, models.JobKind.BOOK_CARDS.value} <= queued


def test_a_book_that_already_has_cards_gets_no_book_cards_job(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A bootstrap book arrives with its hand-tuned cards, so its refresher queues search and filing only."""
    source_id = _add_book(engine, state=models.SourceState.CONSUMED, with_card=True)
    _enqueue(engine, source_id, kind=models.JobKind.WRITE_BOOK)

    with replay("write_book_thinking_fast"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    queued = _queued_kinds(engine)
    assert {models.JobKind.EMBED.value, models.JobKind.FILE_TOPIC.value} <= queued
    assert models.JobKind.BOOK_CARDS.value not in queued
    assert len(_cards(engine)) == 1


def test_a_deleted_book_is_not_written_up(engine: sqlalchemy.Engine) -> None:
    """No cassette: a request would fail the job, so finishing proves no call was made."""
    source_id = _add_book(engine, state=models.SourceState.CONSUMED)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, source_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    _enqueue(engine, source_id, kind=models.JobKind.WRITE_BOOK)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_book_cards_follow_the_kind_the_model_named(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The count sits inside the named kind's range, and each card belongs to the book and its refresher."""
    source_id = _add_book(engine, state=models.SourceState.CONSUMED, note=THOUGHTS, refresher=True)
    summary = _current(engine, source_id, kind=models.ArtifactKind.SUMMARY)
    _enqueue(engine, source_id, kind=models.JobKind.BOOK_CARDS)

    with replay("book_cards_thinking_fast"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    cards = _cards(engine)
    kinds = [kind for kind, floor in BOOK_CARD_FLOORS.items() if floor <= len(cards) <= book_cards.BOOK_CARD_CAPS[kind]]
    assert kinds
    for card in cards:
        assert (card.source_id, card.artifact_id) == (source_id, summary.id)
        assert card.kind in prompts.CARD_KINDS
        assert card.available_at is None

    [call] = _llm_calls(engine)
    assert (call.step, call.model) == (models.JobKind.BOOK_CARDS.value, llm.SONNET)


def test_book_cards_are_cut_to_the_kinds_cap(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever kind the model names, a list longer than its cap keeps only the first (most important) cards."""
    monkeypatch.setattr(book_cards, "BOOK_CARD_CAPS", dict.fromkeys(prompts.BookKind, 2))
    source_id = _add_book(engine, state=models.SourceState.CONSUMED, note=THOUGHTS, refresher=True)
    _enqueue(engine, source_id, kind=models.JobKind.BOOK_CARDS)

    with replay("book_cards_thinking_fast"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert len(_cards(engine)) == 2


def test_a_reading_book_gets_no_book_cards(engine: sqlalchemy.Engine) -> None:
    """Cards come when the book is finished: a reading book's job ends without a call."""
    source_id = _add_book(engine, state=models.SourceState.READING, refresher=True)
    _enqueue(engine, source_id, kind=models.JobKind.BOOK_CARDS)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _cards(engine) == []
    assert _llm_calls(engine) == []


def _add_book(
    engine: sqlalchemy.Engine,
    *,
    state: models.SourceState,
    note: str | None = None,
    with_card: bool = False,
    refresher: bool = False,
) -> uuid.UUID:
    """A whitelisted user who has chosen topics, with a book (and maybe a hand-tuned card or a refresher)."""
    source_id = uuid.uuid4()
    url = "https://openlibrary.org/works/OL15992072W"
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=True)
        db.add(user)
        db.flush()
        changes.lock_user_writes(db, user.id)
        user_topics.seed_owner_topics(db, user=user)

        source = models.Source(
            id=source_id,
            user_id=user.id,
            url=url,
            normalized_url=url,
            title=TITLE,
            author=AUTHOR,
            kind=models.SourceKind.BOOK.value,
            state=state.value,
            intent=models.SourceIntent.FINISHED.value,
            processing=models.ProcessingStatus.PROCESSING.value,
            note=note,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        if with_card:
            db.add(
                models.Card(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    source_id=source_id,
                    kind=models.CardKind.CONCEPT.value,
                    question="What does System 1 do?",
                    answer="Fast, automatic thinking",
                    available_at=datetime(2026, 12, 1, tzinfo=UTC),
                    change_seq=changes.next_change_seq(),
                )
            )
        if refresher:
            pipeline.write_artifact(
                db, source=source, kind=models.ArtifactKind.SUMMARY, content=REFRESHER, model=None, prompt_version=None
            )
        db.commit()
    return source_id


def _enqueue(engine: sqlalchemy.Engine, source_id: uuid.UUID, *, kind: models.JobKind) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        user_id = db.get_one(models.Source, source_id).user_id
        jobs.enqueue(db, kind=kind, user_id=user_id, payload={pipeline.SOURCE_ID_KEY: str(source_id)})
        db.commit()


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _current(engine: sqlalchemy.Engine, source_id: uuid.UUID, *, kind: models.ArtifactKind) -> models.SourceArtifact:
    with sqlalchemy.orm.Session(engine) as db:
        artifact = pipeline.current_artifact(db, source_id=source_id, kind=kind)
        assert artifact is not None
        return artifact


def _cards(engine: sqlalchemy.Engine) -> list[models.Card]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.Card).where(models.Card.deleted_at.is_(None)).order_by(models.Card.change_seq)
            )
        )


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _queued_kinds(engine: sqlalchemy.Engine) -> set[str]:
    return {job.kind for job in _jobs(engine) if job.status == models.JobStatus.QUEUED.value}


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
