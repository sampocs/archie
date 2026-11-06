"""Takes through the real API: write, edit, clean up, restore, change kind and delete; pull takes and versions.

A save that makes a version queues that version's next step (`take_cards`, or `clean_take` with Clean it up on); a save
with an unchanged body makes no version and queues nothing. A take is never a source.
"""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

BODY = "Crypto's lasting use is moving dollars. Stablecoins settle ~$10T a year."
EDITED = "Crypto's lasting use is moving dollars. Stablecoins settle ~$10T a year, with no bank in the middle."
RAMBLE = "ok so the main thing is people think it's all speculation but stablecoins did like 10 trillion last year"
CLEANED = "Crypto's lasting use is moving dollars.\n\n## Main points\n\n- Stablecoins did ~10 trillion last year."
TITLE = "The argument for crypto"


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


def _versions(rows: dict[str, list[dict[str, Any]]], take_id: str) -> list[dict[str, Any]]:
    return sorted((row for row in rows["take_versions"] if row["take_id"] == take_id), key=lambda row: row["version"])


def _save_payload(
    take_id: str,
    *,
    version_id: str,
    body: str = BODY,
    title: str = TITLE,
    kind: str = "talking_point",
    clean: bool = False,
) -> dict[str, Any]:
    return {"id": take_id, "version_id": version_id, "kind": kind, "title": title, "body": body, "clean": clean}


def _save(authed: httpx.Client, *, take_id: str | None = None, **fields: Any) -> tuple[str, str]:
    """Push one save_take that must apply; returns the take id and the version id it sent."""
    take_id = take_id or str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    assert _reasons(_push(authed, _action("save_take", _save_payload(take_id, version_id=version_id, **fields)))) == [
        None
    ]
    return take_id, version_id


def _db(live_stack: LiveStack) -> sqlalchemy.orm.Session:
    return sqlalchemy.orm.Session(session.engine_for(live_stack.database_url))


def _queued(live_stack: LiveStack) -> list[tuple[str, str]]:
    """Every job as (kind, the version it names), oldest first."""
    with _db(live_stack) as db:
        queued = db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id))
        return [(job.kind, job.payload[jobs.TAKE_VERSION_ID_KEY]) for job in queued]


def _set_version(live_stack: LiveStack, *, version_id: str, body: str, clean_failed: bool) -> None:
    """What the worker writes: a cleaned body, or the raw text after the cleanup gave up."""
    with _db(live_stack) as db:
        version = db.get_one(models.TakeVersion, uuid.UUID(version_id))
        changes.lock_user_writes(db, version.user_id)
        version.body = body
        version.clean_failed = clean_failed
        version.change_seq = changes.next_change_seq()
        db.commit()


