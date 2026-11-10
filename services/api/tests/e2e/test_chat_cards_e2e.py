"""Cards from a chat end to end: recorded `Make cards` answers that propose a card set (in a chat, and in a chat about
a note), then Save and Discard on card sets seeded through the test route (no model), and the Keep ticks a question
carries to the model (the answer itself skipped).

Anthropic is replayed from recorded real responses, round by round (`allow_playback_repeats=False`). Re-record a
cassette by deleting it and running `uv run pytest services/api/tests/e2e/test_chat_cards_e2e.py --record-mode=once
-m postgres` with TEST_DATABASE_URL set (a few cents of Sonnet 5.5; needs ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import uuid
from collections.abc import AsyncGenerator, Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api.ask import answer, context
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
    about_note_id: str | None = None,
) -> dict[str, Any]:
    response = _seed_response(
        authed,
        conversation_id=conversation_id,
        title=title,
        cheat_sheet=cheat_sheet,
        cards=cards,
        about_note_id=about_note_id,
    )
    assert response.status_code == 200, response.text
    proposal: dict[str, Any] = response.json()
    return proposal


def _seed_response(
    authed: httpx.Client,
    *,
    conversation_id: str | None = None,
    title: str = TITLE,
    cheat_sheet: str = CHEAT_SHEET,
    cards: list[dict[str, str]] = CARDS,
    about_note_id: str | None = None,
) -> httpx.Response:
    body = {
        "conversation_id": conversation_id,
        "title": title,
        "cheat_sheet": cheat_sheet,
        "cards": cards,
        "about_note_id": about_note_id,
    }
    return authed.post("/test/card-sets", json=body)


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


def _ask(
    authed: httpx.Client,
    conversation_id: uuid.UUID,
    text: str,
    *,
    about: dict[str, str] | None = None,
    card_set_choice: dict[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    payload = {
        "user_message_id": str(uuid.uuid4()),
        "text": text,
        "web_search": False,
        "about": about,
        "card_set_choice": card_set_choice,
    }
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


@pytest.fixture
def asked_turns(monkeypatch: pytest.MonkeyPatch) -> list[list[dict[str, Any]]]:
    """The turns each question would send the model, as the route built them; the answer is skipped (no model call)."""
    turns: list[list[dict[str, Any]]] = []

    async def skipped_answer(engine: sqlalchemy.Engine, request: answer.AnswerRequest) -> AsyncGenerator[str, None]:
        turns.append(request.messages)
        yield ": answer skipped\n\n"

    monkeypatch.setattr(answer, "stream_async", skipped_answer)
    return turns


def _question_segments(authed: httpx.Client, text: str) -> list[Any]:
    """The stored `segments` of every question with this text, oldest first."""
    messages = sorted(_rows(authed)["messages"], key=lambda message: message["created_at"])
    return [message["segments"] for message in messages if message["role"] == "user" and message["text"] == text]


def _add_answer(live_stack: LiveStack, *, user_id: int, conversation_id: uuid.UUID, text: str) -> None:
    """A finished answer to the chat's last question, as a real stream would save it."""
    with _db(live_stack) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Message(
                id=uuid.uuid4(), user_id=user_id, conversation_id=conversation_id,
                role=models.MessageRole.ASSISTANT.value, text=text, segments=None, web_search=False,
                status=models.MessageStatus.COMPLETE.value, created_at=sqlalchemy.func.clock_timestamp(),
                change_seq=changes.next_change_seq(),
            )
        )  # fmt: skip
        db.commit()


