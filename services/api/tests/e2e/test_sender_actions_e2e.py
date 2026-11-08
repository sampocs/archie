"""Allow, Block and Unblock through the real API: `set_sender_status` settles waiting newsletters and later mail."""

from __future__ import annotations

import email.message
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, senders, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

T = TypeVar("T")

INGEST_SECRET = "test-ingest-secret"
INGEST_DOMAIN = "example.com"


@pytest.fixture(autouse=True)
def ingest_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The secret and domain the ingest endpoint reads per request."""
    monkeypatch.setenv("INGEST_SECRET", INGEST_SECRET)
    monkeypatch.setenv("INGEST_EMAIL_DOMAIN", INGEST_DOMAIN)


def test_allowing_a_waiting_newsletter_releases_every_pending_source_sharing_an_identifier(
    live_stack: LiveStack,
) -> None:
    """Both example.com mails start processing, an unrelated sender's stays waiting, and repeating queues nothing."""
    authed = live_stack.authed(live_stack.sign_in())
    first = _deliver(live_stack, authed, from_header="Writer <w@example.com>", message_id="first")
    second = _deliver(live_stack, authed, from_header="News Desk <news@example.com>", message_id="second")
    unrelated = _deliver(live_stack, authed, from_header="Other <o@example.org>", message_id="unrelated")
    assert _query(live_stack, sqlalchemy.select(models.Job)) == []

    result = _push(authed, _set_status(status="allowed", source_id=first))[0]

    assert result["result"] == "applied"
    released = {_source(live_stack, source_id).sender_pending for source_id in (first, second)}
    assert released == {False}
    assert {_source(live_stack, source_id).processing for source_id in (first, second)} == {"pending"}
    assert (_source(live_stack, unrelated).sender_pending, _source(live_stack, unrelated).processing) == (True, "ready")
    assert _fetch_content_sources(live_stack) == {first, second}
    [sender] = _pull(authed)["newsletter_senders"]
    assert (sender["label"], sender["status"]) == ("Writer", "allowed")

    assert _push(authed, _set_status(status="allowed", source_id=first))[0]["result"] == "applied"
    assert _push(authed, _set_status(status="allowed", source_id=second))[0]["result"] == "applied"
    assert len(_query(live_stack, sqlalchemy.select(models.Job))) == 2
    assert _pull(authed)["newsletter_senders"] == [sender]


def test_blocking_deletes_waiting_mail_and_drops_later_mail_from_the_sender(live_stack: LiveStack) -> None:
    """Block removes the pending sources of that sender only, and the next email from them is not stored."""
    authed = live_stack.authed(live_stack.sign_in())
    first = _deliver(live_stack, authed, from_header="Writer <w@example.com>", message_id="first")
    second = _deliver(live_stack, authed, from_header="News Desk <news@example.com>", message_id="second")
    unrelated = _deliver(live_stack, authed, from_header="Other <o@example.org>", message_id="unrelated")

    assert _push(authed, _set_status(status="blocked", source_id=first))[0]["result"] == "applied"

    assert _source(live_stack, first).deleted_at is not None
    assert _source(live_stack, second).deleted_at is not None
    assert _source(live_stack, unrelated).deleted_at is None
    [sender] = _pull(authed)["newsletter_senders"]
    assert sender["status"] == "blocked"

    _deliver(live_stack, authed, from_header="Writer <w@example.com>", message_id="third", expect_stored=False)
    assert len(_query(live_stack, sqlalchemy.select(models.Source))) == 3
    assert _query(live_stack, sqlalchemy.select(models.Job)) == []


def test_unblocking_by_sender_id_lets_later_mail_through(live_stack: LiveStack) -> None:
    """Unblock sets the known sender to allowed; the next email from it is processed."""
    authed = live_stack.authed(live_stack.sign_in())
    first = _deliver(live_stack, authed, from_header="Writer <w@example.com>", message_id="first")
    _push(authed, _set_status(status="blocked", source_id=first))
    [sender] = _pull(authed)["newsletter_senders"]

    result = _push(authed, _set_status(status="allowed", sender_id=sender["id"]))[0]

    assert result["result"] == "applied"
    [unblocked] = _pull(authed)["newsletter_senders"]
    assert (unblocked["status"], unblocked["id"]) == ("allowed", sender["id"])
    assert unblocked["change_seq"] > sender["change_seq"]
    later = _deliver(live_stack, authed, from_header="Writer <w@example.com>", message_id="second")
    assert _source(live_stack, later).processing == "pending"
    assert _fetch_content_sources(live_stack) == {later}