def _add_take_card(live_stack: LiveStack, *, take_id: str, version_id: str) -> str:
    """A card as take_cards writes it."""
    card_id = uuid.uuid4()
    with _db(live_stack) as db:
        take = db.get_one(models.Take, uuid.UUID(take_id))
        changes.lock_user_writes(db, take.user_id)
        db.add(
            models.Card(
                id=card_id,
                user_id=take.user_id,
                take_id=take.id,
                take_version_id=uuid.UUID(version_id),
                kind=models.CardKind.TAKE.value,
                question="Roughly how much do stablecoins settle a year?",
                answer="About $10T, Visa scale.",
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    return str(card_id)


def test_writing_a_take_makes_version_one_and_queues_its_cards(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The title is stored with whitespace collapsed; the body is version 1 as written; no source is made."""
    take_id, version_id = _save(authed, title="  The argument   for crypto ", body=f"  {BODY}\n")

    rows = _rows(authed)

    take = _by_id(rows["takes"], take_id)
    assert (take["kind"], take["title"], take["current_version"], take["deleted_at"]) == (
        "talking_point",
        TITLE,
        1,
        None,
    )
    [version] = rows["take_versions"]
    assert (version["id"], version["take_id"], version["version"]) == (version_id, take_id, 1)
    assert (version["body"], version["raw_body"], version["cleaned"], version["clean_failed"]) == (
        BODY,
        BODY,
        False,
        False,
    )
    assert rows["sources"] == []
    assert _queued(live_stack) == [(models.JobKind.TAKE_CARDS.value, version_id)]


def test_clean_it_up_leaves_the_body_empty_and_queues_the_cleanup(live_stack: LiveStack, authed: httpx.Client) -> None:
    """With Clean it up on, the raw text is kept and the shown body waits for clean_take."""
    _, version_id = _save(authed, body=RAMBLE, clean=True)

    [version] = _rows(authed)["take_versions"]

    assert (version["body"], version["raw_body"], version["cleaned"]) == (None, RAMBLE, True)
    assert _queued(live_stack) == [(models.JobKind.CLEAN_TAKE.value, version_id)]


def test_an_unchanged_body_makes_no_version_but_saves_the_title_and_kind(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Fixing a title or the kind keeps the take's version (and so its date), and queues nothing."""
    take_id, first = _save(authed)
    before = _by_id(_rows(authed)["takes"], take_id)

    _save(authed, take_id=take_id, title="Crypto, the case", kind="opinion", body=f"{BODY}  ")
    rows = _rows(authed)

    take = _by_id(rows["takes"], take_id)
    assert (take["title"], take["kind"], take["current_version"]) == ("Crypto, the case", "opinion", 1)
    assert take["change_seq"] > before["change_seq"]
    assert [row["id"] for row in rows["take_versions"]] == [first]
    assert _queued(live_stack) == [(models.JobKind.TAKE_CARDS.value, first)]


def test_an_edit_makes_the_next_version_and_clean_on_alone_asks_for_a_cleanup(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A changed body is version 2; the same body with Clean it up switched on is version 3, waiting for cleanup."""
    take_id, first = _save(authed)
    _, second = _save(authed, take_id=take_id, body=EDITED)
    _, third = _save(authed, take_id=take_id, body=EDITED, clean=True)

    rows = _rows(authed)

    assert [(row["id"], row["version"], row["body"], row["cleaned"]) for row in _versions(rows, take_id)] == [
        (first, 1, BODY, False),
        (second, 2, EDITED, False),
        (third, 3, None, True),
    ]
    assert _by_id(rows["takes"], take_id)["current_version"] == 3
    assert _queued(live_stack) == [
        (models.JobKind.TAKE_CARDS.value, first),
        (models.JobKind.TAKE_CARDS.value, second),
        (models.JobKind.CLEAN_TAKE.value, third),
    ]


def test_saving_while_the_cleanup_runs_compares_against_the_raw_text(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Before clean_take lands, the editor shows the raw text; saving it unchanged makes no version."""
    take_id, first = _save(authed, body=RAMBLE, clean=True)

    _save(authed, take_id=take_id, body=RAMBLE, clean=True)

    assert [row["id"] for row in _versions(_rows(authed), take_id)] == [first]
    assert len(_queued(live_stack)) == 1


def test_restoring_copies_an_earlier_version_without_cleaning_it_again(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """The copy keeps the cleaned body, the raw text and the cleaned flag, and gets fresh cards."""
    take_id, first = _save(authed, body=RAMBLE, clean=True)
    _set_version(live_stack, version_id=first, body=CLEANED, clean_failed=False)
    _save(authed, take_id=take_id, body=EDITED)
    restored = str(uuid.uuid4())

    results = _push(authed, _action("restore_take_version", {"id": take_id, "version": 1, "version_id": restored}))
    rows = _rows(authed)

    assert _reasons(results) == [None]
    copy = _by_id(rows["take_versions"], restored)
    assert (copy["version"], copy["body"], copy["raw_body"], copy["cleaned"]) == (3, CLEANED, RAMBLE, True)
    assert _by_id(rows["takes"], take_id)["current_version"] == 3
    assert _queued(live_stack)[-1] == (models.JobKind.TAKE_CARDS.value, restored)


def test_restoring_a_version_whose_cleanup_never_finished_uses_its_raw_text(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A version replaced while clean_take was still running has no body; its copy shows the raw text instead."""
    take_id, _ = _save(authed, body=RAMBLE, clean=True)
    _save(authed, take_id=take_id, body=EDITED)
    restored = str(uuid.uuid4())

    _push(authed, _action("restore_take_version", {"id": take_id, "version": 1, "version_id": restored}))

    copy = _by_id(_rows(authed)["take_versions"], restored)
    assert (copy["version"], copy["body"], copy["raw_body"], copy["cleaned"]) == (3, RAMBLE, RAMBLE, True)
    assert _queued(live_stack)[-1] == (models.JobKind.TAKE_CARDS.value, restored)


def test_renaming_and_changing_the_kind_make_no_version(live_stack: LiveStack, authed: httpx.Client) -> None:
    """update_take saves the title (collapsed) and kind on the take alone, and queues nothing."""
    take_id, version_id = _save(authed)

    results = _push(authed, _action("update_take", {"id": take_id, "title": " Crypto,  the case ", "kind": "opinion"}))
    rows = _rows(authed)

    assert _reasons(results) == [None]
    take = _by_id(rows["takes"], take_id)
    assert (take["title"], take["kind"], take["current_version"], take["deleted_at"]) == (
        "Crypto, the case",
        "opinion",
        1,
        None,
    )
    assert [row["id"] for row in rows["take_versions"]] == [version_id]
    assert len(_queued(live_stack)) == 1


def test_deleting_a_take_retires_its_cards_and_refuses_later_changes(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A deleted take's cards leave review with it; every take action then answers "take not found"."""
    take_id, version_id = _save(authed)
    card_id = _add_take_card(live_stack, take_id=take_id, version_id=version_id)

    _push(authed, _action("update_take", {"id": take_id, "deleted": True}))
    rows = _rows(authed)
    after = _push(
        authed,
        _action("update_take", {"id": take_id, "title": "Again"}),
        _action("save_take", _save_payload(take_id, version_id=str(uuid.uuid4()), body=EDITED)),
        _action("restore_take_version", {"id": take_id, "version": 1, "version_id": str(uuid.uuid4())}),
        _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}),
    )

    assert _by_id(rows["takes"], take_id)["deleted_at"] is not None
    card = _by_id(rows["cards"], card_id)
    assert card["deleted_at"] is not None
    assert (card["take_id"], card["take_version_id"], card["source_id"], card["kind"]) == (
        take_id,
        version_id,
        None,
        "take",
    )
    assert _reasons(after) == ["take not found"] * 4


def test_try_again_re_queues_a_failed_cleanup(live_stack: LiveStack, authed: httpx.Client) -> None:
    """After the cleanup gave up (raw text shown), Try again empties the body and queues clean_take again."""
    take_id, version_id = _save(authed, body=RAMBLE, clean=True)
    _set_version(live_stack, version_id=version_id, body=RAMBLE, clean_failed=True)
    before = _by_id(_rows(authed)["take_versions"], version_id)

    results = _push(authed, _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}))
    after = _by_id(_rows(authed)["take_versions"], version_id)
    again = _push(authed, _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}))

    assert _reasons(results) == [None]
    assert (after["body"], after["clean_failed"]) == (None, False)
    assert after["change_seq"] > before["change_seq"]
    # Nothing failed any more, so the second Try again is applied but queues nothing.
    assert _reasons(again) == [None]
    assert _queued(live_stack) == [(models.JobKind.CLEAN_TAKE.value, version_id)] * 2


