"""Ask through the real API: a library-cited answer, a web-cited answer, failed and unfinished answers, a hang-up,
and the refusals.

Anthropic is replayed from recorded real responses, in order (`allow_playback_repeats=False`: a multi-round answer
replays round by round). Re-record a cassette by deleting it and running
`uv run pytest services/api/tests/e2e/test_ask_e2e.py --record-mode=once -m postgres` (a few cents of Sonnet 5.5 and
one or two web searches; needs ANTHROPIC_API_KEY). `ask_unauthorized` is recorded with a deliberately wrong key,
`ask_max_tokens` with `MAX_TOKENS_CUTOFF`. The kept `ask_library` recording opens with an announced search ("Let me
search your library for this."), which the answer must not save.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import pathlib
import threading
import uuid
from typing import Any

import anyio
import httpx
import pytest
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.orm
from archie_api.ask import answer, context, prompts
from archie_db import changes, models, search, session
from archie_shared import config
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
PASSAGE = (
    "The Fed creates money by buying bonds from banks and paying for them with newly created reserves. "
    "Those reserves sit in the banks' accounts at the Fed; they are not cash in anyone's pocket."
)
QUESTION = "How does the Fed create money, going by what I saved?"
PREAMBLE = "Let me search"
# Small enough that the model is cut off before it finishes its first round.
MAX_TOKENS_CUTOFF = 16


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay (no OpenAI key: keyword search in the tool)."""
    recording.use_recording_api_key(request, monkeypatch)


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=False)


def _ask(authed: httpx.Client, conversation_id: str, **body: Any) -> list[tuple[str, dict[str, Any]]]:
    """POST the question, with the phone's time zone as the app sends it, and parse the server-sent events."""
    payload = {
        "user_message_id": str(uuid.uuid4()),
        "text": QUESTION,
        "web_search": False,
        "timezone": "America/New_York",
        **body,
    }
    with authed.stream("POST", f"/ask/conversations/{conversation_id}/messages", json=payload, timeout=180) as response:
        assert response.status_code == 200, response.read()
        raw = "".join(response.iter_text())
    events = []
    for chunk in raw.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _seed_source(live_stack: LiveStack, *, user_id: int) -> str:
    """A saved article with one indexed passage (no embedding: the tool searches it by keyword)."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        url = "https://example.com/fed"
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=url,
            normalized_url=url,
            title="How the Fed creates money",
            kind=models.SourceKind.ARTICLE.value,
            state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        db.add(
            models.Chunk(
                user_id=user_id,
                source_id=source.id,
                owner_kind=models.ChunkOwner.SOURCE_TEXT.value,
                chunk_index=0,
                text=PASSAGE,
            )
        )
        db.commit()
        source_id = str(source.id)
    engine.dispose()
    return source_id


def _seed_removed_topic_primer(live_stack: LiveStack, *, user_id: int) -> str:
    """The current primer of a topic the user removed."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        topic = models.Topic(
            id=uuid.uuid4(),
            user_id=user_id,
            domain="Macro",
            name="Reserves",
            origin=models.TopicOrigin.USER.value,
            removed_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
        db.add(topic)
        db.flush()
        primer = models.TopicPrimer(
            id=uuid.uuid4(),
            user_id=user_id,
            topic_id=topic.id,
            version=1,
            is_current=True,
            content={"markdown": "## Reserves"},
            change_seq=changes.next_change_seq(),
        )
        db.add(primer)
        db.commit()
        primer_id = str(primer.id)
    engine.dispose()
    return primer_id


