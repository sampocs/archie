"""Favorites through the real API: set_favorite stars and unstars a source, and the pull carries favorited_at."""

import uuid
from typing import Any

import httpx
import pytest
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

# Columns a star is allowed to change; everything else about the source must stay as it was.
_STAR_COLUMNS = {"favorited_at", "updated_at", "change_seq"}


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


def _source(authed: httpx.Client, source_id: str) -> dict[str, Any]:
    rows = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return next(row for row in rows["sources"] if row["id"] == source_id)


def _add(authed: httpx.Client) -> str:
    source_id = str(uuid.uuid4())
    payload = {"id": source_id, "url": f"https://example.com/{source_id}", "intent": "queue"}
    _push(authed, _action("add_source", payload))
    return source_id


def _star(authed: httpx.Client, source_id: str, *, favorited: bool) -> dict[str, Any]:
    return _push(authed, _action("set_favorite", {"id": source_id, "favorited": favorited}))[0]


def test_starring_and_unstarring_round_trip_through_the_pull(authed: httpx.Client) -> None:
    """A star sets favorited_at and a fresh change_seq; unstarring clears it with another."""
    source_id = _add(authed)
    before = _source(authed, source_id)

    _star(authed, source_id, favorited=True)
    starred = _source(authed, source_id)
    _star(authed, source_id, favorited=False)
    unstarred = _source(authed, source_id)

    assert before["favorited_at"] is None
    assert starred["favorited_at"] is not None
    assert starred["change_seq"] > before["change_seq"]
    assert unstarred["favorited_at"] is None
    assert unstarred["change_seq"] > starred["change_seq"]


def test_starring_changes_nothing_else_about_the_source(authed: httpx.Client) -> None:
    """State, queue position, processing and the rest are untouched by a star."""
    source_id = _add(authed)
    before = _source(authed, source_id)

    _star(authed, source_id, favorited=True)
    after = _source(authed, source_id)

    unchanged_before = {key: value for key, value in before.items() if key not in _STAR_COLUMNS}
    unchanged_after = {key: value for key, value in after.items() if key not in _STAR_COLUMNS}
    assert unchanged_after == unchanged_before


def test_starring_a_starred_source_again_keeps_its_first_star(authed: httpx.Client) -> None:
    """A second star (a new action id) is applied without a write, so favorites keep their order."""
    source_id = _add(authed)
    _star(authed, source_id, favorited=True)
    first = _source(authed, source_id)

    result = _star(authed, source_id, favorited=True)
    second = _source(authed, source_id)

    assert result["result"] == "applied"
    assert (second["favorited_at"], second["change_seq"]) == (first["favorited_at"], first["change_seq"])


def test_set_favorite_refuses_other_users_deleted_and_malformed(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Someone else's source and a deleted one are not found; a payload without `favorited` is malformed."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    source_id = _add(authed)
    deleted_id = _add(authed)
    _push(authed, _action("delete_source", {"id": deleted_id}))

    foreign = _push(other, _action("set_favorite", {"id": source_id, "favorited": True}))
    own = _push(
        authed,
        _action("set_favorite", {"id": deleted_id, "favorited": True}),
        _action("set_favorite", {"id": source_id}),
    )

    assert [result["reason"] for result in foreign + own] == [
        "source not found",
        "source not found",
        "payload is malformed",
    ]
    assert _source(authed, source_id)["favorited_at"] is None
