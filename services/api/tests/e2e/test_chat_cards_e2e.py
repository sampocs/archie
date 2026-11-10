"""Cards from a chat end to end: a recorded `Make cards` answer that proposes a card set, then Save and Discard on card
sets seeded through the test route (no model).

Anthropic is replayed from recorded real responses, round by round (`allow_playback_repeats=False`). Re-record a
cassette by deleting it and running `uv run pytest services/api/tests/e2e/test_chat_cards_e2e.py --record-mode=once
-m postgres` with TEST_DATABASE_URL set (a few cents of Sonnet 5.5; needs ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api.ask import context
from archie_db import changes, models, pipeline, session
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
QUESTION = "What's the difference between JWTs and session tokens?"
ANSWER = (
    "A session token is a random id: the server keeps the session in its own store and looks it up on every request, "
    "so logging out or revoking is instant. A JWT carries the claims itself, signed by the server, so any server can "
    "check it without a lookup, but it stays valid until it expires unless you keep a deny list."
)
TITLE = "JWTs vs session tokens"
CHEAT_SHEET = (
    "# JWTs vs session tokens\n\n"
    "A session token is a random id the server looks up; a JWT carries signed claims any server can check.\n\n"
    "| | Session token | JWT |\n|---|---|---|\n| Revoke | Instant | Wait for expiry |"
)
CARDS: list[dict[str, str]] = [
    {"kind": "concept", "question": "What does a session token hold?", "answer": "A random id the server looks up."},
    {"kind": "mechanism", "question": "How is a JWT checked?", "answer": "By verifying the server's signature."},
    {"kind": "concept", "question": "Why is revoking a JWT hard?", "answer": "It stays valid until it expires."},
]


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay (no OpenAI key: keyword search in the tool)."""
    recording.use_recording_api_key(request, monkeypatch)