def test_take_actions_refuse_other_users_and_bad_input(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Another user's take is not found; titles, bodies, kinds, versions and ids are checked before any write."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    take_id, version_id = _save(authed)
    other_take_id, other_version_id = _save(authed, title="Another take")

    foreign = _push(
        other,
        _action("save_take", _save_payload(take_id, version_id=str(uuid.uuid4()), body=EDITED)),
        _action("update_take", {"id": take_id, "deleted": True}),
        _action("restore_take_version", {"id": take_id, "version": 1, "version_id": str(uuid.uuid4())}),
        _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}),
    )
    own = _push(
        authed,
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), title="   ")),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), title="t" * 201)),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), body=" \n ")),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), body="b" * 20001)),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), kind="rant")),
        _action("update_take", {"id": take_id, "title": "  "}),
        _action("restore_take_version", {"id": take_id, "version": 9, "version_id": str(uuid.uuid4())}),
        _action("restore_take_version", {"id": take_id, "version": 1, "version_id": version_id}),
        _action("save_take", _save_payload(take_id, version_id=version_id, body=EDITED)),
        _action("retry_take_cleanup", {"id": take_id, "version_id": str(uuid.uuid4())}),
        _action("retry_take_cleanup", {"id": take_id, "version_id": other_version_id}),
        _action("restore_take_version", {"id": take_id, "version": 0, "version_id": str(uuid.uuid4())}),
    )

    assert _reasons(foreign) == ["take not found"] * 4
    assert _reasons(own) == [
        "take title is empty",
        "take title is longer than 200 characters",
        "take is empty",
        "take is longer than 20000 characters",
        "payload is malformed",
        "take title is empty",
        "take version not found",
        "id already exists",
        "id already exists",
        "take version not found",
        "take version not found",
        "payload is malformed",
    ]
    rows = _rows(authed)
    assert sorted((row["id"], row["title"], row["deleted_at"]) for row in rows["takes"]) == sorted(
        [(take_id, TITLE, None), (other_take_id, "Another take", None)]
    )
    assert sorted(row["id"] for row in rows["take_versions"]) == sorted([version_id, other_version_id])
