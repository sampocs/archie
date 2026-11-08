"""The Bear import script reads a Bear database read-only, strips tag lines, and never prints note text."""

from __future__ import annotations

import datetime
import importlib.util
import json
import pathlib
import sqlite3
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[3]
SCRIPT = REPO_ROOT / "scripts" / "import_bear.py"

_spec = importlib.util.spec_from_file_location("import_bear", SCRIPT)
assert _spec and _spec.loader
import_bear = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = import_bear  # dataclasses resolve string annotations through sys.modules
_spec.loader.exec_module(import_bear)

NOTE_COLUMNS = (
    "Z_PK, ZUNIQUEIDENTIFIER, ZTITLE, ZTEXT, ZCREATIONDATE, ZMODIFICATIONDATE, "
    "ZTRASHED, ZARCHIVED, ZPERMANENTLYDELETED, ZENCRYPTED"
)
STAKING_TEXT = "# Staking\n#crypto #crypto/staking\nBody line\n"


@pytest.fixture
def bear_db(tmp_path: pathlib.Path) -> pathlib.Path:
    """An invented database with Bear's table shapes: live A and E, trashed B, archived C, encrypted D."""
    path = tmp_path / "database.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        f"""
        create table ZSFNOTE ({NOTE_COLUMNS});
        create table ZSFNOTETAG (Z_PK, ZTITLE);
        create table Z_5TAGS (Z_5NOTES, Z_13TAGS);
        insert into ZSFNOTE values
            (1, 'A', 'Staking', '{STAKING_TEXT}', 0.0, 86400.0, 0, 0, 0, 0),
            (2, 'B', 'Trashed', 'gone', 0.0, 0.0, 1, 0, 0, 0),
            (3, 'C', 'Archived', 'old', 0.0, 0.0, 0, 1, 0, 0),
            (4, 'D', 'Secret', null, 0.0, 0.0, 0, 0, 0, 1),
            (5, 'E', null, '## Plain\nunmarked', 0.0, 0.0, null, null, null, null);
        insert into ZSFNOTETAG values (1, 'crypto/staking'), (2, 'crypto');
        insert into Z_5TAGS values (1, 1), (1, 2);
        """
    )
    connection.commit()
    connection.close()
    return path


def _marks_file(tmp_path: pathlib.Path) -> pathlib.Path:
    marks = [{"id": "A", "mark": "cards"}, {"id": "D", "mark": "import"}, {"id": "E", "mark": "skip"}]
    path = tmp_path / "marks.json"
    path.write_text(json.dumps(marks))
    return path


def test_read_bear_returns_live_notes_with_utc_dates_and_sorted_tags(bear_db: pathlib.Path) -> None:
    """Trashed and archived notes are left out; Core Data seconds become UTC datetimes."""
    notes = {note.bear_id: note for note in import_bear.read_bear(bear_db)}

    assert sorted(notes) == ["A", "D", "E"]
    assert notes["A"].tags == ["crypto", "crypto/staking"]
    assert notes["A"].created_at == datetime.datetime(2001, 1, 1, tzinfo=datetime.UTC)
    assert notes["A"].edited_at == datetime.datetime(2001, 1, 2, tzinfo=datetime.UTC)
    assert notes["D"].encrypted
    assert notes["E"].title == "Plain"


def test_strip_tag_lines_drops_only_lines_made_of_tags() -> None:
    """Headings and inline tags in prose stay."""
    stripped = import_bear.strip_tag_lines("# T\n#a #b/c\n#multi word#\ntext #inline tag\n")

    assert stripped == "# T\ntext #inline tag\n"


def test_marked_notes_counts_missing_and_encrypted(bear_db: pathlib.Path) -> None:
    """Only notes marked import or cards that Bear has and can read are uploaded."""
    notes = import_bear.read_bear(bear_db)
    by_id = {note.bear_id: note for note in notes}

    marked = import_bear.marked_notes(notes, {"A": "cards", "D": "import", "E": "skip", "Z": "cards"})

    assert marked.to_import == [(by_id["A"], "cards")]
    assert marked.missing == 1
    assert marked.encrypted == 1


def test_note_payload_matches_the_wire_contract(bear_db: pathlib.Path) -> None:
    """The payload carries the tag-stripped markdown and ISO dates."""
    note = next(note for note in import_bear.read_bear(bear_db) if note.bear_id == "A")

    assert import_bear.note_payload(note, "cards") == {
        "bear_id": "A",
        "title": "Staking",
        "markdown": "# Staking\nBody line\n",
        "tags": ["crypto", "crypto/staking"],
        "created_at": "2001-01-01T00:00:00+00:00",
        "edited_at": "2001-01-02T00:00:00+00:00",
        "mark": "cards",
    }


def test_dry_run_prints_counts_and_no_note_text(
    bear_db: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The privacy promise: counts only."""
    exit_code = import_bear.main(["--marks", str(_marks_file(tmp_path)), "--bear-db", str(bear_db), "--dry-run"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "1 import, 1 cards" in output
    assert "Staking" not in output
    assert "Body line" not in output


def test_a_real_run_needs_the_session_key(
    bear_db: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the key nothing is sent and the message names the variable."""
    monkeypatch.delenv("ARCHIE_SESSION_KEY", raising=False)

    exit_code = import_bear.main(["--marks", str(_marks_file(tmp_path)), "--bear-db", str(bear_db)])

    assert exit_code != 0
    assert "ARCHIE_SESSION_KEY" in capsys.readouterr().err
