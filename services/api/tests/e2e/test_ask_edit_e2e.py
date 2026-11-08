"""Ask's editing tools end to end: recorded answers that propose a summary edit and a card edit, plus the tools'
validation and supersede rules on seeded rows (no model).

Anthropic is replayed from recorded real responses, round by round (`allow_playback_repeats=False`). Re-record a
cassette by deleting it and running `uv run pytest services/api/tests/e2e/test_ask_edit_e2e.py --record-mode=once -m
postgres` with TEST_DATABASE_URL set (a few cents of Sonnet 5.5; needs ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api.ask import edit_tools
from archie_db import changes, models, pipeline, session, versions
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
SUMMARY: dict[str, Any] = {
    "gist": "Index funds beat most stock pickers because they cost less and don't try to time the market.",
    "key_ideas": [
        {"timestamp": None, "idea": "An index fund buys every stock in an index instead of picking winners."},
        {"timestamp": None, "idea": "Low fees compound into large differences over decades."},
        {"timestamp": None, "idea": "Most active managers trail their index after fees."},
    ],
    "numbers": [{"timestamp": None, "fact": "~90% of US large-cap funds trailed the S&P 500 over 15 years."}],
}
PASSAGE = "Index funds buy every stock in the index. Their low fees compound into large differences over decades."
FEES_QUESTION = "What do low fees do over decades?"
FEES_ANSWER = "They compound into large differences."
# Fixed ids: the recorded tool calls name them, so a replay must seed the same ones (every test empties the tables).
SOURCE_ID = uuid.UUID("5f0c2a4e-1d3b-4c6a-9e8f-0a1b2c3d4e5f")
CARD_ID = uuid.UUID("c4a1d2e3-f405-4617-8a9b-0c1d2e3f4a5b")


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay (no OpenAI key: keyword search in the tool)."""
    recording.use_recording_api_key(request, monkeypatch)


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=False)


