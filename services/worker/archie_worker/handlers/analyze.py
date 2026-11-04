"""`analyze`: summarize a source's text and, when it teaches something, make review cards from it.

Each run writes the next summary version. The previous version's cards are soft-deleted and the new
version's inserted, so the cards always come from the current summary.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline

from archie_worker import llm, prompts
from archie_worker.handlers import _llm_step

MAX_OUTPUT_TOKENS = 8000


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Analyze the source's text with the model and store the summary, its cards and the source's progress."""
    run = _llm_step.prepare_run(db, job, step=models.JobKind.ANALYZE)
    if run is None:
        return

    completion = _llm_step.call_model(
        db,
        run,
        model_pair=llm.ANALYZE_MODELS,
        system=prompts.ANALYZE_SYSTEM,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.ANALYSIS_SCHEMA,
    )
    analysis = json.loads(completion.text)

    source = _llm_step.lock_live_source(db, run)
    if source is None:
        return

    summary = pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.SUMMARY,
        content=analysis,
        model=completion.model,
        prompt_version=prompts.ANALYZE_PROMPT_VERSION,
    )
    _retire_cards_before(db, source_id=source.id, current_artifact_id=summary.id)
    if analysis["is_educational"]:
        _insert_cards(db, source=source, artifact_id=summary.id, cards=analysis["cards"])
    pipeline.finish_step(db, source=source)


def _retire_cards_before(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID, current_artifact_id: uuid.UUID) -> None:
    """Soft-delete the source's live cards from earlier summary versions."""
    db.execute(
        sqlalchemy.update(models.Card)
        .where(
            models.Card.source_id == source_id,
            models.Card.artifact_id != current_artifact_id,
            models.Card.deleted_at.is_(None),
        )
        .values(
            deleted_at=sqlalchemy.func.now(),
            updated_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
    )


def _insert_cards(
    db: sqlalchemy.orm.Session, *, source: models.Source, artifact_id: uuid.UUID, cards: list[dict[str, Any]]
) -> None:
    for card in cards:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=source.user_id,
                source_id=source.id,
                artifact_id=artifact_id,
                kind=card["kind"],
                question=card["question"],
                answer=card["answer"],
                change_seq=changes.next_change_seq(),
            )
        )
