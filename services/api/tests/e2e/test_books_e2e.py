"""Books through the real API: lookup, the `add_book` action, finishing a book, and the bootstrap import.

Lookups replay recorded real responses from Goodreads and Open Library. Re-record one by deleting its cassette and
running `uv run pytest services/api/tests/e2e/test_books_e2e.py --record-mode=once -m postgres` with
`TEST_DATABASE_URL` set; nothing here spends an API key.
"""

from __future__ import annotations

import datetime
import pathlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
GOODREADS_URL = "https://www.goodreads.com/book/show/11468377-thinking-fast-and-slow"
OPEN_LIBRARY_URL = "https://openlibrary.org/works/OL15992072W"
COVER_URL = "https://covers.example.com/thinking-fast-and-slow.jpg"
THOUGHTS = "Anchoring stuck with me."


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a fresh user."""
    return live_stack.authed(live_stack.sign_in())


@pytest.fixture
def owner(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a whitelisted user, who may spend the owner's keys."""
    return live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))


# --- lookup ---


def test_lookup_needs_a_session(live_stack: LiveStack) -> None:
    """No session, no lookup."""
    assert live_stack.client.post("/books/lookup", json={"query": "Thinking"}).status_code == 401


def test_a_goodreads_link_is_read_from_its_page(request: pytest.FixtureRequest, authed: httpx.Client) -> None:
    """Title, author and cover come from the page's JSON-LD; the URL is the page's canonical one; no year."""
    with _replay(request, "books_goodreads"):
        response = authed.post("/books/lookup", json={"query": f"{GOODREADS_URL}?ref=share"})

    assert response.status_code == 200
    book = response.json()
    assert (book["title"], book["author"], book["year"], book["url"]) == (
        "Thinking, Fast and Slow",
        "Daniel Kahneman",
        None,
        GOODREADS_URL,
    )
    assert book["cover_url"].startswith("https://")


def test_a_title_is_searched_on_open_library(request: pytest.FixtureRequest, authed: httpx.Client) -> None:
    """The top match: its work URL, first author, first publish year and large cover."""
    with _replay(request, "books_open_library_hit"):
        response = authed.post("/books/lookup", json={"query": "thinking fast and slow"})

    assert response.status_code == 200
    assert response.json() == {
        "title": "Thinking, Fast and Slow",
        "author": "Daniel Kahneman",
        "year": 2011,
        "cover_url": "https://covers.openlibrary.org/b/id/13290711-L.jpg",
        "url": OPEN_LIBRARY_URL,
    }


def test_a_title_with_no_match_is_404(request: pytest.FixtureRequest, authed: httpx.Client) -> None:
    """Open Library answered with no docs."""
    with _replay(request, "books_open_library_miss"):
        response = authed.post("/books/lookup", json={"query": "qzxv wplkj nonexistent book"})

    assert (response.status_code, response.json()) == (404, {"detail": "No book found"})


def test_a_lookup_answered_with_an_error_is_502(request: pytest.FixtureRequest, authed: httpx.Client) -> None:
    """Goodreads answering anything but 200 means the lookup couldn't be done."""
    with _replay(request, "books_goodreads_missing"):
        response = authed.post("/books/lookup", json={"query": "https://www.goodreads.com/book/show/0"})

    assert (response.status_code, response.json()) == (502, {"detail": "Couldn't reach the book lookup"})


# --- add_book ---


def test_a_book_added_as_reading_has_its_primer_written_and_queued(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Reading, processing, a primer job, the primer at the top of Up next; author and cover are pulled."""
    book_id = str(uuid.uuid4())
    [result] = _push(authed, _add_book(book_id, state="reading"))

    assert result["result"] == "applied"
    book = _source(authed, book_id)
    assert (book["kind"], book["state"], book["processing"]) == ("book", "reading", "processing")
    assert (book["title"], book["author"], book["image_url"]) == (
        "Thinking, Fast and Slow",
        "Daniel Kahneman",
        COVER_URL,
    )
    assert book["primer_queue_position"] is not None
    assert book["queue_position"] is None
    assert _job_kinds(live_stack) == [models.JobKind.PRIMER.value]


def test_a_book_added_as_finished_has_its_refresher_written(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Consumed with the owner's thoughts, a write_book job (two attempts), and no primer queued."""
    book_id = str(uuid.uuid4())
    _push(authed, _add_book(book_id, state="finished", note=THOUGHTS))

    book = _source(authed, book_id)
    assert (book["state"], book["note"], book["processing"]) == ("consumed", THOUGHTS, "processing")
    assert book["primer_queue_position"] is None
    [job] = _jobs(live_stack)
    assert (job.kind, job.max_attempts) == (models.JobKind.WRITE_BOOK.value, 2)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"note": THOUGHTS}, "note needs state finished"),
        ({"url": "ftp://example.com/book"}, "url must be http or https"),
        ({"image_url": "javascript:alert(1)"}, "image_url: url must be http or https"),
        ({"title": ""}, "payload is malformed"),
        ({"state": "want_to_read"}, "payload is malformed"),
    ],
)
def test_a_bad_add_book_is_rejected_and_writes_nothing(
    live_stack: LiveStack, authed: httpx.Client, change: dict[str, Any], reason: str
) -> None:
    """Each rule rejects the action before any write."""
    book_id = str(uuid.uuid4())
    [result] = _push(authed, _add_book(book_id, **{"state": "reading", **change}))

    assert (result["result"], result["reason"]) == ("rejected", reason)
    assert not [row for row in _pull(authed)["sources"] if row["id"] == book_id]
    assert _jobs(live_stack) == []


