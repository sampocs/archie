"""`transcribe` end to end: real jobs in a real Postgres, real ffmpeg, Groq/OpenAI/Anthropic replayed from cassettes.

Re-record with `uv run pytest services/worker/tests/test_transcribe_e2e.py --record-mode=once -m postgres` after
deleting a cassette (a few cents; needs ANTHROPIC_API_KEY, GROQ_API_KEY and OPENAI_API_KEY in the repo root .env).
- `transcribe_short_episode`: the UPI Odd News Minute episode in `media` (~128 s), cut into 60 s chunks so it makes
  three Groq calls, then one Haiku corrections call. The only cassette that carries audio (the download); the
  resume and too-long tests replay it too.
- `transcribe_openai_chunk`: one OpenAI call for `fixtures/audio/short_chunk.mp3` (the episode's first 60 s).
- `transcribe_groq_rejected`: a real Groq 401, recorded with the literal invalid key, then the OpenAI fallback.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, models, pipeline, session
from archie_shared import config
from archie_testing import media, recording
from archie_worker import content, errors, handlers, llm, loop, transcription
from archie_worker.content import episode as episode_content
from archie_worker.handlers import _text

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[vcr_module.cassette.Cassette]]

TESTS_DIR = pathlib.Path(__file__).parent
CASSETTE_DIR = TESTS_DIR / "cassettes"
SHORT_CHUNK = TESTS_DIR / "fixtures" / "audio" / "short_chunk.mp3"
SHORT_CHUNK_SECONDS = 60.0
TEST_CHUNK_SECONDS = 60
# The ~128 s episode in 60 s chunks: 60 + 60 + ~8.
EPISODE_CHUNKS = 3
INVALID_GROQ_KEY = "gsk-invalid"
RESUMED_TEXT = "RESUMED CHUNK ZERO"
MIN_OPENAI_WORDS = 50

EPISODE = episode_content.PodcastEpisode(
    show_name=media.SPOTIFY_SHOW_NAME,
    title=media.SPOTIFY_EPISODE_TITLE,
    description="The day's oddest news stories in about a minute.",
    feed_url=media.EPISODE_FEED_URL,
    guid=None,
    audio_url=media.EPISODE_AUDIO_URL,
    duration_s=128,
)
PROMPT = f"{EPISODE.show_name}. {EPISODE.title}."


@dataclass(frozen=True)
class _Added:
    source_id: uuid.UUID
    user_id: int


@pytest.fixture(autouse=True)
def recording_api_keys(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real keys while recording, placeholders on replay; 60 s chunks so a short episode exercises several."""
    recording.use_recording_api_key(
        request,
        monkeypatch,
        env_names=(config.ANTHROPIC_API_KEY_ENV, config.GROQ_API_KEY_ENV, config.OPENAI_API_KEY_ENV),
    )
    monkeypatch.setattr(transcription, "CHUNK_SECONDS", TEST_CHUNK_SECONDS)


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


@pytest.fixture
def no_http(tmp_path: pathlib.Path) -> contextlib.AbstractContextManager[vcr_module.cassette.Cassette]:
    """An empty cassette that never records, even under `--record-mode`, so any HTTP request fails the test."""
    return vcr_module.VCR(cassette_library_dir=str(tmp_path), record_mode="none").use_cassette("none.yaml")


