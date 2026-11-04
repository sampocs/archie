"""`primer`: write the background a source assumes its reader already has, as markdown."""

from __future__ import annotations

import sqlalchemy.orm
from archie_db import models, pipeline

from archie_worker import llm, prompts
from archie_worker.handlers import _llm_step

MAX_OUTPUT_TOKENS = 6000


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the source's primer with the model and store it as the next primer version."""
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

    source = _llm_step.lock_live_source(db, run)
    if source is None:
        return

    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.PRIMER,
        content={"markdown": completion.text},
        model=completion.model,
        prompt_version=prompts.PRIMER_PROMPT_VERSION,
    )
    pipeline.finish_step(db, source=source)
