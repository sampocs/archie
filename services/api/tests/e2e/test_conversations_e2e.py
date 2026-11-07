"""Saved Ask chats through the real API: the phone pulls conversations and messages, and deletes a chat with a push.

Chats are written by the server (the ask route, Task 6); these tests seed them directly. Deleting a chat keeps the
cards made from it.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

SEGMENTS = [{"label": "background", "text": "Reserves are bank money.", "citations": []}]


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _rows(authed: httpx.Client, since: int = 0) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": since}).json()["rows"]


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _seed_chat(live_stack: LiveStack, *, user_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A conversation with one question and one answer, and a card made from the answer."""
    engine = session.engine_for(live_stack.database_url)
    conversation_id, answer_id = uuid.uuid4(), uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Conversation(
                id=conversation_id,
                user_id=user_id,
                title="How does the Fed create money?",
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        db.add_all(
            [
                models.Message(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role=models.MessageRole.USER.value,
                    text="How does the Fed create money?",
                    segments=None,
                    web_search=False,
                    status=models.MessageStatus.COMPLETE.value,
                    change_seq=changes.next_change_seq(),
                ),
                models.Message(
                    id=answer_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role=models.MessageRole.ASSISTANT.value,
                    text="Reserves are bank money.",
                    segments=SEGMENTS,
                    web_search=False,
                    status=models.MessageStatus.COMPLETE.value,
                    change_seq=changes.next_change_seq(),
                ),
            ]
        )
        db.flush()
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=answer_id,
                kind=models.CardKind.CONCEPT.value,
                question="Q?",
                answer="A.",
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()
    return conversation_id, answer_id


def test_a_pull_carries_the_users_chats_messages_and_conversation_cards(live_stack: LiveStack) -> None:
    """Shapes as the phone stores them; another user sees none of it."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner"))
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger"))
    conversation_id, answer_id = _seed_chat(live_stack, user_id=_user_id(owner))

    rows = _rows(owner)

    [conversation] = rows["conversations"]
    assert conversation["id"] == str(conversation_id)
    assert (conversation["title"], conversation["about_kind"], conversation["deleted_at"]) == (
        "How does the Fed create money?",
        None,
        None,
    )
    assert {message["role"] for message in rows["messages"]} == {"user", "assistant"}
    answer = next(message for message in rows["messages"] if message["id"] == str(answer_id))
    assert (answer["segments"], answer["status"], answer["web_search"]) == (SEGMENTS, "complete", False)
    [card] = rows["cards"]
    assert (card["conversation_id"], card["message_id"], card["source_id"]) == (
        str(conversation_id),
        str(answer_id),
        None,
    )
    assert _rows(stranger)["conversations"] == []


def test_deleting_a_chat_soft_deletes_it_and_keeps_its_cards(live_stack: LiveStack) -> None:
    """The deleted conversation comes back on the next pull with `deleted_at`; its card stays live."""
    authed = live_stack.authed(live_stack.sign_in())
    conversation_id, _ = _seed_chat(live_stack, user_id=_user_id(authed))
    position = authed.get("/sync/pull", params={"since": 0}).json()["position"]

    [result] = _push(authed, _action("delete_conversation", {"id": str(conversation_id)}))

    assert (result["result"], result["reason"]) == ("applied", None)
    [conversation] = _rows(authed, since=position)["conversations"]
    assert conversation["deleted_at"] is not None
    assert all(card["deleted_at"] is None for card in _rows(authed)["cards"])


def test_deleting_an_unknown_or_someone_elses_chat_is_rejected(live_stack: LiveStack) -> None:
    """Both read as not found, and a malformed payload is malformed."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner"))
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger"))
    conversation_id, _ = _seed_chat(live_stack, user_id=_user_id(owner))

    results = _push(
        stranger,
        _action("delete_conversation", {"id": str(conversation_id)}),
        _action("delete_conversation", {"id": str(uuid.uuid4())}),
        _action("delete_conversation", {"id": "not-a-uuid"}),
    )

    assert [result["reason"] for result in results] == [
        "conversation not found",
        "conversation not found",
        "payload is malformed",
    ]


def test_me_says_whether_the_user_is_whitelisted(live_stack: LiveStack) -> None:
    """The Ask tab reads this to show its not-available state."""
    plain = live_stack.authed(live_stack.sign_in(apple_sub="plain"))
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))

    assert (plain.get("/me").json()["is_whitelisted"], owner.get("/me").json()["is_whitelisted"]) == (False, True)
