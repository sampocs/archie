"""Upload the Bear notes marked in a marks file to Archie.

Usage:
    ARCHIE_SESSION_KEY=... python scripts/import_bear.py --marks marks.json [--dry-run] [--write]

The marks file is a JSON list of ``{"id": <Bear note id>, "mark": "import" | "cards" | "skip"}``. Get the session key
by running ``archie-issue-session --email <your email>`` against the target database (see
``services/api/archie_api/auth/issue_session.py``) and exporting its output as ``ARCHIE_SESSION_KEY``.

Privacy: Bear's database is opened read-only, only marked notes are uploaded, and this script prints counts and
statuses only - never a note title or any note text, including in error messages.

Standard library only.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import pathlib
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence

DEFAULT_BEAR_DB = pathlib.Path.home() / (
    "Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite"
)
DEFAULT_API_URL = "https://archie-production-4856.up.railway.app"
SESSION_KEY_VARIABLE = "ARCHIE_SESSION_KEY"
BATCH_SIZE = 25
REQUEST_TIMEOUT_SECONDS = 60
MAX_TITLE_LENGTH = 500
MAX_BEAR_ID_LENGTH = 64
MAX_MARKDOWN_LENGTH = 200_000
MAX_TAGS = 50
MAX_TAG_LENGTH = 200
UNTITLED = "Untitled"
CORE_DATA_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.UTC)

MARK_IMPORT = "import"
MARK_CARDS = "cards"
UPLOADED_MARKS = (MARK_IMPORT, MARK_CARDS)

STATUS_CREATED = "created"
STATUS_UPDATED = "updated"
STATUS_UNCHANGED = "unchanged"
STATUS_DELETED = "deleted"

_TAG = r"(#[^\s#][^#\n]*#|#[\w/\-]+)"
_TAG_LINE = re.compile(rf"^\s*{_TAG}(\s+{_TAG})*\s*$")
_CODE_FENCE = "```"

_TAGS_QUERY = "select t.Z_5NOTES, g.ZTITLE from Z_5TAGS t join ZSFNOTETAG g on g.Z_PK = t.Z_13TAGS"
_NOTES_QUERY = """
    select Z_PK, ZUNIQUEIDENTIFIER, ZTITLE, ZTEXT, ZCREATIONDATE, ZMODIFICATIONDATE, coalesce(ZENCRYPTED, 0)
    from ZSFNOTE
    where coalesce(ZTRASHED, 0) = 0 and coalesce(ZARCHIVED, 0) = 0 and coalesce(ZPERMANENTLYDELETED, 0) = 0
"""


@dataclasses.dataclass(frozen=True)
class BearNote:
    """One live Bear note."""

    bear_id: str
    title: str
    markdown: str
    tags: list[str]
    created_at: datetime.datetime
    edited_at: datetime.datetime
    encrypted: bool


@dataclasses.dataclass(frozen=True)
class MarkedNotes:
    """The marked notes that can be uploaded, plus counts of those that cannot."""

    to_import: list[tuple[BearNote, str]]
    missing: int
    encrypted: int
    too_large: int


@dataclasses.dataclass(frozen=True)
class ImportTally:
    """How many notes the server reported per status."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0


def read_bear(db_path: pathlib.Path) -> list[BearNote]:
    """Read every live (not trashed, archived or deleted) note from a Bear database, read-only.

    Notes without a usable id (NULL or longer than the server accepts) are skipped; a NULL edit date falls back to the
    creation date.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tags_by_note: dict[int, list[str]] = {}
        for note_pk, tag_title in connection.execute(_TAGS_QUERY):
            tags_by_note.setdefault(note_pk, []).append(tag_title)

        rows = connection.execute(_NOTES_QUERY).fetchall()
    finally:
        connection.close()

    return [
        BearNote(
            bear_id=bear_id,
            title=_note_title(title=title, text=text),
            markdown=text or "",
            tags=sorted(tags_by_note.get(note_pk, [])),
            created_at=_from_core_data(created),
            edited_at=_from_core_data(created if modified is None else modified),
            encrypted=bool(encrypted),
        )
        for note_pk, bear_id, title, text, created, modified, encrypted in rows
        if bear_id is not None and len(bear_id) <= MAX_BEAR_ID_LENGTH
    ]


def marked_notes(notes: Sequence[BearNote], marks: Mapping[str, str]) -> MarkedNotes:
    """Pair notes marked import or cards with their mark, counting those missing, encrypted or over server limits."""
    by_id = {note.bear_id: note for note in notes}
    to_import: list[tuple[BearNote, str]] = []
    missing = 0
    encrypted = 0
    too_large = 0

    for bear_id, mark in marks.items():
        if mark not in UPLOADED_MARKS:
            continue

        note = by_id.get(bear_id)
        if note is None:
            missing += 1
        elif note.encrypted:
            encrypted += 1
        elif _exceeds_server_limits(note):
            too_large += 1
        else:
            to_import.append((note, mark))

    return MarkedNotes(to_import=to_import, missing=missing, encrypted=encrypted, too_large=too_large)


def note_payload(note: BearNote, mark: str) -> dict[str, object]:
    """The JSON body entry for one note."""
    return {
        "bear_id": note.bear_id,
        "title": note.title,
        "markdown": strip_tag_lines(note.markdown),
        "tags": note.tags,
        "created_at": note.created_at.isoformat(),
        "edited_at": note.edited_at.isoformat(),
        "mark": mark,
    }


def strip_tag_lines(markdown: str) -> str:
    """Drop lines made only of Bear tags (the tags travel separately), except inside fenced code blocks.

    Headings keep their space after the #.
    """
    kept: list[str] = []
    in_code_block = False

    for line in markdown.splitlines(keepends=True):
        # A "#tag" line inside a fenced code block is code (a shell comment, say), not a Bear tag.
        if line.lstrip().startswith(_CODE_FENCE):
            in_code_block = not in_code_block
        if in_code_block or not _TAG_LINE.match(line):
            kept.append(line)

    return "".join(kept)


def main(argv: list[str] | None = None) -> int:
    """Read Bear, report counts, and (unless --dry-run) upload the marked notes."""
    args = _parse_args(argv)
    marks = _load_marks(args.marks)
    marked = marked_notes(read_bear(args.bear_db), marks)

    counts = list(marks.values())
    print(
        f"Marked in the file: {counts.count(MARK_IMPORT)} import, {counts.count(MARK_CARDS)} cards; "
        f"found in Bear: {len(marked.to_import) + marked.encrypted}; missing from Bear: {marked.missing}; "
        f"skipped as encrypted: {marked.encrypted}; "
        f"skipped as over the server's size limits: {marked.too_large}."
    )
    if args.dry_run:
        return 0

    session_key = os.environ.get(SESSION_KEY_VARIABLE)
    if not session_key:
        print(f"Set {SESSION_KEY_VARIABLE} (see archie-issue-session) before importing.", file=sys.stderr)
        return 2

    try:
        tally = _upload(marked=marked, api_url=args.api_url, session_key=session_key)
        print(f"Imported: {_format_tally(tally)}")
        if args.write:
            queued = _post(api_url=args.api_url, path="/notes/write-ups", body=None, session_key=session_key)
            print(f"Queued {queued['queued']} write-ups (about one a minute).")
    except _RequestFailedError as error:
        print(str(error), file=sys.stderr)
        return 1

    return 0


class _RequestFailedError(Exception):
    """A failed API request, carrying only the path, the status and the server's plain detail - never note text."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload marked Bear notes to Archie.")
    parser.add_argument("--marks", type=pathlib.Path, required=True, help="JSON list of {id, mark}")
    parser.add_argument("--bear-db", type=pathlib.Path, default=DEFAULT_BEAR_DB)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--dry-run", action="store_true", help="print counts and stop")
    parser.add_argument("--write", action="store_true", help="queue write-ups after importing")
    return parser.parse_args(argv)


