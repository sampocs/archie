"""The parts the model steps share: read the source's text, call the model, and re-check the source after.

`analyze` and `primer` use all of it, `clean_text` the call and the re-check. Each follows the loop's handler
contract: read into locals, commit, make the (slow, billed) model call holding no transaction, then take the user's
write lock and write.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, models, pipeline
from archie_llm import llm

from archie_worker import keys, prompts


@dataclass(frozen=True)
class StepRun:
    """What a model step needs after its first transaction ends, so it holds no ORM objects across the call."""

    source_id: uuid.UUID
    user_id: int
    kind: models.SourceKind
    context: llm.CallContext
    api_key: str
    user_message: str


def prepare_run(db: sqlalchemy.orm.Session, job: models.Job, *, step: models.JobKind) -> StepRun | None:
    """Read what the model call needs and commit; None when the source is gone or deleted, so there is nothing to do.

    Raises `PermanentJobError` for a user without an API key (checked first, so it fails at once even when the text
    artifact is missing), and a plain error when the text artifact is missing (the loop retries, as fetch_content may
    still be committing).
    """
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, source.user_id))

    text_artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if text_artifact is None:
        raise LookupError(f"Source {source.id} has no text artifact yet")

    # Both steps that call this write cards, so the model hears what the user said about earlier ones.
    kind = models.SourceKind(source.kind)
    source_message = prompts.user_message(
        kind=kind, title=source.title, url=source.url, text=prompts.model_text(text_artifact.content)
    )
    preferences = prompts.preferences_block(card_rows.recent_preferences(db, user_id=source.user_id))
    run = StepRun(
        source_id=source.id,
        user_id=source.user_id,
        kind=kind,
        context=llm.CallContext(user_id=source.user_id, source_id=source.id, job_id=job.id, step=step),
        api_key=api_key,
        user_message=source_message + preferences,
    )
    db.commit()
    return run


def call_model(
    db: sqlalchemy.orm.Session,
    run: StepRun,
    *,
    model_pair: llm.ModelPair,
    system: str,
    max_tokens: int,
    json_schema: dict[str, Any] | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
) -> llm.Completion:
    """Make the model call on its own connection, so no transaction of `db` is open meanwhile."""
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)

    return llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=model_pair,
        system=system,
        user_message=run.user_message,
        max_tokens=max_tokens,
        json_schema=json_schema,
        tools=tools,
    )


def lock_live_source(db: sqlalchemy.orm.Session, run: StepRun) -> models.Source | None:
    """Take the user's write lock and reload the source; None when the user deleted it during the call."""
    changes.lock_user_writes(db, run.user_id)
    source = db.get_one(models.Source, run.source_id)
    db.refresh(source)
    return None if source.deleted_at is not None else source
