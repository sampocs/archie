"""The books import script looks each title up, keeps going without a match, and prints counts only."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[3]
SCRIPT = REPO_ROOT / "scripts" / "import_books.py"

_spec = importlib.util.spec_from_file_location("import_books", SCRIPT)
assert _spec and _spec.loader
import_books = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = import_books  # dataclasses resolve string annotations through sys.modules
_spec.loader.exec_module(import_books)

MATCHED_TITLE = "Thinking, Fast and Slow"
UNMATCHED_TITLE = "SENTINEL-UNMATCHED-TITLE"
NOTES = "SENTINEL-NOTE-TEXT"
CARD = {
    "kind": "concept",
    "question": "What is anchoring?",
    "answer": "A first number pulls estimates",
    "detail": [],
    "available_at": "2026-12-01T09:00:00+00:00",
}
MATCH = {
    "title": MATCHED_TITLE,
    "author": "Daniel Kahneman",
    "year": 2011,
    "cover_url": "https://covers.example.com/1-L.jpg",
    "url": "https://openlibrary.org/works/OL15992072W",
}


def _books_file(tmp_path: pathlib.Path) -> pathlib.Path:
    books = [
        {"title": MATCHED_TITLE, "author": None, "notes_markdown": NOTES, "cards": [CARD]},
        {"title": UNMATCHED_TITLE, "author": "Someone", "notes_markdown": NOTES, "cards": []},
    ]
    path = tmp_path / "books.json"
    path.write_text(json.dumps(books))
    return path


def test_a_run_imports_matched_and_unmatched_books_and_prints_only_counts(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The match lends its URL, cover and author; the unmatched book goes without; no title or note is printed."""
    monkeypatch.setenv("ARCHIE_SESSION_KEY", "k")
    imported: list[dict[str, object]] = []

    def fake_post(api_url: str, path: str, body: dict[str, object], session_key: str) -> dict[str, object]:
        if path == import_books.LOOKUP_PATH:
            if body["query"] == MATCHED_TITLE:
                return MATCH
            raise import_books._RequestFailedError("/books/lookup failed with HTTP 404: No book found", status=404)
        imported.extend(body["books"])  # type: ignore[arg-type]
        return {"created": ["id-1"], "skipped": [UNMATCHED_TITLE]}

    monkeypatch.setattr(import_books, "_post", fake_post)

    exit_code = import_books.main([str(_books_file(tmp_path))])

    assert exit_code == 0
    assert imported == [
        {
            "title": MATCHED_TITLE,
            "author": "Daniel Kahneman",
            "url": MATCH["url"],
            "image_url": MATCH["cover_url"],
            "notes_markdown": NOTES,
            "cards": [CARD],
        },
        {
            "title": UNMATCHED_TITLE,
            "author": "Someone",
            "url": None,
            "image_url": None,
            "notes_markdown": NOTES,
            "cards": [],
        },
    ]
    output = capsys.readouterr().out
    assert "Books in the file: 2; matched by the lookup: 1; created 1, skipped as already imported 1." in output
    assert UNMATCHED_TITLE not in output
    assert NOTES not in output


def test_a_lookup_failing_for_another_reason_stops_the_run(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad session (401) is not "no match": nothing is imported and the error is reported."""
    monkeypatch.setenv("ARCHIE_SESSION_KEY", "k")
    paths: list[str] = []

    def fake_post(api_url: str, path: str, body: dict[str, object], session_key: str) -> dict[str, object]:
        paths.append(path)
        raise import_books._RequestFailedError(f"{path} failed with HTTP 401: bad session", status=401)

    monkeypatch.setattr(import_books, "_post", fake_post)

    exit_code = import_books.main([str(_books_file(tmp_path))])

    assert exit_code == 1
    assert paths == [import_books.LOOKUP_PATH]
    assert "HTTP 401" in capsys.readouterr().err


def test_a_run_needs_the_session_key(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the key nothing is sent and the message names the variable."""
    monkeypatch.delenv("ARCHIE_SESSION_KEY", raising=False)

    exit_code = import_books.main([str(_books_file(tmp_path))])

    assert exit_code == 2
    assert "ARCHIE_SESSION_KEY" in capsys.readouterr().err


def test_a_book_without_a_title_stops_with_its_position(tmp_path: pathlib.Path) -> None:
    """The entry is named by index, never by its contents."""
    path = tmp_path / "books.json"
    path.write_text(json.dumps([{"title": "A"}, {"notes_markdown": NOTES}]))

    with pytest.raises(SystemExit) as raised:
        import_books.main([str(path)])

    assert str(raised.value) == "Books file entry 1 needs a title."
