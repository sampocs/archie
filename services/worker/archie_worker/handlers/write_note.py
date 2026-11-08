"""`write_note`: write an imported note's write-up, a fresh explanation of its subject as of today.

The note's Markdown is the direction, not the content: the model also reads the pages the note links to (best effort,
a link that cannot be fetched is skipped) and writes a summary that never mentions the note. Every link is stored on
the summary as a source. A note has no cards from this step (`note_cards` makes them), so the summary carries none.

A note re-imported with new Markdown during the call has a newer text artifact, so the finished write-up of the old
text is dropped: the re-import queued its own run. Follows the loop's handler contract: read and commit, fetch and
call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import datetime
import json
import urllib.parse
import uuid
from dataclasses import dataclass

import httpx
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, user_topics
from archie_llm import llm
from archie_shared import logging, podcast_feed

from archie_worker import keys, note_links, prompts
from archie_worker.content import article
from archie_worker.handlers import fetch_title

MAX_OUTPUT_TOKENS = 8000

_PAGE_TIMEOUT_SECONDS = 15
_PAGE_MAX_BYTES = 5_000_000
_EPISODE_MAX_BYTES = 1_000_000
# Wikipedia answers 403 to httpx's default User-Agent and to a bare client name; a browser-like one is let through.
_HEADERS = {"User-Agent": podcast_feed.USER_AGENT}
_MAX_REFERENCE_CHARACTERS = 20_000
_MAX_TOTAL_REFERENCE_CHARACTERS = 60_000

_logger = logging.get_logger(logging.LoggerName.WORKER, "write_note")


@dataclass(frozen=True)
class _WriteRun:
    """What the fetches, the model call and the write need after the first transaction ends."""

    source_id: uuid.UUID
    user_id: int
    text_artifact_id: uuid.UUID
    title: str | None
    tags: list[str]
    edited_on: datetime.date | None
    markdown: str
    context: llm.CallContext
    api_key: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the note's summary from its Markdown and linked pages, then queue its search and filing."""
    run = _prepare(db, job)
    if run is None:
        return

    links = note_links.links_in(run.markdown)
    references = _references(links)
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.NOTE_WRITE_UP_MODELS,
        system=prompts.NOTE_WRITE_UP_SYSTEM,
        user_message=prompts.note_write_up_message(
            today=datetime.date.today(),
            title=run.title,
            tags=run.tags,
            edited_on=run.edited_on,
            markdown=run.markdown,
            references=references,
        ),
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.NOTE_WRITE_UP_SCHEMA,
    )
    write_up = json.loads(completion.text)
    for item in [*write_up["summary"]["key_ideas"], *write_up["summary"]["numbers"]]:
        item["timestamp"] = None

    changes.lock_user_writes(db, run.user_id)
    source = db.get_one(models.Source, run.source_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return

    # Re-imported during the call: this write-up describes text that is no longer current.
    current_text = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if current_text is None or current_text.id != run.text_artifact_id:
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.READY)
        return

    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.SUMMARY,
        content={**write_up, "cards": [], prompts.SOURCES_KEY: _source_entries(links, references)},
        model=completion.model,
        prompt_version=prompts.NOTE_WRITE_UP_PROMPT_VERSION,
    )
    jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)

    # Filed once, after the first write-up; a later one never overrides a topic the user chose.
    user = db.get_one(models.User, source.user_id)
    if source.domain is None and user.topics_chosen_at is not None:
        user_topics.enqueue_file_topic(db, source=source)
    pipeline.finish_step(db, source=source)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _WriteRun | None:
    """Read what the call needs, mark the note processing and commit; None when the note is gone, deleted or no note.

    Raises `PermanentJobError` for a user without an API key (checked first), and a plain error when the note has no
    text artifact (the loop retries).
    """
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None or source.kind != models.SourceKind.NOTE:
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, source.user_id))
    text_artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if text_artifact is None:
        raise LookupError(f"Source {source.id} has no text artifact yet")

    changes.lock_user_writes(db, source.user_id)
    db.refresh(source)
    if source.deleted_at is not None:
        db.commit()
        return None

    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    run = _WriteRun(
        source_id=source.id,
        user_id=source.user_id,
        text_artifact_id=text_artifact.id,
        title=source.title,
        tags=list(source.note_tags or []),
        edited_on=source.note_edited_at.date() if source.note_edited_at else None,
        markdown=text_artifact.content["text"],
        context=llm.CallContext(
            user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.WRITE_NOTE
        ),
        api_key=api_key,
    )
    db.commit()
    return run


def _references(links: list[note_links.NoteLink]) -> list[prompts.NoteReference]:
    """What each reachable link says; a link that cannot be fetched or read is skipped, never failing the write-up."""
    references: list[prompts.NoteReference] = []
    page_characters = 0
    for link in links:
        if link.kind == note_links.LinkKind.PAGE and page_characters >= _MAX_TOTAL_REFERENCE_CHARACTERS:
            continue

        try:
            reference = _page_reference(link) if link.kind == note_links.LinkKind.PAGE else _episode_reference(link)
        except (httpx.HTTPError, TimeoutError, ValueError) as error:
            _logger.info("Skipping unreadable note link %s: %s", link.url, error)
            continue

        if reference is not None:
            references.append(reference)
            page_characters += len(reference.text) if link.kind == note_links.LinkKind.PAGE else 0
    return references


def _page_reference(link: note_links.NoteLink) -> prompts.NoteReference | None:
    page = fetch_title.fetch_page(
        url=link.url, timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES, headers=_HEADERS
    )
    extracted = article.extract(html=page, url=link.url)
    if extracted is None:
        return None

    return prompts.NoteReference(
        url=link.url,
        title=extracted.title or "",
        kind=note_links.LinkKind.PAGE,
        text=extracted.text[:_MAX_REFERENCE_CHARACTERS],
    )


def _episode_reference(link: note_links.NoteLink) -> prompts.NoteReference:
    page = fetch_title.fetch_page(
        url=link.url, timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_EPISODE_MAX_BYTES, headers=_HEADERS
    )
    return prompts.NoteReference(
        url=link.url,
        title=fetch_title.extract_title(page=page) or "",
        kind=note_links.LinkKind.EPISODE,
        text=fetch_title.extract_description(page=page) or "",
    )


def _source_entries(links: list[note_links.NoteLink], references: list[prompts.NoteReference]) -> list[dict[str, str]]:
    """Every link as a `{url, title}` source: its fetched title, else its link text, else its host."""
    fetched_titles = {reference.url: reference.title for reference in references}
    return [
        {"url": link.url, "title": fetched_titles.get(link.url) or link.text or _host_of(link.url)} for link in links
    ]


def _host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or url).removeprefix("www.")
