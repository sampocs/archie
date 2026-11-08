"""Job handlers, one module per `JobKind`, and the registry the worker loop dispatches through."""

import datetime
import uuid

import sqlalchemy.orm
from archie_db import changes, models, pipeline

from archie_worker.handlers import (
    analyze,
    clean_take,
    clean_text,
    embed,
    fetch_collection_item,
    fetch_content,
    fetch_title,
    file_topic,
    news_quiz,
    note_cards,
    primer,
    take_cards,
    topic_primer,
    transcribe,
    update_brief,
)
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
    models.JobKind.TOPIC_PRIMER: HandlerSpec(run=topic_primer.handle),
    # A long episode is many minutes of downloads and provider calls, so it isn't swept as stale at 900 s.
    models.JobKind.TRANSCRIBE: HandlerSpec(
        run=transcribe.handle,
        on_final_failure=mark_source_failed,
        stale_after=datetime.timedelta(seconds=3600),
    ),
    # No failure hook: filing never blocks a source from being ready.
    models.JobKind.FILE_TOPIC: HandlerSpec(run=file_topic.handle),
    # No failure hook: when cleaning fails, the newsletter is analyzed from its text as it was.
    models.JobKind.CLEAN_TEXT: HandlerSpec(run=clean_text.handle),
    # No failure hook: a failed rewrite leaves the brief's previous content in place.
    models.JobKind.UPDATE_BRIEF: HandlerSpec(run=update_brief.handle),
    # A saved post's preview; when it gives up the post keeps its URL and shows a neutral tile.
    models.JobKind.FETCH_COLLECTION_ITEM: HandlerSpec(
        run=fetch_collection_item.handle, on_final_failure=fetch_collection_item.mark_failed
    ),
    # No failure hook: a failed quiz only means no quiz this week.
    models.JobKind.NEWS_QUIZ: HandlerSpec(run=news_quiz.handle),
    # When it gives up the take shows its raw text with Try again, and still gets its cards.
    models.JobKind.CLEAN_TAKE: HandlerSpec(run=clean_take.handle, on_final_failure=clean_take.mark_failed),
    # No failure hook: a take without cards still reads fine.
    models.JobKind.TAKE_CARDS: HandlerSpec(run=take_cards.handle),
    # No failure hook: a note without cards still reads fine.
    models.JobKind.NOTE_CARDS: HandlerSpec(run=note_cards.handle),
    # No failure hook: an item without chunks is only missing from search until its next save or the backfill.
    models.JobKind.EMBED: HandlerSpec(run=embed.handle),
}
