"""`clean_text`: drop a newsletter's ads, referral blocks, trivia and footers before it is analyzed.

The model sees the text's blank-line-separated paragraphs numbered and answers only with the numbers to drop, so it
can never rewrite the stories. The kept paragraphs become a new current `text` artifact marked cleaned; the original
stays as the previous version. Cleaning never blocks a newsletter from being analyzed, so this step has no failure
hook: if it fails, `analyze` reads the text as it was.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy.orm
from archie_db import models, pipeline

from archie_worker import content, llm, prompts
from archie_worker.handlers import _llm_step

MAX_OUTPUT_TOKENS = 1000

# A model that wants to drop more than this share of the paragraphs has misread the email, so the text is kept as is.
MAX_DROPPED_SHARE = 0.6

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_PARAGRAPH_SEPARATOR = "\n\n"
_DROP_KEY = "drop"


@dataclass(frozen=True)
class _CleanRun:
    """The model step's inputs, plus the text it reads, so the write can check that text is still current."""

    step: _llm_step.StepRun
    text_artifact_id: uuid.UUID
    text_content: dict[str, Any]
    paragraphs: list[str]


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Ask the model which paragraphs are clutter and store the text without them as the current text."""
    run = _prepare(db, job)
    if run is None:
        return

    completion = _llm_step.call_model(
        db,
        run.step,
        model_pair=llm.CLEAN_TEXT_MODELS,
        system=prompts.CLEAN_TEXT_SYSTEM,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.CLEAN_TEXT_SCHEMA,
    )
    kept = kept_paragraphs(run.paragraphs, answer=json.loads(completion.text))
    if kept is None:
        return

    # The text may have been replaced (or the source deleted) during the call; only the text that was read is cleaned.
    source = _llm_step.lock_live_source(db, run.step)
    if source is None:
        return
    current = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if current is None or current.id != run.text_artifact_id:
        return

    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.TEXT,
        content={**run.text_content, content.TEXT_KEY: _PARAGRAPH_SEPARATOR.join(kept), pipeline.CLEANED_KEY: True},
        model=completion.model,
        prompt_version=prompts.CLEAN_TEXT_PROMPT_VERSION,
    )


def split_paragraphs(text: str) -> list[str]:
    """The text's blank-line-separated paragraphs, trimmed, without empty ones."""
    return [paragraph.strip() for paragraph in _PARAGRAPH_BREAK.split(text) if paragraph.strip()]


def kept_paragraphs(paragraphs: Sequence[str], *, answer: Mapping[str, Any]) -> list[str] | None:
    """The paragraphs the model did not drop; None when nothing changes or it would drop more than 60% of them.

    Numbers are 1-based as the model saw them; any number outside the text is ignored.
    """
    dropped = {number for number in answer[_DROP_KEY] if 1 <= number <= len(paragraphs)}
    if not dropped or len(dropped) > MAX_DROPPED_SHARE * len(paragraphs):
        return None
    return [paragraph for number, paragraph in enumerate(paragraphs, start=1) if number not in dropped]


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _CleanRun | None:
    """Read the source's text and commit; None when the source is gone or its text is already cleaned.

    Raises `PermanentJobError` for a user without an API key, and a plain error when the text is missing (the loop
    retries, as fetch_content may still be committing).
    """
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return None

    api_key = llm.api_key_for(db.get_one(models.User, source.user_id))
    text_artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if text_artifact is None:
        raise LookupError(f"Source {source.id} has no text artifact yet")
    if text_artifact.content.get(pipeline.CLEANED_KEY) is True:
        return None

    paragraphs = split_paragraphs(text_artifact.content[content.TEXT_KEY])
    run = _CleanRun(
        step=_llm_step.StepRun(
            source_id=source.id,
            user_id=source.user_id,
            kind=models.SourceKind(source.kind),
            context=llm.CallContext(
                user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.CLEAN_TEXT
            ),
            api_key=api_key,
            user_message=prompts.clean_text_message(title=source.title, paragraphs=paragraphs),
        ),
        text_artifact_id=text_artifact.id,
        text_content=dict(text_artifact.content),
        paragraphs=paragraphs,
    )
    db.commit()
    return run