@pytest.fixture
def owner(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a whitelisted user, who may ask."""
    return live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))


@contextlib.contextmanager
def _db(live_stack: LiveStack) -> Iterator[sqlalchemy.orm.Session]:
    """A session on its own engine, disposed afterwards so the test leaves no pooled connections open."""
    engine = session.engine_for(live_stack.database_url)
    try:
        with sqlalchemy.orm.Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def _seed(
    authed: httpx.Client,
    *,
    conversation_id: str | None = None,
    title: str = TITLE,
    cheat_sheet: str = CHEAT_SHEET,
    cards: list[dict[str, str]] = CARDS,
) -> dict[str, Any]:
    body = {"conversation_id": conversation_id, "title": title, "cheat_sheet": cheat_sheet, "cards": cards}
    response = authed.post("/test/card-sets", json=body)
    assert response.status_code == 200, response.text
    proposal: dict[str, Any] = response.json()
    return proposal


def _save(authed: httpx.Client, proposal_id: str, kept: list[int]) -> httpx.Response:
    return authed.post(f"/ask/card-sets/{proposal_id}/save", json={"kept": kept})


def _artifacts(live_stack: LiveStack, source_id: str) -> list[models.SourceArtifact]:
    with _db(live_stack) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.SourceArtifact)
                .where(models.SourceArtifact.source_id == uuid.UUID(source_id))
                .order_by(models.SourceArtifact.kind, models.SourceArtifact.version)
            )
        )


def _embed_jobs(live_stack: LiveStack) -> int:
    with _db(live_stack) as db:
        return len(db.scalars(sqlalchemy.select(models.Job).where(models.Job.kind == models.JobKind.EMBED.value)).all())


def _seed_chat(live_stack: LiveStack, *, user_id: int) -> uuid.UUID:
    """A chat with one finished exchange about JWTs; returns its id."""
    with _db(live_stack) as db:
        changes.lock_user_writes(db, user_id)
        conversation = models.Conversation(
            id=uuid.uuid4(), user_id=user_id, title=QUESTION, change_seq=changes.next_change_seq()
        )
        db.add(conversation)
        db.flush()
        for role, text in ((models.MessageRole.USER, QUESTION), (models.MessageRole.ASSISTANT, ANSWER)):
            db.add(
                models.Message(
                    id=uuid.uuid4(), user_id=user_id, conversation_id=conversation.id, role=role.value, text=text,
                    segments=None, web_search=False, status=models.MessageStatus.COMPLETE.value,
                    created_at=sqlalchemy.func.clock_timestamp(), change_seq=changes.next_change_seq(),
                )
            )  # fmt: skip
            db.flush()
        db.commit()
        return conversation.id


def _ask(authed: httpx.Client, conversation_id: uuid.UUID, text: str) -> list[tuple[str, dict[str, Any]]]:
    payload = {"user_message_id": str(uuid.uuid4()), "text": text, "web_search": False}
    path = f"/ask/conversations/{conversation_id}/messages"
    with authed.stream("POST", path, json=payload, timeout=180) as response:
        assert response.status_code == 200, response.read()
        raw = "".join(response.iter_text())
    events = []
    for chunk in raw.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_make_cards_proposes_one_card_set_streamed_as_the_row_the_phone_pulls(
    live_stack: LiveStack, owner: httpx.Client, request: pytest.FixtureRequest
) -> None:
    """`Make cards` after a JWT exchange: `drafting_cards`, then one `cards` event that is the stored row (its position
    aside), on the answer the stream ends with; nothing is saved to Library."""
    conversation_id = _seed_chat(live_stack, user_id=int(owner.get("/me").json()["user_id"]))

    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    with recorder.use_cassette("ask_make_cards.yaml", allow_playback_repeats=False):
        events = _ask(owner, conversation_id, "Make cards")

    names = [name for name, _ in events]
    assert names.index("drafting_cards") < names.index("cards") and names[-1] == "done"
    [event] = [data for name, data in events if name == "cards"]
    rows = _rows(owner)
    [row] = rows["card_set_proposals"]
    assert {**event, "change_seq": row["change_seq"]} == row
    assert event["change_seq"] == 0
    assert (row["status"], row["conversation_id"], row["message_id"]) == (
        "proposed",
        str(conversation_id),
        events[-1][1]["message_id"],
    )
    assert 3 <= len(row["cards"]) <= 7
    assert all(card["kind"] in {"concept", "mechanism", "number", "foundation"} for card in row["cards"])
    assert "jwt" in row["cheat_sheet"].lower()
    assert not any(source["kind"] == "chat" for source in rows["sources"])


def test_a_new_card_set_replaces_the_open_one_and_the_model_sees_both(
    live_stack: LiveStack, owner: httpx.Client
) -> None:
    """A second seed in the chat leaves only the newer set open; history names the replaced one and lists the open
    one's cards, so "change card 2" can build on it."""
    first = _seed(owner)
    second = _seed(owner, conversation_id=first["conversation_id"], cards=CARDS[:2])

    statuses = {row["id"]: row["status"] for row in _rows(owner)["card_set_proposals"]}
    assert statuses == {first["id"]: "replaced", second["id"]: "proposed"}

    with _db(live_stack) as db:
        turns = context.history(db, conversation_id=uuid.UUID(first["conversation_id"]))
    answers = [turn["content"] for turn in turns if turn["role"] == "assistant"]
    assert answers[1].endswith(f"[cards proposed: {TITLE} — replaced by a later proposal]")
    assert f"[cards proposed: {TITLE} — waiting for the owner to save it]" in answers[2]
    assert "2. (mechanism) Q: How is a JWT checked?" in answers[2] and CARDS[2]["question"] not in answers[2]


def test_the_seed_route_makes_a_chat_when_none_is_given(owner: httpx.Client) -> None:
    """A new chat holds an exchange about the title, then `Make cards` and the answer the set hangs on."""
    proposal = _seed(owner)

    rows = _rows(owner)
    [conversation] = rows["conversations"]
    assert conversation["id"] == proposal["conversation_id"]
    messages = sorted(rows["messages"], key=lambda message: message["created_at"])
    assert [message["text"] for message in messages[1:3]] == [
        "A session token is a random id the server looks up; a JWT carries signed claims any server can check.",
        "Make cards",
    ]
    assert messages[-1]["id"] == proposal["message_id"]
    assert (proposal["status"], proposal["cards"], proposal["kept"]) == ("proposed", CARDS, None)


def test_save_creates_the_chat_item_with_three_artifacts_and_only_the_kept_cards(
    live_stack: LiveStack, owner: httpx.Client
) -> None:
    """The item is a ready inbox `chat` source tied to the chat; primer = cheat sheet, summary = its gist, text = the
    transcript; the kept cards belong to it and start new; it is queued for search and the set is saved."""
    proposal = _seed(owner)

    response = _save(owner, proposal["id"], [2, 0])

    assert response.status_code == 200, response.text
    saved = response.json()
    assert (saved["status"], saved["kept"]) == ("saved", [0, 2])
    rows = _rows(owner)
    [item] = rows["sources"]
    assert saved["saved_source_id"] == item["id"]
    assert (item["kind"], item["title"], item["state"], item["processing"], item["chat_conversation_id"]) == (
        "chat",
        TITLE,
        "inbox",
        "ready",
        proposal["conversation_id"],
    )
    assert item["queue_position"] is None

    contents = {artifact.kind: artifact.content for artifact in _artifacts(live_stack, item["id"])}
    assert contents["primer"] == {"markdown": CHEAT_SHEET}
    assert contents["summary"] == {
        "summary": {
            "gist": "A session token is a random id the server looks up; a JWT carries signed claims any server can "
            "check.",
            "key_ideas": [],
            "numbers": [],
        }
    }
    assert contents["text"]["text"].startswith(f"**You:** What should I know about {TITLE}?\n\n**Archie:** ")
    assert contents["text"]["text"].endswith(f"**You:** Make cards\n\n**Archie:** Here are cards on {TITLE}.")
    assert _embed_jobs(live_stack) == 1

    cards = sorted(rows["cards"], key=lambda card: card["question"])
    assert [(card["question"], card["kind"], card["fsrs_state"]) for card in cards] == [
        (CARDS[0]["question"], "concept", "new"),
        (CARDS[2]["question"], "concept", "new"),
    ]
    assert all(
        (card["source_id"], card["message_id"], card["conversation_id"]) == (item["id"], proposal["message_id"], None)
        for card in cards
    )


def test_see_original_serves_the_chat_items_transcript(live_stack: LiveStack, owner: httpx.Client) -> None:
    """`/sources/{id}/text` returns the item's current transcript to its owner, and 404 to anyone else."""
    item_id = _save(owner, _seed(owner)["id"], [0]).json()["saved_source_id"]
    [text] = [artifact for artifact in _artifacts(live_stack, item_id) if artifact.kind == "text"]

    response = owner.get(f"/sources/{item_id}/text")

    assert response.status_code == 200
    assert response.json() == {"text": text.content["text"]}
    assert response.json()["text"].endswith(f"**You:** Make cards\n\n**Archie:** Here are cards on {TITLE}.")
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger"))
    assert stranger.get(f"/sources/{item_id}/text").status_code == 404


def test_a_later_save_in_the_chat_updates_the_same_item(live_stack: LiveStack, owner: httpx.Client) -> None:
    """The second set retitles the item and adds new current versions; an identical kept card stays as it was, a
    changed one is added and an unkept one retired."""
    first = _seed(owner)
    item_id = _save(owner, first["id"], [0, 1]).json()["saved_source_id"]
    kept_before = {card["question"]: card["id"] for card in _rows(owner)["cards"]}
    changed = {**CARDS[1], "answer": "By checking its signature with the server's key."}
    second = _seed(owner, conversation_id=first["conversation_id"], title="Session tokens", cards=[CARDS[0], changed])

    response = _save(owner, second["id"], [0, 1])

    assert response.status_code == 200 and response.json()["saved_source_id"] == item_id
    rows = _rows(owner)
    [item] = rows["sources"]
    assert (item["id"], item["title"]) == (item_id, "Session tokens")
    current = [artifact for artifact in _artifacts(live_stack, item_id) if artifact.is_current]
    assert sorted((artifact.kind, artifact.version) for artifact in current) == [
        ("primer", 2),
        ("summary", 2),
        ("text", 2),
    ]

    live = {card["answer"]: card for card in rows["cards"] if card["deleted_at"] is None}
    assert set(live) == {CARDS[0]["answer"], changed["answer"]}
    assert live[CARDS[0]["answer"]]["id"] == kept_before[CARDS[0]["question"]]
    [retired] = [card for card in rows["cards"] if card["deleted_at"] is not None]
    assert retired["answer"] == CARDS[1]["answer"]


def test_a_later_save_replaces_a_primer_the_owner_edited(live_stack: LiveStack, owner: httpx.Client) -> None:
    """Saving again is the owner choosing the new set, so its cheat sheet becomes the current primer even over their own
    chat edit, and it is labelled `archie`, not as one of their edits."""
    first = _seed(owner)
    item_id = _save(owner, first["id"], [0]).json()["saved_source_id"]
    with _db(live_stack) as db:
        changes.lock_user_writes(db, int(owner.get("/me").json()["user_id"]))
        item = db.get(models.Source, uuid.UUID(item_id))
        assert item is not None
        pipeline.write_artifact(
            db,
            source=item,
            kind=models.ArtifactKind.PRIMER,
            content={"markdown": "# My own edit"},
            model=None,
            prompt_version=None,
            origin=models.VersionOrigin.CHAT_EDIT,
        )
        db.commit()
    new_sheet = "# Session tokens\n\nA second cheat sheet."
    second = _seed(owner, conversation_id=first["conversation_id"], cheat_sheet=new_sheet)

    assert _save(owner, second["id"], [0]).status_code == 200

    [primer] = [a for a in _artifacts(live_stack, item_id) if a.kind == "primer" and a.is_current]
    assert (primer.content["markdown"], primer.origin) == (new_sheet, models.VersionOrigin.ARCHIE.value)


def test_a_later_save_never_retires_a_reviewed_card(live_stack: LiveStack, owner: httpx.Client) -> None:
    """A card the owner has reviewed keeps its progress even when the new set drops or rewords it; an unreviewed
    unkept card is still retired and the new cards are added."""
    first = _seed(owner)
    _save(owner, first["id"], [0, 1])
    saved = {card["question"]: card["id"] for card in _rows(owner)["cards"]}
    reviewed_id, unreviewed_id = saved[CARDS[0]["question"]], saved[CARDS[1]["question"]]
    with _db(live_stack) as db:
        changes.lock_user_writes(db, int(owner.get("/me").json()["user_id"]))
        reviewed = db.get(models.Card, uuid.UUID(reviewed_id))
        assert reviewed is not None
        reviewed.reps = 1
        reviewed.last_review_at = sqlalchemy.func.now()
        reviewed.fsrs_state = models.FsrsState.REVIEW.value
        reviewed.change_seq = changes.next_change_seq()
        db.commit()
    reworded = {**CARDS[0], "answer": "An opaque id the server looks up on each request."}
    second = _seed(owner, conversation_id=first["conversation_id"], title="Session tokens", cards=[CARDS[2], reworded])

    assert _save(owner, second["id"], [0, 1]).status_code == 200

    cards = {card["id"]: card for card in _rows(owner)["cards"]}
    assert cards[reviewed_id]["deleted_at"] is None and cards[reviewed_id]["reps"] == 1
    assert cards[unreviewed_id]["deleted_at"] is not None
    live_answers = {card["answer"] for card in cards.values() if card["deleted_at"] is None}
    assert live_answers == {CARDS[0]["answer"], CARDS[2]["answer"], reworded["answer"]}


def test_saving_after_the_item_was_deleted_makes_a_new_one(owner: httpx.Client) -> None:
    """The deleted item stays deleted and lets go of the chat; the new set becomes a fresh item."""
    first = _seed(owner)
    old_id = _save(owner, first["id"], [0]).json()["saved_source_id"]
    deleted = owner.post("/sync/push", json={"actions": [_action("delete_source", {"id": old_id})]})
    assert deleted.json()["results"][0]["result"] == "applied"
    second = _seed(owner, conversation_id=first["conversation_id"])

    new_id = _save(owner, second["id"], [0]).json()["saved_source_id"]

    sources = {row["id"]: row for row in _rows(owner)["sources"]}
    assert new_id != old_id
    assert sources[old_id]["deleted_at"] is not None and sources[old_id]["chat_conversation_id"] is None
    assert sources[new_id]["chat_conversation_id"] == first["conversation_id"]


def test_discard_and_the_refusals(live_stack: LiveStack, owner: httpx.Client) -> None:
    """Discard closes an open set; a decided set is 409 for both routes; bad kept lists are 422; another user's set or
    one in a deleted chat is 404."""
    discarded = _seed(owner)
    response = owner.post(f"/ask/card-sets/{discarded['id']}/discard")
    assert (response.status_code, response.json()["status"]) == (200, "discarded")
    assert _save(owner, discarded["id"], [0]).status_code == 409
    assert owner.post(f"/ask/card-sets/{discarded['id']}/discard").status_code == 409

    replaced = _seed(owner, conversation_id=discarded["conversation_id"])
    open_set = _seed(owner, conversation_id=discarded["conversation_id"])
    assert _save(owner, replaced["id"], [0]).status_code == 409
    for kept in ([], [0, 0], [3], [-1]):
        assert _save(owner, open_set["id"], kept).status_code == 422
    assert _save(owner, open_set["id"], [1]).status_code == 200
    assert owner.post(f"/ask/card-sets/{open_set['id']}/discard").status_code == 409

    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger"))
    theirs = _seed(stranger)
    assert _save(owner, theirs["id"], [0]).status_code == 404
    assert owner.post(f"/ask/card-sets/{uuid.uuid4()}/discard").status_code == 404
    stranger.post("/sync/push", json={"actions": [_action("delete_conversation", {"id": theirs["conversation_id"]})]})
    assert _save(stranger, theirs["id"], [0]).status_code == 404
    assert [row["status"] for row in _rows(stranger)["card_set_proposals"]] == ["proposed"]


_QUEUEING_ACTIONS = [
    ("go_deeper", {}),
    ("read_later", {}),
    ("finish_source", {}),
    ("queue_primer", {"queued": True}),
    ("snooze", {"target": "source", "until": "2099-01-01T00:00:00+00:00"}),
    ("set_queue_position", {"position": 1.0, "target": "source"}),
    ("set_queue_position", {"position": 1.0, "target": "source_primer"}),
]


@pytest.mark.parametrize(("action_type", "extra"), _QUEUEING_ACTIONS)
def test_a_chat_item_never_enters_the_queue(owner: httpx.Client, action_type: str, extra: dict[str, Any]) -> None:
    """Chat items are saved from Ask, not scheduled: every queueing action is refused and changes nothing."""
    item_id = _save(owner, _seed(owner)["id"], [0]).json()["saved_source_id"]
    before = _rows(owner)["sources"]

    results = owner.post("/sync/push", json={"actions": [_action(action_type, {"id": item_id, **extra})]}).json()

    assert results["results"][0]["result"] == "rejected"
    assert _rows(owner)["sources"] == before


def test_cards_on_for_a_chat_item_queues_no_analysis(live_stack: LiveStack, owner: httpx.Client) -> None:
    """A chat item has text but is never analyzed: cards off then on only flips the flag."""
    item_id = _save(owner, _seed(owner)["id"], [0]).json()["saved_source_id"]
    actions = [_action("set_cards_off", {"id": item_id, "off": off}) for off in (True, False)]

    results = owner.post("/sync/push", json={"actions": actions}).json()["results"]

    assert [result["result"] for result in results] == ["applied", "applied"]
    [item] = _rows(owner)["sources"]
    assert (item["cards_off"], item["processing"]) == (False, "ready")
    with _db(live_stack) as db:
        kinds = set(db.scalars(sqlalchemy.select(models.Job.kind)))
    assert kinds == {models.JobKind.EMBED.value}


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}