def test_adding_a_reading_book_again_as_finished_finishes_it(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The second row is merged into the first, which moves to finished with the thoughts and gets its refresher."""
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    _push(authed, _add_book(first_id, state="reading"))
    _push(authed, _add_book(second_id, state="finished", note=THOUGHTS, url=f"{GOODREADS_URL}/?utm_source=x"))

    rows = {row["id"]: row for row in _pull(authed)["sources"]}
    first, merged = rows[first_id], rows[second_id]
    assert (merged["merged_into_id"], merged["deleted_at"] is not None) == (first_id, True)
    assert (first["state"], first["note"], first["processing"]) == ("consumed", THOUGHTS, "processing")
    assert first["primer_queue_position"] is not None
    assert _job_kinds(live_stack) == [models.JobKind.PRIMER.value, models.JobKind.WRITE_BOOK.value]


def test_adding_a_book_again_otherwise_changes_nothing(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Reading again, or finished again, only records the merged duplicate."""
    reading_id, finished_id = str(uuid.uuid4()), str(uuid.uuid4())
    _push(authed, _add_book(reading_id, state="reading"))
    _push(authed, _add_book(finished_id, state="finished", url=OPEN_LIBRARY_URL))
    _push(
        authed,
        _add_book(str(uuid.uuid4()), state="reading"),
        _add_book(str(uuid.uuid4()), state="finished", note=THOUGHTS, url=OPEN_LIBRARY_URL),
    )

    rows = {row["id"]: row for row in _pull(authed)["sources"]}
    assert rows[reading_id]["state"] == "reading"
    assert (rows[finished_id]["state"], rows[finished_id]["note"]) == ("consumed", None)
    assert sorted(row["merged_into_id"] for row in rows.values() if row["merged_into_id"]) == sorted(
        [reading_id, finished_id]
    )
    assert _job_kinds(live_stack) == [models.JobKind.PRIMER.value, models.JobKind.WRITE_BOOK.value]


def test_a_link_to_a_books_page_never_merges_into_the_book(authed: httpx.Client) -> None:
    """add_source with the book's URL makes its own source; the book keeps its state, reaction and note."""
    book_id, link_id = str(uuid.uuid4()), str(uuid.uuid4())
    _push(authed, _add_book(book_id, state="reading"))
    link = _action(
        "add_source",
        {"id": link_id, "url": GOODREADS_URL, "intent": "finished", "reaction": "easy", "note": THOUGHTS},
    )
    [result] = _push(authed, link)

    rows = {row["id"]: row for row in _pull(authed)["sources"]}
    book = rows[book_id]
    assert (book["state"], book["reaction"], book["note"]) == ("reading", None, None)
    assert result["result"] == "applied"
    assert rows[link_id]["merged_into_id"] is None
    assert rows[link_id]["kind"] != "book"


# --- finishing ---


def test_finishing_a_reading_book_writes_its_refresher_and_keeps_its_primer_queued(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Consumed, the thoughts stored, processing again, a write_book job; the primer stays in Up next."""
    book_id = str(uuid.uuid4())
    _push(authed, _add_book(book_id, state="reading"))
    _set_ready(live_stack, book_id)

    [result] = _push(authed, _action("finish_source", {"id": book_id, "note": THOUGHTS}))

    assert result["result"] == "applied"
    book = _source(authed, book_id)
    assert (book["state"], book["note"], book["processing"]) == ("consumed", THOUGHTS, "processing")
    assert book["primer_queue_position"] is not None
    assert _job_kinds(live_stack) == [models.JobKind.PRIMER.value, models.JobKind.WRITE_BOOK.value]


def test_finishing_a_book_rejects_a_reaction_and_a_finished_book(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A reaction is for links; a book already finished can't be finished again."""
    reading_id, finished_id = str(uuid.uuid4()), str(uuid.uuid4())
    _push(
        authed, _add_book(reading_id, state="reading"), _add_book(finished_id, state="finished", url=OPEN_LIBRARY_URL)
    )

    results = _push(
        authed,
        _action("finish_source", {"id": reading_id, "reaction": "easy"}),
        _action("finish_source", {"id": finished_id}),
    )

    assert [(result["result"], result["reason"]) for result in results] == [
        ("rejected", "a book takes no reaction"),
        ("rejected", "book is not being read"),
    ]
    assert _source(authed, reading_id)["state"] == "reading"
    assert _job_kinds(live_stack) == [models.JobKind.PRIMER.value, models.JobKind.WRITE_BOOK.value]


def test_a_books_primer_is_a_queue_entry_but_the_book_is_not(authed: httpx.Client) -> None:
    """Its primer can be moved, snoozed and taken out of Up next; the book itself never enters the queue."""
    book_id = str(uuid.uuid4())
    _push(authed, _add_book(book_id, state="reading"))
    until = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)).isoformat()

    results = _push(
        authed,
        _action("set_queue_position", {"id": book_id, "position": 5.5, "target": "source_primer"}),
        _action("snooze", {"id": book_id, "target": "source_primer", "until": until}),
        _action("read_later", {"id": book_id}),
        _action("set_queue_position", {"id": book_id, "position": 1.0, "target": "source"}),
        _action("queue_primer", {"id": book_id, "queued": False}),
    )

    assert [(result["result"], result["reason"]) for result in results] == [
        ("applied", None),
        ("applied", None),
        ("rejected", "books are not queued"),
        ("rejected", "books are not queued"),
        ("applied", None),
    ]
    book = _source(authed, book_id)
    assert (book["state"], book["queue_position"], book["primer_queue_position"]) == ("reading", None, None)
    assert book["primer_snoozed_until"] is not None