def test_keep_ticks_sent_with_a_question_reach_the_model_and_stay_in_its_history(
    live_stack: LiveStack, owner: httpx.Client, asked_turns: list[list[dict[str, Any]]]
) -> None:
    """Cards 1 and 3 kept of the open set: the turn opens with the line naming the dropped card's question, the
    question stores the ticks for the phone, and later turns rebuild the same line, even once the set is replaced."""
    proposal = _seed(owner)
    conversation_id = uuid.UUID(proposal["conversation_id"])
    text = "Make the first one shorter"

    _ask(owner, conversation_id, text, card_set_choice={"proposal_id": proposal["id"], "kept": [2, 0]})

    line = f"The owner kept cards 1 and 3 of the proposed set and dropped 2 (“{CARDS[1]['question']}”)."
    asked = {"role": "user", "content": f"{line}\n\n{text}"}
    assert asked_turns[-1][-1] == asked
    choice = {"proposal_id": proposal["id"], "kept": [0, 2], "card_count": 3}
    assert _question_segments(owner, text) == [[{"card_set_choice": choice}]]

    user_id = int(owner.get("/me").json()["user_id"])
    _add_answer(live_stack, user_id=user_id, conversation_id=conversation_id, text="Here is the shorter set.")
    _seed(owner, conversation_id=proposal["conversation_id"], cards=[CARDS[0], CARDS[2]])
    with _db(live_stack) as db:
        turns = context.history(db, conversation_id=conversation_id)
    assert asked in turns
    assert turns[turns.index(asked) + 1] == {"role": "assistant", "content": "Here is the shorter set."}


def test_keep_ticks_that_dont_fit_the_open_set_are_ignored_and_the_question_still_goes(
    live_stack: LiveStack, owner: httpx.Client, asked_turns: list[list[dict[str, Any]]]
) -> None:
    """A replaced, discarded, another chat's or another user's set, an unknown id, a repeated or out-of-range index and
    every card kept all leave the question as typed, with nothing stored; dropping every card is a choice."""
    replaced = _seed(owner)
    in_chat = replaced["conversation_id"]
    discarded = _seed(owner, conversation_id=in_chat)
    assert owner.post(f"/ask/card-sets/{discarded['id']}/discard").status_code == 200
    open_elsewhere = _seed(owner)
    theirs = _seed(live_stack.authed(live_stack.sign_in(apple_sub="stranger")))

    ignored = [
        (in_chat, replaced["id"], [0]),
        (in_chat, discarded["id"], [0]),
        (in_chat, open_elsewhere["id"], [0]),
        (in_chat, theirs["id"], [0]),
        (in_chat, str(uuid.uuid4()), [0]),
        (open_elsewhere["conversation_id"], open_elsewhere["id"], [0, 0]),
        (open_elsewhere["conversation_id"], open_elsewhere["id"], [3]),
        (open_elsewhere["conversation_id"], open_elsewhere["id"], [-1]),
        (open_elsewhere["conversation_id"], open_elsewhere["id"], [0, 1, 2]),
    ]
    for number, (conversation_id, proposal_id, kept) in enumerate(ignored):
        text = f"Ignored ticks {number}"
        choice = {"proposal_id": proposal_id, "kept": kept}
        _ask(owner, uuid.UUID(conversation_id), text, card_set_choice=choice)
        assert asked_turns[-1][-1] == {"role": "user", "content": text}, (proposal_id, kept)
        assert _question_segments(owner, text) == [None], (proposal_id, kept)

    _ask(owner, uuid.UUID(open_elsewhere["conversation_id"]), "None of these", card_set_choice={
        "proposal_id": open_elsewhere["id"], "kept": [],
    })  # fmt: skip
    dropped = ", ".join(f"{number} (“{card['question']}”)" for number, card in enumerate(CARDS[:2], start=1))
    line = (
        f"The owner kept none of the cards of the proposed set and dropped {dropped} and 3 (“{CARDS[2]['question']}”)."
    )
    assert asked_turns[-1][-1] == {"role": "user", "content": f"{line}\n\nNone of these"}


def test_keep_ticks_must_be_integers(owner: httpx.Client) -> None:
    """A boolean is not an index: `kept: [true]` is refused rather than read as card 2."""
    proposal = _seed(owner)
    payload = {
        "user_message_id": str(uuid.uuid4()),
        "text": "Bad ticks",
        "web_search": False,
        "card_set_choice": {"proposal_id": proposal["id"], "kept": [True]},
    }

    response = owner.post(f"/ask/conversations/{proposal['conversation_id']}/messages", json=payload)

    assert response.status_code == 422


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


