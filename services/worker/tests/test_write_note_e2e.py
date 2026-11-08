"""`write_note` end to end: real jobs in a real Postgres, Anthropic and the linked pages replayed.

Re-record `write_note_staking` by deleting it and running
`uv run pytest services/worker/tests/test_write_note_e2e.py --record-mode=once -m postgres` with `TEST_DATABASE_URL`
set (a few cents of Sonnet; needs ANTHROPIC_API_KEY in the repo root .env; fetches two public pages).
"""

from __future__ import annotations

import contextlib
import pathlib
import re
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, session, user_topics
from archie_llm import llm
from archie_testing import recording
from archie_worker import errors, handlers, loop

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Proof_of_stake"
SPOTIFY_URL = "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk"
NOTE_MARKDOWN = (
    "# Proof of stake\n\n"
    "## Basics\n"
    "- Validators stake 32 ETH, chosen to propose blocks\n"
    "- Misbehave → slashed\n"
    "- Rewards ~4%/yr?\n\n"
    "## Links\n"
    f"- [PoS on Wikipedia]({WIKIPEDIA_URL})\n"
    f"- {SPOTIFY_URL}\n"
)
NOTE_WORD = re.compile(r"\bnotes?\b", re.IGNORECASE)


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
    """Returns `use_cassette(name)`: the recorded HTTP for one test, replayable any number of times."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def test_a_note_is_written_up_fresh_with_its_links_as_sources(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The write-up has no cards, lists both links as sources, and never mentions the note itself."""
    source_id = _add_note(engine)
    _enqueue(engine, source_id)

    with replay("write_note_staking"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    summary = _current_summary(engine, source_id)
    content = summary.content
    assert summary.prompt_version == "note-write-up-v1"
    assert content["cards"] == []
    assert [entry["url"] for entry in content["sources"]] == [WIKIPEDIA_URL, SPOTIFY_URL]
    assert all(entry["title"].strip() for entry in content["sources"])
    assert content["is_educational"] is True

    # The contract: the write-up reads as an explanation from scratch.
    prose = [content["summary"]["gist"], *(item["idea"] for item in content["summary"]["key_ideas"])]
    assert content["summary"]["key_ideas"]
    assert not [text for text in prose if NOTE_WORD.search(text)]
    assert all(item["timestamp"] is None for item in content["summary"]["key_ideas"])

    [call] = _llm_calls(engine)
    assert (call.step, call.model, call.source_id) == (models.JobKind.WRITE_NOTE.value, llm.SONNET, source_id)
    queued = {job.kind for job in _jobs(engine) if job.status == models.JobStatus.QUEUED.value}
    assert {models.JobKind.EMBED.value, models.JobKind.FILE_TOPIC.value} <= queued
    assert _source(engine, source_id).processing == models.ProcessingStatus.READY.value


def test_a_note_re_imported_during_the_call_gets_no_stale_write_up(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newer text artifact appearing mid-call means the finished write-up describes old text, so none is stored."""
    source_id = _add_note(engine)
    _enqueue(engine, source_id)
    real_complete = llm.complete

    def complete_then_re_import(*args: Any, **kwargs: Any) -> Any:
        completion = real_complete(*args, **kwargs)
        with sqlalchemy.orm.Session(engine) as db:
            source = db.get_one(models.Source, source_id)
            changes.lock_user_writes(db, source.user_id)
            pipeline.write_artifact(
                db,
                source=source,
                kind=models.ArtifactKind.TEXT,
                content={"text": "# Proof of stake\n\nEdited."},
                model=None,
                prompt_version=None,
            )
            db.commit()
        return completion

    monkeypatch.setattr(llm, "complete", complete_then_re_import)

    with replay("write_note_staking"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _summaries(engine, source_id) == []
    assert _source(engine, source_id).processing == models.ProcessingStatus.READY.value
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_deleted_note_is_not_written_up(engine: sqlalchemy.Engine) -> None:
    """No cassette: a request would fail the job, so finishing proves no call was made."""
    source_id = _add_note(engine)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, source_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    _enqueue(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _summaries(engine, source_id) == []
    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_note_without_the_owners_key_fails_at_once(engine: sqlalchemy.Engine) -> None:
    """Not whitelisted and no key of their own: the job and the note fail before any call."""
    source_id = _add_note(engine, is_whitelisted=False)
    _enqueue(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    [job] = _jobs(engine)
    assert (job.status, job.last_error) == (models.JobStatus.FAILED.value, errors.FailureReason.NEEDS_API_KEY)
    source = _source(engine, source_id)
    assert (source.processing, source.processing_error) == (
        models.ProcessingStatus.FAILED.value,
        errors.FailureReason.NEEDS_API_KEY,
    )
    assert _llm_calls(engine) == []


def _add_note(engine: sqlalchemy.Engine, *, is_whitelisted: bool = True) -> uuid.UUID:
    """A user who has chosen topics, with an imported note and its current text artifact."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.flush()
        changes.lock_user_writes(db, user.id)
        user_topics.seed_owner_topics(db, user=user)

        source = models.Source(
            id=source_id,
            user_id=user.id,
            url="bear:ABC-123",
            normalized_url="bear:ABC-123",
            title="Proof of stake",
            kind=models.SourceKind.NOTE.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            bear_id="ABC-123",
            note_markdown=NOTE_MARKDOWN,
            note_tags=["crypto", "ethereum"],
            note_edited_at=datetime(2024, 3, 2, tzinfo=UTC),
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.READY)
        pipeline.write_artifact(
            db,
            source=source,
            kind=models.ArtifactKind.TEXT,
            content={"text": NOTE_MARKDOWN},
            model=None,
            prompt_version=None,
        )
        db.commit()
    return source_id


def _enqueue(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        user_id = db.get_one(models.Source, source_id).user_id
        jobs.enqueue(
            db, kind=models.JobKind.WRITE_NOTE, user_id=user_id, payload={pipeline.SOURCE_ID_KEY: str(source_id)}
        )
        db.commit()


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _summaries(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> list[models.SourceArtifact]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.SourceArtifact).where(
                    models.SourceArtifact.source_id == source_id,
                    models.SourceArtifact.kind == models.ArtifactKind.SUMMARY.value,
                )
            )
        )


def _current_summary(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.SourceArtifact:
    [summary] = [artifact for artifact in _summaries(engine, source_id) if artifact.is_current]
    return summary


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))
