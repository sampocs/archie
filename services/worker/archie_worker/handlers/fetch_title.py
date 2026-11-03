"""`fetch_title`: read a saved link's page and store its title on the source.

The page's `og:title` (what sites choose to show when shared) wins over its `<title>`. A page with
neither is a success with nothing to write; only a failed fetch raises, so the loop retries it.
"""

from __future__ import annotations

import html.parser
import uuid

import httpx
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models
from archie_shared import logging

SOURCE_ID_KEY = "source_id"

_FETCH_TIMEOUT_SECONDS = 10
_MAX_BODY_BYTES = 1_000_000
_OG_TITLE_PROPERTY = "og:title"

_logger = logging.get_logger(logging.LoggerName.WORKER, "fetch_title")


class _TitleParser(html.parser.HTMLParser):
    """Collects the page's `og:title` and the text of its first `<title>`."""

    def __init__(self) -> None:
        super().__init__()
        self.og_title: str | None = None
        self.title_text = ""
        self._in_title = False
        self._title_done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Note an `og:title` meta tag, or the start of the first `<title>`."""
        if tag == "title" and not self._title_done:
            self._in_title = True
            return

        if tag != "meta" or self.og_title is not None:
            return
        attributes = dict(attrs)
        if attributes.get("property") == _OG_TITLE_PROPERTY and attributes.get("content"):
            self.og_title = attributes["content"]

    def handle_endtag(self, tag: str) -> None:
        """Close the first `<title>`."""
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_done = True

    def handle_data(self, data: str) -> None:
        """Accumulate text while inside `<title>`."""
        if self._in_title:
            self.title_text += data


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Fetch the source's page and write its title, bumping the source's change position so phones pull it."""
    source = db.get(models.Source, uuid.UUID(job.payload[SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return

    # The page is fetched before the user's write lock is taken, so a slow site never blocks their syncs.
    title = extract_title(page=_fetch_page(url=source.url))
    if title is None:
        _logger.info("No title found for source %s", source.id)
        return

    changes.lock_user_writes(db, job.user_id)
    source.title = title
    source.updated_at = sqlalchemy.func.now()
    source.change_seq = changes.next_change_seq()


def extract_title(*, page: str) -> str | None:
    """The page's `og:title`, else its `<title>`, with whitespace collapsed; None when it has neither."""
    parser = _TitleParser()
    parser.feed(page)
    parser.close()

    raw_title = parser.og_title or parser.title_text
    return " ".join(raw_title.split()) or None


def _fetch_page(*, url: str) -> str:
    """Download `url` as text, reading at most 1 MB; raises on any 4xx/5xx so the job retries."""
    with httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()

            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) >= _MAX_BODY_BYTES:
                    break
            return bytes(body[:_MAX_BODY_BYTES]).decode(response.encoding or "utf-8", errors="replace")
