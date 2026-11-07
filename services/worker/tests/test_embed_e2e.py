"""`embed` end to end: real jobs in a real Postgres, OpenAI replayed from a recorded real response.

Re-record `embed_article` by deleting it and running
`uv run pytest services/worker/tests/test_embed_e2e.py --record-mode=once -m postgres` with `TEST_DATABASE_URL` set
(a tiny fraction of a cent; needs OPENAI_API_KEY in the repo root .env).
"""

from __future__ import annotations

import pathlib
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import backfill_embed, changes, jobs, models, pipeline, session
from archie_shared import config
from archie_testing import recording
from archie_worker import handlers, loop

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
ARTICLE = "Stablecoins settle about ten trillion dollars a year. They move dollars without a bank in the middle."
SUMMARY = {
    "gist": "Stablecoins already move dollars at scale.",
    "key_ideas": [{"timestamp": None, "idea": "They settle without a bank."}],
    "numbers": [{"timestamp": None, "fact": "About $10T a year."}],
}


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real OpenAI key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch, env_names=(config.OPENAI_API_KEY_ENV,))


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


def test_a_paid_source_gets_text_and_summary_chunks_with_embeddings(
    engine: sqlalchemy.Engine, request: pytest.FixtureRequest
) -> None:
    """Text and summary passages, numbered per kind, each with a 1536-dimension embedding and one costed request."""
    source_id = _add_source(engine, whitelisted=True)
    _enqueue(engine, source_id)

    with recording.vcr_for(request, cassette_dir=CASSETTE_DIR).use_cassette("embed_article.yaml"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    chunks = _chunks(engine)
    assert [(chunk.owner_kind, chunk.chunk_index) for chunk in chunks] == [
        ("source_summary", 0),
        ("source_summary", 1),
        ("source_summary", 2),
        ("source_text", 0),
    ]
    assert all(chunk.embedding is not None and len(chunk.embedding) == models.EMBEDDING_DIMENSIONS for chunk in chunks)
    [call] = _llm_calls(engine)
    assert (call.step, call.provider, call.source_id) == ("embed", "openai", source_id)
    assert [job.status for job in _jobs(engine)] == ["done"]


def test_without_the_owners_keys_chunks_are_stored_with_no_embedding_and_rebuilt_on_rerun(
    engine: sqlalchemy.Engine,
) -> None:
    """No cassette: any request would fail the job. A second run replaces, never duplicates."""
    source_id = _add_source(engine, whitelisted=False)
    _enqueue(engine, source_id)
    loop.run_one(engine, handlers=handlers.HANDLERS)
    first_ids = {chunk.id for chunk in _chunks(engine)}

    _enqueue(engine, source_id)
    loop.run_one(engine, handlers=handlers.HANDLERS)

    chunks = _chunks(engine)
    assert len(chunks) == len(first_ids) and not ({chunk.id for chunk in chunks} & first_ids)
    assert all(chunk.embedding is None for chunk in chunks)
    assert _llm_calls(engine) == []


def test_a_deleted_source_gets_no_chunks(engine: sqlalchemy.Engine) -> None:
    """Deleted before the job ran: nothing is written."""
    source_id = _add_source(engine, whitelisted=False, deleted=True)
    _enqueue(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _chunks(engine) == []


def test_a_new_topic_primer_version_replaces_the_old_versions_chunks(engine: sqlalchemy.Engine) -> None:
    """Only the current version is searchable."""
    user_id = _add_user(engine, whitelisted=False)
    old_id, new_id = _add_topic_primers(engine, user_id=user_id)
    _enqueue(engine, old_id, kind=models.SearchItemKind.TOPIC_PRIMER, user_id=user_id)
    _enqueue(engine, new_id, kind=models.SearchItemKind.TOPIC_PRIMER, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)
    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert {chunk.topic_primer_id for chunk in _chunks(engine)} == {new_id}


def test_backfill_queues_every_live_item_once(engine: sqlalchemy.Engine) -> None:
    """A live source with text, the current topic primer and a take with a body; a deleted source is skipped."""
    user_id = _add_user(engine, whitelisted=False)
    _add_source(engine, whitelisted=False, user_id=user_id)
    _add_source(engine, whitelisted=False, user_id=user_id, deleted=True)
    _add_topic_primers(engine, user_id=user_id)
    _add_take(engine, user_id=user_id)

    with sqlalchemy.orm.Session(engine) as db:
        queued = backfill_embed.backfill_all(db)
        db.commit()
        again = backfill_embed.backfill_all(db)
        db.commit()

    assert (queued, again) == (3, 0)
    assert sorted(job.payload[jobs.ITEM_KIND_KEY] for job in _jobs(engine)) == ["source", "take", "topic_primer"]


def test_backfill_skips_items_that_already_have_chunks(engine: sqlalchemy.Engine) -> None:
    """An indexed source, topic (on an older version) and take are not queued; an unindexed source is."""
    user_id = _add_user(engine, whitelisted=False)
    indexed_source = _add_source(engine, whitelisted=False, user_id=user_id)
    unindexed_source = _add_source(engine, whitelisted=False, user_id=user_id)
    old_primer, _ = _add_topic_primers(engine, user_id=user_id)
    take_id = _add_take(engine, user_id=user_id)
    _add_chunk(engine, user_id=user_id, source_id=indexed_source)
    _add_chunk(engine, user_id=user_id, topic_primer_id=old_primer)
    _add_chunk(engine, user_id=user_id, take_id=take_id)

    with sqlalchemy.orm.Session(engine) as db:
        queued = backfill_embed.backfill_all(db)
        db.commit()
        again = backfill_embed.backfill_all(db)
        db.commit()

    assert (queued, again) == (1, 0)
    assert [job.payload[jobs.ITEM_ID_KEY] for job in _jobs(engine)] == [str(unindexed_source)]


def _add_chunk(
    engine: sqlalchemy.Engine,
    *,
    user_id: int,
    source_id: uuid.UUID | None = None,
    topic_primer_id: uuid.UUID | None = None,
    take_id: uuid.UUID | None = None,
) -> None:
    owner = (
        models.ChunkOwner.SOURCE_TEXT
        if source_id
        else models.ChunkOwner.TOPIC_PRIMER
        if topic_primer_id
        else models.ChunkOwner.TAKE
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.add(
            models.Chunk(
                user_id=user_id,
                owner_kind=owner.value,
                source_id=source_id,
                topic_primer_id=topic_primer_id,
                take_id=take_id,
                chunk_index=0,
                text="A passage.",
            )
        )
        db.commit()


def _add_user(engine: sqlalchemy.Engine, *, whitelisted: bool) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4().hex}", is_whitelisted=whitelisted)
        db.add(user)
        db.commit()
        return user.id


def _add_source(
    engine: sqlalchemy.Engine, *, whitelisted: bool, user_id: int | None = None, deleted: bool = False
) -> uuid.UUID:
    """A ready article with its text and summary artifacts."""
    owner_id = user_id if user_id is not None else _add_user(engine, whitelisted=whitelisted)
    source_id = uuid.uuid4()
    url = f"https://example.com/{source_id}"
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, owner_id)
        source = models.Source(
            id=source_id,
            user_id=owner_id,
            url=url,
            normalized_url=url,
            title="Stablecoins",
            kind=models.SourceKind.ARTICLE.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            deleted_at=sqlalchemy.func.now() if deleted else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.READY)
        pipeline.write_artifact(
            db,
            source=source,
            kind=models.ArtifactKind.TEXT,
            content={"text": ARTICLE},
            model=None,
            prompt_version=None,
        )
        pipeline.write_artifact(
            db,
            source=source,
            kind=models.ArtifactKind.SUMMARY,
            content={"summary": SUMMARY},
            model=None,
            prompt_version=None,
        )
        db.commit()
    return source_id


def _add_topic_primers(engine: sqlalchemy.Engine, *, user_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A topic with an old version and a current one."""
    topic_id, old_id, new_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Topic(
                id=topic_id,
                user_id=user_id,
                domain="Macro",
                name="Reserves",
                origin=models.TopicOrigin.USER.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        for primer_id, version, markdown in (
            (old_id, 1, "## Old\n\nReserves before."),
            (new_id, 2, "## Reserves\n\nBanks hold reserves at the Fed."),
        ):
            db.add(
                models.TopicPrimer(
                    id=primer_id,
                    user_id=user_id,
                    topic_id=topic_id,
                    version=version,
                    is_current=version == 2,
                    content={"markdown": markdown},
                    change_seq=changes.next_change_seq(),
                )
            )
            db.flush()
        db.commit()
    return old_id, new_id


def _add_take(engine: sqlalchemy.Engine, *, user_id: int) -> uuid.UUID:
    take_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Take(
                id=take_id,
                user_id=user_id,
                kind=models.TakeKind.TALKING_POINT.value,
                title="Stablecoins",
                current_version=1,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        db.add(
            models.TakeVersion(
                id=uuid.uuid4(),
                user_id=user_id,
                take_id=take_id,
                version=1,
                body="Stablecoins are the real use.",
                raw_body="Stablecoins are the real use.",
                cleaned=True,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    return take_id


def _enqueue(
    engine: sqlalchemy.Engine,
    item_id: uuid.UUID,
    *,
    kind: models.SearchItemKind = models.SearchItemKind.SOURCE,
    user_id: int | None = None,
) -> None:
    """Queue `embed` directly (not `enqueue_embed`), so a test can queue the same item twice."""
    with sqlalchemy.orm.Session(engine) as db:
        owner_id = user_id if user_id is not None else db.get_one(models.Source, item_id).user_id
        jobs.enqueue(
            db,
            kind=models.JobKind.EMBED,
            user_id=owner_id,
            payload={jobs.ITEM_KIND_KEY: kind.value, jobs.ITEM_ID_KEY: str(item_id)},
        )
        db.commit()


def _chunks(engine: sqlalchemy.Engine) -> list[models.Chunk]:
    with sqlalchemy.orm.Session(engine) as db:
        ordered = sqlalchemy.select(models.Chunk).order_by(models.Chunk.owner_kind, models.Chunk.chunk_index)
        return list(db.scalars(ordered))


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall)))
