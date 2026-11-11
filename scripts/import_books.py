"""Import finished books, with the owner's notes and hand-tuned cards, into Archie (the one-off books bootstrap).

Usage:
    ARCHIE_SESSION_KEY=... python scripts/import_books.py books.json [--api-url URL]

The file (kept outside the repo) is a JSON list of books::

    {"title": str, "author": str | null, "notes_markdown": str,
     "cards": [{"kind": "concept" | "mechanism" | "number", "question": str, "answer": str,
                "detail": [str], "available_at": ISO datetime}]}

Each title is looked up through ``/books/lookup`` for its URL and cover (a book with no match is still imported, under
a URL made from its title), then the books go to ``/books/import``, which queues their refreshers a minute apart. Get
the session key by running ``archie-issue-session --email <your email>`` against the target database (see
``services/api/archie_api/auth/issue_session.py``) and exporting its output as ``ARCHIE_SESSION_KEY``.

Privacy: this script prints counts only - never a title, a note or a card, including in error messages.

Standard library only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence

DEFAULT_API_URL = "https://archie-production-4856.up.railway.app"
SESSION_KEY_VARIABLE = "ARCHIE_SESSION_KEY"
# The server's per-request limit.
BATCH_SIZE = 10
REQUEST_TIMEOUT_SECONDS = 60
LOOKUP_PATH = "/books/lookup"
IMPORT_PATH = "/books/import"
# What the lookup answers when it found no book, and when it couldn't reach Goodreads or Open Library.
NO_MATCH_STATUSES = frozenset({404, 502})


@dataclasses.dataclass(frozen=True)
class ImportTally:
    """How many books the lookup matched, and what the import did with them."""

    matched: int = 0
    created: int = 0
    skipped: int = 0


def book_payload(book: dict[str, object], match: dict[str, object] | None) -> dict[str, object]:
    """The import entry for one book: the file's fields, with the lookup's URL and cover (and author, if missing)."""
    author = book.get("author") or (match.get("author") if match else None)
    return {
        "title": book["title"],
        "author": author,
        "url": match.get("url") if match else None,
        "image_url": match.get("cover_url") if match else None,
        "notes_markdown": book.get("notes_markdown", ""),
        "cards": book.get("cards", []),
    }


def main(argv: list[str] | None = None) -> int:
    """Look each book up, import them in batches, and print the counts."""
    args = _parse_args(argv)
    books = _load_books(args.books)

    session_key = os.environ.get(SESSION_KEY_VARIABLE)
    if not session_key:
        print(f"Set {SESSION_KEY_VARIABLE} (see archie-issue-session) before importing.", file=sys.stderr)
        return 2

    try:
        tally = _import(books=books, api_url=args.api_url, session_key=session_key)
    except _RequestFailedError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(
        f"Books in the file: {len(books)}; matched by the lookup: {tally.matched}; "
        f"created {tally.created}, skipped as already imported {tally.skipped}."
    )
    return 0


class _RequestFailedError(Exception):
    """A failed API request, carrying only the path, the status and the server's plain detail - never book text."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import finished books with their notes and cards into Archie.")
    parser.add_argument("books", type=pathlib.Path, help="JSON list of books")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    return parser.parse_args(argv)


def _load_books(path: pathlib.Path) -> list[dict[str, object]]:
    entries = json.loads(path.read_text())
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("title"):
            raise SystemExit(f"Books file entry {index} needs a title.")
    return entries


def _import(books: Sequence[dict[str, object]], api_url: str, session_key: str) -> ImportTally:
    matches = [_lookup(title=str(book["title"]), api_url=api_url, session_key=session_key) for book in books]
    payloads = [book_payload(book, match) for book, match in zip(books, matches, strict=True)]

    created = 0
    skipped = 0
    for start in range(0, len(payloads), BATCH_SIZE):
        body = {"books": payloads[start : start + BATCH_SIZE]}
        response = _post(api_url=api_url, path=IMPORT_PATH, body=body, session_key=session_key)
        created += len(response["created"])
        skipped += len(response["skipped"])

    return ImportTally(matched=sum(match is not None for match in matches), created=created, skipped=skipped)


def _lookup(title: str, api_url: str, session_key: str) -> dict[str, object] | None:
    """The lookup's match for `title`, or None when it found none or couldn't reach its sources."""
    try:
        return _post(api_url=api_url, path=LOOKUP_PATH, body={"query": title}, session_key=session_key)
    except _RequestFailedError as error:
        if error.status in NO_MATCH_STATUSES:
            return None
        raise


def _post(api_url: str, path: str, body: dict[str, object], session_key: str) -> dict[str, object]:
    request = urllib.request.Request(
        url=f"{api_url.rstrip('/')}{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {session_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        message = f"{path} failed with HTTP {error.code}: {_error_detail(error)}"
        raise _RequestFailedError(message, status=error.code) from None
    except (urllib.error.URLError, TimeoutError):
        # No body text: the reason string of a URLError can echo the request URL.
        raise _RequestFailedError(f"{path} failed: could not reach the server") from None


def _error_detail(error: urllib.error.HTTPError) -> str:
    """The server's detail when it is a plain string, else only the field locations and messages of a 422.

    A 422's entries carry an ``input`` key holding the submitted notes or cards, so it is never read.
    """
    try:
        detail = json.loads(error.read()).get("detail", "")
        if isinstance(detail, str):
            return detail
        return "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in detail)
    except (ValueError, AttributeError, KeyError, TypeError):
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
