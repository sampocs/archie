"""`take_cards`: 2-4 review cards from a take's current version, answered in the owner's own words.

It runs only for the take's current version once it has a body: a version replaced before the call is skipped, and so
is one replaced during it, re-checked under the lock (the save that replaced it queued its own job). Writing the new
cards retires the take's previous ones, so their review history stays on the old rows. There is no failure hook: a take
without cards still reads fine, and the next save tries again.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pydantic
import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, jobs, models, takes
from archie_llm import llm

from archie_worker import keys, prompts

MAX_TAKE_CARDS = 4
MAX_OUTPUT_TOKENS = 2000


class _TakeCard(pydantic.BaseModel):
    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)


class _TakeCardsOutput(pydantic.BaseModel):
    # An empty list would retire the old cards and write none, so it fails the call and the old cards stay live.
    cards: list[_TakeCard] = pydantic.Field(min_length=1)


@dataclass(frozen=True)
class _CardsRun:
    """What the model call and the write need after the first transaction ends."""

    take_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Replace the take's cards with new ones written from its current version."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.TAKE_CARDS_MODELS,
        system=prompts.TAKE_CARDS_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.TAKE_CARDS_SCHEMA,
    )
    output = _TakeCardsOutput.model_validate(json.loads(completion.text))

    changes.lock_user_writes(db, run.user_id)
    take = db.get_one(models.Take, run.take_id)
    db.refresh(take)
    # Saved again or deleted during the call: a newer save queued its own job, and a deleted take wants none.
    if take.deleted_at is not None or take.current_version != run.version:
        return

    card_rows.retire_cards(db, models.Card.take_id == take.id)
    for card in output.cards[:MAX_TAKE_CARDS]:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=run.user_id,
                take_id=take.id,
                take_version_id=run.version_id,
                kind=models.CardKind.TAKE.value,
                question=card.question.strip(),
                answer=card.answer.strip(),
                change_seq=changes.next_change_seq(),
            )
        )


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _CardsRun | None:
    """Read the take's current version and build the call, then commit; None when this version gets no cards."""
    version = db.get(models.TakeVersion, uuid.UUID(job.payload[jobs.TAKE_VERSION_ID_KEY]))
    take = db.get(models.Take, version.take_id) if version is not None else None
    # A version still being cleaned has no body yet; `clean_take` queues this job again when it lands.
    if version is None or take is None or not takes.is_current(take, version) or version.body is None:
        db.commit()
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, take.user_id))
    run = _CardsRun(
        take_id=take.id,
        version_id=version.id,
        version=version.version,
        user_id=take.user_id,
        context=llm.CallContext(user_id=take.user_id, source_id=None, job_id=job.id, step=models.JobKind.TAKE_CARDS),
        api_key=api_key,
        user_message=prompts.take_cards_message(kind=models.TakeKind(take.kind), title=take.title, body=version.body),
    )
    db.commit()
    return run
