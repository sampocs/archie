"""`primer`: write the background a source assumes its reader already has, as markdown, plus its foundation cards.

The model writes the foundation cards after the primer's markdown; they are split off, stored as the source's
`foundation` cards tied to the primer artifact, and replace the cards of any earlier primer.
"""

from __future__ import annotations

import uuid

import sqlalchemy.orm
from archie_db import card_rows, changes, jobs, models, pipeline
from archie_llm import llm

from archie_worker import prompts
from archie_worker.handlers import _llm_step

MAX_OUTPUT_TOKENS = 6000


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the source's primer with the model and store it as the next primer version, with its foundation cards."""
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
                change_seq=changes.next_change_seq(),
            )
        )
