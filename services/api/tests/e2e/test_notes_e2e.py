"""Notes through the real API: import, write-up queueing, refresh and skip actions, the seed route, the session CLI."""

import datetime
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api import deps
from archie_api.auth import issue_session
from archie_db import jobs, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

WRITE_UP = {
    "domain": "Crypto",
    "summary": {"gist": "Validators stake ETH.", "key_ideas": ["Slashing"], "numbers": []},
    "sources": [{"url": "https://example.com/pos", "title": "PoS explained"}],
}


def _note(
    bear_id: str = "NOTE-1", *, mark: str = "cards", markdown: str | None = None, title: str = "Proof of stake"
) -> dict[str, Any]:
    return {
        "bear_id": bear_id,
        "title": title,
        "markdown": markdown or f"# {title}\n\n## Overview\n- Validators lock ETH\n- **Slashing** for misbehaviour\n",
        "tags": ["crypto/staking"],
        "created_at": "2023-03-01T10:00:00+00:00",
        "edited_at": "2024-02-13T18:30:00+00:00",
        "mark": mark,
    }


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _pull(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _import(authed: httpx.Client, *notes: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/notes/import", json={"notes": list(notes)})
    response.raise_for_status()
    return response.json()["results"]


def _source(authed: httpx.Client, source_id: str) -> dict[str, Any]:
    return next(row for row in _pull(authed)["sources"] if row["id"] == source_id)


def _db(live_stack: LiveStack) -> sqlalchemy.orm.Session:
    return sqlalchemy.orm.Session(session.engine_for(live_stack.database_url))


def _jobs(live_stack: LiveStack, kind: models.JobKind) -> list[models.Job]:
    with _db(live_stack) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.Job).where(models.Job.kind == kind.value).order_by(models.Job.next_run_at)
            )
        )


def _texts(live_stack: LiveStack, source_id: str) -> list[models.SourceArtifact]:
    with _db(live_stack) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.SourceArtifact)
                .where(
                    models.SourceArtifact.source_id == uuid.UUID(source_id),
                    models.SourceArtifact.kind == models.ArtifactKind.TEXT.value,
                )
                .order_by(models.SourceArtifact.version)
            )
        )


def _seed_write_up(authed: httpx.Client, source_id: str) -> None:
    authed.post(f"/test/notes/{source_id}/write-up", json=WRITE_UP).raise_for_status()


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a fresh user."""
    return live_stack.authed(live_stack.sign_in())


@pytest.fixture
def owner(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a whitelisted user, who may spend the owner's keys."""
    return live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def test_import_needs_a_session(live_stack: LiveStack) -> None:
    """The import is the owner's only: no session, no import."""
    response = live_stack.client.post("/notes/import", json={"notes": [_note()]})

    assert response.status_code == 401


