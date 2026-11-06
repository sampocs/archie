"""`analyze`: summarize a source's text and, when it teaches something, make review cards from it.

Each run writes the next summary version. The previous version's cards are soft-deleted and the new
version's inserted, so the summary cards always come from the current summary. The primer's foundation cards are
left alone, and no cards are written while the user has cards off for the source.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, models, pipeline, user_topics
from archie_llm import llm

from archie_worker import prompts, timestamps
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
    _clean_timestamps(analysis)

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
    # A newsletter gets cards only once the user went deeper (it is then consumed); other sources always may, unless
    # the user turned cards off for this one (read after the lock, so a change during the call counts).
    is_card_worthy = run.kind != models.SourceKind.NEWSLETTER or source.state == models.SourceState.CONSUMED
    wants_cards = is_card_worthy and not source.cards_off
    if analysis["is_educational"] and wants_cards:
        _insert_cards(db, source=source, artifact_id=summary.id, cards=analysis["cards"])

    # File each source once, after its first summary; a re-analysis never overrides a topic the user chose. Queued
    # before `finish_step` so a newsletter's kind (news or essay) is known when the brief rewrite it queues runs.
    user = db.get_one(models.User, source.user_id)
    if source.domain is None and user.topics_chosen_at is not None:
        user_topics.enqueue_file_topic(db, source=source)
    pipeline.finish_step(db, source=source)


def _clean_timestamps(analysis: dict[str, Any]) -> None:
    """Strip brackets from the model's key-idea and number timestamps and null any that still are not a time."""
    summary = analysis["summary"]
    for item in [*summary["key_ideas"], *summary["numbers"]]:
        item["timestamp"] = timestamps.clean_model_timestamp(item["timestamp"])


def _retire_cards_before(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID, current_artifact_id: uuid.UUID) -> None:
    """Soft-delete the source's live cards from earlier summary versions."""
    # Foundation cards belong to the primer and are retired only when it is rewritten.
    card_rows.retire_cards(
        db,
        models.Card.source_id == source_id,
        models.Card.artifact_id != current_artifact_id,
        models.Card.kind != models.CardKind.FOUNDATION.value,
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
