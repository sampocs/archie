"""Capture actions: add_source (classify, merge duplicates, start the pipeline) and retry_source."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib import parse

import pydantic
import sqlalchemy
from archie_db import changes, jobs, models, pipeline
from archie_shared import urls
from sqlalchemy import orm

MAX_URL_LENGTH = 2048
MAX_NOTE_LENGTH = 2_000
MAX_CAPTURE_TEXT_LENGTH = 400_000
MAX_CAPTURE_TITLE_LENGTH = 500

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
_INVALID_URL = "url is not a valid URL"
_MALFORMED_ADD_SOURCE = "payload needs id, url and intent"
_MALFORMED_RETRY_SOURCE = "payload needs id"
_NOT_FAILED = "source is not failed"
_SOURCE_ID_EXISTS = "source id already exists"

_SHOW_LINK_REASON = "Share an episode, not the show."
_CHANNEL_LINK_REASON = "Share a video, not the channel."


@dataclass(frozen=True)
class _Start:
    """How a new source begins: its processing status, any error to show, and the first job to queue."""

    processing: models.ProcessingStatus
    error: str | None
    first_job: models.JobKind


class _CapturePayload(pydantic.BaseModel):
    title: str | None = None
    text: str


class _AddSourcePayload(pydantic.BaseModel):
    id: uuid.UUID
    url: str
    intent: str
    reaction: str | None = None
    note: str | None = None
    prep_me: bool | None = None
    capture: _CapturePayload | None = None


class _RetrySourcePayload(pydantic.BaseModel):
    id: uuid.UUID


def add_source(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Add a source, or fold it into the user's existing source for the same page.

    Returns the rejection reason, or None when applied. The caller holds `changes.lock_user_writes`.
    """
    try:
        parsed = _AddSourcePayload.model_validate(payload)
    except pydantic.ValidationError:
        return _MALFORMED_ADD_SOURCE

    reason = _validate_add_source(db, payload=parsed)
    if reason is not None:
        return reason

    normalized_url = urls.normalize_url(parsed.url)
    existing = db.scalars(
        sqlalchemy.select(models.Source)
        .where(
            models.Source.user_id == user.id,
            models.Source.normalized_url == normalized_url,
            models.Source.deleted_at.is_(None),
        )
        .order_by(models.Source.created_at, models.Source.change_seq)
        .limit(1)
    ).one_or_none()

    if existing is None:
        _insert_source(db, user=user, payload=parsed, normalized_url=normalized_url)
        return None

    _insert_merged_source(db, user=user, payload=parsed, normalized_url=normalized_url, existing=existing)
    _merge_into(db, existing=existing, payload=parsed)
    return None