def test_allowing_a_source_whose_identifiers_span_two_senders_merges_into_the_oldest(live_stack: LiveStack) -> None:
    """The oldest sender is kept and gains the new identifier, the other one takes the status, untouched ones stay."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = authed.get("/me").json()["user_id"]
    older = _record(live_stack, user_id, address="w@example.com", status=models.SenderStatus.BLOCKED, label="Old")
    newer = _record(live_stack, user_id, name="Writer", status=models.SenderStatus.BLOCKED, label="New")
    unrelated = _record(live_stack, user_id, name="Other", status=models.SenderStatus.BLOCKED, label="Unrelated")
    before = {row["id"]: row for row in _pull(authed)["newsletter_senders"]}
    source_id = _insert_pending_source(
        live_stack, user_id, sender="Writer", sender_address="w@example.com", list_id="list.example.invalid"
    )

    assert _push(authed, _set_status(status="allowed", source_id=source_id))[0]["result"] == "applied"

    after = {row["id"]: row for row in _pull(authed)["newsletter_senders"]}
    assert {sender_id: row["status"] for sender_id, row in after.items()} == {
        str(older): "allowed",
        str(newer): "allowed",
        str(unrelated): "blocked",
    }
    assert after[str(unrelated)] == before[str(unrelated)]
    owners = _query_with(
        live_stack,
        lambda db: {
            (row.kind, row.value): row.sender_id
            for row in db.scalars(sqlalchemy.select(models.NewsletterSenderIdentifier))
        },
    )
    assert owners[("list_id", "list.example.invalid")] == older
    assert owners[("name", "writer")] == newer
    # The source had no capture, so releasing it can only mark it unreadable; nothing is queued.
    released = _source(live_stack, source_id)
    assert (released.sender_pending, released.processing, released.processing_error) == (
        False,
        "failed",
        models.UNREADABLE_EMAIL_ERROR,
    )
    assert _fetch_content_sources(live_stack) == set()


def test_an_action_for_a_missing_foreign_or_ill_formed_target_is_rejected_and_writes_nothing(
    live_stack: LiveStack,
) -> None:
    """Exactly one id, a valid status, the caller's own newsletter or sender, and something to match on."""
    authed = live_stack.authed(live_stack.sign_in())
    other = live_stack.authed(live_stack.sign_in(apple_sub="other"))
    other_source = _deliver(live_stack, other, from_header="Writer <w@example.com>", message_id="theirs")
    other_user_id = other.get("/me").json()["user_id"]
    other_sender = _record(live_stack, other_user_id, name="Theirs", status=models.SenderStatus.ALLOWED, label="Theirs")
    user_id = authed.get("/me").json()["user_id"]
    article_id = str(uuid.uuid4())
    _push(authed, _action("add_source", {"id": article_id, "url": "https://example.com/a", "intent": "queue"}))
    anonymous_id = _insert_pending_source(live_stack, user_id, sender=None, sender_address=None, list_id=None)

    results = _push(
        authed,
        _set_status(status="maybe", source_id=str(anonymous_id)),
        _action("set_sender_status", {"status": "allowed"}),
        _action(
            "set_sender_status",
            {"status": "allowed", "source_id": str(uuid.uuid4()), "sender_id": str(uuid.uuid4())},
        ),
        _set_status(status="allowed", source_id=str(uuid.uuid4())),
        _set_status(status="allowed", source_id=other_source),
        _set_status(status="allowed", source_id=article_id),
        _set_status(status="allowed", source_id=str(anonymous_id)),
        _set_status(status="allowed", sender_id=str(uuid.uuid4())),
        _set_status(status="allowed", sender_id=str(other_sender)),
    )

    assert [(row["result"], row["reason"]) for row in results] == [
        ("rejected", "payload is malformed"),
        ("rejected", "payload is malformed"),
        ("rejected", "payload is malformed"),
        ("rejected", "source not found"),
        ("rejected", "source not found"),
        ("rejected", "source is not a newsletter"),
        ("rejected", "source has no sender to record"),
        ("rejected", "sender not found"),
        ("rejected", "sender not found"),
    ]
    other_senders = _query(live_stack, sqlalchemy.select(models.NewsletterSender))
    assert [(row.user_id, row.status) for row in other_senders] == [(other_user_id, "allowed")]
    assert _source(live_stack, uuid.UUID(other_source)).sender_pending is True


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _set_status(
    *, status: str, source_id: str | uuid.UUID | None = None, sender_id: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status}
    if source_id is not None:
        payload["source_id"] = str(source_id)
    if sender_id is not None:
        payload["sender_id"] = sender_id
    return _action("set_sender_status", payload)


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _pull(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _deliver(
    live_stack: LiveStack, authed: httpx.Client, *, from_header: str, message_id: str, expect_stored: bool = True
) -> str:
    """Post an email to the user's address; returns the new source's id (the message id when it was dropped)."""
    message = email.message.EmailMessage()
    message["From"] = from_header
    message["Subject"] = f"Issue {message_id}"
    message["Message-ID"] = f"<{message_id}@example.com>"
    message.set_content("Just a short plain note.")
    headers = {"x-ingest-secret": INGEST_SECRET, "x-ingest-to": authed.get("/me").json()["ingest_address"]}

    response = live_stack.client.post("/ingest/email", content=message.as_bytes(), headers=headers)

    assert response.status_code == 202
    stored = _query(
        live_stack,
        sqlalchemy.select(models.Source.id).where(models.Source.newsletter_message_id == f"{message_id}@example.com"),
    )
    assert bool(stored) == expect_stored
    return str(stored[0]) if stored else message_id


def _insert_pending_source(
    live_stack: LiveStack, user_id: int, *, sender: str | None, sender_address: str | None, list_id: str | None = None
) -> uuid.UUID:
    source_id = uuid.uuid4()

    def run(db: sqlalchemy.orm.Session) -> None:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Source(
                id=source_id,
                user_id=user_id,
                url=f"newsletter:{source_id}",
                normalized_url=f"newsletter:{source_id}",
                kind=models.SourceKind.NEWSLETTER.value,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                sender=sender,
                sender_address=sender_address,
                list_id=list_id,
                sender_pending=True,
                processing=models.ProcessingStatus.READY.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()

    _query_with(live_stack, run)
    return source_id


def _record(
    live_stack: LiveStack,
    user_id: int,
    *,
    status: models.SenderStatus,
    label: str,
    address: str | None = None,
    name: str | None = None,
) -> uuid.UUID:
    """Make a sender in its own transaction (so creation times differ) and return its id."""
    identifiers = senders.identifiers_for(address=address, list_id=None, name=name)

    def run(db: sqlalchemy.orm.Session) -> uuid.UUID:
        changes.lock_user_writes(db, user_id)
        senders.record(db, user_id=user_id, identifiers=identifiers, status=status, label=label)
        db.commit()
        return db.scalars(
            sqlalchemy.select(models.NewsletterSender.id).where(models.NewsletterSender.label == label)
        ).one()

    return _query_with(live_stack, run)


def _source(live_stack: LiveStack, source_id: str | uuid.UUID) -> models.Source:
    return _query(live_stack, sqlalchemy.select(models.Source).where(models.Source.id == uuid.UUID(str(source_id))))[0]


def _fetch_content_sources(live_stack: LiveStack) -> set[str]:
    jobs = _query(live_stack, sqlalchemy.select(models.Job).where(models.Job.kind == "fetch_content"))
    return {job.payload[pipeline.SOURCE_ID_KEY] for job in jobs}


def _query(live_stack: LiveStack, statement: Any) -> list[Any]:
    return _query_with(live_stack, lambda db: list(db.scalars(statement)))


def _query_with(live_stack: LiveStack, run: Callable[[sqlalchemy.orm.Session], T]) -> T:
    engine = session.engine_for(live_stack.database_url)
    try:
        with sqlalchemy.orm.Session(engine) as db:
            return run(db)
    finally:
        engine.dispose()
