"""`name_chat` end to end: real jobs in a real Postgres, Haiku replayed from a recorded real response.

The chats are invented here. Re-record with
`uv run pytest services/worker/tests/test_name_chat_e2e.py --record-mode=once -m postgres` after deleting the cassette
(a fraction of a cent; needs ANTHROPIC_API_KEY in the repo root .env).
- `name_chat_derivatives`: a "Make cards" chat about a saved explainer on derivatives that proposed one card set.
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, chat_names, models, session
from archie_llm import llm
from archie_testing import recording
from archie_worker import errors, handlers, loop
from archie_worker.handlers import name_chat

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
ITEM_TITLE = "Derivatives"
QUESTION = "Make cards"
GENERAL_QUESTION = "What is the difference between a perpetual future and an option?"
ANSWER = (
    "A perpetual future (a perp) is a futures contract with no expiry: traders keep a leveraged long or short "
    "position open as long as they like, and a funding rate paid between longs and shorts every few hours keeps its "
    "price close to the spot price. An option instead gives its buyer the right, but not the obligation, to buy "
    "(a call) or sell (a put) at a strike price before it expires; the buyer pays a premium up front and can lose no "
    "more than that, while the seller takes on the risk. Here is a card set on how perps and options differ."
)
CARD_SET_TITLE = "Perps vs options"
OWNER_NAME = "My derivatives notes"


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> Replay:
    """Returns `use_cassette(name)`: the recorded Anthropic HTTP for one test, replayable any number of times."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


# --- Recorded naming runs ---


