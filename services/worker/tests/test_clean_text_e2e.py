"""`clean_text` end to end: real jobs in a real Postgres, Anthropic replayed from a recorded real response.

`fixtures/morning_brew.md` is the API's Morning Brew fixture as ingest and `fetch_content` store it (the email's HTML
reduced to markdown, then tidied as a capture). Re-record with
`uv run pytest services/worker/tests/test_clean_text_e2e.py --record-mode=once -m postgres` after deleting
`cassettes/clean_text_morning_brew.yaml` (a fraction of a cent; needs ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, session
from archie_llm import llm
from archie_testing import recording
from archie_worker import content, handlers, loop, prompts
from archie_worker.handlers import clean_text

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

TESTS_DIR = pathlib.Path(__file__).parent
CASSETTE_DIR = TESTS_DIR / "cassettes"
MORNING_BREW_TEXT = (TESTS_DIR / "fixtures" / "morning_brew.md").read_text()
MORNING_BREW_URL = "https://example.invalid/tracked"
MORNING_BREW_TITLE = "☕ Putting it to a vote"

# Paragraphs that open each of the issue's stories, and the referral block's, as they appear in the fixture.
STORY_OPENINGS = (
    "**Mission control:** Currently, Republicans control both chambers of Congress",
    "**💰 Marvell bets $115 billion on lasers",
    "Boiled gelato was the plat du jour after hackers targeted fridges",
    "If the people of Washington, DC are tired of having this issue forced down their throats",
)
REFERRAL_BLOCK = (
    "Share the Brew, watch your referral count climb",
    "**Your referral count:** 0",
    "Or copy & paste your referral link to others:",
)


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


def test_cleaning_a_newsletter_drops_the_referral_block_and_keeps_the_stories(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """Haiku's paragraph numbers become a cleaned current text; the original stays as version 1, unchanged."""
    source_id = _add_newsletter(engine, text_content={content.TEXT_KEY: MORNING_BREW_TEXT})
    _enqueue(engine, source_id)

    with replay("clean_text_morning_brew"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    original, cleaned = _texts(engine, source_id)
    assert (original.version, original.is_current, original.content) == (
        1,
        False,
        {content.TEXT_KEY: MORNING_BREW_TEXT},
    )
    assert (cleaned.version, cleaned.is_current) == (2, True)
    assert (cleaned.model, cleaned.prompt_version) == (llm.HAIKU, prompts.CLEAN_TEXT_PROMPT_VERSION)
    assert cleaned.content[pipeline.CLEANED_KEY] is True

    cleaned_paragraphs = clean_text.split_paragraphs(cleaned.content[content.TEXT_KEY])
    original_paragraphs = clean_text.split_paragraphs(MORNING_BREW_TEXT)
    assert set(cleaned_paragraphs) < set(original_paragraphs)
    assert all(any(p.startswith(opening) for p in cleaned_paragraphs) for opening in STORY_OPENINGS)
    assert not any(p.startswith(line) for p in cleaned_paragraphs for line in REFERRAL_BLOCK)

    assert [(call.step, call.model) for call in _llm_calls(engine)] == [(models.JobKind.CLEAN_TEXT.value, llm.HAIKU)]
    assert _only_job(engine).status == models.JobStatus.DONE.value
    # Cleaning is not the last step: the source waits for `analyze`.
    assert _source(engine, source_id).processing == models.ProcessingStatus.PROCESSING.value


def test_a_text_already_cleaned_is_left_alone_without_a_model_call(engine: sqlalchemy.Engine) -> None:
    """No cassette: a request would raise, so finishing proves no call was made."""
    source_id = _add_newsletter(engine, text_content={content.TEXT_KEY: MORNING_BREW_TEXT, pipeline.CLEANED_KEY: True})
    _enqueue(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert len(_texts(engine, source_id)) == 1
    assert _llm_calls(engine) == []
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_kept_paragraphs_refuses_an_answer_that_drops_more_than_sixty_percent() -> None:
    """Six of ten is still cleaned; seven of ten keeps the text as is, as does dropping nothing."""
    paragraphs = [f"p{number}" for number in range(1, 11)]

    six = clean_text.kept_paragraphs(paragraphs, answer={"drop": [1, 2, 3, 4, 5, 6]})
    seven = clean_text.kept_paragraphs(paragraphs, answer={"drop": [1, 2, 3, 4, 5, 6, 7]})

    assert six == ["p7", "p8", "p9", "p10"]
    assert seven is None
    assert clean_text.kept_paragraphs(paragraphs, answer={"drop": []}) is None


def test_kept_paragraphs_ignores_numbers_outside_the_text_and_repeats() -> None:
    """Numbers are 1-based; 0, 11 and a repeated 2 count as nothing extra toward the 60% cap."""
    paragraphs = [f"p{number}" for number in range(1, 11)]

    kept = clean_text.kept_paragraphs(paragraphs, answer={"drop": [0, 2, 2, 11, 3, 4, 5, 6, 7]})

    assert kept == ["p1", "p8", "p9", "p10"]


def test_split_paragraphs_splits_on_blank_lines_only() -> None:
    """Single line breaks stay inside a paragraph; whitespace-only lines still separate."""
    text = "Title\nsubtitle\n\n  \nBody one.\n \t\nBody two.\n"

    assert clean_text.split_paragraphs(text) == ["Title\nsubtitle", "Body one.", "Body two."]


def _add_newsletter(engine: sqlalchemy.Engine, *, text_content: dict[str, object]) -> uuid.UUID:
    """A whitelisted user's processing inbox newsletter with `text_content` as its current text."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=True)
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        source = models.Source(
            id=source_id,
            user_id=user.id,
            url=MORNING_BREW_URL,
            normalized_url=MORNING_BREW_URL,
            title=MORNING_BREW_TITLE,
            kind=models.SourceKind.NEWSLETTER.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
        pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.TEXT, content=text_content, model=None, prompt_version=None
        )
        db.commit()
    return source_id


def _enqueue(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        user_id = db.get_one(models.Source, source_id).user_id
        jobs.enqueue(
            db, kind=models.JobKind.CLEAN_TEXT, user_id=user_id, payload={pipeline.SOURCE_ID_KEY: str(source_id)}
        )
        db.commit()


def _texts(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> list[models.SourceArtifact]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.SourceArtifact)
                .where(
                    models.SourceArtifact.source_id == source_id,
                    models.SourceArtifact.kind == models.ArtifactKind.TEXT.value,
                )
                .order_by(models.SourceArtifact.version)
            )
        )


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _only_job(engine: sqlalchemy.Engine) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        return db.scalars(sqlalchemy.select(models.Job)).one()


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