def test_an_episode_is_transcribed_corrected_and_queued_for_analysis(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Every chunk is transcribed by Groq and stored, offsets make one timeline, and analyze + primer are queued."""
    added = _add_transcribe_job(engine)

    with replay("transcribe_short_episode"):
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    transcribe_job, *next_jobs = _jobs(engine)
    assert transcribe_job.status == models.JobStatus.DONE.value
    assert [(job.kind, job.status) for job in next_jobs] == [
        (models.JobKind.ANALYZE.value, models.JobStatus.QUEUED.value),
        (models.JobKind.PRIMER.value, models.JobStatus.QUEUED.value),
    ]

    text = _text_artifact(engine, added.source_id)
    starts = [segment.start for segment in content.segments_of(text.content)]
    assert starts == sorted(starts)
    assert starts[-1] > TEST_CHUNK_SECONDS
    assert text.content[episode_content.EPISODE_KEY] == EPISODE.to_payload()
    assert len(text.content[content.TEXT_KEY].split()) > MIN_OPENAI_WORDS

    chunks = _transcript_chunks(engine, added.source_id)
    assert [chunk.chunk_index for chunk in chunks] == list(range(EPISODE_CHUNKS))
    assert {chunk.provider for chunk in chunks} == {models.TranscriptProvider.GROQ.value}

    groq_calls = _llm_calls(engine, provider=models.TranscriptProvider.GROQ.value)
    assert len(groq_calls) == EPISODE_CHUNKS
    assert all(call.step == models.JobKind.TRANSCRIBE.value and call.model == llm.GROQ_WHISPER for call in groq_calls)
    assert all(call.audio_seconds and call.audio_seconds > 0 and call.cost_usd > 0 for call in groq_calls)
    assert all(call.input_tokens == 0 and call.output_tokens == 0 for call in groq_calls)

    [corrections_call] = _llm_calls(engine, provider=llm.PROVIDER)
    assert (corrections_call.step, corrections_call.model) == (llm.CORRECTIONS_STEP, llm.HAIKU)
    assert corrections_call.cost_usd > 0
    assert _source(engine, added.source_id).processing == models.ProcessingStatus.PROCESSING.value


def test_a_retried_job_skips_the_chunks_already_stored(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A stored chunk 0 is reused as is: Groq is called only for the other chunks, and its text leads the transcript."""
    added = _add_transcribe_job(engine)
    with sqlalchemy.orm.Session(engine) as db:
        db.add(
            models.TranscriptChunk(
                source_id=added.source_id,
                chunk_index=0,
                provider=models.TranscriptProvider.GROQ.value,
                model=llm.GROQ_WHISPER,
                segments=[{"start": 0.0, "text": RESUMED_TEXT}],
            )
        )
        db.commit()

    with replay("transcribe_short_episode"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    # Each Groq call writes one cost row, so one fewer row than chunks proves chunk 0 was never sent.
    assert len(_llm_calls(engine, provider=models.TranscriptProvider.GROQ.value)) == EPISODE_CHUNKS - 1
    assert len(_transcript_chunks(engine, added.source_id)) == EPISODE_CHUNKS
    assert _text_artifact(engine, added.source_id).content[content.TEXT_KEY].startswith(RESUMED_TEXT)


def test_an_episode_over_the_size_cap_fails_at_once(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audio past `MAX_AUDIO_BYTES` fails the job on its first attempt with the too-long reason; nothing is billed."""
    monkeypatch.setattr(transcription, "MAX_AUDIO_BYTES", 1000)
    added = _add_transcribe_job(engine)

    with replay("transcribe_short_episode"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    _assert_failed_at_once(engine, added, reason=errors.FailureReason.EPISODE_TOO_LONG)


def test_a_user_without_a_key_fails_before_any_call(
    engine: sqlalchemy.Engine, no_http: contextlib.AbstractContextManager[vcr_module.cassette.Cassette]
) -> None:
    """A non-whitelisted user can't spend the owner's transcription keys: failed at once, no HTTP at all."""
    added = _add_transcribe_job(engine, is_whitelisted=False)

    with no_http as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 0
    _assert_failed_at_once(engine, added, reason=errors.FailureReason.NEEDS_API_KEY)


def test_a_server_without_transcription_keys_fails_before_any_call(
    engine: sqlalchemy.Engine,
    no_http: contextlib.AbstractContextManager[vcr_module.cassette.Cassette],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With neither a Groq nor an OpenAI key the job fails at once as not set up."""
    monkeypatch.delenv(config.GROQ_API_KEY_ENV)
    monkeypatch.delenv(config.OPENAI_API_KEY_ENV)
    added = _add_transcribe_job(engine)

    with no_http:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    _assert_failed_at_once(engine, added, reason=errors.FailureReason.TRANSCRIPTION_NOT_SET_UP)


def test_openai_transcribes_a_chunk_as_one_segment_per_part(replay: Replay, tmp_path: pathlib.Path) -> None:
    """A 60 s chunk is one OpenAI part: one call, one segment at the chunk's start in episode time."""
    chunk = transcription.AudioChunk(
        index=3, path=SHORT_CHUNK, start_seconds=180.0, duration_seconds=SHORT_CHUNK_SECONDS
    )

    with replay("transcribe_openai_chunk") as cassette:
        segments = transcription.transcribe_openai(
            chunk=chunk, api_key=os.environ[config.OPENAI_API_KEY_ENV], prompt=PROMPT, directory=tmp_path
        )

    assert len(cassette) == 1
    [segment] = segments
    assert segment.start == 180.0
    assert len(segment.text.split()) >= MIN_OPENAI_WORDS


def test_a_groq_rejection_falls_back_to_openai(
    engine: sqlalchemy.Engine, replay: Replay, tmp_path: pathlib.Path
) -> None:
    """Groq's real 401 for a bad key sends the chunk to OpenAI; only OpenAI's call is billed."""
    added = _add_transcribe_job(engine)
    chunk = transcription.AudioChunk(index=0, path=SHORT_CHUNK, start_seconds=0.0, duration_seconds=SHORT_CHUNK_SECONDS)
    keys = transcription.TranscriptionKeys(groq=INVALID_GROQ_KEY, openai=os.environ[config.OPENAI_API_KEY_ENV])

    with replay("transcribe_groq_rejected"):
        transcript = transcription.transcribe_chunk(
            engine,
            chunk=chunk,
            keys=keys,
            prompt=PROMPT,
            context=_context(engine, added),
            directory=tmp_path,
        )

    assert (transcript.provider, transcript.model) == (models.TranscriptProvider.OPENAI, llm.OPENAI_TRANSCRIBE)
    assert len(transcript.segments[0].text.split()) >= MIN_OPENAI_WORDS
    assert _llm_calls(engine, provider=models.TranscriptProvider.GROQ.value) == []
    [openai_call] = _llm_calls(engine, provider=models.TranscriptProvider.OPENAI.value)
    assert openai_call.cost_usd > 0


def _add_transcribe_job(engine: sqlalchemy.Engine, *, is_whitelisted: bool = True) -> _Added:
    """A user with an untitled podcast source in `processing` and its `transcribe` job, queued as fetch_content does."""
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user.id,
            url=media.SPOTIFY_EPISODE_URL,
            normalized_url=media.SPOTIFY_EPISODE_URL,
            kind=models.SourceKind.PODCAST.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
        _text.enqueue_transcribe(db, source=source, episode=EPISODE)
        added = _Added(source_id=source.id, user_id=user.id)
        db.commit()
    return added


def _context(engine: sqlalchemy.Engine, added: _Added) -> llm.CallContext:
    [job] = _jobs(engine)
    return llm.CallContext(
        user_id=added.user_id, source_id=added.source_id, job_id=job.id, step=models.JobKind.TRANSCRIBE
    )


def _assert_failed_at_once(engine: sqlalchemy.Engine, added: _Added, *, reason: errors.FailureReason) -> None:
    [job] = _jobs(engine)
    assert (job.status, job.attempts) == (models.JobStatus.FAILED.value, 1)
    source = _source(engine, added.source_id)
    assert (source.processing, source.processing_error) == (models.ProcessingStatus.FAILED.value, reason.value)
    assert _llm_calls(engine) == []
    assert _transcript_chunks(engine, added.source_id) == []


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _text_artifact(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.SourceArtifact:
    with sqlalchemy.orm.Session(engine) as db:
        artifact = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.TEXT)
        assert artifact is not None
        return artifact


def _transcript_chunks(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> list[models.TranscriptChunk]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.TranscriptChunk)
                .where(models.TranscriptChunk.source_id == source_id)
                .order_by(models.TranscriptChunk.chunk_index)
            )
        )


def _llm_calls(engine: sqlalchemy.Engine, *, provider: str | None = None) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        query = sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)
        if provider is not None:
            query = query.where(models.LlmCall.provider == provider)
        return list(db.scalars(query))
