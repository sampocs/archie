"""`fetch_title`: read a saved link's page and store its title on the source.

The page's `og:title` (what sites choose to show when shared) wins over its `<title>`. A page with
neither is a success with nothing to write; only a failed fetch raises, so the loop retries it.
"""

from __future__ import annotations

import html.parser
import time
import urllib.parse
import uuid
from collections.abc import Mapping

import httpx
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline
from archie_shared import logging

SOURCE_ID_KEY = pipeline.SOURCE_ID_KEY

_FETCH_TIMEOUT_SECONDS = 10
_MAX_BODY_BYTES = 1_000_000
_MAX_TITLE_LENGTH = 500
_OG_TITLE_PROPERTY = "og:title"
_OG_IMAGE_PROPERTY = "og:image"
_OG_DESCRIPTION_PROPERTY = "og:description"
_MAX_DESCRIPTION_LENGTH = 1000
_MAX_IMAGE_URL_LENGTH = 2048
_IMAGE_SCHEMES = frozenset({"http", "https"})
# Postgres text columns reject NUL, so a page containing one would fail the job forever.
_NUL = "\x00"

_logger = logging.get_logger(logging.LoggerName.WORKER, "fetch_title")


class _TitleParser(html.parser.HTMLParser):
    """Collects the page's `og:title`, first `og:image` and description tags and the text of its first `<title>`."""

    def __init__(self) -> None:
        super().__init__()
        self.og_title: str | None = None
        self.og_image: str | None = None
        self.og_description: str | None = None
        self.meta_description: str | None = None
        self.title_text = ""
        self._in_title = False
        self._title_done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Note an `og:title` meta tag, or the start of the first `<title>`."""
        if tag == "title" and not self._title_done:
            self._in_title = True
            return

        if tag != "meta":
            return
        attributes = dict(attrs)
        content = attributes.get("content")
        if content is None:
            return
        if attributes.get("property") == _OG_TITLE_PROPERTY and self.og_title is None:
            self.og_title = content
        if attributes.get("property") == _OG_IMAGE_PROPERTY and self.og_image is None:
            self.og_image = content
        if attributes.get("property") == _OG_DESCRIPTION_PROPERTY and self.og_description is None:
            self.og_description = content
        if attributes.get("name") == "description" and self.meta_description is None:
            self.meta_description = content

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

    # Committing first releases the connection's transaction, and the page is fetched before the user's
    # write lock is taken, so a slow site never holds either or blocks their syncs.
    source_id, url, user_id = source.id, source.url, source.user_id
    db.commit()
    page = fetch_page(url=url, timeout_seconds=_FETCH_TIMEOUT_SECONDS, max_bytes=_MAX_BODY_BYTES)
    title = extract_title(page=page)
    image_url = extract_image(page=page, base_url=url)
    if title is None and image_url is None:
        _logger.info("No title or image found for source %s", source_id)
        return

    # The user may have deleted the link during the fetch; the lock makes the refreshed state final.
    changes.lock_user_writes(db, user_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return

    if title is not None:
        source.title = title
    if image_url is not None and not source.image_url:
        source.image_url = image_url
    source.updated_at = sqlalchemy.func.now()
    source.change_seq = changes.next_change_seq()


def extract_title(*, page: str) -> str | None:
    """The page's `og:title`, else its `<title>`: NUL stripped, whitespace collapsed, capped at 500 characters.

    A blank candidate is skipped, so it never hides the next one; None when neither has text.
    """
    parser = _TitleParser()
    parser.feed(page)
    parser.close()

    raw_titles = (parser.og_title or "", parser.title_text)
    candidates = (" ".join(raw_title.replace(_NUL, "").split()) for raw_title in raw_titles)
    title = next((candidate for candidate in candidates if candidate), None)
    return title[:_MAX_TITLE_LENGTH] if title else None


def extract_description(*, page: str) -> str | None:
    """The page's `og:description`, else its meta description: NUL stripped, whitespace collapsed, capped at 1,000.

    A blank candidate is skipped, so it never hides the next one; None when neither has text.
    """
    parser = _TitleParser()
    parser.feed(page)
    parser.close()

    raw_descriptions = (parser.og_description or "", parser.meta_description or "")
    candidates = (" ".join(raw.replace(_NUL, "").split()) for raw in raw_descriptions)
    description = next((candidate for candidate in candidates if candidate), None)
    return description[:_MAX_DESCRIPTION_LENGTH] if description else None


def extract_image(*, page: str, base_url: str) -> str | None:
    """The page's first `og:image` made absolute against `base_url`; None unless it is a sane http(s) URL."""
    parser = _TitleParser()
    parser.feed(page)
    parser.close()
    if not parser.og_image:
        return None

    absolute = urllib.parse.urljoin(base_url, parser.og_image.strip()).replace(_NUL, "")
    if urllib.parse.urlparse(absolute).scheme not in _IMAGE_SCHEMES or len(absolute) > _MAX_IMAGE_URL_LENGTH:
        return None
    return absolute


def fetch_page(*, url: str, timeout_seconds: float, max_bytes: int, headers: Mapping[str, str] | None = None) -> str:
    """Download `url` as text, reading at most `max_bytes`; raises on any 4xx/5xx or past a total `timeout_seconds`.

    httpx's timeout applies to each read, so the deadline is checked per chunk to stop a trickling server
    from holding the worker; the loop's error boundary retries the `TimeoutError`.
    """
    body, encoding = _download(
        url=url, timeout_seconds=timeout_seconds, max_bytes=max_bytes, headers=headers, params=None
    )
    return body.decode(encoding or "utf-8", errors="replace")


def fetch_bytes(
    *,
    url: str,
    timeout_seconds: float,
    max_bytes: int,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
) -> bytes:
    """Download `url` as bytes with the same limits and errors as `fetch_page` (feeds, transcripts, JSON)."""
    body, _ = _download(url=url, timeout_seconds=timeout_seconds, max_bytes=max_bytes, headers=headers, params=params)
    return body


def _download(
    *,
    url: str,
    timeout_seconds: float,
    max_bytes: int,
    headers: Mapping[str, str] | None,
    params: Mapping[str, str] | None,
) -> tuple[bytes, str | None]:
    deadline = time.monotonic() + timeout_seconds
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        with client.stream("GET", url, params=params) as response:
            response.raise_for_status()

            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Fetching {url} took longer than {timeout_seconds}s")
                body.extend(chunk)
                if len(body) >= max_bytes:
                    break
            return bytes(body[:max_bytes]), response.encoding