def _load_marks(path: pathlib.Path) -> dict[str, str]:
    entries = json.loads(path.read_text())
    marks: dict[str, str] = {}

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or "id" not in entry or "mark" not in entry:
            raise SystemExit(f"Marks file entry {index} needs an id and a mark.")
        marks[entry["id"]] = entry["mark"]

    return marks


def _exceeds_server_limits(note: BearNote) -> bool:
    return (
        len(strip_tag_lines(note.markdown)) > MAX_MARKDOWN_LENGTH
        or len(note.tags) > MAX_TAGS
        or any(len(tag) > MAX_TAG_LENGTH for tag in note.tags)
    )


def _upload(marked: MarkedNotes, api_url: str, session_key: str) -> ImportTally:
    statuses: list[str] = []
    for start in range(0, len(marked.to_import), BATCH_SIZE):
        batch = marked.to_import[start : start + BATCH_SIZE]
        body = {"notes": [note_payload(note, mark) for note, mark in batch]}
        try:
            response = _post(api_url=api_url, path="/notes/import", body=body, session_key=session_key)
        except _RequestFailedError:
            # Earlier batches are already committed; say so before the failure message.
            print(f"Stopped part-way; already imported: {_format_tally(_tally(statuses))}", file=sys.stderr)
            raise
        statuses.extend(result["status"] for result in response["results"])

    return _tally(statuses)


def _tally(statuses: list[str]) -> ImportTally:
    return ImportTally(
        created=statuses.count(STATUS_CREATED),
        updated=statuses.count(STATUS_UPDATED),
        unchanged=statuses.count(STATUS_UNCHANGED),
        deleted=statuses.count(STATUS_DELETED),
    )


def _format_tally(tally: ImportTally) -> str:
    return (
        f"created {tally.created}, updated {tally.updated}, unchanged {tally.unchanged}, "
        f"deleted in Archie {tally.deleted}."
    )


def _post(api_url: str, path: str, body: dict[str, object] | None, session_key: str) -> dict[str, object]:
    request = urllib.request.Request(
        url=f"{api_url.rstrip('/')}{path}",
        data=json.dumps(body if body is not None else {}).encode(),
        headers={"Authorization": f"Bearer {session_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise _RequestFailedError(f"{path} failed with HTTP {error.code}: {_error_detail(error)}") from None
    except (urllib.error.URLError, TimeoutError):
        # No body text: the reason string of a URLError can echo the request URL.
        raise _RequestFailedError(f"{path} failed: could not reach the server") from None


def _error_detail(error: urllib.error.HTTPError) -> str:
    """The server's detail when it is a plain string, else only the field locations and messages of a 422.

    A 422's entries carry an ``input`` key holding the submitted note text, so it is never read.
    """
    try:
        detail = json.loads(error.read()).get("detail", "")
        if isinstance(detail, str):
            return detail
        return "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in detail)
    except (ValueError, AttributeError, KeyError, TypeError):
        return ""


def _note_title(title: str | None, text: str | None) -> str:
    if title:
        return title[:MAX_TITLE_LENGTH]

    for line in (text or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:MAX_TITLE_LENGTH]

    return UNTITLED


def _from_core_data(seconds: float | None) -> datetime.datetime:
    return CORE_DATA_EPOCH + datetime.timedelta(seconds=seconds or 0)


if __name__ == "__main__":
    raise SystemExit(main())