def _user_id(authed: httpx.Client) -> int:
    return int(authed.get("/me").json()["user_id"])


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def _ask(
    authed: httpx.Client, conversation_id: str, text: str, about: dict[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    payload = {"user_message_id": str(uuid.uuid4()), "text": text, "web_search": False, "about": about}
    with authed.stream("POST", f"/ask/conversations/{conversation_id}/messages", json=payload, timeout=180) as response:
        assert response.status_code == 200, response.read()
        raw = "".join(response.iter_text())
    events = []
    for chunk in raw.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _seed_source(live_stack: LiveStack, *, user_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    """An index-funds article with its summary, one indexed passage and one card; returns the source and card ids."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        url = "https://example.com/index-funds"
        source = models.Source(
            id=SOURCE_ID, user_id=user_id, url=url, normalized_url=url, title="How index funds work",
            kind=models.SourceKind.ARTICLE.value, state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(source)
        db.flush()
        pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY,
            content={"summary": SUMMARY, "domain": "Finance", "cards": []}, model="m", prompt_version="p",
        )  # fmt: skip
        db.add(
            models.Chunk(
                user_id=user_id, source_id=source.id, owner_kind=models.ChunkOwner.SOURCE_TEXT.value, chunk_index=0,
                text=PASSAGE,
            )
        )  # fmt: skip
        card = models.Card(
            id=CARD_ID, user_id=user_id, source_id=source.id, kind=models.CardKind.MECHANISM.value,
            question=FEES_QUESTION, answer=FEES_ANSWER, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(card)
        db.commit()
        ids = (source.id, card.id)
    engine.dispose()
    return ids


def _seed_chat(live_stack: LiveStack, *, user_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A chat with one stored answer; returns the chat and answer ids."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        conversation = models.Conversation(
            id=uuid.uuid4(), user_id=user_id, title="Edit", change_seq=changes.next_change_seq()
        )
        db.add(conversation)
        db.flush()
        message = models.Message(
            id=uuid.uuid4(), user_id=user_id, conversation_id=conversation.id,
            role=models.MessageRole.ASSISTANT.value, text="Done.", segments=[], web_search=False,
            status=models.MessageStatus.COMPLETE.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(message)
        db.commit()
        ids = (conversation.id, message.id)
    engine.dispose()
    return ids


def test_text_edits_must_match_and_a_new_proposal_supersedes_the_pending_one(
    live_stack: LiveStack,
) -> None:
    """A missing find is an error result; a card proposal stored twice leaves only the newer one proposed; read_item
    then shows the pending edit."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    _, card_id = _seed_source(live_stack, user_id=user_id)
    conversation_id, message_id = _seed_chat(live_stack, user_id=user_id)
    engine = session.engine_for(live_stack.database_url)
    context = edit_tools.ToolContext(user_id=user_id, conversation_id=conversation_id)

    unknown = edit_tools.run(
        engine, context=context, tool_use_id="t1", name=edit_tools.PROPOSE_TEXT_EDIT,
        tool_input={
            "kind": "take", "id": str(uuid.uuid4()), "description": "x", "replacements": [{"find": "a", "replace": "b"}]
        },
    )  # fmt: skip
    same = edit_tools.run(
        engine, context=context, tool_use_id="t2", name=edit_tools.PROPOSE_CARD_EDIT,
        tool_input={"card_id": str(card_id), "description": "x", "question": FEES_QUESTION, "answer": FEES_ANSWER},
    )  # fmt: skip
    assert unknown.result["is_error"] and "that the owner can edit" in unknown.result["content"]
    assert same.result["is_error"] and "exactly what it says now" in same.result["content"]

    proposals = [
        edit_tools.run(
            engine, context=context, tool_use_id=f"p{index}", name=edit_tools.PROPOSE_CARD_EDIT,
            tool_input={"card_id": str(card_id), "description": "Longer", "question": FEES_QUESTION, "answer": answer},
        ).proposal
        for index, answer in enumerate(["They compound.", "They compound over decades."])
    ]  # fmt: skip
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        edit_tools.save_proposals(
            db, user_id=user_id, conversation_id=conversation_id, message_id=message_id,
            proposals=[proposal for proposal in proposals if proposal is not None],
        )  # fmt: skip
        db.commit()

    rows = sorted(_rows(authed)["edit_proposals"], key=lambda row: row["created_at"])
    assert [row["status"] for row in rows] == ["superseded", "proposed"]
    assert rows[0]["created_at"] < rows[1]["created_at"]
    read = edit_tools.run(
        engine, context=context, tool_use_id="r1", name=edit_tools.READ_ITEM,
        tool_input={"kind": "card", "id": str(card_id)},
    )  # fmt: skip
    assert json.loads(read.result["content"])["pending"] == {
        "question": FEES_QUESTION,
        "answer": "They compound over decades.",
    }
    engine.dispose()


def test_a_pending_edit_made_against_an_older_version_is_not_built_on(live_stack: LiveStack) -> None:
    """Once the card moves on past a stored proposal's base version, read_item shows no pending edit and a new
    proposal starts from the newer version, so Apply can't drop it."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    _, card_id = _seed_source(live_stack, user_id=user_id)
    conversation_id, message_id = _seed_chat(live_stack, user_id=user_id)
    engine = session.engine_for(live_stack.database_url)
    context = edit_tools.ToolContext(user_id=user_id, conversation_id=conversation_id)
    target = versions.Target(kind=models.EditTarget.CARD, id=card_id)

    # A proposal stored against version 1, then Review's care rewrites the card to version 2.
    stale = edit_tools.run(
        engine, context=context, tool_use_id="p1", name=edit_tools.PROPOSE_CARD_EDIT,
        tool_input={"card_id": str(card_id), "description": "Shorter", "question": FEES_QUESTION, "answer": "Grow."},
    ).proposal  # fmt: skip
    assert stale is not None
    newer = {"question": "What do low fees add up to over decades?", "answer": FEES_ANSWER}
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        edit_tools.save_proposals(
            db, user_id=user_id, conversation_id=conversation_id, message_id=message_id, proposals=[stale]
        )
        newer_version = versions.write(
            db, target=target, content=newer, origin=models.VersionOrigin.CARE, instruction=None, derived_from=None
        )
        db.commit()

    read = edit_tools.run(
        engine, context=context, tool_use_id="r1", name=edit_tools.READ_ITEM,
        tool_input={"kind": "card", "id": str(card_id)},
    )  # fmt: skip
    assert json.loads(read.result["content"])["pending"] is None

    # The same holds for a proposal made earlier in this answer.
    in_answer = edit_tools.ToolContext(user_id=user_id, conversation_id=conversation_id, pending=(stale,))
    read_in_answer = edit_tools.run(
        engine, context=in_answer, tool_use_id="r2", name=edit_tools.READ_ITEM,
        tool_input={"kind": "card", "id": str(card_id)},
    )  # fmt: skip
    assert json.loads(read_in_answer.result["content"])["pending"] is None

    fresh = edit_tools.run(
        engine, context=context, tool_use_id="p2", name=edit_tools.PROPOSE_CARD_EDIT,
        tool_input={"card_id": str(card_id), "description": "Short", "question": newer["question"], "answer": "Grow."},
    ).proposal  # fmt: skip
    assert fresh is not None
    assert (fresh.before, fresh.base_version) == (newer, newer_version)
    engine.dispose()


def test_a_text_edit_replaces_text_that_is_there_and_another_users_items_are_out_of_reach(
    live_stack: LiveStack,
) -> None:
    """A primer find that isn't in the text is an error; one that is lands in the proposal's markdown; another user
    can neither read nor propose an edit of the owner's card."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    source_id, card_id = _seed_source(live_stack, user_id=user_id)
    conversation_id, _ = _seed_chat(live_stack, user_id=user_id)
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        pipeline.write_artifact(
            db, source=db.get_one(models.Source, source_id), kind=models.ArtifactKind.PRIMER,
            content={"markdown": PASSAGE}, model="m", prompt_version="p",
        )  # fmt: skip
        db.commit()
    context = edit_tools.ToolContext(user_id=user_id, conversation_id=conversation_id)

    def propose_primer_edit(find: str) -> edit_tools.ToolOutcome:
        return edit_tools.run(
            engine, context=context, tool_use_id="t", name=edit_tools.PROPOSE_TEXT_EDIT,
            tool_input={
                "kind": "primer", "id": str(source_id), "description": "Fees",
                "replacements": [{"find": find, "replace": "Their tiny fees"}],
            },
        )  # fmt: skip

    missing = propose_primer_edit("Their high fees")
    assert missing.result["is_error"] and "isn't in the current text" in missing.result["content"]
    valid = propose_primer_edit("Their low fees")
    assert valid.proposal is not None
    assert valid.proposal.after["markdown"] == PASSAGE.replace("Their low fees", "Their tiny fees")

    stranger = edit_tools.ToolContext(user_id=user_id + 1000, conversation_id=uuid.uuid4())
    card_edit = edit_tools.run(
        engine, context=stranger, tool_use_id="s1", name=edit_tools.PROPOSE_CARD_EDIT,
        tool_input={"card_id": str(card_id), "description": "x", "question": FEES_QUESTION, "answer": "Mine now."},
    )  # fmt: skip
    card_read = edit_tools.run(
        engine, context=stranger, tool_use_id="s2", name=edit_tools.READ_ITEM,
        tool_input={"kind": "card", "id": str(card_id)},
    )  # fmt: skip
    for outcome in (card_edit, card_read):
        assert outcome.result["is_error"] and "that the owner can edit" in outcome.result["content"]
    engine.dispose()


def test_asking_to_drop_a_key_idea_proposes_a_summary_edit_and_changes_nothing(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """read_item then propose_summary_edit: an `edit` event and a stored proposal with one key idea fewer."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id, _ = _seed_source(live_stack, user_id=_user_id(authed))

    with _replay(request, "ask_edit_summary"):
        events = _ask(
            authed,
            str(uuid.uuid4()),
            "Please remove the key idea about fees compounding from the summary.",
            about={"kind": "source", "id": str(source_id)},
        )

    names = [name for name, _ in events]
    assert "editing" in names and names[-1] == "done"
    [edit] = [data for name, data in events if name == "edit"]
    assert (edit["target_kind"], edit["target_id"], edit["base_version"], edit["status"]) == (
        "summary",
        str(source_id),
        1,
        "proposed",
    )
    assert edit["before"] == SUMMARY
    ideas = [item["idea"] for item in edit["after"]["key_ideas"]]
    assert len(ideas) == 2 and not any("fees compound" in idea.lower() for idea in ideas)
    assert edit["after"]["gist"] == SUMMARY["gist"] and edit["after"]["numbers"] == SUMMARY["numbers"]

    rows = _rows(authed)
    [proposal] = rows["edit_proposals"]
    assert (proposal["id"], proposal["status"], proposal["message_id"]) == (
        edit["id"],
        "proposed",
        events[-1][1]["message_id"],
    )
    [current] = [row for row in rows["artifacts"] if row["is_current"]]
    assert current["version"] == 1


def test_asking_to_fix_a_card_finds_it_and_proposes_a_card_edit(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """find_cards then propose_card_edit: the edit targets the seeded card and carries the owner's new answer."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id, card_id = _seed_source(live_stack, user_id=_user_id(authed))

    with _replay(request, "ask_edit_card"):
        events = _ask(
            authed,
            str(uuid.uuid4()),
            "Change my card about low fees so its answer says a 1% fee can eat about a quarter of your savings "
            "over 40 years.",
            about={"kind": "source", "id": str(source_id)},
        )

    [edit] = [data for name, data in events if name == "edit"]
    assert (edit["target_kind"], edit["target_id"]) == ("card", str(card_id))
    assert edit["before"] == {"question": FEES_QUESTION, "answer": FEES_ANSWER}
    assert "quarter" in edit["after"]["answer"].lower()
    assert events[-1][0] == "done"
