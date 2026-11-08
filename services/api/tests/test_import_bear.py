"""The Bear import script reads a Bear database read-only, strips tag lines, and never prints note text."""

from __future__ import annotations

import datetime
import importlib.util
import io
import json
import pathlib
import sqlite3
import sys
import urllib.error
from email.message import Message
from typing import Any

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
    assert marked.too_large == 0


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


SENTINEL = "SENTINEL-NOTE-TEXT"


def _note(**overrides: object) -> Any:
    fields: dict[str, object] = {
        "bear_id": "N",
        "title": "T",
        "markdown": "body",
        "tags": [],
        "created_at": datetime.datetime(2001, 1, 1, tzinfo=datetime.UTC),
        "edited_at": datetime.datetime(2001, 1, 1, tzinfo=datetime.UTC),
        "encrypted": False,
    }
    return import_bear.BearNote(**{**fields, **overrides})


def _http_error(status: int, body: object) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x/notes", status, "err", Message(), io.BytesIO(json.dumps(body).encode()))


def _failing_urlopen(error: Exception) -> object:
    def urlopen(*args: object, **kwargs: object) -> object:
        raise error

    return urlopen


def _post(monkeypatch: pytest.MonkeyPatch, error: Exception) -> str:
    monkeypatch.setattr(import_bear.urllib.request, "urlopen", _failing_urlopen(error))
    with pytest.raises(import_bear._RequestFailedError) as raised:
        import_bear._post(api_url="http://x", path="/notes/import", body={}, session_key="k")
    return str(raised.value)


def test_a_422_message_has_locations_and_messages_but_never_the_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastAPI echoes the submitted note text as `input`; it must not reach the terminal."""
    detail = [{"loc": ["body", "notes", 0, "markdown"], "msg": "too long", "input": SENTINEL, "type": "x"}]

    message = _post(monkeypatch, _http_error(422, {"detail": detail}))

    assert "HTTP 422" in message
    assert "body.notes.0.markdown: too long" in message
    assert SENTINEL not in message


def test_a_string_detail_is_printed_and_an_unparseable_body_gives_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain-string details are safe; anything unexpected prints no detail."""
    assert _post(monkeypatch, _http_error(401, {"detail": "bad session"})).endswith("HTTP 401: bad session")
    assert _post(monkeypatch, _http_error(500, {"detail": [{"input": SENTINEL}]})).endswith("HTTP 500: ")
    assert _post(monkeypatch, _http_error(500, ["not", "a", "dict"])).endswith("HTTP 500: ")


@pytest.mark.parametrize("error", [urllib.error.URLError(f"refused {SENTINEL}"), TimeoutError(SENTINEL)])
def test_network_failures_become_request_failures_without_detail(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Timeouts and connection errors are reported cleanly, with no reason text."""
    message = _post(monkeypatch, error)

    assert message == "/notes/import failed: could not reach the server"


def test_notes_over_the_server_limits_are_counted_not_uploaded() -> None:
    """Markdown is measured after tag lines are stripped; tag count and length are checked too."""
    fine = _note(
        bear_id="fine", markdown="x" * import_bear.MAX_MARKDOWN_LENGTH, tags=["t" * import_bear.MAX_TAG_LENGTH]
    )
    only_over_before_strip = _note(bear_id="strip", markdown="#tag\n" + "x" * import_bear.MAX_MARKDOWN_LENGTH)
    long_text = _note(bear_id="text", markdown="x" * (import_bear.MAX_MARKDOWN_LENGTH + 1))
    many_tags = _note(bear_id="many", tags=[f"t{n}" for n in range(import_bear.MAX_TAGS + 1)])
    long_tag = _note(bear_id="tag", tags=["t" * (import_bear.MAX_TAG_LENGTH + 1)])
    notes = [fine, only_over_before_strip, long_text, many_tags, long_tag]

    marked = import_bear.marked_notes(notes, {note.bear_id: "import" for note in notes})

    assert [note.bear_id for note, _ in marked.to_import] == ["fine", "strip"]
    assert marked.too_large == 3


def test_summary_reports_the_too_large_count(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The dry-run summary says how many notes were skipped for size, without naming them."""
    db_path = tmp_path / "database.sqlite"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        f"""
        create table ZSFNOTE ({NOTE_COLUMNS});
        create table ZSFNOTETAG (Z_PK, ZTITLE);
        create table Z_5TAGS (Z_5NOTES, Z_13TAGS);
        insert into ZSFNOTE values
            (1, 'BIG', 'Huge', '{"x" * (import_bear.MAX_MARKDOWN_LENGTH + 1)}', 0, 0, 0, 0, 0, 0);
        """
    )
    connection.commit()
    connection.close()
    marks = tmp_path / "marks.json"
    marks.write_text(json.dumps([{"id": "BIG", "mark": "import"}]))

    import_bear.main(["--marks", str(marks), "--bear-db", str(db_path), "--dry-run"])

    output = capsys.readouterr().out
    assert "over the server's size limits: 1" in output
    assert "Huge" not in output


