"""`fetch_content`: get a source's readable text, store it as a `text` artifact, and queue the kind's next steps.

The text comes from the Safari capture when the phone sent one, else from the X thread (for X posts) or the fetched
page (for articles, and for an article whose capture is too short to use). Too little text, or a page that answers
401, 403, 404, 410 or 451 (a paywall, block or missing page), fails the job at once as `TEXT_MISSING`, since fetching
the same page again will not help; the user is told to share it from Safari instead, and the row keeps the captured
title. A newsletter has no page to fetch (its URL is `newsletter:<message-id>`), so one without a capture, or with too
little text, fails as `NEWSLETTER_UNREADABLE`. Other failures are retried. Following the loop's handler contract, the
source is read and marked `processing` in a committed transaction before any outside call, and the result is written
under the user's lock afterwards.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass

import httpx
import sqlalchemy
import sqlalchemy.orm
import youtube_transcript_api
from archie_db import changes, models, pipeline
from archie_shared import config, logging, urls

from archie_worker import content, errors
from archie_worker.content import article, podcast, transcripts, x, youtube
from archie_worker.content import episode as episode_content
from archie_worker.handlers import _text, fetch_title

_PAGE_TIMEOUT_SECONDS = 15
_PAGE_MAX_BYTES = 5_000_000
_MIN_ARTICLE_WORDS = 50
_MIN_X_WORDS = 1
# Page statuses that mean "paywalled, blocked or gone"; a retry cannot fix them, sharing from Safari can.
_PERMANENT_PAGE_STATUSES = frozenset({401, 403, 404, 410, 451})

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
    episode_guid: str | None


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Fetch the source's text and store it as the current `text` artifact, then queue the kind's next steps."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return

    source_input = _start_processing(db, source=source)
    if source_input is None:
        return

    if source_input.kind == models.SourceKind.YOUTUBE:
        _fetch_youtube(db, source=source, source_input=source_input)
        return

    if source_input.kind == models.SourceKind.PODCAST:
        _fetch_podcast(db, source=source, source_input=source_input)
        return

    is_newsletter = source_input.kind == models.SourceKind.NEWSLETTER
    if is_newsletter and source_input.capture_text is None:
        raise errors.PermanentJobError(errors.FailureReason.NEWSLETTER_UNREADABLE)

    extracted = _get_text(source_input)
    word_count = len(extracted.text.split())
    minimum_words = _MIN_X_WORDS if source_input.kind == models.SourceKind.X else _MIN_ARTICLE_WORDS
    if word_count < minimum_words:
        _logger.info("Source %s has %d words, needs %d", source_input.source_id, word_count, minimum_words)
        raise errors.PermanentJobError(
            errors.FailureReason.NEWSLETTER_UNREADABLE if is_newsletter else errors.FailureReason.TEXT_MISSING
        )

    _text.store_text(
        db,
        source=source,
        text_content={content.TEXT_KEY: content.strip_nul(extracted.text)},
        title=extracted.title,
        image_url=extracted.image_url,
        published_at=extracted.published_at,
    )


def _fetch_podcast(db: sqlalchemy.orm.Session, *, source: models.Source, source_input: _SourceInput) -> None:
    """Resolve the episode, then store its published transcript as the text, or queue `transcribe` when it has none."""
    link = urls.podcast_link(source_input.url)
    if link is None:
        raise errors.PermanentJobError(errors.FailureReason.EPISODE_NOT_FOUND)

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    resolved = podcast.resolve(engine, link=link, episode_guid=source_input.episode_guid)
    published = transcripts.fetch_best(resolved.transcripts)
    if published is None:
        _text.enqueue_transcribe(db, source=source, episode=resolved.episode)
        return

    episode_extra = {episode_content.EPISODE_KEY: resolved.episode.to_payload()}
    text_content = (
        content.timed_text_content(segments=published.segments, extra=episode_extra)
        if published.segments
        else {content.TEXT_KEY: content.strip_nul(published.text), **episode_extra}
    )
    _text.store_text(
        db,
        source=source,
        text_content=text_content,
        title=resolved.episode.title,
        image_url=resolved.episode.image_url,
        published_at=content.noon_utc(resolved.episode.published),
    )


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
        episode_guid=source.episode_guid,
    )

    changes.lock_user_writes(db, source_input.user_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return None

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    db.commit()
    return source_input


def _get_text(source_input: _SourceInput) -> content.ExtractedText:
    """The source's text: its capture if it has one, else the X thread or the fetched page.

    An article whose capture is too short to use falls back to its page: the share sheet sometimes reads the wrong part
    of a page (only the author box, say) while the page itself is readable. The capture's title stays the fallback.
    """
    if source_input.capture_text is not None:
        captured = content.ExtractedText(
            title=source_input.capture_title, text=article.clean_capture(source_input.capture_text)
        )
        if source_input.kind != models.SourceKind.ARTICLE or len(captured.text.split()) >= _MIN_ARTICLE_WORDS:
            return captured
        _logger.info("Source %s capture is too short; fetching its page", source_input.source_id)
        page = _fetch_article(source_input)
        # A paywall teaser can be no better than the capture; the page wins only when it has more text.
        return page if len(page.text.split()) > len(captured.text.split()) else captured

    if source_input.kind == models.SourceKind.X:
        post_id = urls.x_post_id(source_input.url)
        if post_id is None:
            raise errors.PermanentJobError(errors.FailureReason.TEXT_MISSING)
        return x.fetch_thread(post_id=post_id)

    return _fetch_article(source_input)


def _fetch_article(source_input: _SourceInput) -> content.ExtractedText:
    """The fetched page's text, titled by the capture when the page has no title of its own."""
    try:
        page = fetch_title.fetch_page(
            url=source_input.url, timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code not in _PERMANENT_PAGE_STATUSES:
            raise
        _logger.info("Source %s page answered %d", source_input.source_id, error.response.status_code)
        raise errors.PermanentJobError(errors.FailureReason.TEXT_MISSING) from error

    extracted = article.extract(html=page, url=source_input.url) or content.ExtractedText(title=None, text="")
    if not extracted.title and source_input.capture_title:
        return dataclasses.replace(extracted, title=source_input.capture_title)
    return extracted


def _fetch_youtube(db: sqlalchemy.orm.Session, *, source: models.Source, source_input: _SourceInput) -> None:
    """Store the video's captions as timed text, titling the source from its watch page if it has no title."""
    video_id = urls.youtube_video_id(source_input.url)
    if video_id is None:
        raise errors.PermanentJobError(errors.FailureReason.VIDEO_UNAVAILABLE)

    # Read before the commit that ends the transaction, so no connection is held during the outside calls.
    has_title = bool(source.title)
    db.commit()

    supadata_api_key = config.Settings().supadata_api_key
    try:
        segments = youtube.fetch_segments(video_id=video_id, supadata_api_key=supadata_api_key)
    except youtube_transcript_api.CouldNotRetrieveTranscript as error:
        permanent_error = youtube.permanent_error_for(error)
        if permanent_error is None:
            raise
        raise permanent_error from error

    word_count = sum(len(segment.text.split()) for segment in segments)
    if word_count < _MIN_ARTICLE_WORDS:
        _logger.info("Video %s has %d caption words, needs %d", video_id, word_count, _MIN_ARTICLE_WORDS)
        raise errors.PermanentJobError(errors.FailureReason.NO_CAPTIONS)

    title = None if has_title else youtube.fetch_title(video_id=video_id)
    _text.store_text(
        db,
        source=source,
        text_content=content.timed_text_content(segments=segments),
        title=title,
        image_url=youtube.thumbnail_url(video_id),
    )