def test_import_creates_note_sources_without_generating_anything(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Importing stores the note and its text and queues only embedding: no model call, no write-up."""
    markdown = "# Proof of stake\n\n- Validators lock ETH\n"
    results = _import(authed, _note("NOTE-1", mark="cards", markdown=markdown), _note("NOTE-2", mark="import"))

    assert [(result["bear_id"], result["status"]) for result in results] == [
        ("NOTE-1", "created"),
        ("NOTE-2", "created"),
    ]
    rows = _pull(authed)
    sources = {row["url"]: row for row in rows["sources"]}
    cards, import_only = sources["bear:NOTE-1"], sources["bear:NOTE-2"]
    assert (cards["kind"], cards["state"], cards["cards_off"]) == ("note", "inbox", False)
    assert (import_only["state"], import_only["cards_off"]) == ("consumed", True)
    assert cards["created_at"].startswith("2023-03-01")
    assert cards["note_markdown"] == markdown
    assert cards["note_edited_at"].startswith("2024-02-13")
    assert cards["refreshed_at"] is None
    assert cards["refreshed_from_queue"] is False
    assert cards["processing"] == "ready"
    assert not [artifact for artifact in rows["artifacts"] if artifact["kind"] == "summary"]

    with _db(live_stack) as db:
        for result in results:
            source = db.get_one(models.Source, uuid.UUID(result["id"]))
            assert source.bear_id == result["bear_id"]
            assert source.note_tags == ["crypto/staking"]
    assert _texts(live_stack, results[0]["id"])[0].content == {"text": markdown}
    assert len(_jobs(live_stack, models.JobKind.EMBED)) == 2
    with _db(live_stack) as db:
        assert db.scalar(sqlalchemy.select(sqlalchemy.func.count()).select_from(models.Job)) == 2
        assert db.scalar(sqlalchemy.select(sqlalchemy.func.count()).select_from(models.LlmCall)) == 0


def test_reimporting_is_idempotent(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The same note again changes nothing; an edit versions the text; a changed mark applies until refreshed."""
    source_id = _import(authed, _note())[0]["id"]
    seq = _source(authed, source_id)["change_seq"]

    assert _import(authed, _note())[0]["status"] == "unchanged"
    assert _source(authed, source_id)["change_seq"] == seq
    assert len(_texts(live_stack, source_id)) == 1

    edited = _note(markdown="# Proof of stake\n\n- New line\n")
    with _db(live_stack) as db:
        for job in db.scalars(sqlalchemy.select(models.Job).where(models.Job.kind == models.JobKind.EMBED.value)):
            job.status = models.JobStatus.DONE.value
        db.commit()
    assert _import(authed, edited)[0]["status"] == "updated"
    texts = _texts(live_stack, source_id)
    assert [(text.version, text.is_current) for text in texts] == [(1, False), (2, True)]
    assert texts[1].content == {"text": edited["markdown"]}
    queued = [job for job in _jobs(live_stack, models.JobKind.EMBED) if job.status == models.JobStatus.QUEUED.value]
    assert [job.payload[jobs.ITEM_ID_KEY] for job in queued] == [source_id]

    assert _import(authed, _note(markdown=edited["markdown"], mark="import"))[0]["status"] == "updated"
    row = _source(authed, source_id)
    assert (row["state"], row["cards_off"]) == ("consumed", True)


def test_a_changed_mark_is_ignored_once_refreshed(live_stack: LiveStack, owner: httpx.Client) -> None:
    """After a refresh the phone owns the note's state, so re-importing with another mark leaves it alone."""
    source_id = _import(owner, _note())[0]["id"]
    _seed_write_up(owner, source_id)
    _push(owner, _action("refresh_note", {"id": source_id, "counted": False, "at": _now()}))

    assert _import(owner, _note(mark="import"))[0]["status"] == "unchanged"
    assert _source(owner, source_id)["cards_off"] is False


def test_a_deleted_note_stays_deleted(authed: httpx.Client) -> None:
    """Re-importing a note the owner deleted on the phone does not bring it back."""
    source_id = _import(authed, _note())[0]["id"]
    _push(authed, _action("delete_source", {"id": source_id}))

    results = _import(authed, _note())

    assert results[0]["status"] == "deleted"
    assert _source(authed, source_id)["deleted_at"] is not None


def test_bear_ids_are_per_user(live_stack: LiveStack) -> None:
    """Two users may import the same Bear id and get separate sources."""
    first = live_stack.authed(live_stack.sign_in(apple_sub="one"))
    second = live_stack.authed(live_stack.sign_in(apple_sub="two"))

    assert _import(first, _note())[0]["id"] != _import(second, _note())[0]["id"]


def test_a_repeated_bear_id_in_one_request_is_refused(authed: httpx.Client) -> None:
    """A batch naming one note twice is a client bug."""
    response = authed.post("/notes/import", json={"notes": [_note(), _note()]})

    assert response.status_code == 422


def test_write_ups_need_the_owners_keys(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Write-ups spend the owner's money, so a non-whitelisted user is refused and nothing is queued."""
    _import(authed, _note())

    response = authed.post("/notes/write-ups")

    assert response.status_code == 403
    assert response.json()["detail"] == deps.NEEDS_OWN_KEY
    assert not _jobs(live_stack, models.JobKind.WRITE_NOTE)


def test_write_ups_queue_once_per_note_without_one(live_stack: LiveStack, owner: httpx.Client) -> None:
    """One spaced job per note lacking a write-up, newest edit first; asking again queues nothing."""
    older = _note("OLD")
    older["edited_at"] = "2023-01-01T00:00:00+00:00"
    ids = {result["bear_id"]: result["id"] for result in _import(owner, older, _note("NEW"))}

    assert owner.post("/notes/write-ups").json() == {"queued": 2}

    jobs = _jobs(live_stack, models.JobKind.WRITE_NOTE)
    assert [job.payload["source_id"] for job in jobs] == [ids["NEW"], ids["OLD"]]
    assert (jobs[1].next_run_at - jobs[0].next_run_at).total_seconds() >= 59
    assert owner.post("/notes/write-ups").json() == {"queued": 0}


def test_write_ups_skip_notes_that_already_have_one(live_stack: LiveStack, owner: httpx.Client) -> None:
    """A note with a current write-up is not written again until its text changes."""
    source_id = _import(owner, _note())[0]["id"]
    _seed_write_up(owner, source_id)

    assert owner.post("/notes/write-ups").json() == {"queued": 0}

    _import(owner, _note(markdown="# Proof of stake\n\n- Edited\n"))
    assert owner.post("/notes/write-ups").json() == {"queued": 1}


def test_refresh_note_consumes_it_and_queues_cards(live_stack: LiveStack, owner: httpx.Client) -> None:
    """Done on a note stamps the refresh, files it as Done and queues its cards, once."""
    source_id = _import(owner, _note())[0]["id"]
    _seed_write_up(owner, source_id)
    refreshed_at = "2026-11-08T09:00:00+00:00"

    first = _push(owner, _action("refresh_note", {"id": source_id, "counted": True, "at": refreshed_at}))
    second = _push(owner, _action("refresh_note", {"id": source_id, "counted": True, "at": refreshed_at}))

    assert first[0]["result"] == "applied"
    assert second[0]["result"] == "rejected"
    row = _source(owner, source_id)
    assert (row["state"], row["refreshed_from_queue"], row["domain"]) == ("consumed", True, "Crypto")
    assert row["refreshed_at"].startswith("2026-11-08T09:00:00")
    assert len(_jobs(live_stack, models.JobKind.NOTE_CARDS)) == 1


def test_refresh_note_never_stamps_the_future(owner: httpx.Client) -> None:
    """A phone clock ahead of the server cannot write a future refresh time."""
    source_id = _import(owner, _note())[0]["id"]
    _seed_write_up(owner, source_id)
    future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)).isoformat()

    _push(owner, _action("refresh_note", {"id": source_id, "counted": False, "at": future}))

    refreshed_at = datetime.datetime.fromisoformat(_source(owner, source_id)["refreshed_at"])
    assert refreshed_at.replace(tzinfo=refreshed_at.tzinfo or datetime.UTC) <= datetime.datetime.now(datetime.UTC)


