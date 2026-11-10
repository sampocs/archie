"""`news_quiz` end to end: real jobs in a real Postgres, Anthropic replayed from recorded real responses.

The first test builds its brief the way production does: `fixtures/morning_brew.md` through `update_brief` (replaying
`cassettes/brief_morning_brew.yaml`), then marks it Done a day ago. Re-record `news_quiz_morning_brew` and
`news_quiz_two_stories` by deleting them and running
`uv run pytest services/worker/tests/test_news_quiz_e2e.py --record-mode=once -m postgres` (a few cents of Haiku;
needs ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import briefs, card_rows, changes, jobs, models, pipeline, session, user_topics
from archie_llm import llm
from archie_shared.domains import Domain
from archie_testing import recording
from archie_worker import brief_content, content, errors, handlers, loop
from archie_worker.handlers import news_quiz

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

TESTS_DIR = pathlib.Path(__file__).parent
CASSETTE_DIR = TESTS_DIR / "cassettes"
# The card rules' ceiling on an answer.
MAX_ANSWER_WORDS = 15
MORNING_BREW_TEXT = (TESTS_DIR / "fixtures" / "morning_brew.md").read_text()
# Fixed, so the recorded update_brief answer's source ids name the newsletter again on replay.
MORNING_BREW_ID = uuid.UUID("6f0c1a52-3d4e-4b7a-9c1e-2a5b8d7e0f11")


@dataclass(frozen=True)
class _Newsletter:
    sender: str
    title: str
    kind: models.NewsletterKind | None
    text: str
    analysis: dict[str, Any]


MORNING_BREW = _Newsletter(
    sender="Morning Brew",
    title="☕ Putting it to a vote",
    kind=models.NewsletterKind.NEWS,
    text=MORNING_BREW_TEXT,
    analysis={"summary": {"gist": "Morning Brew's daily roundup.", "key_ideas": [], "numbers": []}},
)


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


def _add_user(
    engine: sqlalchemy.Engine, *, is_whitelisted: bool = True, topics: list[tuple[Domain, str]] | None = None
) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.flush()
        changes.lock_user_writes(db, user.id)
        for domain, name in topics or []:
            user_topics.create_topic(db, user_id=user.id, domain=domain, name=name, origin=models.TopicOrigin.USER)
        db.commit()
        return user.id


def _add_newsletter(
    engine: sqlalchemy.Engine,
    *,
    user_id: int,
    newsletter: _Newsletter,
    state: models.SourceState = models.SourceState.INBOX,
    age: datetime.timedelta = datetime.timedelta(hours=1),
    fixed_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A ready newsletter with its (cleaned) text and summary; no `update_brief` is queued for it."""
    source_id = fixed_id or uuid.uuid4()
    url = f"https://example.invalid/{source_id}"
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        source = models.Source(
            id=source_id,
            user_id=user_id,
            url=url,
            normalized_url=url,
            title=newsletter.title,
            sender=newsletter.sender,
            kind=models.SourceKind.NEWSLETTER.value,
            state=state.value,
            intent=models.SourceIntent.QUEUE.value,
            processing=models.ProcessingStatus.READY.value,
            newsletter_kind=newsletter.kind.value if newsletter.kind else None,
            created_at=datetime.datetime.now(datetime.UTC) - age,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.write_artifact(
            db,
            source=source,
            kind=models.ArtifactKind.TEXT,
            content={content.TEXT_KEY: newsletter.text, pipeline.CLEANED_KEY: True},
            model=None,
            prompt_version=None,
        )
        pipeline.write_artifact(
            db,
            source=source,
            kind=models.ArtifactKind.SUMMARY,
            content=newsletter.analysis,
            model=None,
            prompt_version=None,
        )
        db.commit()
    return source_id


def _enqueue_update_brief(engine: sqlalchemy.Engine, *, user_id: int) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        jobs.enqueue(db, kind=models.JobKind.UPDATE_BRIEF, user_id=user_id, payload={briefs.USER_ID_KEY: user_id})
        db.commit()


def _briefs(engine: sqlalchemy.Engine) -> list[models.Brief]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Brief).order_by(models.Brief.created_at, models.Brief.status)))


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))


