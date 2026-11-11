"""`write_book`: write a finished book's refresher, researched on the web, steered by the owner's thoughts and notes.

The refresher is the book's SUMMARY (as a note's write-up, timestamps null and no cards in it). Its text is also
stored as the book's TEXT artifact, so search and Ask index the book. Then come search, filing (once) and, only when
the book has no live cards yet, `book_cards`: a bootstrap book arrives with its hand-tuned cards.

One call, not the research-then-structure fallback: the API accepts the web search server tool together with
`output_config.format` (recorded in `llm_web_search_schema`, a call that searched and then answered in the schema),
so the model researches and answers in the JSON schema in a single request, and the answer is the text after its
last search.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, user_topics
from archie_llm import llm

from archie_worker import keys, prompts

# Searches, thinking and the refresher share the budget.
MAX_OUTPUT_TOKENS = 16000


@dataclass(frozen=True)
class _WriteRun:
    """What the model call and the write need after the first transaction ends."""

    source_id: uuid.UUID
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the book's refresher, store it as its summary and text, then queue search, filing and its cards."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.NOTE_WRITE_UP_MODELS,
        system=prompts.BOOK_WRITE_UP_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.NOTE_WRITE_UP_SCHEMA,
        tools=[llm.WEB_SEARCH_TOOL],
    )
    write_up = json.loads(completion.text)
    for item in [*write_up["summary"]["key_ideas"], *write_up["summary"]["numbers"]]:
        item["timestamp"] = None

    changes.lock_user_writes(db, run.user_id)
    source = db.get_one(models.Source, run.source_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return

    _store_refresher(db, source=source, write_up=write_up, completion=completion)
    _enqueue_follow_ups(db, source=source)
    pipeline.finish_step(db, source=source)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _WriteRun | None:
    """Read what the call needs, mark the book processing and commit; None when the book is gone, deleted or no book.

    Raises `PermanentJobError` for a user without an API key.
    """
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None or source.kind != models.SourceKind.BOOK:
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, source.user_id))

    changes.lock_user_writes(db, source.user_id)
    db.refresh(source)
    if source.deleted_at is not None:
        db.commit()
        return None

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    run = _WriteRun(
        source_id=source.id,
        user_id=source.user_id,
        context=llm.CallContext(
            user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.WRITE_BOOK
        ),
        api_key=api_key,
        user_message=prompts.book_write_up_message(
            today=datetime.datetime.now(datetime.UTC).date(),
            title=source.title or "",
            author=source.author,
            thoughts=source.note,
            notes=source.note_markdown,
        ),
    )
    db.commit()
    return run


def _store_refresher(
    db: sqlalchemy.orm.Session, *, source: models.Source, write_up: dict[str, object], completion: llm.Completion
) -> None:
    """Write the refresher as the summary, then its text as the book's text (what search and Ask read)."""
    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.SUMMARY,
        content={**write_up, "cards": []},
        model=completion.model,
        prompt_version=prompts.BOOK_WRITE_UP_PROMPT_VERSION,
    )
    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.TEXT,
        content={"text": prompts.summary_text(write_up)},
        model=None,
        prompt_version=None,
    )


def _enqueue_follow_ups(db: sqlalchemy.orm.Session, *, source: models.Source) -> None:
    jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)

    # Filed once, after the first refresher; a later one never overrides a topic the user chose.
    user = db.get_one(models.User, source.user_id)
    if source.domain is None and user.topics_chosen_at is not None:
        user_topics.enqueue_file_topic(db, source=source)

    # A bootstrap book came with its hand-tuned cards, and a rewritten refresher keeps the cards already written.
    has_cards = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(models.Card.source_id == source.id, models.Card.deleted_at.is_(None))
        )
    )
    if not has_cards:
        pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.BOOK_CARDS])
