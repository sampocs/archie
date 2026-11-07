"""Apply, undo and discard Ask's edit proposals, and restore versions, through the real API on seeded rows.

No model is called here: proposals are seeded as the Ask stream stores them (see test_ask_edit_e2e.py for that).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session, takes, versions
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

SUMMARY: dict[str, Any] = {
    "gist": "Index funds beat most stock pickers.",
    "key_ideas": [
        {"timestamp": None, "idea": "They track an index."},
        {"timestamp": None, "idea": "Low fees compound."},
    ],
    "numbers": [],
}
EDITED = {**SUMMARY, "key_ideas": SUMMARY["key_ideas"][:1]}


@dataclass(frozen=True)
class Seeded:
    """A whitelisted user's source with a summary, a card and a take, and a chat whose answer can hold proposals."""

    user_id: int
    source_id: uuid.UUID
    card_id: uuid.UUID
    take_id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID


def _user_id(authed: httpx.Client) -> int:
    return int(authed.get("/me").json()["user_id"])


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def _db(live_stack: LiveStack) -> sqlalchemy.orm.Session:
    return sqlalchemy.orm.Session(session.engine_for(live_stack.database_url))


def _seed(live_stack: LiveStack, *, user_id: int) -> Seeded:
    with _db(live_stack) as db:
        changes.lock_user_writes(db, user_id)
        url = f"https://example.com/{uuid.uuid4()}"
        source = models.Source(
            id=uuid.uuid4(), user_id=user_id, url=url, normalized_url=url, title="Index funds",
            kind=models.SourceKind.ARTICLE.value, state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(source)
        db.flush()
        pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY, content={"summary": SUMMARY, "cards": []},
            model="m", prompt_version="p",
        )  # fmt: skip
        card = models.Card(
            id=uuid.uuid4(), user_id=user_id, source_id=source.id, kind=models.CardKind.CONCEPT.value,
            question="What do fees do?", answer="They compound.", change_seq=changes.next_change_seq(),
        )  # fmt: skip
        take = models.Take(
            id=uuid.uuid4(), user_id=user_id, kind=models.TakeKind.OPINION.value, title="Rates", current_version=0,
            change_seq=changes.next_change_seq(),
        )  # fmt: skip
        conversation = models.Conversation(
            id=uuid.uuid4(), user_id=user_id, title="Edit", about_source_id=source.id, about_kind="source",
            change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add_all([card, take, conversation])
        db.flush()
        takes.add_version(
            db, take=take, version_id=uuid.uuid4(), body="Rates stay high.", raw_body="Rates stay high.",
            cleaned=False, origin=models.VersionOrigin.OWNER,
        )  # fmt: skip
        message = models.Message(
            id=uuid.uuid4(), user_id=user_id, conversation_id=conversation.id,
            role=models.MessageRole.ASSISTANT.value, text="Here's the edit.", segments=[], web_search=False,
            status=models.MessageStatus.COMPLETE.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(message)
        db.execute(sqlalchemy.delete(models.Job))
        db.commit()
        return Seeded(
            user_id=user_id, source_id=source.id, card_id=card.id, take_id=take.id,
            conversation_id=conversation.id, message_id=message.id,
        )  # fmt: skip


def _propose(
    live_stack: LiveStack,
    seeded: Seeded,
    *,
    kind: models.EditTarget,
    target_id: uuid.UUID,
    before: dict[str, Any],
    after: dict[str, Any],
    base_version: int = 1,
) -> str:
    """A stored proposal, as `_save` writes it at the end of an answer."""
    with _db(live_stack) as db:
        changes.lock_user_writes(db, seeded.user_id)
        proposal = models.EditProposal(
            id=uuid.uuid4(), user_id=seeded.user_id, conversation_id=seeded.conversation_id,
            message_id=seeded.message_id, target_kind=kind.value, target_id=target_id, title="Index funds",
            description="Drop the fees idea", base_version=base_version, before=before, after=after,
            status=models.EditStatus.PROPOSED.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(proposal)
        db.commit()
        return str(proposal.id)


def _current(live_stack: LiveStack, seeded: Seeded, kind: models.EditTarget, target_id: uuid.UUID) -> versions.Snapshot:
    with _db(live_stack) as db:
        target = versions.resolve(db, user_id=seeded.user_id, kind=kind, item_id=target_id)
        assert target is not None
        return versions.current(db, target=target)


def _jobs(live_stack: LiveStack) -> list[str]:
    with _db(live_stack) as db:
        return list(db.scalars(sqlalchemy.select(models.Job.kind).order_by(models.Job.id)))


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A whitelisted user's client."""
    return live_stack.authed(live_stack.sign_in(is_whitelisted=True))


def test_apply_writes_the_edit_as_the_next_version_and_repeats_harmlessly(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Version 2 is the edit (origin chat_edit, the description as instruction); a second Apply changes nothing."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )

    first = authed.post(f"/ask/edits/{proposal_id}/apply")
    again = authed.post(f"/ask/edits/{proposal_id}/apply")

    assert first.status_code == 200 and again.status_code == 200
    assert (first.json()["status"], first.json()["applied_version"]) == ("applied", 2)
    assert again.json()["change_seq"] == first.json()["change_seq"]
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id) == versions.Snapshot(
        version=2, content=EDITED
    )
    current = next(row for row in _rows(authed)["artifacts"] if row["is_current"])
    assert (current["origin"], current["instruction"]) == ("chat_edit", "Drop the fees idea")
    assert _jobs(live_stack) == [models.JobKind.EMBED.value]


def test_apply_goes_stale_when_the_target_changed_or_is_gone(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A proposal made against version 1 of a summary now at 2 is stale; so is one for a deleted source."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    behind = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    newer = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY,
        after={**SUMMARY, "gist": "Other."},
    )  # fmt: skip
    authed.post(f"/ask/edits/{newer}/apply")

    assert authed.post(f"/ask/edits/{behind}/apply").json()["status"] == "stale"
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id).version == 2

    card_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.CARD, target_id=seeded.card_id,
        before={"question": "What do fees do?", "answer": "They compound."},
        after={"question": "What do fees do?", "answer": "They compound over decades."},
    )  # fmt: skip
    with _db(live_stack) as db:
        db.get_one(models.Card, seeded.card_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    assert authed.post(f"/ask/edits/{card_edit}/apply").json()["status"] == "stale"


def test_undo_restores_the_version_the_edit_was_made_against(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Undo makes version 3 a copy of version 1 (origin archie) and marks the edit undone; again is harmless."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    authed.post(f"/ask/edits/{proposal_id}/apply")

    undone = authed.post(f"/ask/edits/{proposal_id}/undo")

    assert undone.status_code == 200 and undone.json()["status"] == "undone"
    assert authed.post(f"/ask/edits/{proposal_id}/undo").status_code == 200
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id) == versions.Snapshot(
        version=3, content=SUMMARY
    )
    assert next(row for row in _rows(authed)["artifacts"] if row["is_current"])["origin"] == "archie"


def test_undo_is_refused_once_something_else_changed_the_target(live_stack: LiveStack, authed: httpx.Client) -> None:
    """After a restore moved the summary past the edit, Undo answers 409 "changed since" and writes nothing."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    authed.post(f"/ask/edits/{proposal_id}/apply")
    authed.post("/versions/restore", json={"target_kind": "summary", "target_id": str(seeded.source_id), "version": 1})

    refused = authed.post(f"/ask/edits/{proposal_id}/undo")

    assert (refused.status_code, refused.json()["detail"]) == (409, "changed since")
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id).version == 3


def test_discard_is_final_and_apply_after_it_is_refused(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Discard marks the edit discarded (twice is harmless); Apply and Undo then answer 409 naming the status."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )

    assert authed.post(f"/ask/edits/{proposal_id}/discard").json()["status"] == "discarded"
    assert authed.post(f"/ask/edits/{proposal_id}/discard").status_code == 200
    applied = authed.post(f"/ask/edits/{proposal_id}/apply")
    assert (applied.status_code, applied.json()["detail"]) == (409, "edit is discarded")
    assert authed.post(f"/ask/edits/{proposal_id}/undo").status_code == 409
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id).version == 1


def test_card_and_take_edits_apply_with_their_side_effects(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A card edit pulls card versions 1 and 2; a take edit is take version 2 and queues its cards."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    card_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.CARD, target_id=seeded.card_id,
        before={"question": "What do fees do?", "answer": "They compound."},
        after={"question": "What do fees do?", "answer": "They compound over decades."},
    )  # fmt: skip
    take_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.TAKE, target_id=seeded.take_id,
        before={"markdown": "Rates stay high."}, after={"markdown": "Rates stay high into 2027."},
    )  # fmt: skip

    assert authed.post(f"/ask/edits/{card_edit}/apply").json()["applied_version"] == 2
    assert authed.post(f"/ask/edits/{take_edit}/apply").json()["applied_version"] == 2

    rows = _rows(authed)
    assert [(row["version"], row["origin"]) for row in rows["card_versions"]] == [(1, "archie"), (2, "chat_edit")]
    [card] = rows["cards"]
    assert (card["version"], card["answer"]) == (2, "They compound over decades.")
    take_versions = sorted(rows["take_versions"], key=lambda row: row["version"])
    assert [(row["version"], row["origin"], row["body"]) for row in take_versions] == [
        (1, "owner", "Rates stay high."),
        (2, "chat_edit", "Rates stay high into 2027."),
    ]
    assert models.JobKind.TAKE_CARDS.value in _jobs(live_stack)


def test_restore_copies_a_version_and_refuses_the_current_one_or_a_missing_one(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Restoring version 1 of an edited card makes version 3; restoring the current one is 409, version 9 is 404."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    card_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.CARD, target_id=seeded.card_id,
        before={"question": "What do fees do?", "answer": "They compound."},
        after={"question": "What do fees do?", "answer": "They compound over decades."},
    )  # fmt: skip
    authed.post(f"/ask/edits/{card_edit}/apply")
    body = {"target_kind": "card", "target_id": str(seeded.card_id)}

    restored = authed.post("/versions/restore", json={**body, "version": 1})
    current = authed.post("/versions/restore", json={**body, "version": 3})
    missing = authed.post("/versions/restore", json={**body, "version": 9})
    unknown = authed.post("/versions/restore", json={**body, "target_id": str(uuid.uuid4()), "version": 1})

    assert (restored.status_code, restored.json()) == (200, {"version": 3})
    assert (current.status_code, current.json()["detail"]) == (409, "already current")
    assert (missing.status_code, missing.json()["detail"]) == (404, "version not found")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "not found")
    [card] = _rows(authed)["cards"]
    assert (card["version"], card["answer"]) == (3, "They compound.")


def test_restore_copies_an_earlier_take_version(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Restoring version 1 of an edited take makes version 3 (origin restore) with version 1's body."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    take_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.TAKE, target_id=seeded.take_id,
        before={"markdown": "Rates stay high."}, after={"markdown": "Rates stay high into 2027."},
    )  # fmt: skip
    authed.post(f"/ask/edits/{take_edit}/apply")

    restored = authed.post(
        "/versions/restore", json={"target_kind": "take", "target_id": str(seeded.take_id), "version": 1}
    )

    assert (restored.status_code, restored.json()) == (200, {"version": 3})
    third = next(row for row in _rows(authed)["take_versions"] if row["version"] == 3)
    assert (third["origin"], third["body"]) == ("restore", "Rates stay high.")


def test_apply_on_a_superseded_proposal_is_refused(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A superseded edit answers 409 "edit is superseded" and writes nothing."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    with _db(live_stack) as db:
        changes.lock_user_writes(db, seeded.user_id)
        db.get_one(models.EditProposal, uuid.UUID(proposal_id)).status = models.EditStatus.SUPERSEDED.value
        db.commit()

    refused = authed.post(f"/ask/edits/{proposal_id}/apply")

    assert (refused.status_code, refused.json()["detail"]) == (409, "edit is superseded")
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id).version == 1


def test_another_users_proposal_and_a_deleted_chats_are_not_found(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Every edit route answers 404 for someone else's proposal, and for one whose chat was deleted."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger", is_whitelisted=True))

    for action in ("apply", "undo", "discard"):
        response = stranger.post(f"/ask/edits/{proposal_id}/{action}")
        assert (response.status_code, response.json()["detail"]) == (404, "edit not found")

    with _db(live_stack) as db:
        db.get_one(models.Conversation, seeded.conversation_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    for action in ("apply", "undo", "discard"):
        assert authed.post(f"/ask/edits/{proposal_id}/{action}").status_code == 404
