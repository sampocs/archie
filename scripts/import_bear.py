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


@dataclasses.dataclass(frozen=True)
class ImportTally:
    """How many notes the server reported per status."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0


def read_bear(db_path: pathlib.Path) -> list[BearNote]:
    """Read every live (not trashed, archived or deleted) note from a Bear database, read-only."""
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
            edited_at=_from_core_data(modified),
            encrypted=bool(encrypted),
        )
        for note_pk, bear_id, title, text, created, modified, encrypted in rows
    ]


def marked_notes(notes: Sequence[BearNote], marks: Mapping[str, str]) -> MarkedNotes:
    """Pair the notes marked import or cards with their mark, counting marked ids that are missing or encrypted."""
    by_id = {note.bear_id: note for note in notes}
    to_import: list[tuple[BearNote, str]] = []
    missing = 0
    encrypted = 0

    for bear_id, mark in marks.items():
        if mark not in UPLOADED_MARKS:
            continue

        note = by_id.get(bear_id)
        if note is None:
            missing += 1
        elif note.encrypted:
            encrypted += 1
        else:
            to_import.append((note, mark))

    return MarkedNotes(to_import=to_import, missing=missing, encrypted=encrypted)


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
    """Drop lines made only of Bear tags (the tags travel separately); headings keep their space after the #."""
    lines = markdown.splitlines(keepends=True)
    return "".join(line for line in lines if not _TAG_LINE.match(line))


def main(argv: list[str] | None = None) -> int:
    """Read Bear, report counts, and (unless --dry-run) upload the marked notes."""
    args = _parse_args(argv)
    marks = _load_marks(args.marks)
    marked = marked_notes(read_bear(args.bear_db), marks)

    counts = list(marks.values())
    print(
        f"Marked in the file: {counts.count(MARK_IMPORT)} import, {counts.count(MARK_CARDS)} cards; "
        f"found in Bear: {len(marked.to_import) + marked.encrypted}; missing from Bear: {marked.missing}; "
        f"skipped as encrypted: {marked.encrypted}."
    )
    if args.dry_run:
        return 0

    session_key = os.environ.get(SESSION_KEY_VARIABLE)
    if not session_key:
        print(f"Set {SESSION_KEY_VARIABLE} (see archie-issue-session) before importing.", file=sys.stderr)
        return 2

    try:
        tally = _upload(marked=marked, api_url=args.api_url, session_key=session_key)
        print(
            f"Imported: created {tally.created}, updated {tally.updated}, unchanged {tally.unchanged}, "
            f"deleted in Archie {tally.deleted}."
        )
        if args.write:
            queued = _post(api_url=args.api_url, path="/notes/write-ups", body=None, session_key=session_key)
            print(f"Queued {queued['queued']} write-ups (about one a minute).")
    except _RequestFailedError as error:
        print(str(error), file=sys.stderr)
        return 1

    return 0


class _RequestFailedError(Exception):
    """An HTTP error from the API, carrying only the status and the server's detail."""


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
    return {entry["id"]: entry["mark"] for entry in entries}


def _upload(marked: MarkedNotes, api_url: str, session_key: str) -> ImportTally:
    statuses: list[str] = []
    for start in range(0, len(marked.to_import), BATCH_SIZE):
        batch = marked.to_import[start : start + BATCH_SIZE]
        body = {"notes": [note_payload(note, mark) for note, mark in batch]}
        response = _post(api_url=api_url, path="/notes/import", body=body, session_key=session_key)
        statuses.extend(result["status"] for result in response["results"])

    return ImportTally(
        created=statuses.count(STATUS_CREATED),
        updated=statuses.count(STATUS_UPDATED),
        unchanged=statuses.count(STATUS_UNCHANGED),
        deleted=statuses.count(STATUS_DELETED),
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


def _error_detail(error: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(error.read()).get("detail", ""))
    except (ValueError, AttributeError):
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
