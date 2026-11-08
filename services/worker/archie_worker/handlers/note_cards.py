"""`note_cards`: 3-5 review cards from a refreshed note's write-up, written when the owner taps Done on it.

It runs only for a live note that is refreshed, still has cards on, and has a current summary. Writing the new cards
retires the note's previous ones, so a retry never doubles them. A write-up replaced during the model call is skipped,
re-checked under the lock (the edit that replaced it refreshes the note again). There is no failure hook: a note
without cards still reads fine.

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

MAX_NOTE_CARDS = 5
MAX_OUTPUT_TOKENS = 2000


class _NoteCard(pydantic.BaseModel):
    kind: models.CardKind
    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)


class _NoteCardsOutput(pydantic.BaseModel):
    # Empty is allowed: a note of errands has nothing worth remembering.
    cards: list[_NoteCard]


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
    """Replace the note's cards with new ones written from its current summary."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.NOTE_CARDS_MODELS,
        system=prompts.NOTE_CARDS_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.NOTE_CARDS_SCHEMA,
    )
    output = _NoteCardsOutput.model_validate(json.loads(completion.text))

    changes.lock_user_writes(db, run.user_id)
    source = db.get_one(models.Source, run.source_id)
    db.refresh(source)
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    # Deleted, switched to no cards, or re-written during the call: whichever did it queued its own work.
    if source.deleted_at is not None or source.cards_off or summary is None or summary.id != run.summary_id:
        return

    card_rows.retire_cards(db, models.Card.source_id == source.id)
    for card in output.cards[:MAX_NOTE_CARDS]:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=run.user_id,
                source_id=source.id,
                artifact_id=summary.id,
                kind=card.kind.value,
                question=card.question.strip(),
                answer=card.answer.strip(),
                change_seq=changes.next_change_seq(),
            )
        )


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _CardsRun | None:
    """Read the note and its write-up and build the call, then commit; None when this note gets no cards."""
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
        or source.kind != models.SourceKind.NOTE.value
        or source.refreshed_at is None
        or source.cards_off
    ):
        db.commit()
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, source.user_id))
    preferences = prompts.preferences_block(card_rows.recent_preferences(db, user_id=source.user_id))
    message = prompts.note_cards_message(
        title=source.title or "", markdown=source.note_markdown or "", write_up=summary.content
    )
    run = _CardsRun(
        source_id=source.id,
        summary_id=summary.id,
        user_id=source.user_id,
        context=llm.CallContext(
            user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.NOTE_CARDS
        ),
        api_key=api_key,
        user_message=message + preferences,
    )
    db.commit()
    return run