def test_refresh_note_is_refused_without_a_write_up_or_for_import_notes(
    live_stack: LiveStack, owner: httpx.Client
) -> None:
    """No write-up yet, or a note whose cards are off, cannot be refreshed; a malformed or foreign source neither."""
    no_write_up = _import(owner, _note("A"))[0]["id"]
    import_only = _import(owner, _note("B", mark="import"))[0]["id"]
    _seed_write_up(owner, import_only)
    payload = {"counted": False, "at": _now()}

    results = _push(
        owner,
        _action("refresh_note", {"id": no_write_up, **payload}),
        _action("refresh_note", {"id": import_only, **payload}),
        _action("refresh_note", {"id": str(uuid.uuid4()), **payload}),
        _action("refresh_note", {"id": no_write_up}),
    )

    assert [result["result"] for result in results] == ["rejected"] * 4
    assert not _jobs(live_stack, models.JobKind.NOTE_CARDS)


def test_refresh_and_skip_are_refused_for_other_kinds(authed: httpx.Client) -> None:
    """The note actions only touch notes."""
    source_id = str(uuid.uuid4())
    _push(authed, _action("add_source", {"id": source_id, "url": "https://example.com/a", "intent": "queue"}))

    results = _push(
        authed,
        _action("refresh_note", {"id": source_id, "counted": False, "at": _now()}),
        _action("skip_note", {"id": source_id, "at": _now()}),
    )

    assert [result["result"] for result in results] == ["rejected", "rejected"]


def test_skip_note_moves_it_to_the_back(owner: httpx.Client) -> None:
    """Skipping stamps the note; once refreshed it can no longer be skipped."""
    source_id = _import(owner, _note())[0]["id"]
    _seed_write_up(owner, source_id)

    skipped = _push(owner, _action("skip_note", {"id": source_id, "at": "2026-11-08T09:00:00+00:00"}))
    assert skipped[0]["result"] == "applied"
    assert _source(owner, source_id)["refresh_skipped_at"].startswith("2026-11-08T09:00:00")

    _push(owner, _action("refresh_note", {"id": source_id, "counted": False, "at": _now()}))
    late = _push(owner, _action("skip_note", {"id": source_id, "at": _now()}))
    assert late[0]["result"] == "rejected"
    assert _push(owner, _action("skip_note", {"id": source_id}))[0]["result"] == "rejected"


def test_the_seeded_write_up_reaches_the_phone(owner: httpx.Client) -> None:
    """The test route stores a current summary artifact with sources and no cards."""
    source_id = _import(owner, _note())[0]["id"]
    _seed_write_up(owner, source_id)

    summaries = [
        artifact
        for artifact in _pull(owner)["artifacts"]
        if artifact["source_id"] == source_id and artifact["kind"] == "summary" and artifact["is_current"]
    ]

    assert len(summaries) == 1
    content = summaries[0]["content"]
    assert content["summary"]["gist"] == "Validators stake ETH."
    assert content["sources"] == WRITE_UP["sources"]
    assert content["cards"] == []


def test_issue_session_signs_in_the_user_with_that_email(live_stack: LiveStack) -> None:
    """The CLI starts a working session for the one user with that email, whatever its case; unknown emails fail."""
    user_id = live_stack.authed(live_stack.sign_in(email="owner@example.com")).get("/me").json()["user_id"]

    with _db(live_stack) as db:
        key = issue_session.issue_session(db, email="OWNER@example.com")
        with pytest.raises(issue_session.IssueSessionError):
            issue_session.issue_session(db, email="nobody@example.com")

    response = live_stack.authed(key).get("/me")
    assert response.status_code == 200
    assert response.json()["user_id"] == user_id


def test_skip_note_applies_to_a_cards_off_note(owner: httpx.Client) -> None:
    """Skipping only needs a live note, so an import-mark note (cards off) can still be skipped."""
    source_id = _import(owner, _note(mark="import"))[0]["id"]

    skipped = _push(owner, _action("skip_note", {"id": source_id, "at": _now()}))

    assert skipped[0]["result"] == "applied"