def test_strip_tag_lines_keeps_tag_looking_lines_inside_code_fences() -> None:
    """A `#comment` line in a fenced block is code; the fence toggles back off afterwards."""
    markdown = "#a\n```sh\n#comment\n```\n#b\ntext\n"

    assert import_bear.strip_tag_lines(markdown) == "```sh\n#comment\n```\ntext\n"


def test_load_marks_names_only_the_index_of_a_bad_entry(tmp_path: pathlib.Path) -> None:
    """A missing id or mark (or a non-object entry) stops the run with the entry's position, not its contents."""
    for entries in ([{"id": "A", "mark": "import"}, {"mark": "import"}], [{"id": "A"}], ["A"]):
        path = tmp_path / "marks.json"
        path.write_text(json.dumps(entries))

        with pytest.raises(SystemExit) as raised:
            import_bear._load_marks(path)

        assert str(raised.value) == f"Marks file entry {len(entries) - 1} needs an id and a mark."


def test_read_bear_skips_unusable_ids_and_falls_back_to_the_creation_date(tmp_path: pathlib.Path) -> None:
    """NULL or over-long ids can't be uploaded; a NULL modification date uses the creation date."""
    path = tmp_path / "database.sqlite"
    connection = sqlite3.connect(path)
    long_id = "L" * (import_bear.MAX_BEAR_ID_LENGTH + 1)
    ok_id = "K" * import_bear.MAX_BEAR_ID_LENGTH
    connection.executescript(
        f"""
        create table ZSFNOTE ({NOTE_COLUMNS});
        create table ZSFNOTETAG (Z_PK, ZTITLE);
        create table Z_5TAGS (Z_5NOTES, Z_13TAGS);
        insert into ZSFNOTE values
            (1, null, 'NoId', 'x', 0, 0, 0, 0, 0, 0),
            (2, '{long_id}', 'LongId', 'x', 0, 0, 0, 0, 0, 0),
            (3, '{ok_id}', 'Ok', 'x', 86400, null, 0, 0, 0, 0);
        """
    )
    connection.commit()
    connection.close()

    notes = import_bear.read_bear(path)

    assert [note.bear_id for note in notes] == [ok_id]
    assert notes[0].edited_at == datetime.datetime(2001, 1, 2, tzinfo=datetime.UTC)


def test_a_failed_batch_reports_what_was_already_imported(
    bear_db: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Earlier batches are committed, so the tally so far is printed before the failure."""
    monkeypatch.setenv("ARCHIE_SESSION_KEY", "k")
    monkeypatch.setattr(import_bear, "BATCH_SIZE", 1)
    marks = tmp_path / "marks.json"
    marks.write_text(json.dumps([{"id": "A", "mark": "import"}, {"id": "E", "mark": "import"}]))
    calls: list[int] = []

    def fake_post(api_url: str, path: str, body: dict[str, object] | None, session_key: str) -> dict[str, object]:
        calls.append(1)
        if len(calls) == 2:
            raise import_bear._RequestFailedError("/notes/import failed with HTTP 500: ")
        return {"results": [{"status": "created"}]}

    monkeypatch.setattr(import_bear, "_post", fake_post)

    exit_code = import_bear.main(["--marks", str(marks), "--bear-db", str(bear_db)])

    error = capsys.readouterr().err
    assert exit_code == 1
    assert "already imported: created 1, updated 0" in error
    assert "HTTP 500" in error