def test_retrying_a_failed_reading_book_rewrites_its_primer(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A book has no text to fetch, so the retry goes straight to its primer."""
    book_id = str(uuid.uuid4())
    _push(authed, _add_book(book_id, state="reading"))
    with _db(live_stack) as db:
        book = db.get_one(models.Source, uuid.UUID(book_id))
        book.processing = models.ProcessingStatus.FAILED.value
        db.commit()

    _push(authed, _action("retry_source", {"id": book_id}))

    assert _source(authed, book_id)["processing"] == "processing"
    assert _job_kinds(live_stack) == [models.JobKind.PRIMER.value, models.JobKind.PRIMER.value]


def test_cards_on_for_a_finished_book_rewrites_its_cards_and_never_analyzes_it(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A finished book with a refresher gets `book_cards` again; a reading book only flips the flag."""
    finished_id, reading_id = str(uuid.uuid4()), str(uuid.uuid4())
    _push(
        authed, _add_book(finished_id, state="finished", url=OPEN_LIBRARY_URL), _add_book(reading_id, state="reading")
    )
    _write_refresher(live_stack, finished_id)

    toggles = [(book_id, off) for book_id in (finished_id, reading_id) for off in (True, False)]
    results = _push(authed, *[_action("set_cards_off", {"id": book_id, "off": off}) for book_id, off in toggles])

    assert {result["result"] for result in results} == {"applied"}
    assert _job_kinds(live_stack) == [
        models.JobKind.WRITE_BOOK.value,
        models.JobKind.PRIMER.value,
        models.JobKind.BOOK_CARDS.value,
    ]


# --- import ---


def test_the_import_is_the_owners_only(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A user who isn't whitelisted gets a 403 and nothing is stored."""
    response = authed.post("/books/import", json={"books": [_import_book()]})

    assert response.status_code == 403
    assert _pull(authed)["sources"] == []
    assert _jobs(live_stack) == []


def test_the_import_creates_finished_books_with_their_cards_and_spaced_refreshers(
    live_stack: LiveStack, owner: httpx.Client
) -> None:
    """Each book is finished with its notes; its cards carry `available_at` and up to four detail lines."""
    available_at = "2026-12-01T09:00:00+00:00"
    card = {
        "kind": "concept",
        "question": "What is anchoring?",
        "answer": "A first number pulls later estimates",
        "detail": ["One", "Two", "Three", "Four"],
        "available_at": available_at,
    }
    books = [
        _import_book(url=GOODREADS_URL, image_url=COVER_URL, cards=[card]),
        _import_book(title="The Design of Everyday Things", author=None, url=None),
    ]

    response = owner.post("/books/import", json={"books": books})

    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] == []
    first_id, second_id = body["created"]
    rows = _pull(owner)
    sources = {row["id"]: row for row in rows["sources"]}
    first, second = sources[first_id], sources[second_id]
    assert (first["kind"], first["state"], first["processing"]) == ("book", "consumed", "processing")
    assert (first["url"], first["author"], first["image_url"]) == (GOODREADS_URL, "Daniel Kahneman", COVER_URL)
    assert first["note_markdown"] == "# Notes\n- System 1 is fast\n"
    assert (second["url"], second["author"]) == ("book:the-design-of-everyday-things", None)

    [pulled_card] = rows["cards"]
    assert pulled_card["source_id"] == first_id
    assert pulled_card["detail"] == "One\nTwo\nThree\nFour"
    assert datetime.datetime.fromisoformat(pulled_card["available_at"]) == datetime.datetime.fromisoformat(available_at)

    write_ups = [job for job in _jobs(live_stack) if job.kind == models.JobKind.WRITE_BOOK.value]
    assert [job.payload["source_id"] for job in write_ups] == [first_id, second_id]
    assert write_ups[1].next_run_at - write_ups[0].next_run_at == datetime.timedelta(seconds=60)


def test_re_importing_a_book_skips_it(live_stack: LiveStack, owner: httpx.Client) -> None:
    """The same URL (tracking noise aside) is already there, so it is left as it was and named in `skipped`."""
    owner.post("/books/import", json={"books": [_import_book(url=GOODREADS_URL)]}).raise_for_status()

    response = owner.post("/books/import", json={"books": [_import_book(url=f"{GOODREADS_URL}?utm_source=x")]})

    assert response.json() == {"created": [], "skipped": ["Thinking, Fast and Slow"]}
    assert len(_pull(owner)["sources"]) == 1
    assert len(_jobs(live_stack)) == 1


_LATER = "2026-12-01T00:00:00Z"
_FIVE = ["1", "2", "3", "4", "5"]


@pytest.mark.parametrize(
    "change",
    [
        {"cards": [{"kind": "foundation", "question": "Q?", "answer": "A", "detail": [], "available_at": _LATER}]},
        {"cards": [{"kind": "concept", "question": "Q?", "answer": "A", "detail": _FIVE, "available_at": _LATER}]},
        {"url": "ftp://example.com/book"},
    ],
)
def test_the_import_refuses_a_bad_book(owner: httpx.Client, change: dict[str, Any]) -> None:
    """A card of another kind, a fifth detail line or a non-http URL fails the whole request."""
    response = owner.post("/books/import", json={"books": [_import_book(**change)]})

    assert response.status_code == 422
    assert _pull(owner)["sources"] == []


# --- helpers ---


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    # The test's own calls to the live API must reach it; only the lookup's requests are replayed.
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=True)


