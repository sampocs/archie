"""`book_cards`: review cards for a finished book, from its refresher and the owner's notes or thoughts on it.

The model first names the book's kind, which sets how many cards it gets however long the book is (the workshop
rule); the list is cut to that kind's cap here as well. It runs only for a live, finished book that still has cards on
and has a current refresher. Writing the new cards retires the book's previous ones, so a retry never doubles them. A
refresher replaced during the model call is skipped (whatever replaced it queues its own work). There is no failure
hook: a book without cards still reads fine.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pydantic
import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, models, pipeline
from archie_llm import llm

from archie_worker import keys, prompts

MAX_OUTPUT_TOKENS = 6000

# The most cards each kind of book gets: the top of the prompt's range for it.
BOOK_CARD_CAPS: dict[prompts.BookKind, int] = {
    prompts.BookKind.HOW_TO: 6,
    prompts.BookKind.IDEA: 10,
    prompts.BookKind.TEXTBOOK: 15,
}


class _BookCard(pydantic.BaseModel):
    kind: models.CardKind
    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)
    detail: list[str]


class _BookCardsOutput(pydantic.BaseModel):
    book_kind: prompts.BookKind
    cards: list[_BookCard]


@dataclass(frozen=True)
class _CardsRun:
    """What the model call and the write need after the first transaction ends."""

    source_id: uuid.UUID
    summary_id: uuid.UUID
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Replace the book's cards with new ones written from its current refresher, capped by the book's kind."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.BOOK_CARDS_MODELS,
        system=prompts.BOOK_CARDS_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.BOOK_CARDS_SCHEMA,
    )
    output = _BookCardsOutput.model_validate(json.loads(completion.text))

    changes.lock_user_writes(db, run.user_id)
    source = db.get_one(models.Source, run.source_id)
    db.refresh(source)
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    # Deleted, switched to no cards, or re-written during the call: whichever did it queued its own work.
    if source.deleted_at is not None or source.cards_off or summary is None or summary.id != run.summary_id:
        return

    card_rows.retire_cards(db, models.Card.source_id == source.id)
    for card in output.cards[: BOOK_CARD_CAPS[output.book_kind]]:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=run.user_id,
                source_id=source.id,
                artifact_id=summary.id,
                kind=card.kind.value,
                question=card.question.strip(),
                answer=card.answer.strip(),
                detail=card_rows.joined_detail(card.detail),
                change_seq=changes.next_change_seq(),
            )
        )


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _CardsRun | None:
    """Read the book and its refresher and build the call, then commit; None when this book gets no cards."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    summary = (
        pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
        if source is not None
        else None
    )
    if (
        source is None
        or summary is None
        or source.deleted_at is not None
        or source.kind != models.SourceKind.BOOK.value
        or source.state != models.SourceState.CONSUMED.value
        or source.cards_off
    ):
        db.commit()
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, source.user_id))
    preferences = prompts.preferences_block(card_rows.recent_preferences(db, user_id=source.user_id))
    message = prompts.book_cards_message(
        title=source.title or "",
        author=source.author,
        notes=source.note_markdown,
        thoughts=source.note,
        write_up=summary.content,
    )
    run = _CardsRun(
        source_id=source.id,
        summary_id=summary.id,
        user_id=source.user_id,
        context=llm.CallContext(
            user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.BOOK_CARDS
        ),
        api_key=api_key,
        user_message=message + preferences,
    )
    db.commit()
    return run
