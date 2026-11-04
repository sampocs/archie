"""Job handlers, one module per `JobKind`, and the registry the worker loop dispatches through."""

import datetime
import uuid

import sqlalchemy.orm
from archie_db import changes, models, pipeline

from archie_worker.handlers import analyze, fetch_content, fetch_title, primer, transcribe
from archie_worker.loop import HandlerSpec


def mark_source_failed(db: sqlalchemy.orm.Session, job: models.Job, reason: str) -> None:
    """Failure hook for pipeline steps: show `reason` on the job's source, unless the user deleted it."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None:
        return

    changes.lock_user_writes(db, source.user_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.FAILED, error=reason)


HANDLERS: dict[models.JobKind, HandlerSpec] = {
    models.JobKind.FETCH_TITLE: HandlerSpec(run=fetch_title.handle),
    models.JobKind.FETCH_CONTENT: HandlerSpec(run=fetch_content.handle, on_final_failure=mark_source_failed),
    models.JobKind.ANALYZE: HandlerSpec(run=analyze.handle, on_final_failure=mark_source_failed),
    models.JobKind.PRIMER: HandlerSpec(run=primer.handle, on_final_failure=mark_source_failed),
    # A long episode is many minutes of downloads and provider calls, so it isn't swept as stale at 900 s.
    models.JobKind.TRANSCRIBE: HandlerSpec(
        run=transcribe.handle,
        on_final_failure=mark_source_failed,
        stale_after=datetime.timedelta(seconds=3600),
    ),
}
