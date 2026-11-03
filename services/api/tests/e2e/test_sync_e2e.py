"""Sync through the real API: actions apply once and in order, and pulls never skip a row."""

import threading
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

PAGE_SIZE = 500
BATCH_SIZE = 50


def _add_source(url: str, *, action_id: uuid.UUID | None = None, intent: str = "queue") -> dict[str, Any]:
    return {
        "id": str(action_id or uuid.uuid4()),
        "type": "add_source",
        "payload": {"id": str(uuid.uuid4()), "url": url, "intent": intent},
    }


def _push_sources(authed: httpx.Client, *, count: int) -> None:
    for batch_start in range(0, count, BATCH_SIZE):
        urls = [f"https://example.com/{index}" for index in range(batch_start, batch_start + BATCH_SIZE)]
        actions = [_add_source(url) for url in urls]
        authed.post("/sync/push", json={"actions": actions}).raise_for_status()


def _pull_all_pages(authed: httpx.Client) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    position, more = 0, True
    while more:
        page = authed.get("/sync/pull", params={"since": position}).json()
        pages.append(page)
        position, more = page["position"], page["more"]
    return pages


def test_added_source_comes_back_in_a_pull(live_stack: LiveStack) -> None:
    """A pushed add_source appears in the next pull as a queued link, with a higher position."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")

    pushed = authed.post("/sync/push", json={"actions": [action]}).json()
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    assert pushed["results"] == [{"id": action["id"], "result": "applied", "reason": None}]
    assert [row["id"] for row in pulled["rows"]["sources"]] == [action["payload"]["id"]]
    assert pulled["rows"]["sources"][0]["state"] == "queued"
    assert pulled["position"] > 0


def test_an_added_source_gets_a_title_job_and_a_finished_one_is_consumed(live_stack: LiveStack) -> None:
    """Each applied add_source enqueues fetch_title in the same transaction; intent finished starts consumed."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a", intent="finished")

    authed.post("/sync/push", json={"actions": [action]})
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        job_payloads = [(job.kind, job.payload) for job in db.scalars(sqlalchemy.select(models.Job))]
    assert job_payloads == [("fetch_title", {"source_id": action["payload"]["id"]})]
    assert pulled["rows"]["sources"][0]["state"] == "consumed"


