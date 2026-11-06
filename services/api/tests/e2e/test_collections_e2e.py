"""Collections through the real API: make, rename and delete them; save, edit, move and remove posts; pull both tables.

A saved post is never a source: saving one adds no source row and queues only its `fetch_collection_item` preview.
"""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import jobs, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

X_POST_URL = "https://x.com/BearsFilmRoom/status/1850000000000000000"
YOUTUBE_URL = "https://www.youtube.com/watch?v=e0gVE3YxZs8"
PAGE_URL = "https://example.com/bears"


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a fresh user."""
    return live_stack.authed(live_stack.sign_in())


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _reasons(results: list[dict[str, Any]]) -> list[str | None]:
    return [result["reason"] for result in results]


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next(row for row in rows if row["id"] == row_id)


def _create(authed: httpx.Client, name: str = "Bears hype") -> str:
    collection_id = str(uuid.uuid4())
    _push(authed, _action("create_collection", {"id": collection_id, "name": name}))
    return collection_id


def _save(authed: httpx.Client, collection_id: str, *, url: str = X_POST_URL, **extra: Any) -> str:
    item_id = str(uuid.uuid4())
    _push(authed, _action("add_collection_item", {"id": item_id, "collection_id": collection_id, "url": url, **extra}))
    return item_id


def _jobs(live_stack: LiveStack) -> list[models.Job]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def test_collections_are_made_at_the_end_with_cleaned_names(authed: httpx.Client) -> None:
    """Each new collection goes after the last one; names are stored with whitespace collapsed."""
    first = _create(authed, name="  Bears   hype ")
    second = _create(authed, name="Funny")

    collections = _rows(authed)["collections"]

    assert [(row["name"], row["position"]) for row in collections] == [("Bears hype", 0.0), ("Funny", 1.0)]
    assert [row["id"] for row in collections] == [first, second]
    assert all(row["deleted_at"] is None for row in collections)


def test_a_saved_post_is_not_a_source_and_queues_only_its_preview(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Posts get their kind from the URL and a pending preview; no source, capture or pipeline job is made."""
    collection_id = _create(authed)
    x_item = _save(authed, collection_id, note="  the 4th-quarter scramble ")
    youtube_item = _save(authed, collection_id, url=YOUTUBE_URL)
    page_item = _save(authed, collection_id, url=PAGE_URL)

    rows = _rows(authed)
    queued = _jobs(live_stack)

    assert rows["sources"] == []
    items = rows["collection_items"]
    expected_kinds = [(x_item, "x"), (youtube_item, "youtube"), (page_item, "link")]
    assert [(row["id"], row["kind"]) for row in items] == expected_kinds
    assert _by_id(items, x_item)["note"] == "the 4th-quarter scramble"
    assert {row["metadata_status"] for row in items} == {"pending"}
    assert all(row["collection_id"] == collection_id for row in items)
    assert [job.kind for job in queued] == [models.JobKind.FETCH_COLLECTION_ITEM.value] * 3
    assert [job.payload[jobs.COLLECTION_ITEM_ID_KEY] for job in queued] == [x_item, youtube_item, page_item]


def test_renaming_and_deleting_a_collection(authed: httpx.Client) -> None:
    """A rename bumps the row; a delete soft-deletes the collection and every post in it, and then refuses changes."""
    collection_id = _create(authed)
    first_item = _save(authed, collection_id)
    second_item = _save(authed, collection_id, url=PAGE_URL)
    before = _by_id(_rows(authed)["collections"], collection_id)

    _push(authed, _action("update_collection", {"id": collection_id, "name": "Bears  film room"}))
    renamed = _by_id(_rows(authed)["collections"], collection_id)
    _push(authed, _action("update_collection", {"id": collection_id, "deleted": True}))
    rows = _rows(authed)
    after_delete = _push(
        authed,
        _action("update_collection", {"id": collection_id, "name": "Again"}),
        _action("add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": PAGE_URL}),
        _action("update_collection_item", {"id": first_item, "note": "late"}),
    )

    assert renamed["name"] == "Bears film room"
    assert renamed["change_seq"] > before["change_seq"]
    assert _by_id(rows["collections"], collection_id)["deleted_at"] is not None
    assert all(_by_id(rows["collection_items"], item)["deleted_at"] is not None for item in (first_item, second_item))
    assert _reasons(after_delete) == ["collection not found", "collection not found", "collection item not found"]


def test_a_collection_can_be_moved_and_a_false_delete_is_ignored(authed: httpx.Client) -> None:
    """A pushed position reorders the tiles; `deleted: false` keeps the collection (there is no undelete)."""
    first = _create(authed)
    second = _create(authed, name="Funny")

    _push(authed, _action("update_collection", {"id": second, "position": -1.5, "deleted": False}))
    collections = _rows(authed)["collections"]

    assert [(row["id"], row["position"]) for row in sorted(collections, key=lambda row: row["position"])] == [
        (second, -1.5),
        (first, 0.0),
    ]
    assert _by_id(collections, second)["deleted_at"] is None


def test_a_post_can_have_its_note_edited_moved_and_removed(authed: httpx.Client) -> None:
    """A blank note clears it, an absent note keeps it, a move changes the collection, a remove soft-deletes."""
    first = _create(authed)
    second = _create(authed, name="Funny")
    item_id = _save(authed, first, note="keep me")

    _push(authed, _action("update_collection_item", {"id": item_id, "collection_id": second}))
    moved = _by_id(_rows(authed)["collection_items"], item_id)
    _push(authed, _action("update_collection_item", {"id": item_id, "note": "   "}))
    cleared = _by_id(_rows(authed)["collection_items"], item_id)
    _push(authed, _action("update_collection_item", {"id": item_id, "deleted": True}))
    removed = _by_id(_rows(authed)["collection_items"], item_id)

    assert (moved["collection_id"], moved["note"]) == (second, "keep me")
    assert cleared["note"] is None
    assert removed["deleted_at"] is not None
    assert removed["change_seq"] > cleared["change_seq"] > moved["change_seq"]


def test_collection_actions_refuse_other_users_and_bad_input(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Another user's collection or post is not found; names, URLs, notes and ids are checked before any write."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    collection_id = _create(authed)
    item_id = _save(authed, collection_id)
    others_collection = _create(other, name="Mallory's")

    foreign = _push(
        other,
        _action("add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": PAGE_URL}),
        _action("update_collection_item", {"id": item_id, "note": "mine now"}),
        _action("update_collection", {"id": collection_id, "deleted": True}),
    )
    own = _push(
        authed,
        _action("create_collection", {"id": str(uuid.uuid4()), "name": "   "}),
        _action("create_collection", {"id": str(uuid.uuid4()), "name": "x" * 101}),
        _action("create_collection", {"id": collection_id, "name": "Again"}),
        _action(
            "add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": "ftp://x.com/a"}
        ),
        _action("add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id}),
        _action(
            "add_collection_item",
            {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": PAGE_URL, "note": "n" * 2001},
        ),
        _action("update_collection_item", {"id": item_id, "collection_id": others_collection}),
    )

    assert _reasons(foreign) == ["collection not found", "collection item not found", "collection not found"]
    assert _reasons(own) == [
        "collection name is empty",
        "collection name is longer than 100 characters",
        "id already exists",
        "url must be http or https",
        "payload is malformed",
        "note is longer than 2000 characters",
        "collection not found",
    ]
    rows = _rows(authed)
    assert _by_id(rows["collection_items"], item_id)["collection_id"] == collection_id
    assert [row["name"] for row in rows["collections"]] == ["Bears hype"]
