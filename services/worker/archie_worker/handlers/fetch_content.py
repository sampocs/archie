"""`fetch_content`: get a source's readable text, store it as a `text` artifact, and queue analyze and primer.

The text comes from the Safari capture when the phone sent one, else from the X thread (for X posts) or
the fetched page (for articles). Too little text fails the job at once as `TEXT_MISSING`, since fetching
the same page again will not help; the user is told to share it from Safari instead. Following the loop's
handler contract, the source is read and marked `processing` in a committed transaction before any
outside call, and the result is written under the user's lock afterwards.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy.orm
from archie_db import changes, models, pipeline
from archie_shared import logging, urls

from archie_worker import content, errors
from archie_worker.content import article, x
from archie_worker.handlers import fetch_title

_PAGE_TIMEOUT_SECONDS = 15
_PAGE_MAX_BYTES = 5_000_000
_MIN_ARTICLE_WORDS = 50
_MIN_X_WORDS = 1
_MAX_TITLE_LENGTH = 500
# Postgres text columns reject NUL, so a page containing one would fail the job forever.
_NUL = "\x00"

_logger = logging.get_logger(logging.LoggerName.WORKER, "fetch_content")


@dataclass(frozen=True)
class _SourceInput:
    """What the fetch needs from the source, copied out so no ORM object is touched during the outside call."""

    source_id: uuid.UUID
    user_id: int
    url: str
    kind: str
    capture_title: str | None
    capture_text: str | None


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Fetch the source's text and store it as the current `text` artifact, then queue analyze and primer."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return

    source_input = _start_processing(db, source=source)
    if source_input is None:
        return

    extracted = _get_text(source_input)
    word_count = len(extracted.text.split())
    minimum_words = _MIN_X_WORDS if source_input.kind == models.SourceKind.X else _MIN_ARTICLE_WORDS
    if word_count < minimum_words:
        _logger.info("Source %s has %d words, needs %d", source_input.source_id, word_count, minimum_words)
        raise errors.PermanentJobError(errors.FailureReason.TEXT_MISSING)

    # The user may have deleted the source during the fetch; the lock makes the refreshed state final.
    changes.lock_user_writes(db, source_input.user_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return

    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.TEXT,
        content={"text": extracted.text},
        model=None,
        prompt_version=None,
    )
    _set_title_if_empty(source, title=extracted.title)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.ANALYZE, models.JobKind.PRIMER])


def _start_processing(db: sqlalchemy.orm.Session, *, source: models.Source) -> _SourceInput | None:
    """Mark the source `processing` and commit, returning what the fetch needs; None if it was just deleted.

    Committing ends the transaction so no connection is held while the page or thread is fetched.
    """
    capture = db.get(models.SourceCapture, source.id)
    source_input = _SourceInput(
        source_id=source.id,
        user_id=source.user_id,
        url=source.url,
        kind=source.kind,
        capture_title=capture.title if capture else None,
        capture_text=capture.text if capture else None,
    )

    changes.lock_user_writes(db, source_input.user_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return None

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    db.commit()
    return source_input


def _get_text(source_input: _SourceInput) -> content.ExtractedText:
    """The source's text: its capture if it has one, else the X thread or the fetched page."""
    if source_input.capture_text is not None:
        return content.ExtractedText(
            title=source_input.capture_title, text=article.clean_capture(source_input.capture_text)
        )

    if source_input.kind == models.SourceKind.X:
        post_id = urls.x_post_id(source_input.url)
        if post_id is None:
            raise errors.PermanentJobError(errors.FailureReason.TEXT_MISSING)
        return x.fetch_thread(post_id=post_id)

    page = fetch_title.fetch_page(
        url=source_input.url, timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES
    )
    return article.extract(html=page, url=source_input.url) or content.ExtractedText(title=None, text="")


def _set_title_if_empty(source: models.Source, *, title: str | None) -> None:
    cleaned = " ".join((title or "").replace(_NUL, "").split())[:_MAX_TITLE_LENGTH]
    if source.title or not cleaned:
        return

    source.title = cleaned
    source.updated_at = sqlalchemy.func.now()
    source.change_seq = changes.next_change_seq()