def test_a_retried_action_is_applied_once(live_stack: LiveStack) -> None:
    """Pushing the same action id twice returns duplicate and leaves one source."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")

    authed.post("/sync/push", json={"actions": [action]})
    second = authed.post("/sync/push", json={"actions": [action]}).json()
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    assert second["results"][0]["result"] == "duplicate"
    assert len(pulled["rows"]["sources"]) == 1


def test_a_rejected_action_does_not_block_later_ones(live_stack: LiveStack) -> None:
    """A non-http URL is rejected with a reason; the next action in the batch still applies."""
    authed = live_stack.authed(live_stack.sign_in())
    bad, good = _add_source("ftp://example.com"), _add_source("https://example.com/ok")

    results = authed.post("/sync/push", json={"actions": [bad, good]}).json()["results"]

    assert results[0]["result"] == "rejected" and results[0]["reason"]
    assert results[1]["result"] == "applied"


def test_each_invalid_add_source_is_rejected_with_a_reason(live_stack: LiveStack) -> None:
    """Over-long URLs, hostless URLs, unknown intents and malformed payloads are rejected; retries are duplicates."""
    authed = live_stack.authed(live_stack.sign_in())
    too_long = _add_source("https://example.com/" + "a" * 2048)
    hostless = _add_source("https:///path")
    bad_intent = _add_source("https://example.com/a", intent="someday")
    malformed = {"id": str(uuid.uuid4()), "type": "add_source", "payload": {"url": "https://example.com"}}
    batch = [too_long, hostless, bad_intent, malformed]

    first = authed.post("/sync/push", json={"actions": batch}).json()["results"]
    retried = authed.post("/sync/push", json={"actions": batch}).json()["results"]

    assert [result["result"] for result in first] == ["rejected"] * 4
    assert all(result["reason"] for result in first)
    assert [result["result"] for result in retried] == ["duplicate"] * 4
    assert authed.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def test_a_reused_source_id_is_rejected_even_for_the_same_user(live_stack: LiveStack) -> None:
    """Re-adding an existing source id under a new action id is rejected and leaves the row alone."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")
    authed.post("/sync/push", json={"actions": [action]})

    again = {**action, "id": str(uuid.uuid4())}
    result = authed.post("/sync/push", json={"actions": [again]}).json()["results"][0]

    assert result["result"] == "rejected"
    assert len(authed.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"]) == 1


def test_a_source_id_owned_by_another_user_is_rejected(live_stack: LiveStack) -> None:
    """Reusing someone else's source id is rejected instead of overwriting their row."""
    first = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    second = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    action = _add_source("https://example.com/a")
    first.post("/sync/push", json={"actions": [action]})

    stolen = {**action, "id": str(uuid.uuid4())}
    result = second.post("/sync/push", json={"actions": [stolen]}).json()["results"][0]

    assert result["result"] == "rejected"
    assert second.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []
    assert first.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"][0]["url"] == "https://example.com/a"


def test_a_pull_only_returns_the_callers_rows(live_stack: LiveStack) -> None:
    """Another user's sources never appear in a pull."""
    first = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    second = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    first.post("/sync/push", json={"actions": [_add_source("https://example.com/a")]})

    assert second.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def test_more_than_fifty_actions_are_refused(live_stack: LiveStack) -> None:
    """A push over the batch limit is a 422 and applies nothing."""
    authed = live_stack.authed(live_stack.sign_in())

    response = authed.post("/sync/push", json={"actions": [_add_source("https://example.com/a")] * 51})

    assert response.status_code == 422


def test_pull_does_not_skip_a_row_committed_after_a_later_one(live_stack: LiveStack) -> None:
    """A write holding the user's lock blocks a push, so the pull position can never jump past it."""
    session_key = live_stack.sign_in()
    authed = live_stack.authed(session_key)
    engine = session.engine_for(live_stack.database_url)
    user_id = authed.get("/me").json()["user_id"]

    # Writer A: takes the lock and a position, and stays uncommitted.
    slow_writer = sqlalchemy.orm.Session(engine)
    # Writer B: a push through the API, which must wait for A. It gets its own client for the longer timeout.
    pusher = httpx.Client(base_url=live_stack.base_url, headers={"Authorization": f"Bearer {session_key}"}, timeout=10)
    # Closing in finally releases the advisory lock even when an assertion fails, so later tests can't hang.
    try:
        changes.lock_user_writes(slow_writer, user_id)
        slow_source_id = uuid.uuid4()
        slow_writer.add(
            models.Source(
                id=slow_source_id,
                user_id=user_id,
                url="https://example.com/slow",
                normalized_url="https://example.com/slow",
                kind="link",
                state="queued",
                intent="queue",
                change_seq=slow_writer.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one(),
            )
        )
        slow_writer.flush()

        push_thread = threading.Thread(
            target=lambda: pusher.post("/sync/push", json={"actions": [_add_source("https://example.com/fast")]})
        )
        push_thread.start()
        push_thread.join(timeout=0.5)
        assert push_thread.is_alive()

        mid = authed.get("/sync/pull", params={"since": 0}).json()
        assert mid["rows"]["sources"] == []

        slow_writer.commit()
        push_thread.join(timeout=5)
        assert not push_thread.is_alive()
        final_rows = authed.get("/sync/pull", params={"since": mid["position"]}).json()["rows"]["sources"]
    finally:
        slow_writer.close()
        pusher.close()

    assert len(final_rows) == 2
    assert str(slow_source_id) in {row["id"] for row in final_rows}


def test_unparseable_urls_are_rejected_without_blocking_later_actions(live_stack: LiveStack) -> None:
    """A malformed or NUL-bearing url is a rejection, not a 500, so a retried batch can't wedge the outbox."""
    authed = live_stack.authed(live_stack.sign_in())
    actions = [
        _add_source("http://[::1"),
        _add_source("https://example.com/\u0000"),
        _add_source("https://example.com/ok"),
    ]

    response = authed.post("/sync/push", json={"actions": actions})

    assert response.status_code == 200
    assert [(result["result"], result["reason"]) for result in response.json()["results"]] == [
        ("rejected", "url is not a valid URL"),
        ("rejected", "url is not a valid URL"),
        ("applied", None),
    ]


def test_another_users_action_id_is_rejected_and_leaves_the_owner_untouched(live_stack: LiveStack) -> None:
    """Action ids are global: B reusing A's id is refused, and A's pull is unchanged."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    intruder = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    action = _add_source("https://example.com/a")
    owner.post("/sync/push", json={"actions": [action]})
    before = owner.get("/sync/pull", params={"since": 0}).json()

    stolen = _add_source("https://example.com/b", action_id=uuid.UUID(action["id"]))
    result = intruder.post("/sync/push", json={"actions": [stolen]}).json()["results"]

    assert result == [{"id": action["id"], "result": "rejected", "reason": "action id already used"}]
    assert owner.get("/sync/pull", params={"since": 0}).json() == before
    assert intruder.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def _race_push_against_uncommitted_insert(
    live_stack: LiveStack, *, rival_row: Any, pushed_action: dict[str, Any], pusher_key: str
) -> dict[str, Any]:
    """Push while another transaction holds an uncommitted row with a clashing key, then let it commit.

    The push passes its existence checks (the rival is uncommitted), blocks on the unique index, and hits an
    IntegrityError once the rival commits. Returns the push's single result.
    """
    engine = session.engine_for(live_stack.database_url)
    rival = sqlalchemy.orm.Session(engine)
    pusher = httpx.Client(base_url=live_stack.base_url, headers={"Authorization": f"Bearer {pusher_key}"}, timeout=10)
    responses: list[httpx.Response] = []
    try:
        rival.add(rival_row)
        rival.flush()

        push_thread = threading.Thread(
            target=lambda: responses.append(pusher.post("/sync/push", json={"actions": [pushed_action]}))
        )
        push_thread.start()
        push_thread.join(timeout=0.5)
        assert push_thread.is_alive()

        rival.commit()
        push_thread.join(timeout=5)
        assert not push_thread.is_alive()
    finally:
        rival.close()
        pusher.close()

    assert responses[0].status_code == 200
    return responses[0].json()["results"][0]


def test_two_users_racing_on_one_action_id_rejects_the_loser(live_stack: LiveStack) -> None:
    """The unique index on action ids decides the race; the loser is told so and records nothing."""
    winner_key = live_stack.sign_in(apple_sub="user-a")
    loser_key = live_stack.sign_in(apple_sub="user-b")
    winner_id = live_stack.authed(winner_key).get("/me").json()["user_id"]
    action = _add_source("https://example.com/b")

    result = _race_push_against_uncommitted_insert(
        live_stack,
        rival_row=models.AppliedAction(action_id=uuid.UUID(action["id"]), user_id=winner_id, result="applied"),
        pushed_action=action,
        pusher_key=loser_key,
    )

    assert result == {"id": action["id"], "result": "rejected", "reason": "action id already used"}
    assert live_stack.authed(loser_key).get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def test_two_users_racing_on_one_source_id_rejects_the_loser(live_stack: LiveStack) -> None:
    """The unique index on source ids decides the race; the loser's action is recorded as rejected."""
    winner_key = live_stack.sign_in(apple_sub="user-a")
    loser_key = live_stack.sign_in(apple_sub="user-b")
    winner_id = live_stack.authed(winner_key).get("/me").json()["user_id"]
    action = _add_source("https://example.com/b")
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as seq_db:
        change_seq = seq_db.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one()
        seq_db.commit()
    rival_source = models.Source(
        id=uuid.UUID(action["payload"]["id"]),
        user_id=winner_id,
        url="https://example.com/a",
        normalized_url="https://example.com/a",
        kind="link",
        state="queued",
        intent="queue",
        change_seq=change_seq,
    )

    result = _race_push_against_uncommitted_insert(
        live_stack, rival_row=rival_source, pushed_action=action, pusher_key=loser_key
    )

    assert result == {"id": action["id"], "result": "rejected", "reason": "source id already exists"}
    retried = live_stack.authed(loser_key).post("/sync/push", json={"actions": [action]}).json()["results"]
    assert retried[0]["result"] == "duplicate"


def test_pull_pages_until_more_is_false(live_stack: LiveStack) -> None:
    """With more rows than one page, following positions returns every row exactly once."""
    authed = live_stack.authed(live_stack.sign_in())
    _push_sources(authed, count=550)

    pages = _pull_all_pages(authed)

    seen = [row["id"] for page in pages for row in page["rows"]["sources"]]
    assert [len(page["rows"]["sources"]) for page in pages] == [PAGE_SIZE, 50]
    assert len(seen) == 550 and len(set(seen)) == 550


def test_a_pull_of_exactly_one_page_ends_with_an_empty_page(live_stack: LiveStack) -> None:
    """At exactly 500 rows the first page says more, and the follow-up is empty with the position unchanged."""
    authed = live_stack.authed(live_stack.sign_in())
    _push_sources(authed, count=PAGE_SIZE)

    pages = _pull_all_pages(authed)

    assert [(len(page["rows"]["sources"]), page["more"]) for page in pages] == [(PAGE_SIZE, True), (0, False)]
    assert pages[1]["position"] == pages[0]["position"]
