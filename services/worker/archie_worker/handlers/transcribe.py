"""`transcribe`: turn a podcast episode's audio into timed text, then queue analyze and primer.

The audio is downloaded and cut into chunks; each chunk is transcribed (Groq, OpenAI as the fallback) and stored in
`transcript_chunks` as soon as it finishes, so a retried job re-downloads but skips the chunks already done. The
joined transcript gets a corrections pass for misheard names; if that pass fails, the transcript is used as is.
Following the loop's handler contract, the source is read and the transaction committed before any outside call.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any

import anthropic
import sqlalchemy
import sqlalchemy.orm
from archie_db import models, pipeline
from archie_llm import llm
from archie_shared import logging
from sqlalchemy.dialects import postgresql

from archie_worker import content, corrections, keys, transcription
from archie_worker.content import episode as episode_content
from archie_worker.handlers import _text

_logger = logging.get_logger(logging.LoggerName.WORKER, "transcribe")


@dataclass(frozen=True)
class _Run:
    """Plain values read in the first transaction, used by the steps after it commits."""

    source_id: uuid.UUID
    keys: transcription.TranscriptionKeys
    anthropic_api_key: str
    episode: episode_content.PodcastEpisode
    finished_chunks: frozenset[int]
    context: llm.CallContext


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Transcribe the episode in the job's payload, correct names, and store it as the source's `text`."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return

    run = _prepare(db, job=job, source=source)
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)

    _transcribe_missing_chunks(engine, run=run)
    segments = _stored_segments(engine, source_id=run.source_id)
    corrected = corrections.apply(segments, _corrections(engine, run=run, segments=segments))

    _text.store_text(
        db,
        source=source,
        text_content=content.timed_text_content(
            segments=corrected, extra={episode_content.EPISODE_KEY: run.episode.to_payload()}
        ),
        title=run.episode.title,
    )


def _prepare(db: sqlalchemy.orm.Session, *, job: models.Job, source: models.Source) -> _Run:
    """Check the keys, read the episode and the finished chunks, and commit so no transaction stays open."""
    user = db.get_one(models.User, source.user_id)
    transcription_keys = transcription.keys_for(user)
    anthropic_api_key = keys.anthropic_key_for(user)

    finished_chunks = frozenset(
        db.scalars(
            sqlalchemy.select(models.TranscriptChunk.chunk_index).where(models.TranscriptChunk.source_id == source.id)
        )
    )
    run = _Run(
        source_id=source.id,
        keys=transcription_keys,
        anthropic_api_key=anthropic_api_key,
        episode=episode_content.PodcastEpisode.from_payload(job.payload[episode_content.EPISODE_KEY]),
        finished_chunks=finished_chunks,
        context=llm.CallContext(
            user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.TRANSCRIBE
        ),
    )
    db.commit()
    return run


def _transcribe_missing_chunks(engine: sqlalchemy.Engine, *, run: _Run) -> None:
    """Download the audio, refuse one that is too long or unreadable, chunk it, then transcribe and store every chunk
    not finished by an earlier attempt."""
    prompt = f"{run.episode.show_name}. {run.episode.title}."
    with tempfile.TemporaryDirectory() as directory_name:
        directory = pathlib.Path(directory_name)
        audio = transcription.download(url=run.episode.audio_url, directory=directory)
        audio_seconds = transcription.episode_seconds(audio)
        chunks = transcription.split(
            audio=audio, audio_seconds=audio_seconds, directory=directory, chunk_seconds=transcription.CHUNK_SECONDS
        )

        for chunk in chunks:
            if chunk.index in run.finished_chunks:
                continue

            _logger.info("Transcribing chunk %d/%d of source %s", chunk.index + 1, len(chunks), run.source_id)
            transcript = transcription.transcribe_chunk(
                engine, chunk=chunk, keys=run.keys, prompt=prompt, context=run.context, directory=directory
            )
            _store_chunk(engine, source_id=run.source_id, chunk=chunk, transcript=transcript)


def _store_chunk(
    engine: sqlalchemy.Engine,
    *,
    source_id: uuid.UUID,
    chunk: transcription.AudioChunk,
    transcript: transcription.ChunkTranscript,
) -> None:
    # Committed on its own at once, so a later chunk's failure keeps this one for the retry. A duplicate (another
    # worker that picked up a stale job) is ignored: whichever transcript landed first stays.
    statement = (
        postgresql.insert(models.TranscriptChunk)
        .values(
            source_id=source_id,
            chunk_index=chunk.index,
            provider=transcript.provider.value,
            model=transcript.model,
            segments=[
                {"start": segment.start, "text": content.strip_nul(segment.text)} for segment in transcript.segments
            ],
        )
        .on_conflict_do_nothing(index_elements=["source_id", "chunk_index"])
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.execute(statement)
        db.commit()


def _stored_segments(engine: sqlalchemy.Engine, *, source_id: uuid.UUID) -> list[content.Segment]:
    """Every stored chunk's segments, in chunk order, as one list."""
    with sqlalchemy.orm.Session(engine) as db:
        stored: list[list[dict[str, Any]]] = list(
            db.scalars(
                sqlalchemy.select(models.TranscriptChunk.segments)
                .where(models.TranscriptChunk.source_id == source_id)
                .order_by(models.TranscriptChunk.chunk_index)
            )
        )
    return [content.Segment(start=float(raw["start"]), text=raw["text"]) for segments in stored for raw in segments]


def _corrections(
    engine: sqlalchemy.Engine, *, run: _Run, segments: list[content.Segment]
) -> list[corrections.Correction]:
    """The model's name corrections; none when the pass fails, since an uncorrected transcript is still useful."""
    text = " ".join(segment.text for segment in segments)
    try:
        return corrections.request(
            engine, api_key=run.anthropic_api_key, context=run.context, episode=run.episode, text=text
        )
    except (llm.ModelOutputError, anthropic.APIError, json.JSONDecodeError) as error:
        _logger.warning("Corrections failed for source %s, keeping the transcript as is: %r", run.source_id, error)
        return []