def test_haiku_names_the_chat_after_its_subject(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A "Make cards" chat gets a short subject name, a new change position, and one Haiku call recorded as the step."""
    user_id = _add_user(engine)
    conversation_id = _add_chat(engine, user_id=user_id, about_title=ITEM_TITLE, card_set=True)
    before = _conversation(engine, conversation_id)
    seq_before = before.change_seq

    with replay("name_chat_derivatives"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    conversation = _conversation(engine, conversation_id)
    assert (conversation.title, conversation.change_seq > seq_before) == ("Perps vs options", True)
    assert conversation.updated_at == before.updated_at
    [call] = _llm_calls(engine)
    assert (call.step, call.model) == (models.JobKind.NAME_CHAT.value, llm.HAIKU)
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_a_chat_the_owner_renamed_during_the_call_keeps_the_owners_name(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's rename lands while Haiku is answering; the guarded write leaves it alone."""
    user_id = _add_user(engine)
    conversation_id = _add_chat(engine, user_id=user_id, about_title=ITEM_TITLE, card_set=True)
    complete = llm.complete

    def rename_then_complete(*args: Any, **kwargs: Any) -> llm.Completion:
        _rename(engine, conversation_id=conversation_id, title=OWNER_NAME)
        return complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete", rename_then_complete)
    with replay("name_chat_derivatives"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _conversation(engine, conversation_id).title == OWNER_NAME
    assert _only_job(engine).status == models.JobStatus.DONE.value


# --- The fallback, when the job fails for good ---


@pytest.mark.parametrize(
    ("card_set", "expected"),
    [(True, f"{ITEM_TITLE}{name_chat.CARDS_SUFFIX}"), (False, ITEM_TITLE)],
)
def test_a_chat_about_an_item_falls_back_to_the_items_title(
    engine: sqlalchemy.Engine, card_set: bool, expected: str
) -> None:
    """With no key to pay for Haiku the job fails at once; " · cards" marks a first answer that proposed a card set."""
    user_id = _add_user(engine, is_whitelisted=False)
    conversation_id = _add_chat(engine, user_id=user_id, about_title=ITEM_TITLE, card_set=card_set)
    before = _conversation(engine, conversation_id)
    seq_before = before.change_seq

    loop.run_one(engine, handlers=handlers.HANDLERS)

    conversation = _conversation(engine, conversation_id)
    assert (conversation.title, conversation.change_seq > seq_before) == (expected, True)
    assert conversation.updated_at == before.updated_at
    assert _only_job(engine).status == models.JobStatus.FAILED.value
    assert _llm_calls(engine) == []


def test_a_general_chat_keeps_its_first_question_when_naming_gives_up(engine: sqlalchemy.Engine) -> None:
    """No item to name it after: the title and its change position stay as they were."""
    user_id = _add_user(engine, is_whitelisted=False)
    conversation_id = _add_chat(engine, user_id=user_id, question=GENERAL_QUESTION, about_title=None, card_set=True)
    before = _conversation(engine, conversation_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    after = _conversation(engine, conversation_id)
    assert (after.title, after.change_seq) == (GENERAL_QUESTION[:60], before.change_seq)
    assert _only_job(engine).status == models.JobStatus.FAILED.value


def test_the_fallback_leaves_a_renamed_chat_alone(engine: sqlalchemy.Engine) -> None:
    """The hook runs the same guarded write as the job."""
    user_id = _add_user(engine)
    conversation_id = _add_chat(engine, user_id=user_id, about_title=ITEM_TITLE, card_set=True)
    _rename(engine, conversation_id=conversation_id, title=OWNER_NAME)

    with sqlalchemy.orm.Session(engine) as db:
        name_chat.name_from_fallback(db, _only_job(engine), errors.FailureReason.GAVE_UP.value)
        db.commit()

    assert _conversation(engine, conversation_id).title == OWNER_NAME


def test_a_long_item_title_is_cut_so_the_fallback_fits_60_characters(engine: sqlalchemy.Engine) -> None:
    """The suffix survives the cut, so the name still says the chat made cards."""
    user_id = _add_user(engine)
    long_title = "An unusually long explainer title about every kind of derivative contract"
    conversation_id = _add_chat(engine, user_id=user_id, about_title=long_title, card_set=True)

    with sqlalchemy.orm.Session(engine) as db:
        title = name_chat.fallback_title(db, conversation=db.get_one(models.Conversation, conversation_id))

    assert title is not None and len(title) <= models.CONVERSATION_TITLE_LENGTH
    assert title.endswith(name_chat.CARDS_SUFFIX) and title.startswith("An unusually long")


@pytest.mark.parametrize("raw_name", ["", "   ", '""', "x" * (models.CONVERSATION_TITLE_LENGTH + 1)])
def test_an_empty_or_over_long_name_fails_at_once_for_the_fallback(raw_name: str) -> None:
    """Asking again would only give the same kind of answer, so it is a permanent failure."""
    with pytest.raises(errors.PermanentJobError):
        name_chat.parse_name({"name": raw_name})


def test_a_name_loses_stray_quotes_a_trailing_period_and_extra_spaces() -> None:
    """The prompt asks for none of these; the parse makes sure."""
    assert name_chat.parse_name({"name": '  "Perps  vs options."  '}) == "Perps vs options"


# --- The one-off backfill ---


def test_the_backfill_queues_a_name_for_every_live_chat_with_a_complete_answer(engine: sqlalchemy.Engine) -> None:
    """A deleted chat and one whose only answer failed get none; each job expects the chat's creation title."""
    user_id = _add_user(engine)
    named_ids = {
        _add_chat(engine, user_id=user_id, about_title=ITEM_TITLE, card_set=True, enqueue=False),
        _add_chat(engine, user_id=user_id, question=GENERAL_QUESTION, about_title=None, card_set=False, enqueue=False),
    }
    _add_chat(engine, user_id=user_id, about_title=None, card_set=False, enqueue=False, answer_failed=True)
    deleted_id = _add_chat(engine, user_id=user_id, about_title=None, card_set=False, enqueue=False)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Conversation, deleted_id).deleted_at = sqlalchemy.func.now()
        db.commit()

    with sqlalchemy.orm.Session(engine) as db:
        queued = chat_names.backfill_all(db)

    jobs = _jobs(engine)
    assert queued == len(jobs) == 2
    payloads = {job.payload[chat_names.CONVERSATION_ID_KEY]: job.payload[chat_names.EXPECTED_TITLE_KEY] for job in jobs}
    assert set(payloads) == {str(conversation_id) for conversation_id in named_ids}
    assert set(payloads.values()) == {QUESTION, GENERAL_QUESTION[:60]}


# --- Helpers ---


def _add_user(engine: sqlalchemy.Engine, *, is_whitelisted: bool = True) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.commit()
        return user.id


def _add_chat(
    engine: sqlalchemy.Engine,
    *,
    user_id: int,
    about_title: str | None,
    card_set: bool,
    question: str = QUESTION,
    enqueue: bool = True,
    answer_failed: bool = False,
) -> uuid.UUID:
    """A chat with its first question and answer (optionally about a saved item, with a card set), as the API stores
    it; `enqueue` queues its `name_chat` as the first complete answer does."""
    conversation_id, answer_id = uuid.uuid4(), uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        about_source_id = _add_source(db, user_id=user_id, title=about_title) if about_title is not None else None
        db.add(
            models.Conversation(
                id=conversation_id,
                user_id=user_id,
                title=chat_names.creation_title(question),
                about_kind=models.SearchItemKind.SOURCE.value if about_source_id else None,
                about_source_id=about_source_id,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        db.add(_message(user_id=user_id, conversation_id=conversation_id, role=models.MessageRole.USER, text=question))
        db.flush()
        db.add(
            _message(
                user_id=user_id,
                conversation_id=conversation_id,
                role=models.MessageRole.ASSISTANT,
                text=ANSWER,
                message_id=answer_id,
                status=models.MessageStatus.FAILED if answer_failed else models.MessageStatus.COMPLETE,
            )
        )
        db.flush()
        if card_set:
            db.add(_card_set(user_id=user_id, conversation_id=conversation_id, message_id=answer_id))
        if enqueue:
            chat_names.enqueue_if_first_complete_answer(db, conversation_id=conversation_id, user_id=user_id)
        db.commit()
    return conversation_id


def _add_source(db: sqlalchemy.orm.Session, *, user_id: int, title: str) -> uuid.UUID:
    url = f"https://example.com/{uuid.uuid4()}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user_id,
        url=url,
        normalized_url=url,
        title=title,
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.CONSUMED.value,
        intent=models.SourceIntent.FINISHED.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source.id


def _message(
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    role: models.MessageRole,
    text: str,
    message_id: uuid.UUID | None = None,
    status: models.MessageStatus = models.MessageStatus.COMPLETE,
) -> models.Message:
    return models.Message(
        id=message_id or uuid.uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        role=role.value,
        text=text,
        segments=None,
        web_search=False,
        status=status.value,
        change_seq=changes.next_change_seq(),
    )


def _card_set(*, user_id: int, conversation_id: uuid.UUID, message_id: uuid.UUID) -> models.CardSetProposal:
    return models.CardSetProposal(
        id=uuid.uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        title=CARD_SET_TITLE,
        cheat_sheet="- A perp never expires; funding keeps it near spot.\n- An option's buyer risks only the premium.",
        cards=[
            {
                "kind": models.CardKind.CONCEPT.value,
                "question": "What keeps a perpetual future's price near spot?",
                "answer": "The funding rate paid between longs and shorts.",
                "detail": [],
            }
        ],
        status=models.CardSetStatus.PROPOSED.value,
        change_seq=changes.next_change_seq(),
    )


def _rename(engine: sqlalchemy.Engine, *, conversation_id: uuid.UUID, title: str) -> None:
    """As the `rename_conversation` push action does."""
    with sqlalchemy.orm.Session(engine) as db:
        conversation = db.get_one(models.Conversation, conversation_id)
        changes.lock_user_writes(db, conversation.user_id)
        conversation.title = title
        changes.touch(conversation)
        db.commit()


def _conversation(engine: sqlalchemy.Engine, conversation_id: uuid.UUID) -> models.Conversation:
    with sqlalchemy.orm.Session(engine, expire_on_commit=False) as db:
        return db.get_one(models.Conversation, conversation_id)


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall)))


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _only_job(engine: sqlalchemy.Engine) -> models.Job:
    [job] = _jobs(engine)
    return job