NOTE_TITLE = "Liquid staking"
NOTE_WRITE_UP = {
    "domain": "Crypto",
    "summary": {
        "gist": "Liquid staking lets you stake ETH and still hold a tradable receipt token (an LST).",
        "key_ideas": [
            {"timestamp": None, "idea": "You stake with a provider such as Lido and get stETH back one for one."},
            {"timestamp": None, "idea": "The LST earns staking rewards while you use it as collateral elsewhere."},
            {"timestamp": None, "idea": "Direct stake waits in the exit queue to withdraw; an LST sells at once."},
        ],
        "numbers": [],
    },
    "sources": [{"url": "https://example.com/lido", "title": "Lido docs"}],
}


def _seed_note(authed: httpx.Client, *, mark: str = "cards") -> str:
    """An imported note with a seeded write-up; returns its id."""
    note = {
        "bear_id": f"NOTE-{uuid.uuid4()}",
        "title": NOTE_TITLE,
        "markdown": f"# {NOTE_TITLE}\n\n- Stake with a provider, get an **LST** back\n",
        "tags": ["crypto"],
        "created_at": "2024-01-20T10:00:00+00:00",
        "edited_at": "2024-02-13T09:00:00+00:00",
        "mark": mark,
    }
    response = authed.post("/notes/import", json={"notes": [note]})
    response.raise_for_status()
    note_id: str = response.json()["results"][0]["id"]
    authed.post(f"/test/notes/{note_id}/write-up", json=NOTE_WRITE_UP).raise_for_status()
    return note_id


def _source_artifacts(live_stack: LiveStack) -> list[tuple[str, str, int]]:
    with _db(live_stack) as db:
        rows = db.execute(
            sqlalchemy.select(
                models.SourceArtifact.source_id, models.SourceArtifact.kind, models.SourceArtifact.version
            ).order_by(models.SourceArtifact.source_id, models.SourceArtifact.kind, models.SourceArtifact.version)
        ).all()
    return [(str(source_id), kind, version) for source_id, kind, version in rows]


def test_make_cards_about_a_note_proposes_its_cards_without_a_cheat_sheet(
    live_stack: LiveStack, owner: httpx.Client, request: pytest.FixtureRequest
) -> None:
    """`Make cards` in a new chat about a note: one set titled after the note, no cheat sheet, 3 to 5 cards of the
    note's kinds; nothing is saved."""
    note_id = _seed_note(owner)

    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    with recorder.use_cassette("ask_make_note_cards.yaml", allow_playback_repeats=False):
        events = _ask(owner, uuid.uuid4(), "Make cards", about={"kind": "source", "id": note_id})

    [event] = [data for name, data in events if name == "cards"]
    assert events[-1][0] == "done"
    assert (event["title"], event["cheat_sheet"]) == (NOTE_TITLE, "")
    assert 3 <= len(event["cards"]) <= 5
    assert all(card["kind"] in {"concept", "mechanism", "number"} for card in event["cards"])
    rows = _rows(owner)
    assert [row["id"] for row in rows["card_set_proposals"]] == [event["id"]]
    assert not rows["cards"]


def test_saving_a_notes_set_puts_the_kept_cards_on_the_note_and_writes_nothing_else(
    live_stack: LiveStack, owner: httpx.Client
) -> None:
    """No chat item, no new artifacts and no search job: the kept cards belong to the note, and the set names it as
    where it was saved."""
    note_id = _seed_note(owner)
    proposal = _seed(owner, title=NOTE_TITLE, cheat_sheet="", about_note_id=note_id)
    artifacts_before, embeds_before = _source_artifacts(live_stack), _embed_jobs(live_stack)

    response = _save(owner, proposal["id"], [2, 0])

    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["saved_source_id"]) == ("saved", note_id)
    rows = _rows(owner)
    assert [source["id"] for source in rows["sources"]] == [note_id]
    assert _source_artifacts(live_stack) == artifacts_before
    assert _embed_jobs(live_stack) == embeds_before
    cards = sorted(rows["cards"], key=lambda card: card["question"])
    assert [(card["question"], card["source_id"], card["message_id"]) for card in cards] == [
        (CARDS[0]["question"], note_id, proposal["message_id"]),
        (CARDS[2]["question"], note_id, proposal["message_id"]),
    ]