def retry_source(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Restart the pipeline for the user's failed source; returns the rejection reason, or None when applied."""
    try:
        parsed = _RetrySourcePayload.model_validate(payload)
    except pydantic.ValidationError:
        return _MALFORMED_RETRY_SOURCE

    source = db.get(models.Source, parsed.id)
    if source is None or source.user_id != user.id or source.deleted_at is not None:
        return _NOT_FAILED
    if source.processing != models.ProcessingStatus.FAILED:
        return _NOT_FAILED

    _restart_pipeline(db, source=source)
    return None


def _validate_add_source(db: orm.Session, *, payload: _AddSourcePayload) -> str | None:
    """The reason this add_source can't be applied, or None."""
    url_reason = _validate_url(payload.url)
    if url_reason is not None:
        return url_reason

    if payload.intent not in set(models.SourceIntent):
        return "intent must be finished or queue"

    finished = payload.intent == models.SourceIntent.FINISHED
    if payload.reaction is not None and payload.reaction not in set(models.Reaction):
        return "reaction must be easy, mostly or lost"
    if payload.reaction is not None and not finished:
        return "reaction needs intent finished"
    if payload.prep_me and finished:
        return "prep_me needs intent queue"
    if payload.note is not None and len(payload.note) > MAX_NOTE_LENGTH:
        return f"note is longer than {MAX_NOTE_LENGTH} characters"

    capture_reason = _validate_capture(payload.capture)
    if capture_reason is not None:
        return capture_reason

    # Even the caller's own id is refused: a retry carries the same action id, so a new one is a client bug.
    if db.get(models.Source, payload.id) is not None:
        return _SOURCE_ID_EXISTS
    return None


def _validate_url(url: str) -> str | None:
    if len(url) > MAX_URL_LENGTH:
        return f"url is longer than {MAX_URL_LENGTH} characters"

    # Postgres text can't hold NUL, and urlsplit raises on e.g. an unclosed IPv6 bracket; both are the client's bug.
    if "\x00" in url:
        return _INVALID_URL
    try:
        parts = parse.urlsplit(url)
    except ValueError:
        return _INVALID_URL

    if parts.scheme not in _ALLOWED_URL_SCHEMES or not parts.netloc:
        return "url must be http or https"
    return None


def _validate_capture(capture: _CapturePayload | None) -> str | None:
    if capture is None:
        return None
    if not capture.text.strip():
        return "capture text is empty"
    if len(capture.text) > MAX_CAPTURE_TEXT_LENGTH:
        return f"capture text is longer than {MAX_CAPTURE_TEXT_LENGTH} characters"
    if capture.title is not None and len(capture.title) > MAX_CAPTURE_TITLE_LENGTH:
        return f"capture title is longer than {MAX_CAPTURE_TITLE_LENGTH} characters"
    return None


def _start_for(url: str) -> _Start:
    """Classify `url`: pages the pipeline can fetch start pending; show and channel links wait unsupported."""
    url_kind = urls.detect_kind(url)
    unsupported_reason = None
    if url_kind == urls.UrlKind.PODCAST and urls.podcast_link(url) is None:
        unsupported_reason = _SHOW_LINK_REASON
    if url_kind == urls.UrlKind.YOUTUBE and urls.youtube_video_id(url) is None:
        unsupported_reason = _CHANNEL_LINK_REASON
    if unsupported_reason is not None:
        return _Start(
            processing=models.ProcessingStatus.UNSUPPORTED,
            error=unsupported_reason,
            first_job=models.JobKind.FETCH_TITLE,
        )

    # Any other kind (including an unrecognized link) is fetched as an article was before this task.
    return _Start(processing=models.ProcessingStatus.PENDING, error=None, first_job=models.JobKind.FETCH_CONTENT)


def _insert_source(db: orm.Session, *, user: models.User, payload: _AddSourcePayload, normalized_url: str) -> None:
    """Insert a new source and queue its first pipeline step."""
    start = _start_for(payload.url)
    source = _build_source(user=user, payload=payload, normalized_url=normalized_url, processing=start.processing)
    source.processing_error = start.error
    db.add(source)
    db.flush()
    if payload.capture is not None:
        _add_capture(db, source_id=source.id, capture=payload.capture)

    if start.first_job == models.JobKind.FETCH_CONTENT:
        pipeline.enqueue_steps(db, source=source, steps=[start.first_job])
        return
    jobs.enqueue(db, kind=start.first_job, user_id=user.id, payload={pipeline.SOURCE_ID_KEY: str(source.id)})


def _insert_merged_source(
    db: orm.Session,
    *,
    user: models.User,
    payload: _AddSourcePayload,
    normalized_url: str,
    existing: models.Source,
) -> None:
    """Record the phone's row as deleted and pointing at `existing`, so the phone learns which source won."""
    merged = _build_source(
        user=user,
        payload=payload,
        normalized_url=normalized_url,
        processing=models.ProcessingStatus(existing.processing),
    )
    merged.deleted_at = sqlalchemy.func.now()
    merged.merged_into_id = existing.id
    db.add(merged)
    db.flush()


def _build_source(
    *, user: models.User, payload: _AddSourcePayload, normalized_url: str, processing: models.ProcessingStatus
) -> models.Source:
    finished = payload.intent == models.SourceIntent.FINISHED
    return models.Source(
        id=payload.id,
        user_id=user.id,
        url=payload.url,
        normalized_url=normalized_url,
        kind=models.SourceKind(urls.detect_kind(payload.url)).value,
        state=(models.SourceState.CONSUMED if finished else models.SourceState.QUEUED).value,
        intent=payload.intent,
        processing=processing.value,
        reaction=payload.reaction,
        note=payload.note,
        prep_me=bool(payload.prep_me),
        change_seq=changes.next_change_seq(),
    )


def _merge_into(db: orm.Session, *, existing: models.Source, payload: _AddSourcePayload) -> None:
    """Fold a duplicate capture into `existing`: state moves forward only, given fields overwrite.

    An `unsupported` source (an M1 `link` row, or a YouTube/podcast share M2 stored without processing) is classified
    afresh by a new share of its page, and starts the pipeline when its URL is one the pipeline handles.
    """
    _start_if_now_processable(db, existing=existing)

    if payload.intent == models.SourceIntent.FINISHED:
        existing.intent = models.SourceIntent.FINISHED.value
        if existing.state == models.SourceState.QUEUED:
            existing.state = models.SourceState.CONSUMED.value

    if payload.reaction is not None:
        existing.reaction = payload.reaction
    if payload.note is not None:
        existing.note = payload.note
    # A finished source with prep_me is the combination validation rejects ("prep_me needs intent queue").
    if payload.prep_me is not None and existing.intent != models.SourceIntent.FINISHED:
        existing.prep_me = payload.prep_me

    stored_capture = False
    if payload.capture is not None and db.get(models.SourceCapture, existing.id) is None:
        _add_capture(db, source_id=existing.id, capture=payload.capture)
        stored_capture = True

    # A failed source retries only when this share brings the capture it lacked; the restart also moves the position.
    if stored_capture and existing.processing == models.ProcessingStatus.FAILED:
        _restart_pipeline(db, source=existing)
        return

    existing.updated_at = sqlalchemy.func.now()
    existing.change_seq = changes.next_change_seq()
    db.flush()


def _start_if_now_processable(db: orm.Session, *, existing: models.Source) -> None:
    """Give an M1 `link` source its real kind; start an `unsupported` source whose URL the pipeline can now process."""
    if existing.kind == models.SourceKind.LINK:
        existing.kind = models.SourceKind(urls.detect_kind(existing.url)).value

    if existing.processing != models.ProcessingStatus.UNSUPPORTED:
        return

    start = _start_for(existing.url)
    if start.processing != models.ProcessingStatus.PENDING:
        return

    pipeline.set_processing(db, source=existing, status=start.processing)
    pipeline.enqueue_steps(db, source=existing, steps=[start.first_job])


def _add_capture(db: orm.Session, *, source_id: uuid.UUID, capture: _CapturePayload) -> None:
    db.add(models.SourceCapture(source_id=source_id, title=capture.title, text=capture.text))
    db.flush()


def _restart_pipeline(db: orm.Session, *, source: models.Source) -> None:
    """Mark the source processing again and queue the steps whose output is missing."""
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.enqueue_steps(db, source=source, steps=pipeline.steps_to_retry(db, source_id=source.id))