def _seed_chat(live_stack: LiveStack, *, user_id: int, conversation_id: str, message_id: str) -> None:
    """A chat with one question, whose id a later ask may not reuse."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Conversation(
                id=uuid.UUID(conversation_id), user_id=user_id, title="Hi", change_seq=changes.next_change_seq()
            )
        )
        db.flush()
        db.add(
            models.Message(
                id=uuid.UUID(message_id),
                user_id=user_id,
                conversation_id=uuid.UUID(conversation_id),
                role=models.MessageRole.USER.value,
                text="Hi",
                segments=None,
                web_search=False,
                status=models.MessageStatus.COMPLETE.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()


def _seed_question(live_stack: LiveStack, *, user_id: int, source_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    """A chat about the source holding the question row, as the route stores it; returns the chat and question ids."""
    conversation_id, question_id = uuid.uuid4(), uuid.uuid4()
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Conversation(
                id=conversation_id,
                user_id=user_id,
                title=QUESTION[:60],
                about_source_id=uuid.UUID(source_id),
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        db.add(
            models.Message(
                id=question_id,
                user_id=user_id,
                conversation_id=conversation_id,
                role=models.MessageRole.USER.value,
                text=QUESTION,
                segments=None,
                web_search=False,
                status=models.MessageStatus.COMPLETE.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()
    return conversation_id, question_id


def _user_id(authed: httpx.Client) -> int:
    return int(authed.get("/me").json()["user_id"])


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def _llm_steps(live_stack: LiveStack) -> list[str]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        steps = list(db.scalars(sqlalchemy.select(models.LlmCall.step)))
    engine.dispose()
    return steps


def test_an_answer_from_the_library_cites_the_passage_and_is_saved(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """A library search runs, a block is labelled library with a chip naming the source, and the chat is pulled."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = _seed_source(live_stack, user_id=_user_id(authed))
    conversation_id = str(uuid.uuid4())

    with _replay(request, "ask_library"):
        events = _ask(authed, conversation_id, about={"kind": "source", "id": source_id})

    names = [name for name, _ in events]
    assert any(name == "searching" and data["kind"] == "library" and data["query"] for name, data in events)
    assert "delta" in names and names[-1] == "done"
    blocks = [data for name, data in events if name == "block"]
    library_blocks = [block for block in blocks if block["label"] == "library"]
    assert library_blocks and any(
        citation["source_id"] == source_id for block in library_blocks for citation in block["citations"]
    )
    # Block indexes count every text block once, the dropped preamble too; deltas never reuse a finished block's index.
    assert [block["block"] for block in blocks] == list(range(len(blocks)))
    delta_blocks = [data["block"] for name, data in events if name == "delta"]
    assert delta_blocks == sorted(delta_blocks) and set(delta_blocks) <= set(range(len(blocks)))
    # Citations split the answer's first paragraph into several blocks; they all share its library label.
    answer_blocks = blocks[1:]
    assert len(answer_blocks) > 2 and [block["label"] for block in answer_blocks[:-1]] == ["library"] * (
        len(answer_blocks) - 1
    )

    rows = _rows(authed)
    [conversation] = rows["conversations"]
    assert (conversation["title"], conversation["about_kind"], conversation["about_source_id"]) == (
        QUESTION[:60],
        "source",
        source_id,
    )
    answer = next(message for message in rows["messages"] if message["role"] == "assistant")
    assert (answer["id"], answer["status"]) == (events[-1][1]["message_id"], "complete")
    assert any(segment["label"] == "library" for segment in answer["segments"])
    assert len(answer["segments"]) == len(answer_blocks)
    assert [segment["label"] for segment in answer["segments"]] == [block["label"] for block in answer_blocks]
    assert not any(segment["text"].startswith(PREAMBLE) for segment in answer["segments"])
    assert PREAMBLE not in answer["text"] and answer["text"].startswith("According")
    assert set(_llm_steps(live_stack)) == {"ask"} and len(_llm_steps(live_stack)) >= 2


def test_with_the_globe_on_the_answer_searches_the_web_and_cites_links(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """A web search runs and a block is labelled web with a link chip."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))

    with _replay(request, "ask_web"):
        events = _ask(
            authed,
            str(uuid.uuid4()),
            text="What is the Fed's current target range for the federal funds rate?",
            web_search=True,
        )

    assert any(name == "searching" and data["kind"] == "web" for name, data in events)
    web_blocks = [data for name, data in events if name == "block" and data["label"] == "web"]
    assert web_blocks and all(citation["url"].startswith("http") for citation in web_blocks[0]["citations"])
    assert events[-1][0] == "done"


def test_a_failed_stream_ends_with_error_and_is_stored_as_failed(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorded with a wrong key: Anthropic answers 401, so the answer is stored failed and the question kept."""
    monkeypatch.setenv(config.ANTHROPIC_API_KEY_ENV, "sk-ant-wrong-key")
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))

    with _replay(request, "ask_unauthorized"):
        events = _ask(authed, str(uuid.uuid4()))

    assert events == [("error", {"message": "Didn't finish. Try again"})]
    statuses = {message["role"]: message["status"] for message in _rows(authed)["messages"]}
    assert statuses == {"user": "complete", "assistant": "failed"}
    # Refused before any message started: nothing was spent, so no cost row.
    assert _llm_steps(live_stack) == []