def test_saving_a_notes_set_again_keeps_reviewed_cards_and_turns_cards_on(
    live_stack: LiveStack, owner: httpx.Client
) -> None:
    """The second set follows the chat rules on the note: an identical card stays, a reviewed dropped one stays, an
    unreviewed dropped one is retired, a new one is added; and a note whose cards were off has them on again."""
    note_id = _seed_note(owner, mark="import")
    first = _seed(owner, title=NOTE_TITLE, cheat_sheet="", about_note_id=note_id)
    _save(owner, first["id"], [0, 1, 2])
    saved = {card["question"]: card["id"] for card in _rows(owner)["cards"]}
    with _db(live_stack) as db:
        changes.lock_user_writes(db, int(owner.get("/me").json()["user_id"]))
        reviewed = db.get_one(models.Card, uuid.UUID(saved[CARDS[1]["question"]]))
        reviewed.reps = 1
        reviewed.last_review_at = sqlalchemy.func.now()
        reviewed.change_seq = changes.next_change_seq()
        db.commit()
    added = {"kind": "number", "question": "How much stETH does 1 ETH get?", "answer": "One stETH."}
    second = _seed(
        owner, conversation_id=first["conversation_id"], title=NOTE_TITLE, cheat_sheet="", cards=[CARDS[0], added]
    )

    assert _save(owner, second["id"], [0, 1]).json()["saved_source_id"] == note_id

    rows = _rows(owner)
    cards = {card["question"]: card for card in rows["cards"]}
    assert cards[CARDS[0]["question"]]["id"] == saved[CARDS[0]["question"]]
    assert cards[CARDS[1]["question"]]["deleted_at"] is None
    assert cards[CARDS[2]["question"]]["deleted_at"] is not None
    assert cards[added["question"]]["deleted_at"] is None
    [note] = rows["sources"]
    assert (note["id"], note["cards_off"]) == (note_id, False)


def test_saving_in_one_note_chat_leaves_the_worker_cards_and_other_chats_cards_live(
    live_stack: LiveStack, owner: httpx.Client
) -> None:
    """A note chat's Save retires only never-reviewed cards saved from that chat, not the worker's or another chat's."""
    note_id = _seed_note(owner)
    user_id = int(owner.get("/me").json()["user_id"])
    with _db(live_stack) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=user_id,
                source_id=uuid.UUID(note_id),
                kind=models.CardKind.CONCEPT.value,
                question="A worker question?",
                answer="A worker answer.",
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    first = _seed(owner, title=NOTE_TITLE, cheat_sheet="", about_note_id=note_id)
    _save(owner, first["id"], [0, 1, 2])
    added = {"kind": "number", "question": "How much stETH does 1 ETH get?", "answer": "One stETH."}
    second = _seed(owner, title=NOTE_TITLE, cheat_sheet="", cards=[added], about_note_id=note_id)
    assert second["conversation_id"] != first["conversation_id"]

    assert _save(owner, second["id"], [0]).status_code == 200

    live = {card["question"] for card in _rows(owner)["cards"] if card["deleted_at"] is None}
    assert live == {"A worker question?", added["question"], *(card["question"] for card in CARDS)}


def test_a_notes_set_refusals(live_stack: LiveStack, owner: httpx.Client) -> None:
    """An empty cheat sheet is refused outside a note's chat; a seed about another kind of item is 404; and Save once
    the note is deleted is 404 and leaves the set open."""
    assert _seed_response(owner, cheat_sheet="").status_code == 422
    chat_item_id = _save(owner, _seed(owner)["id"], [0]).json()["saved_source_id"]
    assert _seed_response(owner, cheat_sheet="", about_note_id=chat_item_id).status_code == 404

    note_id = _seed_note(owner)
    proposal = _seed(owner, title=NOTE_TITLE, cheat_sheet="", about_note_id=note_id)
    deleted = owner.post("/sync/push", json={"actions": [_action("delete_source", {"id": note_id})]})
    assert deleted.json()["results"][0]["result"] == "applied"

    response = _save(owner, proposal["id"], [0])

    assert (response.status_code, response.json()["detail"]) == (404, "note not found")
    statuses = {row["id"]: row["status"] for row in _rows(owner)["card_set_proposals"]}
    assert statuses[proposal["id"]] == "proposed"
    assert not [card for card in _rows(owner)["cards"] if card["source_id"] == note_id]


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}
