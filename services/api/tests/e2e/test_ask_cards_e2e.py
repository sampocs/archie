"""Make a card through the real API: Haiku drafts one card from an answer; saving adds a concept card from the chat.

Re-record `ask_card_draft` by deleting it and running
`uv run pytest services/api/tests/e2e/test_ask_cards_e2e.py --record-mode=once -m postgres` (a fraction of a cent).
"""

from __future__ import annotations

import pathlib
import uuid

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
QUESTION = "How does the Fed actually create money?"
ANSWER = (
    "It buys bonds from banks and pays with newly created reserves. Those reserves sit at the Fed; they aren't "
    "cash in anyone's pocket."
)


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _seed_answer(live_stack: LiveStack, *, user_id: int) -> tuple[str, str]:
    """A chat with one question and its answer; returns the chat id and the answer id."""
    engine = session.engine_for(live_stack.database_url)
    conversation_id, answer_id = uuid.uuid4(), uuid.uuid4()
    turns = ((uuid.uuid4(), models.MessageRole.USER, QUESTION), (answer_id, models.MessageRole.ASSISTANT, ANSWER))
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Conversation(
                id=conversation_id, user_id=user_id, title=QUESTION, change_seq=changes.next_change_seq()
            )
        )
        db.flush()
        for message_id, role, text in turns:
            db.add(
                models.Message(
                    id=message_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role=role.value,
                    text=text,
                    segments=None,
                    web_search=False,
                    status=models.MessageStatus.COMPLETE.value,
                    change_seq=changes.next_change_seq(),
                )
            )
            db.flush()
        db.commit()
    engine.dispose()
    return str(conversation_id), str(answer_id)


def test_a_draft_is_one_question_and_answer_from_the_answer(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """One Haiku call, recorded as `card_draft`; the draft's numbers come from the answer."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    _, answer_id = _seed_answer(live_stack, user_id=_user_id(authed))

    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    with recorder.use_cassette("ask_card_draft.yaml", allow_playback_repeats=True):
        response = authed.post(f"/ask/messages/{answer_id}/card-draft")

    assert response.status_code == 200
    draft = response.json()
    assert draft["question"].strip().endswith("?") and draft["answer"].strip()
    assert _llm_steps(live_stack) == ["card_draft"]


def test_saving_adds_a_new_concept_card_from_the_chat(live_stack: LiveStack) -> None:
    """The card reaches the phone through pull with its chat and answer; it starts new, like every new card."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    conversation_id, answer_id = _seed_answer(live_stack, user_id=_user_id(authed))

    response = authed.post("/ask/cards", json={"message_id": answer_id, "question": " Q? ", "answer": "A."})

    assert response.status_code == 200
    card = response.json()
    assert (card["kind"], card["question"], card["fsrs_state"]) == ("concept", "Q?", "new")
    assert (card["conversation_id"], card["message_id"], card["source_id"]) == (conversation_id, answer_id, None)
    pulled = authed.get("/sync/pull", params={"since": 0}).json()["rows"]["cards"]
    assert [row["id"] for row in pulled] == [card["id"]]


def test_refusals(live_stack: LiveStack) -> None:
    """Drafting needs the owner's keys (403); someone else's or an unknown answer is 404; empty fields 422."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    plain = live_stack.authed(live_stack.sign_in(apple_sub="plain"))
    _, answer_id = _seed_answer(live_stack, user_id=_user_id(owner))

    assert plain.post(f"/ask/messages/{answer_id}/card-draft").status_code == 403
    assert owner.post(f"/ask/messages/{uuid.uuid4()}/card-draft").status_code == 404
    assert plain.post("/ask/cards", json={"message_id": answer_id, "question": "Q?", "answer": "A."}).status_code == 404
    assert owner.post("/ask/cards", json={"message_id": answer_id, "question": "", "answer": "A."}).status_code == 422
    assert _llm_steps(live_stack) == []


def _llm_steps(live_stack: LiveStack) -> list[str]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        steps = list(db.scalars(sqlalchemy.select(models.LlmCall.step)))
    engine.dispose()
    return steps
