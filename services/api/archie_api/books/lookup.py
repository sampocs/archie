"""Find a book from what the owner typed or shared: a Goodreads book link is read from its page, anything else is a
title searched on Open Library.

Goodreads answers 503 without browser-like headers, and its search page answers a bot challenge, so a title search
never goes there.
"""

from __future__ import annotations

import html.parser
import json
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
from archie_shared import podcast_feed, urls

REQUEST_TIMEOUT_SECONDS = 8
# add_book's limits (archie_api.sync.book_actions), so a looked-up book can always be added.
MAX_TITLE_LENGTH = 500
MAX_AUTHOR_LENGTH = 300
GOODREADS_HOST = "goodreads.com"
GOODREADS_BOOK_PATH = "/book/show/"
OPEN_LIBRARY_URL = "https://openlibrary.org"
OPEN_LIBRARY_SEARCH_URL = f"{OPEN_LIBRARY_URL}/search.json"
OPEN_LIBRARY_FIELDS = "key,title,author_name,first_publish_year,cover_i"
OPEN_LIBRARY_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"

_GOODREADS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": podcast_feed.USER_AGENT,
}
_OPEN_LIBRARY_HEADERS = {"User-Agent": podcast_feed.USER_AGENT}
_JSON_LD_TYPE = "application/ld+json"
_BOOK_TYPE = "Book"
_OG_URL = "og:url"
_HTTP_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class BookMatch:
    """The book a lookup found; `author`, `year` and `cover_url` are None when the source doesn't say."""

    title: str
    author: str | None
    year: int | None
    cover_url: str | None
    url: str


class BookNotFoundError(Exception):
    """The lookup answered, but with no book."""


class LookupUnavailableError(Exception):
    """The lookup could not be reached, or answered with something other than 200."""


def find_book(query: str) -> BookMatch:
    """The book `query` names: a Goodreads book URL's page, else the top Open Library match for it as a title.

    Raises `BookNotFoundError` when there is no book, `LookupUnavailableError` when the lookup failed.
    """
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        if is_goodreads_book_url(query):
            page = _get(client, url=query.strip(), params=None, headers=_GOODREADS_HEADERS)
            return parse_goodreads_page(page=page.text, fallback_url=query.strip())

        response = _get(
            client,
            url=OPEN_LIBRARY_SEARCH_URL,
            params={"q": query, "limit": "1", "fields": OPEN_LIBRARY_FIELDS},
            headers=_OPEN_LIBRARY_HEADERS,
        )
        try:
            body = response.json()
        except ValueError as error:
            raise LookupUnavailableError("Open Library answered with something other than JSON") from error
        return _open_library_match(body)


def is_goodreads_book_url(text: str) -> bool:
    """Whether `text` is an http(s) link to a book's page on Goodreads."""
    stripped = text.strip()
    if urllib.parse.urlsplit(stripped).scheme.lower() not in _HTTP_SCHEMES:
        return False

    parts = urllib.parse.urlsplit(urls.normalize_url(stripped))
    return parts.netloc == GOODREADS_HOST and parts.path.startswith(GOODREADS_BOOK_PATH)


def parse_goodreads_page(*, page: str, fallback_url: str) -> BookMatch:
    """The book in a Goodreads page's JSON-LD (`@type` Book), at the page's canonical `og:url` (else `fallback_url`).

    Every author's name is kept, joined with ", ". The JSON-LD carries no year. Raises `BookNotFoundError` when the
    page has no Book block with a name.
    """
    parser = _BookPageParser()
    parser.feed(page)
    book = next((block for block in parser.json_ld_blocks if block.get("@type") == _BOOK_TYPE), None)
    if book is None or not isinstance(book.get("name"), str) or not book["name"].strip():
        raise BookNotFoundError("The page has no book")

    image = book.get("image")
    return BookMatch(
        title=_truncate_words(book["name"].strip(), limit=MAX_TITLE_LENGTH),
        author=_author_names(book.get("author")),
        year=None,
        cover_url=image if isinstance(image, str) and image else None,
        url=parser.og_url or fallback_url,
    )


def _get(client: httpx.Client, *, url: str, params: dict[str, str] | None, headers: dict[str, str]) -> httpx.Response:
    try:
        response = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as error:
        raise LookupUnavailableError(f"Couldn't reach {urllib.parse.urlsplit(url).netloc}") from error

    if response.status_code != httpx.codes.OK:
        raise LookupUnavailableError(f"{urllib.parse.urlsplit(url).netloc} answered {response.status_code}")
    return response


def _open_library_match(body: Any) -> BookMatch:
    docs = body.get("docs") if isinstance(body, dict) else None
    if not docs:
        raise BookNotFoundError("Open Library found nothing")

    doc = docs[0]
    authors = doc.get("author_name") or []
    year = doc.get("first_publish_year")
    cover_id = doc.get("cover_i")
    return BookMatch(
        title=_truncate_words(doc["title"], limit=MAX_TITLE_LENGTH),
        author=_join_authors(authors),
        year=year if isinstance(year, int) else None,
        cover_url=OPEN_LIBRARY_COVER_URL.format(cover_id=cover_id) if cover_id else None,
        url=f"{OPEN_LIBRARY_URL}{doc['key']}",
    )


def _author_names(author: Any) -> str | None:
    """Every author's name joined with ", "; the JSON-LD gives one author as an object and several as a list."""
    entries = author if isinstance(author, list) else [author]
    names = [
        entry["name"].strip() for entry in entries if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ]
    return _join_authors([name for name in names if name])


def _join_authors(names: list[str]) -> str | None:
    """The names joined with ", ", keeping whole names while they fit `MAX_AUTHOR_LENGTH`; a too-long first is cut."""
    if not names:
        return None

    joined = names[0]
    for name in names[1:]:
        if len(joined) + len(", ") + len(name) > MAX_AUTHOR_LENGTH:
            break
        joined = f"{joined}, {name}"
    return _truncate_words(joined, limit=MAX_AUTHOR_LENGTH)


def _truncate_words(text: str, *, limit: int) -> str:
    """`text` cut to `limit` characters at a word boundary, or at `limit` when its first word is that long."""
    if len(text) <= limit:
        return text

    cut = text[:limit]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > 0 else cut).rstrip()


class _BookPageParser(html.parser.HTMLParser):
    """Collects a page's JSON-LD objects and its `og:url`."""

    def __init__(self) -> None:
        super().__init__()
        self.json_ld_blocks: list[dict[str, Any]] = []
        self.og_url: str | None = None
        self._in_json_ld = False
        self._json_ld_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Note a JSON-LD script's start, and read `og:url` from its meta tag."""
        attributes = dict(attrs)
        if tag == "script" and attributes.get("type") == _JSON_LD_TYPE:
            self._in_json_ld = True
            self._json_ld_text = []
        if tag == "meta" and attributes.get("property") == _OG_URL and attributes.get("content"):
            self.og_url = attributes["content"]

    def handle_data(self, data: str) -> None:
        """Gather a JSON-LD script's text."""
        if self._in_json_ld:
            self._json_ld_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Parse a finished JSON-LD script; one that isn't valid JSON is skipped."""
        if tag != "script" or not self._in_json_ld:
            return

        self._in_json_ld = False
        try:
            parsed = json.loads("".join(self._json_ld_text))
        except ValueError:
            return
        blocks = parsed if isinstance(parsed, list) else [parsed]
        self.json_ld_blocks.extend(block for block in blocks if isinstance(block, dict))
