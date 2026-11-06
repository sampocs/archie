"""`update_brief` end to end: real jobs in a real Postgres, Anthropic replayed from a recorded real response.

The news is `fixtures/morning_brew.md` (the API's Morning Brew fixture as ingest stores it); the essay is the API's
ByteByteGo post, represented by `fixtures/bytebytego_analysis.json`, the summary its recorded `ingest_substack` analyze
produced (essays need only their gist). Re-record with
`uv run pytest services/worker/tests/test_update_brief_e2e.py --record-mode=once -m postgres` after deleting
`cassettes/brief_morning_brew.yaml` (a few cents of Sonnet; needs ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import datetime
import json
import pathlib
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import briefs, changes, jobs, models, pipeline, session, user_topics
from archie_llm import llm
from archie_shared.domains import Domain
from archie_testing import recording
from archie_worker import brief_content, content, errors, handlers, loop, prompts

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

TESTS_DIR = pathlib.Path(__file__).parent
CASSETTE_DIR = TESTS_DIR / "cassettes"
MORNING_BREW_TEXT = (TESTS_DIR / "fixtures" / "morning_brew.md").read_text()
BYTEBYTEGO_ANALYSIS: dict[str, Any] = json.loads((TESTS_DIR / "fixtures" / "bytebytego_analysis.json").read_text())
BYTEBYTEGO_GIST = BYTEBYTEGO_ANALYSIS["summary"]["gist"]
PREVIOUS_CONTENT: dict[str, Any] = {"domains": [], "also": [], "essays": [{"source_id": "x", "pitch": "Earlier."}]}

MIN_STORIES = 3
# Fixed, so the recorded answer's source ids name the newsletters again on replay.
MORNING_BREW_ID = uuid.UUID("6f0c1a52-3d4e-4b7a-9c1e-2a5b8d7e0f11")
BYTEBYTEGO_ID = uuid.UUID("9a2e4c71-5b8d-4f3a-8e6c-1d0b7a9f3c22")


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
BYTEBYTEGO = _Newsletter(
    sender="ByteByteGo",
    title="How Netflix Uses AI Agents for Performance Engineering",
    kind=models.NewsletterKind.ESSAY,
    text="The essay's text, never read by the brief.",
    analysis=BYTEBYTEGO_ANALYSIS,
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


def test_a_news_issue_and_an_essay_become_ranked_stories_and_a_pitch(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Sonnet's stories come back ordered and capped, citing only Morning Brew; the essay is pitched by its gist."""
    user_id = _add_user(engine, topics=[(Domain.AI, "AI agents"), (Domain.POLITICS, "US elections")])
    morning_brew = _add_newsletter(
        engine, user_id=user_id, newsletter=MORNING_BREW, age=datetime.timedelta(days=1), fixed_id=MORNING_BREW_ID
    )
    essay = _add_newsletter(
        engine, user_id=user_id, newsletter=BYTEBYTEGO, age=datetime.timedelta(hours=2), fixed_id=BYTEBYTEGO_ID
    )
    _add_newsletter(engine, user_id=user_id, newsletter=MORNING_BREW, state=models.SourceState.QUEUED)
    _enqueue(engine, user_id=user_id)

    with replay("brief_morning_brew"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    brief = _only_brief(engine)
    assert (brief.status, brief.version, brief.done_at) == (models.BriefStatus.OPEN.value, 1, None)
    assert brief.source_ids == [morning_brew, essay]
    assert brief.since == _source(engine, morning_brew).created_at

    assert brief.content is not None
    stored = brief_content.BriefContent.model_validate(brief.content)
    stories = [story for group in stored.domains for story in group.stories]
    tops = [group.stories[0].importance for group in stored.domains]
    assert MIN_STORIES <= len(stories) <= brief_content.MAX_STORIES
    assert tops == sorted(tops, reverse=True)
    assert all(
        [story.importance for story in group.stories]
        == sorted((story.importance for story in group.stories), reverse=True)
        for group in stored.domains
    )
    assert all(
        len(story.headline.split()) <= prompts.MAX_HEADLINE_WORDS and not story.headline.rstrip().endswith(".")
        for story in stories
    )
    assert len({group.domain for group in stored.domains}) == len(stored.domains)
    assert all(story.headline.strip() and story.body.strip() and story.detail.strip() for story in stories)
    cited = [*(story.source_ids for story in stories), *(line.source_ids for line in stored.also)]
    assert {source_id for source_ids in cited for source_id in source_ids} == {morning_brew}
    assert brief.content["essays"] == [{"source_id": str(essay), "pitch": BYTEBYTEGO_GIST}]

    assert [(call.step, call.model, call.source_id) for call in _llm_calls(engine)] == [
        (models.JobKind.UPDATE_BRIEF.value, llm.SONNET, None)
    ]
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_essays_alone_are_listed_without_a_model_call(engine: sqlalchemy.Engine) -> None:
    """No cassette: a request would fail the job, so finishing proves no call was made."""
    user_id = _add_user(engine)
    essay = _add_newsletter(engine, user_id=user_id, newsletter=BYTEBYTEGO)
    _enqueue(engine, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    brief = _only_brief(engine)
    assert brief.content == {"domains": [], "also": [], "essays": [{"source_id": str(essay), "pitch": BYTEBYTEGO_GIST}]}
    assert (brief.source_ids, brief.version) == ([essay], 1)
    assert _llm_calls(engine) == []
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_after_done_the_next_brief_holds_only_what_was_left_unbriefed(engine: sqlalchemy.Engine) -> None:
    """The done brief stays as it was; the new open one covers just the newsletter Done didn't brief."""
    user_id = _add_user(engine)
    briefed = _add_newsletter(engine, user_id=user_id, newsletter=BYTEBYTEGO, state=models.SourceState.BRIEFED)
    left = _add_newsletter(engine, user_id=user_id, newsletter=BYTEBYTEGO)
    done_id = _add_brief(
        engine, user_id=user_id, status=models.BriefStatus.DONE, content=PREVIOUS_CONTENT, source_ids=[briefed, left]
    )
    _enqueue(engine, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    done, opened = _briefs(engine)
    assert (done.id, done.status, done.content, done.version) == (
        done_id,
        models.BriefStatus.DONE.value,
        PREVIOUS_CONTENT,
        3,
    )
    assert (opened.status, opened.source_ids) == (models.BriefStatus.OPEN.value, [left])
    assert opened.content is not None and [essay["source_id"] for essay in opened.content["essays"]] == [str(left)]


def test_a_brief_left_covering_nothing_is_cleared(engine: sqlalchemy.Engine) -> None:
    """Every covered newsletter was queued: the content goes, as a new version so the phone pulls it."""
    user_id = _add_user(engine)
    queued = _add_newsletter(engine, user_id=user_id, newsletter=BYTEBYTEGO, state=models.SourceState.QUEUED)
    _add_brief(engine, user_id=user_id, content=PREVIOUS_CONTENT, source_ids=[queued])
    seq_before = _only_brief(engine).change_seq
    _enqueue(engine, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    brief = _only_brief(engine)
    assert (brief.status, brief.content, brief.source_ids, brief.since, brief.version) == (
        models.BriefStatus.OPEN.value,
        None,
        [],
        None,
        4,
    )
    assert brief.change_seq > seq_before


def test_nothing_covered_and_no_brief_opens_none(engine: sqlalchemy.Engine) -> None:
    """A newsletter deleted before the rewrite ran leaves no empty brief behind."""
    user_id = _add_user(engine)
    deleted = _add_newsletter(engine, user_id=user_id, newsletter=BYTEBYTEGO)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, deleted).deleted_at = sqlalchemy.func.now()
        db.commit()
    _enqueue(engine, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _briefs(engine) == []
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_a_failed_rewrite_keeps_the_previous_content(engine: sqlalchemy.Engine) -> None:
    """A user without the owner's keys fails at once on news; the brief keeps what it showed, at the same version."""
    user_id = _add_user(engine, is_whitelisted=False)
    news = _add_newsletter(engine, user_id=user_id, newsletter=MORNING_BREW)
    _add_brief(engine, user_id=user_id, content=PREVIOUS_CONTENT, source_ids=[])
    _enqueue(engine, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _only_job(engine)
    assert (job.status, job.last_error) == (models.JobStatus.FAILED.value, errors.FailureReason.NEEDS_API_KEY)
    brief = _only_brief(engine)
    assert (brief.content, brief.source_ids, brief.version) == (PREVIOUS_CONTENT, [], 3)
    assert _source(engine, news).state == models.SourceState.INBOX.value
    assert _llm_calls(engine) == []


def test_a_brief_finished_during_the_call_is_not_rewritten(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Done wins: the spend is recorded, the done brief keeps its content, and no new brief is opened."""
    user_id = _add_user(engine, topics=[(Domain.AI, "AI agents"), (Domain.POLITICS, "US elections")])
    _add_newsletter(engine, user_id=user_id, newsletter=MORNING_BREW, age=datetime.timedelta(days=1))
    _add_newsletter(engine, user_id=user_id, newsletter=BYTEBYTEGO, age=datetime.timedelta(hours=2))
    brief_id = _add_brief(engine, user_id=user_id, content=PREVIOUS_CONTENT, source_ids=[])
    _enqueue(engine, user_id=user_id)
    real_complete = llm.complete

    def complete_then_finish(*args: object, **kwargs: object) -> llm.Completion:
        completion = real_complete(*args, **kwargs)  # type: ignore[arg-type]
        with sqlalchemy.orm.Session(engine) as db:
            db.get_one(models.Brief, brief_id).status = models.BriefStatus.DONE.value
            db.commit()
        return completion

    monkeypatch.setattr(llm, "complete", complete_then_finish)

    with replay("brief_morning_brew"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    brief = _only_brief(engine)
    assert (brief.status, brief.content, brief.version) == (models.BriefStatus.DONE.value, PREVIOUS_CONTENT, 3)
    assert len(_llm_calls(engine)) == 1
    assert _only_job(engine).status == models.JobStatus.DONE.value


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


def _add_brief(
    engine: sqlalchemy.Engine,
    *,
    user_id: int,
    content: dict[str, Any],
    source_ids: list[uuid.UUID],
    status: models.BriefStatus = models.BriefStatus.OPEN,
) -> uuid.UUID:
    """A brief already at version 3."""
    brief_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Brief(
                id=brief_id,
                user_id=user_id,
                status=status.value,
                content=content,
                source_ids=source_ids,
                version=3,
                done_at=sqlalchemy.func.now() if status == models.BriefStatus.DONE else None,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    return brief_id


def _enqueue(engine: sqlalchemy.Engine, *, user_id: int) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        jobs.enqueue(db, kind=models.JobKind.UPDATE_BRIEF, user_id=user_id, payload={briefs.USER_ID_KEY: user_id})
        db.commit()


def _briefs(engine: sqlalchemy.Engine) -> list[models.Brief]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Brief).order_by(models.Brief.created_at, models.Brief.status)))


def _only_brief(engine: sqlalchemy.Engine) -> models.Brief:
    [brief] = _briefs(engine)
    return brief


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))


def _only_job(engine: sqlalchemy.Engine) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        [job] = db.scalars(sqlalchemy.select(models.Job))
        return job