def test_an_answer_cut_off_by_max_tokens_is_stored_as_failed(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorded with `MAX_TOKENS_CUTOFF`: the model stops on max_tokens, which isn't a finished answer."""
    monkeypatch.setattr(answer, "MAX_TOKENS", MAX_TOKENS_CUTOFF)
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))

    with _replay(request, "ask_max_tokens"):
        events = _ask(authed, str(uuid.uuid4()))

    assert events[-1] == ("error", {"message": "Didn't finish. Try again"})
    statuses = {message["role"]: message["status"] for message in _rows(authed)["messages"]}
    assert statuses == {"user": "complete", "assistant": "failed"}
    assert _llm_steps(live_stack) == ["ask"]


def test_an_answer_out_of_rounds_is_stored_as_failed(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With one round allowed, the recorded first round's tool call leaves no answer: failed, not complete."""
    monkeypatch.setattr(answer, "MAX_ROUNDS", 1)
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = _seed_source(live_stack, user_id=_user_id(authed))

    with _replay(request, "ask_library"):
        events = _ask(authed, str(uuid.uuid4()), about={"kind": "source", "id": source_id})

    assert events[-1] == ("error", {"message": "Didn't finish. Try again"})
    answer_row = next(message for message in _rows(authed)["messages"] if message["role"] == "assistant")
    assert answer_row["status"] == "failed"
    assert _llm_steps(live_stack) == ["ask"]


def test_the_first_complete_answer_queues_naming_the_chat_once(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """One `name_chat` job carrying the title the chat was created with; a second answer queues no other."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = _seed_source(live_stack, user_id=_user_id(authed))
    conversation_id = str(uuid.uuid4())

    with _replay(request, "ask_library"):
        _ask(authed, conversation_id, about={"kind": "source", "id": source_id})
    with _replay(request, "ask_library"):
        events = _ask(authed, conversation_id, text="And what happens to those reserves later?")

    assert events[-1][0] == "done"
    [job] = _name_chat_jobs(live_stack)
    assert job.payload == {"conversation_id": conversation_id, "expected_title": QUESTION[:60]}
    assert job.status == models.JobStatus.QUEUED.value


def test_a_failed_first_answer_leaves_naming_to_the_first_complete_one(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed answer queues nothing; the next, complete answer queues the name with the first question's title."""
    max_rounds = answer.MAX_ROUNDS
    monkeypatch.setattr(answer, "MAX_ROUNDS", 1)
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = _seed_source(live_stack, user_id=_user_id(authed))
    conversation_id = str(uuid.uuid4())

    with _replay(request, "ask_library"):
        failed = _ask(authed, conversation_id, about={"kind": "source", "id": source_id})
    assert failed[-1][0] == "error"
    assert _name_chat_jobs(live_stack) == []

    monkeypatch.setattr(answer, "MAX_ROUNDS", max_rounds)
    with _replay(request, "ask_library"):
        _ask(authed, conversation_id, text="Try that again, please.")

    [job] = _name_chat_jobs(live_stack)
    assert job.payload == {"conversation_id": conversation_id, "expected_title": QUESTION[:60]}


def _name_chat_jobs(live_stack: LiveStack) -> list[models.Job]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        jobs = list(db.scalars(sqlalchemy.select(models.Job).where(models.Job.kind == models.JobKind.NAME_CHAT.value)))
    engine.dispose()
    return jobs


def test_a_database_error_mid_answer_ends_with_error_and_keeps_the_answer(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The library search breaks: the phone still gets `error`, and the answer is stored failed."""

    def broken_search(*args: object, **kwargs: object) -> list[search.ChunkHit]:
        raise sqlalchemy.exc.OperationalError("SELECT", params=None, orig=Exception("connection lost"))

    monkeypatch.setattr(search, "search_chunks", broken_search)
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = _seed_source(live_stack, user_id=_user_id(authed))

    with _replay(request, "ask_library"):
        events = _ask(authed, str(uuid.uuid4()), about={"kind": "source", "id": source_id})

    assert events[-1] == ("error", {"message": "Didn't finish. Try again"})
    statuses = {message["role"]: message["status"] for message in _rows(authed)["messages"]}
    assert statuses == {"user": "complete", "assistant": "failed"}


def test_a_hang_up_mid_answer_finishes_it_and_stores_it_complete(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """The phone goes away after the first event: the answer still runs to its end and is saved complete, the question
    moves, and every round's spend is kept."""
    engine, answer_request, question_seq = _unfinished_answer_request(live_stack)

    with _replay(request, "ask_library"):
        generator = answer.stream(engine, answer_request)
        next(generator)
        generator.close()

    _assert_hang_up_recorded(
        live_stack,
        engine=engine,
        answer_request=answer_request,
        question_seq=question_seq,
        status=models.MessageStatus.COMPLETE,
    )


def test_closing_the_async_stream_finishes_and_saves_the_answer_at_once(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """Starlette closes the response body with `aclose()` on a hang-up; that must close `stream`, not leave it to GC."""
    engine, answer_request, question_seq = _unfinished_answer_request(live_stack)

    async def hang_up_after_first_event() -> None:
        events = answer.stream_async(engine, answer_request)
        await anext(events)
        await events.aclose()

    with _replay(request, "ask_library"):
        asyncio.run(hang_up_after_first_event())

    _assert_hang_up_recorded(
        live_stack,
        engine=engine,
        answer_request=answer_request,
        question_seq=question_seq,
        status=models.MessageStatus.COMPLETE,
    )


def test_a_cancelled_async_stream_saves_the_answer_off_the_event_loop_thread(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uvicorn hangs up by cancelling the response's task group, landing inside `stream_async`'s wait for the next
    event; the shielded close must still finish and save the answer on a worker thread, never the event loop's."""
    engine, answer_request, question_seq = _unfinished_answer_request(live_stack)
    save_ran_on_main_thread: list[bool] = []
    original_save = answer._save

    def recording_save(*args: Any, **kwargs: Any) -> Any:
        save_ran_on_main_thread.append(threading.current_thread() is threading.main_thread())
        return original_save(*args, **kwargs)

    monkeypatch.setattr(answer, "_save", recording_save)

    async def cancel_while_waiting_for_the_next_event() -> None:
        async with anyio.create_task_group() as task_group:
            async for _ in answer.stream_async(engine, answer_request):
                # The consumer goes back to waiting on the next event, which is where the cancel is delivered.
                task_group.cancel_scope.cancel()

    with _replay(request, "ask_library"):
        asyncio.run(cancel_while_waiting_for_the_next_event())

    _assert_hang_up_recorded(
        live_stack,
        engine=engine,
        answer_request=answer_request,
        question_seq=question_seq,
        status=models.MessageStatus.COMPLETE,
    )
    assert save_ran_on_main_thread
    assert not any(save_ran_on_main_thread)


def test_a_hang_up_then_a_failure_stores_the_answer_failed(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the phone goes away the library search breaks: the answer is stored failed, and closing sends nothing."""

    def broken_search(*args: object, **kwargs: object) -> list[search.ChunkHit]:
        raise sqlalchemy.exc.OperationalError("SELECT", params=None, orig=Exception("connection lost"))

    monkeypatch.setattr(search, "search_chunks", broken_search)
    engine, answer_request, question_seq = _unfinished_answer_request(live_stack)

    with _replay(request, "ask_library"):
        generator = answer.stream(engine, answer_request)
        next(generator)
        generator.close()

    _assert_hang_up_recorded(
        live_stack,
        engine=engine,
        answer_request=answer_request,
        question_seq=question_seq,
        status=models.MessageStatus.FAILED,
    )


def _unfinished_answer_request(live_stack: LiveStack) -> tuple[sqlalchemy.Engine, answer.AnswerRequest, int]:
    """A signed-in owner's chat about a seeded source with its question stored; returns what `stream` needs."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    source_id = _seed_source(live_stack, user_id=user_id)
    conversation_id, question_id = _seed_question(live_stack, user_id=user_id, source_id=source_id)
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        question_seq = db.get_one(models.Message, question_id).change_seq
        conversation = db.get_one(models.Conversation, conversation_id)
        answer_request = answer.AnswerRequest(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message_id=question_id,
            web_search=False,
            system=prompts.system_prompt(
                about=context.about_text(db, conversation=conversation),
                web_required=False,
                now=datetime.datetime(2026, 11, 7, 12, tzinfo=datetime.UTC),
            ),
            messages=[{"role": "user", "content": QUESTION}],
            boost=context.boost(db, conversation=conversation),
            note_title=None,
            day_zone=datetime.UTC,
            anthropic_key=config.Settings().require_anthropic_api_key(),
            openai_key=None,
        )
    return engine, answer_request, question_seq


def _assert_hang_up_recorded(
    live_stack: LiveStack,
    *,
    engine: sqlalchemy.Engine,
    answer_request: answer.AnswerRequest,
    question_seq: int,
    status: models.MessageStatus,
) -> None:
    """The answer is stored with `status`, the question moved, and every round run was recorded.

    A complete answer ran both recorded rounds and holds the recording's whole text; a failed one broke in the first
    round's library search, so only that round was spent.
    """
    with sqlalchemy.orm.Session(engine) as db:
        [answer_row] = db.scalars(
            sqlalchemy.select(models.Message).where(
                models.Message.conversation_id == answer_request.conversation_id,
                models.Message.role == models.MessageRole.ASSISTANT.value,
            )
        )
        assert answer_row.status == status.value
        assert db.get_one(models.Message, answer_request.user_message_id).change_seq > question_seq
        answer_text = answer_row.text
    engine.dispose()
    if status == models.MessageStatus.COMPLETE:
        assert answer_text.startswith("According") and answer_text.endswith("other tools the Fed uses.")
        assert _llm_steps(live_stack) == ["ask", "ask"]
    else:
        assert _llm_steps(live_stack) == ["ask"]


def _seed_card(live_stack: LiveStack, *, user_id: int, dropped: bool = False) -> str:
    """A concept card of the user's, optionally dropped (soft-deleted)."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        card = models.Card(
            id=uuid.uuid4(),
            user_id=user_id,
            source_id=_seed_plain_source(db, user_id=user_id),
            kind=models.CardKind.CONCEPT.value,
            question="What do reserves sit in?",
            answer="Accounts at the Fed.",
            deleted_at=sqlalchemy.func.now() if dropped else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(card)
        db.commit()
        card_id = str(card.id)
    engine.dispose()
    return card_id


def _seed_plain_source(db: sqlalchemy.orm.Session, *, user_id: int) -> uuid.UUID:
    url = f"https://example.com/{uuid.uuid4()}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user_id,
        url=url,
        normalized_url=url,
        title="How banks hold reserves",
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.CONSUMED.value,
        intent=models.SourceIntent.FINISHED.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source.id


def test_a_chat_about_another_users_or_a_dropped_card_is_refused(live_stack: LiveStack) -> None:
    """Another user's card and a dropped card are 404 before any model call. (A chat about a live card is covered,
    with its recorded answer, in test_ask_edit_e2e.py.)"""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    other = live_stack.authed(live_stack.sign_in(apple_sub="other", is_whitelisted=True))
    card_id = _seed_card(live_stack, user_id=_user_id(owner))
    dropped_id = _seed_card(live_stack, user_id=_user_id(owner), dropped=True)
    body = {"user_message_id": str(uuid.uuid4()), "text": "Why?", "web_search": False}

    for refused_card in (card_id, dropped_id):
        who = other if refused_card == card_id else owner
        refused = who.post(
            f"/ask/conversations/{uuid.uuid4()}/messages",
            json={**body, "user_message_id": str(uuid.uuid4()), "about": {"kind": "card", "id": refused_card}},
        )
        assert (refused.status_code, refused.json()["detail"]) == (404, "about item not found")


def test_a_card_chats_about_text_names_the_card_its_text_and_origin_and_boosts_the_origin(
    live_stack: LiveStack,
) -> None:
    """The model is given the card id for read_item + propose_card_edit, so it needs no find_cards."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    card_id = _seed_card(live_stack, user_id=_user_id(owner))
    dropped_id = _seed_card(live_stack, user_id=_user_id(owner), dropped=True)
    engine = session.engine_for(live_stack.database_url)

    with sqlalchemy.orm.Session(engine) as db:
        card = db.get_one(models.Card, uuid.UUID(card_id))
        chat = models.Conversation(about_card_id=card.id)
        text = context.about_text(db, conversation=chat)
        boosted = context.boost(db, conversation=chat)
        assert context.note_title(db, conversation=chat) is None
        dropped_chat = models.Conversation(about_card_id=uuid.UUID(dropped_id))
        dropped_text = context.about_text(db, conversation=dropped_chat)
        dropped_boost = context.boost(db, conversation=dropped_chat)
    engine.dispose()

    assert dropped_text is not None
    assert "removed" in dropped_text and "What do reserves sit in?" in dropped_text
    assert "propose_card_edit" not in dropped_text and dropped_boost is None

    assert text is not None
    assert text.startswith(f"A review card (card id {card_id})")
    expected_parts = ("What do reserves sit in?", "Accounts at the Fed.", "How banks hold reserves")
    assert all(part in text for part in expected_parts) and "propose_card_edit" in text
    assert card.source_id is not None
    assert boosted == search.ItemRef(kind=models.SearchItemKind.SOURCE, id=card.source_id)


def test_refusals_happen_before_any_model_call(live_stack: LiveStack) -> None:
    """Not whitelisted 403; someone else's or a deleted chat 404; a reused question id 409; a bad about item 404."""
    plain = live_stack.authed(live_stack.sign_in(apple_sub="plain"))
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    other = live_stack.authed(live_stack.sign_in(apple_sub="other", is_whitelisted=True))
    used_message_id = str(uuid.uuid4())
    payload = {"user_message_id": used_message_id, "text": "Hi", "web_search": False}
    chat_id = str(uuid.uuid4())
    _seed_chat(live_stack, user_id=_user_id(owner), conversation_id=chat_id, message_id=used_message_id)

    assert plain.post(f"/ask/conversations/{uuid.uuid4()}/messages", json=payload).status_code == 403
    fresh = {**payload, "user_message_id": str(uuid.uuid4())}
    assert other.post(f"/ask/conversations/{chat_id}/messages", json=fresh).status_code == 404
    assert owner.post(f"/ask/conversations/{uuid.uuid4()}/messages", json=payload).status_code == 409
    deleting = {"id": str(uuid.uuid4()), "type": "delete_conversation", "payload": {"id": chat_id}}
    owner.post("/sync/push", json={"actions": [deleting]}).raise_for_status()
    assert owner.post(f"/ask/conversations/{chat_id}/messages", json=fresh).status_code == 404
    bad_about = {**fresh, "about": {"kind": "take", "id": str(uuid.uuid4())}}
    assert owner.post(f"/ask/conversations/{uuid.uuid4()}/messages", json=bad_about).status_code == 404
    removed_topic_primer = _seed_removed_topic_primer(live_stack, user_id=_user_id(owner))
    removed_about = {**fresh, "about": {"kind": "topic_primer", "id": removed_topic_primer}}
    refused = owner.post(f"/ask/conversations/{uuid.uuid4()}/messages", json=removed_about)
    assert (refused.status_code, refused.json()["detail"]) == (404, "about item not found")
    assert owner.post(f"/ask/conversations/{uuid.uuid4()}/messages", json={**fresh, "text": "  "}).status_code == 422
    assert _llm_steps(live_stack) == []
