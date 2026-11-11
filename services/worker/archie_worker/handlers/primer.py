"""`primer`: write the background a source assumes its reader already has, as markdown, plus its foundation cards.

The model writes the foundation cards after the primer's markdown; they are split off, stored as the source's
`foundation` cards tied to the primer artifact, and replace the cards of any earlier primer.

A book has no text: its primer is a spoiler-free one written from the title and author, searching the web when the
model doesn't know the book, and it gets no foundation cards (the book's cards come when it is finished).
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy.orm
from archie_db import card_rows, changes, jobs, models, pipeline
from archie_llm import llm

from archie_worker import keys, prompts
from archie_worker.handlers import _llm_step

MAX_OUTPUT_TOKENS = 6000


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the source's primer with the model and store it as the next primer version, with its foundation cards."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is not None and source.kind == models.SourceKind.BOOK:
        _handle_book(db, job, source=source)
        return

    run = _llm_step.prepare_run(db, job, step=models.JobKind.PRIMER)
    if run is None:
        return

    completion = _llm_step.call_model(
        db,
        run,
        model_pair=llm.PRIMER_MODELS,
        system=prompts.PRIMER_SYSTEM,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    output = prompts.split_primer_output(completion.text)

    source = _llm_step.lock_live_source(db, run)
    if source is None:
        return

    primer = pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.PRIMER,
        content={"markdown": output.markdown},
        model=completion.model,
        prompt_version=prompts.PRIMER_PROMPT_VERSION,
    )
    jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)

    # A rewritten primer replaces its foundation cards; none are written while the user has cards off for the source.
    card_rows.retire_cards(
        db,
        models.Card.source_id == source.id,
        models.Card.kind == models.CardKind.FOUNDATION.value,
        models.Card.artifact_id != primer.id,
    )
    if not source.cards_off:
        _insert_foundation_cards(db, source=source, artifact_id=primer.id, cards=output.foundation_cards)
    pipeline.finish_step(db, source=source)


def _handle_book(db: sqlalchemy.orm.Session, job: models.Job, *, source: models.Source) -> None:
    """Write a book's spoiler-free primer from its title and author, with no foundation cards."""
    run = _prepare_book_run(db, job, source=source)
    if run is None:
        return

    completion = _llm_step.call_model(
        db,
        run,
        model_pair=llm.PRIMER_MODELS,
        system=prompts.BOOK_PRIMER_SYSTEM,
        max_tokens=MAX_OUTPUT_TOKENS,
        tools=[llm.WEB_SEARCH_TOOL],
    )

    locked = _llm_step.lock_live_source(db, run)
    if locked is None:
        return
    pipeline.write_artifact(
        db,
        source=locked,
        kind=models.ArtifactKind.PRIMER,
        content={"markdown": completion.text.strip()},
        model=completion.model,
        prompt_version=prompts.BOOK_PRIMER_PROMPT_VERSION,
    )
    jobs.enqueue_embed(db, user_id=locked.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=locked.id)
    pipeline.finish_step(db, source=locked)


def _prepare_book_run(
    db: sqlalchemy.orm.Session, job: models.Job, *, source: models.Source
) -> _llm_step.StepRun | None:
    """Build the book primer's call and commit; None when the book was deleted. A user without a key fails at once."""
    if source.deleted_at is not None:
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, source.user_id))
    run = _llm_step.StepRun(
        source_id=source.id,
        user_id=source.user_id,
        kind=models.SourceKind.BOOK,
        context=llm.CallContext(user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.PRIMER),
        api_key=api_key,
        user_message=prompts.book_primer_message(
            title=source.title or "", author=source.author, today=datetime.datetime.now(datetime.UTC).date()
        ),
    )
    db.commit()
    return run


def _insert_foundation_cards(
    db: sqlalchemy.orm.Session,
    *,
    source: models.Source,
    artifact_id: uuid.UUID,
    cards: list[prompts.FoundationCard],
) -> None:
    for card in cards:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=source.user_id,
                source_id=source.id,
                artifact_id=artifact_id,
                kind=models.CardKind.FOUNDATION.value,
                question=card.question,
                answer=card.answer,
                detail=card_rows.joined_detail(card.detail),
                change_seq=changes.next_change_seq(),
            )
        )
