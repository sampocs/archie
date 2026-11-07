"""`embed`: rebuild one item's search passages (a source, a topic primer or a take) from scratch, with embeddings.

Follows the loop's handler contract: read the item's words and commit, call OpenAI holding no transaction, then lock
the user's writes, check the item is still live, and replace its chunks in one go, so running it again only rebuilds
the same passages. A user without the owner's keys, or a server without an OpenAI key, gets passages with no
embedding: they still serve keyword search. On its last attempt a failed embeddings call stores the passages without
embeddings rather than leaving the item unsearchable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, search, takes
from archie_llm import embeddings, llm
from archie_shared import config, logging

from archie_worker import chunking, content

_logger = logging.get_logger(logging.LoggerName.WORKER, "embed")


@dataclass(frozen=True)
class _EmbedRun:
    """What the job needs after its read transaction: the item, its passages, and who pays for embeddings."""

    item: search.ItemRef
    user_id: int
    passages: list[chunking.Passage]
    # None when nobody pays: the user isn't whitelisted or the server has no OpenAI key.
    api_key: str | None
    context: llm.CallContext
    last_attempt: bool


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Cut the item's passages, embed them when paid for, and replace the item's chunks."""
    run = _prepare(db, job)
    if run is None:
        return

    vectors = _embed(db, run)

    changes.lock_user_writes(db, run.user_id)
    if not _is_live(db, run.item):
        return
    _replace_chunks(db, run=run, vectors=vectors)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _EmbedRun | None:
    item = search.ItemRef(
        kind=models.SearchItemKind(job.payload[jobs.ITEM_KIND_KEY]), id=uuid.UUID(job.payload[jobs.ITEM_ID_KEY])
    )
    passages = _passages(db, item) if _is_live(db, item) else None
    user = db.get_one(models.User, job.user_id)
    openai_key = config.Settings().openai_api_key or None
    run = (
        None
        if passages is None
        else _EmbedRun(
            item=item,
            user_id=user.id,
            passages=passages,
            api_key=openai_key if user.is_whitelisted else None,
            context=llm.CallContext(
                user_id=user.id,
                source_id=item.id if item.kind == models.SearchItemKind.SOURCE else None,
                job_id=job.id,
                step=llm.EMBED_STEP,
            ),
            last_attempt=job.attempts >= job.max_attempts,
        )
    )
    # No transaction is held during the OpenAI call.
    db.commit()
    return run


def _passages(db: sqlalchemy.orm.Session, item: search.ItemRef) -> list[chunking.Passage]:
    if item.kind == models.SearchItemKind.SOURCE:
        return _source_passages(db, source_id=item.id)
    if item.kind == models.SearchItemKind.TOPIC_PRIMER:
        primer = db.get_one(models.TopicPrimer, item.id)
        return chunking.markdown_passages(primer.content["markdown"], owner_kind=models.ChunkOwner.TOPIC_PRIMER)

    take = db.get_one(models.Take, item.id)
    version = takes.current_version(db, take=take)
    if version is None or version.body is None:
        return []
    return chunking.markdown_passages(version.body, owner_kind=models.ChunkOwner.TAKE)


def _source_passages(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID) -> list[chunking.Passage]:
    """The source's own text (timed when it is a transcript), then Archie's summary and primer of it."""
    passages: list[chunking.Passage] = []
    text = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.TEXT)
    if text is not None:
        segments = content.segments_of(text.content)
        passages += (
            chunking.segment_passages(segments)
            if segments
            else chunking.text_passages(text.content[content.TEXT_KEY], owner_kind=models.ChunkOwner.SOURCE_TEXT)
        )

    summary = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.SUMMARY)
    if summary is not None:
        passages += chunking.markdown_passages(
            chunking.summary_markdown(summary.content["summary"]), owner_kind=models.ChunkOwner.SOURCE_SUMMARY
        )

    primer = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.PRIMER)
    if primer is not None:
        passages += chunking.markdown_passages(primer.content["markdown"], owner_kind=models.ChunkOwner.SOURCE_PRIMER)
    return passages


def _is_live(db: sqlalchemy.orm.Session, item: search.ItemRef) -> bool:
    """Whether search may show the item now (read again after the lock: the owner may have deleted it meanwhile)."""
    if item.kind == models.SearchItemKind.SOURCE:
        source = db.get(models.Source, item.id)
        if source is not None:
            db.refresh(source)
        return source is not None and source.deleted_at is None and source.merged_into_id is None
    if item.kind == models.SearchItemKind.TOPIC_PRIMER:
        primer = db.get(models.TopicPrimer, item.id)
        if primer is None:
            return False
        db.refresh(primer)
        topic = db.get_one(models.Topic, primer.topic_id)
        return primer.is_current and topic.removed_at is None and topic.merged_into_id is None

    take = db.get(models.Take, item.id)
    if take is not None:
        db.refresh(take)
    return take is not None and take.deleted_at is None


def _embed(db: sqlalchemy.orm.Session, run: _EmbedRun) -> list[list[float]] | None:
    if run.api_key is None or not run.passages:
        return None

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    _logger.info("Embedding %d passages of %s %s", len(run.passages), run.item.kind, run.item.id)
    try:
        return embeddings.embed(
            engine, api_key=run.api_key, context=run.context, texts=[passage.text for passage in run.passages]
        )
    except (httpx.HTTPError, embeddings.EmbeddingError) as error:
        if not run.last_attempt:
            raise
        # Out of retries: the passages still serve keyword search, and a later save or the backfill embeds them.
        _logger.warning("Storing %s %s without embeddings: %r", run.item.kind, run.item.id, error)
        return None


def _replace_chunks(db: sqlalchemy.orm.Session, *, run: _EmbedRun, vectors: list[list[float]] | None) -> None:
    db.execute(sqlalchemy.delete(models.Chunk).where(_owned_by(db, run.item)))

    indexes: dict[models.ChunkOwner, int] = {}
    owner = {
        models.SearchItemKind.SOURCE: "source_id",
        models.SearchItemKind.TOPIC_PRIMER: "topic_primer_id",
        models.SearchItemKind.TAKE: "take_id",
    }[run.item.kind]
    for position, passage in enumerate(run.passages):
        index = indexes.get(passage.owner_kind, 0)
        indexes[passage.owner_kind] = index + 1
        db.add(
            models.Chunk(
                user_id=run.user_id,
                owner_kind=passage.owner_kind.value,
                chunk_index=index,
                text=passage.text,
                start_seconds=passage.start_seconds,
                embedding=vectors[position] if vectors is not None else None,
                **{owner: run.item.id},
            )
        )


def _owned_by(db: sqlalchemy.orm.Session, item: search.ItemRef) -> sqlalchemy.ColumnElement[bool]:
    """The chunks this job replaces; for a topic primer, every version's, since only the current one is searchable."""
    if item.kind == models.SearchItemKind.SOURCE:
        return models.Chunk.source_id == item.id
    if item.kind == models.SearchItemKind.TAKE:
        return models.Chunk.take_id == item.id

    topic_id = db.get_one(models.TopicPrimer, item.id).topic_id
    versions = sqlalchemy.select(models.TopicPrimer.id).where(models.TopicPrimer.topic_id == topic_id)
    return models.Chunk.topic_primer_id.in_(versions)
