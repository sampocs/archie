"""Pull carries what edits through chat add: version origins, card versions and Ask's edit proposals."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres


def _user_id(authed: httpx.Client) -> int:
    return int(authed.get("/me").json()["user_id"])


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def test_pull_carries_origins_card_versions_and_proposals(live_stack: LiveStack) -> None:
    """An edited card's versions and the chat's proposal reach the phone with every field the app stores."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    card_id, proposal_id = uuid.uuid4(), uuid.uuid4()

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        conversation = models.Conversation(
            id=uuid.uuid4(), user_id=user_id, title="Q", change_seq=changes.next_change_seq()
        )
        db.add(conversation)
        db.flush()
        message = models.Message(
            id=uuid.uuid4(),
            user_id=user_id,
            conversation_id=conversation.id,
            role=models.MessageRole.ASSISTANT.value,
            text="A",
            segments=[],
            web_search=False,
            status=models.MessageStatus.COMPLETE.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(message)
        db.add(
            models.Card(
                id=card_id,
                user_id=user_id,
                conversation_id=conversation.id,
                kind=models.CardKind.CONCEPT.value,
                question="Q?",
                answer="B.",
                version=2,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        for version, answer in ((1, "A."), (2, "B.")):
            db.add(
                models.CardVersion(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    card_id=card_id,
                    version=version,
                    question="Q?",
                    answer=answer,
                    origin=(models.VersionOrigin.ARCHIE if version == 1 else models.VersionOrigin.CHAT_EDIT).value,
                    instruction=None if version == 1 else "Say B",
                    change_seq=changes.next_change_seq(),
                )
            )
        db.add(
            models.EditProposal(
                id=proposal_id,
                user_id=user_id,
                conversation_id=conversation.id,
                message_id=message.id,
                target_kind=models.EditTarget.CARD.value,
                target_id=card_id,
                title="Q?",
                description="Say B",
                base_version=1,
                before={"question": "Q?", "answer": "A."},
                after={"question": "Q?", "answer": "B."},
                status=models.EditStatus.APPLIED.value,
                applied_version=2,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()

    rows = _rows(authed)
    [card] = rows["cards"]
    assert card["version"] == 2
    assert [(row["version"], row["answer"], row["origin"]) for row in rows["card_versions"]] == [
        (1, "A.", "archie"),
        (2, "B.", "chat_edit"),
    ]
    [proposal] = rows["edit_proposals"]
    assert proposal["id"] == str(proposal_id)
    assert (proposal["target_kind"], proposal["target_id"], proposal["status"], proposal["applied_version"]) == (
        "card",
        str(card_id),
        "applied",
        2,
    )
    assert proposal["after"] == {"question": "Q?", "answer": "B."}
    assert set(proposal) == {
        "id", "conversation_id", "message_id", "target_kind", "target_id", "title", "description", "base_version",
        "before", "after", "status", "applied_version", "created_at", "updated_at", "change_seq",
    }  # fmt: skip


def test_pull_carries_take_version_and_topic_primer_origins(live_stack: LiveStack) -> None:
    """A take version that leaves origin unset reads as owner; a chat-edited primer keeps its origin and instruction."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    take_id, topic_id = uuid.uuid4(), uuid.uuid4()

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Take(
                id=take_id,
                user_id=user_id,
                kind=models.TakeKind.OPINION.value,
                title="T",
                current_version=1,
                change_seq=changes.next_change_seq(),
            )
        )
        db.add(
            models.Topic(
                id=topic_id,
                user_id=user_id,
                domain="Macro",
                name=f"Rates {uuid.uuid4()}",
                origin=models.TopicOrigin.USER.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        db.add(
            models.TakeVersion(
                id=uuid.uuid4(),
                user_id=user_id,
                take_id=take_id,
                version=1,
                body="B",
                raw_body="B",
                cleaned=False,
                change_seq=changes.next_change_seq(),
            )
        )
        db.add(
            models.TopicPrimer(
                id=uuid.uuid4(),
                user_id=user_id,
                topic_id=topic_id,
                version=1,
                is_current=True,
                content={"markdown": "# Rates"},
                origin=models.VersionOrigin.CHAT_EDIT.value,
                instruction="Shorter",
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()

    rows = _rows(authed)
    assert rows["take_versions"][0]["origin"] == "owner"
    [primer] = rows["topic_primers"]
    assert (primer["origin"], primer["instruction"]) == ("chat_edit", "Shorter")