def _add_book(book_id: str, *, state: str, **changes: Any) -> dict[str, Any]:
    payload = {
        "id": book_id,
        "url": GOODREADS_URL,
        "title": "Thinking, Fast and Slow",
        "author": "Daniel Kahneman",
        "image_url": COVER_URL,
        "state": state,
        "note": None,
        **changes,
    }
    return _action("add_book", payload)


def _import_book(**changes: Any) -> dict[str, Any]:
    return {
        "title": "Thinking, Fast and Slow",
        "author": "Daniel Kahneman",
        "url": GOODREADS_URL,
        "image_url": None,
        "notes_markdown": "# Notes\n- System 1 is fast\n",
        "cards": [],
        **changes,
    }


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _pull(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _source(authed: httpx.Client, source_id: str) -> dict[str, Any]:
    return next(row for row in _pull(authed)["sources"] if row["id"] == source_id)


def _db(live_stack: LiveStack) -> sqlalchemy.orm.Session:
    return sqlalchemy.orm.Session(session.engine_for(live_stack.database_url))


def _jobs(live_stack: LiveStack) -> list[models.Job]:
    with _db(live_stack) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _job_kinds(live_stack: LiveStack) -> list[str]:
    return [job.kind for job in _jobs(live_stack)]


def _write_refresher(live_stack: LiveStack, source_id: str) -> None:
    """As if `write_book` had run: the refresher as summary and as text."""
    with _db(live_stack) as db:
        book = db.get_one(models.Source, uuid.UUID(source_id))
        changes.lock_user_writes(db, book.user_id)
        for kind, content in (
            (models.ArtifactKind.SUMMARY, {"summary": {}}),
            (models.ArtifactKind.TEXT, {"text": "x"}),
        ):
            pipeline.write_artifact(db, source=book, kind=kind, content=content, model=None, prompt_version=None)
        db.commit()


def _set_ready(live_stack: LiveStack, source_id: str) -> None:
    """As if the primer had landed."""
    with _db(live_stack) as db:
        db.get_one(models.Source, uuid.UUID(source_id)).processing = models.ProcessingStatus.READY.value
        db.commit()