def test_the_weeks_top_stories_become_quiz_cards_that_expire_in_a_week(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """A real brief, Done yesterday, yields up to five News cards tied to it, new and unscheduled, due to expire."""
    user_id = _add_user(engine, topics=[(Domain.AI, "AI agents"), (Domain.POLITICS, "US elections")])
    _add_newsletter(
        engine, user_id=user_id, newsletter=MORNING_BREW, age=datetime.timedelta(days=1), fixed_id=MORNING_BREW_ID
    )
    _enqueue_update_brief(engine, user_id=user_id)
    with replay("brief_morning_brew"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    brief_id = _done_a_day_ago(engine)
    story_count = sum(len(group.stories) for group in _brief_content(engine, brief_id).domains)
    _enqueue_quiz(engine, user_id=user_id)

    with replay("news_quiz_morning_brew"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    cards = _cards(engine)
    assert len(cards) == min(news_quiz.QUIZ_CARD_COUNT, story_count)
    assert all(
        card.brief_id == brief_id and card.source_id is None and card.kind == models.CardKind.QUIZ.value
        for card in cards
    )
    assert all(
        card.question.strip() and card.answer.strip() and card.fsrs_state == models.FsrsState.NEW.value
        for card in cards
    )
    assert len({card.change_seq for card in cards}) == len(cards)
    # The card rules, with a quiz card's detail at most one line.
    assert all(len(card.answer.split()) <= MAX_ANSWER_WORDS and "\n" not in card.detail for card in cards)
    assert any(card.detail for card in cards)
    now = datetime.datetime.now(datetime.UTC)
    expected = now + card_rows.QUIZ_LIFETIME
    assert all(
        card.expires_at is not None and abs(card.expires_at - expected) < datetime.timedelta(minutes=1)
        for card in cards
    )

    [update_call, quiz_call] = _llm_calls(engine)
    assert (quiz_call.step, quiz_call.model, quiz_call.source_id) == (models.JobKind.NEWS_QUIZ.value, llm.HAIKU, None)
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value] * 2


def test_a_second_run_in_the_same_week_writes_nothing_more(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The first run's cards are recent, so a duplicate job makes its call (replayed) but inserts no cards."""
    user_id = _add_user(engine)
    _add_done_brief(engine, user_id=user_id, stories=_TWO_STORIES, age=datetime.timedelta(days=1))
    _enqueue_quiz(engine, user_id=user_id)
    _enqueue_quiz(engine, user_id=user_id)

    with replay("news_quiz_two_stories"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
        first = _cards(engine)
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert len(first) == 2
    assert [card.id for card in _cards(engine)] == [card.id for card in first]
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value] * 2


def test_a_brief_with_two_stories_yields_two_cards_in_story_order(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Fewer stories than five: exactly one card per story, each citing the brief."""
    user_id = _add_user(engine)
    brief_id = _add_done_brief(engine, user_id=user_id, stories=_TWO_STORIES, age=datetime.timedelta(days=2))
    _enqueue_quiz(engine, user_id=user_id)

    with replay("news_quiz_two_stories"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    cards = _cards(engine)
    assert len(cards) == 2
    assert {card.brief_id for card in cards} == {brief_id}


def test_an_older_brief_is_not_quizzed_and_makes_no_model_call(engine: sqlalchemy.Engine) -> None:
    """No cassette: a request would fail the job, so finishing proves no call was made."""
    user_id = _add_user(engine)
    _add_done_brief(engine, user_id=user_id, stories=_TWO_STORIES, age=datetime.timedelta(days=8))
    _enqueue_quiz(engine, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _cards(engine) == []
    assert _llm_calls(engine) == []
    assert [job.status for job in _jobs(engine)] == [models.JobStatus.DONE.value]


def test_a_user_without_the_owners_keys_fails_at_once(engine: sqlalchemy.Engine) -> None:
    """No cassette and no cards: the job fails before any call."""
    user_id = _add_user(engine, is_whitelisted=False)
    _add_done_brief(engine, user_id=user_id, stories=_TWO_STORIES, age=datetime.timedelta(days=1))
    _enqueue_quiz(engine, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    [job] = _jobs(engine)
    assert (job.status, job.last_error) == (models.JobStatus.FAILED.value, errors.FailureReason.NEEDS_API_KEY)
    assert _cards(engine) == []


def _story(headline: str, *, importance: int, detail: str) -> brief_content.Story:
    return brief_content.Story(
        headline=headline,
        body=detail,
        why="It shapes what comes next.",
        detail=detail,
        importance=importance,
        source_ids=[uuid.uuid4()],
    )


_TWO_STORIES = [
    _story(
        "Fed holds rates steady",
        importance=9,
        detail="The Federal Reserve kept its benchmark rate unchanged, citing sticky inflation and a firm job market.",
    ),
    _story(
        "Chipmaker unveils new AI accelerator",
        importance=6,
        detail="A major chipmaker announced an accelerator it says trains large models twice as fast as its last one.",
    ),
]


def _add_done_brief(
    engine: sqlalchemy.Engine, *, user_id: int, stories: list[brief_content.Story], age: datetime.timedelta
) -> uuid.UUID:
    """A Done brief holding `stories` in one domain, finished `age` ago; our own data, not a model answer."""
    brief_id = uuid.uuid4()
    stored = brief_content.BriefContent(
        domains=[brief_content.DomainStories(domain=Domain.OTHER, stories=stories)], also=[], essays=[]
    )
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Brief(
                id=brief_id,
                user_id=user_id,
                status=models.BriefStatus.DONE.value,
                content=stored.to_json(),
                source_ids=[],
                version=1,
                done_at=sqlalchemy.func.now() - age,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    return brief_id


def _done_a_day_ago(engine: sqlalchemy.Engine) -> uuid.UUID:
    """Mark the only brief Done as of yesterday."""
    with sqlalchemy.orm.Session(engine) as db:
        [brief] = db.scalars(sqlalchemy.select(models.Brief))
        brief.status = models.BriefStatus.DONE.value
        brief.done_at = sqlalchemy.func.now() - datetime.timedelta(days=1)
        db.commit()
        return brief.id


def _brief_content(engine: sqlalchemy.Engine, brief_id: uuid.UUID) -> brief_content.BriefContent:
    with sqlalchemy.orm.Session(engine) as db:
        return brief_content.BriefContent.model_validate(db.get_one(models.Brief, brief_id).content)


def _enqueue_quiz(engine: sqlalchemy.Engine, *, user_id: int) -> None:
    payload = {briefs.USER_ID_KEY: user_id, card_rows.WEEK_START_KEY: "2026-11-01"}
    with sqlalchemy.orm.Session(engine) as db:
        jobs.enqueue(db, kind=models.JobKind.NEWS_QUIZ, user_id=user_id, payload=payload)
        db.commit()


def _cards(engine: sqlalchemy.Engine) -> list[models.Card]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Card).order_by(models.Card.change_seq)))


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))
