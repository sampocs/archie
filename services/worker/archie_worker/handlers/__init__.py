"""Job handlers, one module per `JobKind`, and the registry the worker loop dispatches through."""

import uuid

import sqlalchemy.orm
from archie_db import changes, models, pipeline

from archie_worker.handlers import fetch_title
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
}
