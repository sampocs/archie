"""`file_topic` end to end: real jobs in a real Postgres, Anthropic replayed from recorded real responses.

The summaries the step reads are written here (from `fixtures/greatwork.txt` and the API's Morning Brew fixture), not
taken from a model. Re-record one cassette with
`uv run pytest services/worker/tests/test_file_topic_e2e.py::<test> --record-mode=once -m postgres` after deleting it
(a fraction of a cent each; needs ANTHROPIC_API_KEY in the repo root .env).
- `file_topic_reuse`: "How to Do Great Work" against the owner's topics plus a careers topic.
- `file_topic_new`: the same essay against Sports topics only.
- `file_topic_removed`: the same essay against Sports topics, with the fitting topics removed.
- `file_topic_newsletter`: a Morning Brew digest against the owner's topics.
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session, user_topics
from archie_shared import topics
from archie_shared.domains import Domain
from archie_testing import recording
from archie_worker import errors, handlers, llm, loop, refile
from archie_worker.handlers import file_topic

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
GREATWORK_URL = "https://www.paulgraham.com/greatwork.html"
GREATWORK_TITLE = "How to Do Great Work"
MORNING_BREW_URL = "https://www.morningbrew.com/daily/issues/putting-it-to-a-vote"
MORNING_BREW_TITLE = "☕ Putting it to a vote"
CAREERS_TOPIC = "Careers & doing great work"
FOUNDER_LESSONS_TOPIC = "Founder lessons"
SPORTS_TOPICS = ("NFL play schemes", "Quarterbacks")
MAX_FILING_COST_USD = Decimal("0.001")

GREATWORK_ANALYSIS: dict[str, Any] = {
    "summary": {
        "gist": (
            "Paul Graham distills what people who did great work in many fields have in common: pick work you have "
            "both aptitude for and deep interest in, follow your curiosity to the frontier of a field, notice the gaps "
            "others overlook, and keep working on it steadily for years."
        ),
        "key_ideas": [
            {
                "timestamp": None,
                "idea": "Choose work you have a natural aptitude for and a deep interest in; "
                "if unsure, guess and start.",
            },
            {
                "timestamp": None,
                "idea": "Learn enough to reach the frontier of a field, then look for gaps: things that seem odd, "
                "missing or wrong to you but that others take for granted.",
            },
            {
                "timestamp": None,
                "idea": "Consistent effort compounds: working a few hours a day on something you care about beats "
                "occasional heroic bursts, and curiosity is the engine that keeps it going.",
            },
        ],
        "numbers": [],
    },
    "domain": "Other",
    "topic": "Doing great work",
    "tags": ["careers", "ambition", "curiosity", "creativity"],
    "concepts": ["aptitude and interest", "the frontier of a field", "compounding effort"],
    "is_educational": True,
    "cards": [],
}

MORNING_BREW_ANALYSIS: dict[str, Any] = {
    "summary": {
        "gist": (
            "Morning Brew's Election Day issue: a quick market recap, what is at stake in the US midterms, and a round "
            "of short business headlines."
        ),
        "key_ideas": [
            {
                "timestamp": None,
                "idea": "The midterms decide control of Congress, where Republicans hold narrow 218-214 House and "
                "53-47 Senate majorities; polls suggest Democrats might flip the House.",
            },
            {
                "timestamp": None,
                "idea": "Local ballots include 40+ data-center initiatives and California's proposed one-time 5% "
                "wealth tax on billionaires.",
            },
            {
                "timestamp": None,
                "idea": "Chipmaker Marvell agreed to buy Lumentum, which builds lasers and optical hardware for data "
                "centers, in a $115 billion bet on the AI build-out.",
            },
        ],
        "numbers": [],
    },
    "domain": "Finance",
    "topic": "US midterm elections",
    "tags": ["midterms", "Congress", "markets", "data centers"],
    "concepts": ["midterm elections", "wealth tax"],
    "is_educational": False,
    "cards": [],
}


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


# --- The server guard, on hand-made decisions ---


def test_a_name_matching_a_live_topic_files_there_under_its_domain(engine: sqlalchemy.Engine) -> None:
    """Case and punctuation aside, the model's name reuses the live topic, and the source takes that topic's domain."""
    user_id = _add_user(engine)
    _add_topics(engine, user_id=user_id, live={Domain.MACRO: ("Fed & monetary policy",)})
    source_id = _add_analyzed_source(engine, user_id=user_id)

    _apply(engine, source_id, _decision(domain=Domain.FINANCE, topic="fed and monetary-policy"))

    source = _source(engine, source_id)
    [topic] = _topics(engine, user_id)
    assert source.topic_id == topic.id
    assert source.domain == Domain.MACRO.value


def test_a_name_matching_a_removed_topic_keeps_the_domain_but_no_topic(engine: sqlalchemy.Engine) -> None:
    """The user removed that topic on purpose: no topic, nothing created, the decision's domain kept."""
    user_id = _add_user(engine)
    _add_topics(engine, user_id=user_id, removed={Domain.STARTUPS: (FOUNDER_LESSONS_TOPIC,)})
    source_id = _add_analyzed_source(engine, user_id=user_id)
    seq_before = _source(engine, source_id).change_seq

    _apply(engine, source_id, _decision(domain=Domain.STARTUPS, topic="founder  LESSONS"))

    source = _source(engine, source_id)
    assert source.topic_id is None
    assert source.domain == Domain.STARTUPS.value
    assert source.change_seq > seq_before
    assert len(_topics(engine, user_id)) == 1


def test_a_name_of_a_merged_topic_files_on_the_winner_and_creates_nothing(engine: sqlalchemy.Engine) -> None:
    """Filing doesn't bring a merged topic back: it follows the merge to the topic that took its place."""
    user_id = _add_user(engine)
    _add_topics(engine, user_id=user_id, live={Domain.MACRO: ("Fed & monetary policy", "Monetary history")})
    winner_id = _merge(engine, user_id=user_id, loser_name="Monetary history", winner_name="Fed & monetary policy")
    source_id = _add_analyzed_source(engine, user_id=user_id)

    _apply(engine, source_id, _decision(domain=Domain.HISTORY, topic="monetary history"))

    source = _source(engine, source_id)
    assert (source.topic_id, source.domain) == (winner_id, Domain.MACRO.value)
    assert len(_topics(engine, user_id)) == 2


def _merge(engine: sqlalchemy.Engine, *, user_id: int, loser_name: str, winner_name: str) -> uuid.UUID:
    """Point the loser at the winner, as the merge action does; returns the winner's id."""
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        by_name = {topic.name: topic for topic in db.scalars(sqlalchemy.select(models.Topic))}
        by_name[loser_name].merged_into_id = by_name[winner_name].id
        db.commit()
        return by_name[winner_name].id


def test_a_new_name_becomes_an_archie_topic_in_the_decisions_domain(engine: sqlalchemy.Engine) -> None:
    """Nothing matches, so exactly one `archie` topic is created and the source points at it."""
    user_id = _add_user(engine)
    _add_topics(engine, user_id=user_id, live={Domain.SPORTS: SPORTS_TOPICS})
    source_id = _add_analyzed_source(engine, user_id=user_id)

    _apply(engine, source_id, _decision(domain=Domain.STARTUPS, topic="Doing ambitious work"))

    [created] = [topic for topic in _topics(engine, user_id) if topic.name not in SPORTS_TOPICS]
    assert (created.name, created.domain, created.origin) == (
        "Doing ambitious work",
        Domain.STARTUPS.value,
        models.TopicOrigin.ARCHIE.value,
    )
    source = _source(engine, source_id)
    assert (source.topic_id, source.domain) == (created.id, Domain.STARTUPS.value)


def test_an_empty_name_files_under_the_domain_only(engine: sqlalchemy.Engine) -> None:
    """A blank topic creates nothing and leaves the source with just its domain."""
    user_id = _add_user(engine)
    source_id = _add_analyzed_source(engine, user_id=user_id)

    _apply(engine, source_id, _decision(domain=Domain.HISTORY, topic=""))

    source = _source(engine, source_id)
    assert (source.topic_id, source.domain) == (None, Domain.HISTORY.value)
    assert _topics(engine, user_id) == []


def test_a_newsletter_decision_writes_its_kind(engine: sqlalchemy.Engine) -> None:
    """The newsletter's kind is stored alongside its filing."""
    user_id = _add_user(engine)
    source_id = _add_analyzed_source(engine, user_id=user_id, kind=models.SourceKind.NEWSLETTER)

    _apply(
        engine,
        source_id,
        _decision(domain=Domain.POLITICS, topic="US politics", newsletter_kind=models.NewsletterKind.ESSAY),
    )

    assert _source(engine, source_id).newsletter_kind == models.NewsletterKind.ESSAY.value


def test_parse_decision_cleans_the_models_answer() -> None:
    """An unknown domain is Other, a non-newsletter's kind is dropped, and a long name is cut to 80 characters."""
    decision = file_topic.parse_decision(
        {"domain": "Tech", "topic": "x" * 120, "is_new": True, "newsletter_kind": "news"}, is_newsletter=False
    )

    assert decision.domain == Domain.OTHER
    assert decision.newsletter_kind is None
    assert decision.topic == "x" * user_topics.MAX_TOPIC_NAME_LENGTH

    newsletter = file_topic.parse_decision(
        {"domain": "politics", "topic": "US politics", "is_new": False, "newsletter_kind": "news"}, is_newsletter=True
    )
    assert (newsletter.domain, newsletter.newsletter_kind) == (Domain.POLITICS, models.NewsletterKind.NEWS)


# --- Recorded filing runs ---


def test_filing_reuses_one_of_the_users_topics(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """With a fitting topic on the list, the source is filed there, nothing is created, and one cheap Haiku call ran."""
    user_id = _add_user(engine, seed_owner_topics=True)
    _add_topics(engine, user_id=user_id, live={Domain.STARTUPS: (CAREERS_TOPIC,)})
    source_id = _add_analyzed_source(engine, user_id=user_id)
    topic_ids_before = {topic.id for topic in _topics(engine, user_id)}
    _enqueue_file_topic(engine, source_id)

    with replay("file_topic_reuse"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.topic_id in topic_ids_before
    assert {topic.id for topic in _topics(engine, user_id)} == topic_ids_before
    assert source.domain == _topic(engine, source.topic_id).domain
    assert source.newsletter_kind is None

    [call] = _llm_calls(engine)
    assert (call.step, call.model) == (models.JobKind.FILE_TOPIC.value, llm.HAIKU)
    assert call.cost_usd < MAX_FILING_COST_USD
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_filing_creates_a_topic_when_none_fits(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """An essay on doing great work fits no Sports topic, so a new `archie` topic is made for it."""
    user_id = _add_user(engine)
    _add_topics(engine, user_id=user_id, live={Domain.SPORTS: SPORTS_TOPICS})
    source_id = _add_analyzed_source(engine, user_id=user_id)
    _enqueue_file_topic(engine, source_id)

    with replay("file_topic_new"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [created] = [topic for topic in _topics(engine, user_id) if topic.name not in SPORTS_TOPICS]
    assert created.origin == models.TopicOrigin.ARCHIE.value
    source = _source(engine, source_id)
    assert (source.topic_id, source.domain) == (created.id, created.domain)


def test_filing_never_lands_on_a_removed_topic(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Whatever the model answers, the source's topic never normalizes to a name the user removed."""
    user_id = _add_user(engine)
    _add_topics(
        engine,
        user_id=user_id,
        live={Domain.SPORTS: SPORTS_TOPICS},
        removed={Domain.STARTUPS: (CAREERS_TOPIC, FOUNDER_LESSONS_TOPIC)},
    )
    source_id = _add_analyzed_source(engine, user_id=user_id)
    _enqueue_file_topic(engine, source_id)

    with replay("file_topic_removed"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.domain is not None
    removed_names = {topics.normalize_topic_name(name) for name in (CAREERS_TOPIC, FOUNDER_LESSONS_TOPIC)}
    if source.topic_id is not None:
        topic = _topic(engine, source.topic_id)
        assert topic.removed_at is None
        assert topics.normalize_topic_name(topic.name) not in removed_names


def test_a_digest_newsletter_is_filed_as_news(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Morning Brew's several short stories make it a `news` newsletter."""
    user_id = _add_user(engine, seed_owner_topics=True)
    source_id = _add_analyzed_source(
        engine,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        title=MORNING_BREW_TITLE,
        url=MORNING_BREW_URL,
        analysis=MORNING_BREW_ANALYSIS,
    )
    _enqueue_file_topic(engine, source_id)

    with replay("file_topic_newsletter"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.newsletter_kind == models.NewsletterKind.NEWS.value
    assert source.domain is not None
    [call] = _llm_calls(engine)
    assert call.cost_usd < MAX_FILING_COST_USD


# --- No model call ---


def test_a_user_without_the_owners_keys_fails_filing_but_not_the_source(engine: sqlalchemy.Engine) -> None:
    """The job fails at once with NEEDS_API_KEY; filing has no failure hook, so the source stays ready."""
    user_id = _add_user(engine, is_whitelisted=False)
    source_id = _add_analyzed_source(engine, user_id=user_id)
    _enqueue_file_topic(engine, source_id)

    # No cassette: a request would raise, since recorded mode "none" refuses the network.
    loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _only_job(engine)
    assert (job.status, job.last_error) == (models.JobStatus.FAILED.value, errors.FailureReason.NEEDS_API_KEY)
    source = _source(engine, source_id)
    assert (source.processing, source.processing_error) == (models.ProcessingStatus.READY.value, None)
    assert source.domain is None
    assert _llm_calls(engine) == []


def test_a_user_who_has_not_chosen_topics_is_not_filed(engine: sqlalchemy.Engine) -> None:
    """Before the picker, the job completes without a model call or a write."""
    user_id = _add_user(engine, topics_chosen=False)
    source_id = _add_analyzed_source(engine, user_id=user_id)
    seq_before = _source(engine, source_id).change_seq
    _enqueue_file_topic(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _only_job(engine).status == models.JobStatus.DONE.value
    assert _llm_calls(engine) == []
    assert _source(engine, source_id).change_seq == seq_before


# --- archie-refile-sources ---


def test_refile_queues_only_live_analyzed_sources_of_users_with_topics(engine: sqlalchemy.Engine) -> None:
    """A deleted source, an unanalyzed one, and a user who never chose topics are all skipped."""
    with_topics = _add_user(engine)
    without_topics = _add_user(engine, topics_chosen=False)
    analyzed = _add_analyzed_source(engine, user_id=with_topics)
    deleted = _add_analyzed_source(engine, user_id=with_topics)
    _add_analyzed_source(engine, user_id=with_topics, analysis=None)
    _add_analyzed_source(engine, user_id=without_topics)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, deleted).deleted_at = sqlalchemy.func.now()
        db.commit()

    with sqlalchemy.orm.Session(engine) as db:
        queued = refile.refile_all(db)
        db.commit()

    assert queued == 1
    [job] = _jobs(engine)
    assert job.kind == models.JobKind.FILE_TOPIC.value
    assert job.payload == {pipeline.SOURCE_ID_KEY: str(analyzed)}


def _decision(
    *, domain: Domain, topic: str, newsletter_kind: models.NewsletterKind | None = None
) -> file_topic.FilingDecision:
    return file_topic.FilingDecision(domain=domain, topic=topic, newsletter_kind=newsletter_kind)


def _apply(engine: sqlalchemy.Engine, source_id: uuid.UUID, decision: file_topic.FilingDecision) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        changes.lock_user_writes(db, source.user_id)
        file_topic.apply_filing(db, source=source, decision=decision)
        db.commit()


def _add_user(
    engine: sqlalchemy.Engine,
    *,
    topics_chosen: bool = True,
    is_whitelisted: bool = True,
    seed_owner_topics: bool = False,
) -> int:
    """A user who has chosen topics (none yet unless `seed_owner_topics`), or one who hasn't."""
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.flush()
        changes.lock_user_writes(db, user.id)
        if seed_owner_topics:
            user_topics.seed_owner_topics(db, user=user)
        elif topics_chosen:
            user.topics_chosen_at = sqlalchemy.func.now()
        db.commit()
        return user.id


def _add_topics(
    engine: sqlalchemy.Engine,
    *,
    user_id: int,
    live: Mapping[Domain, Sequence[str]] | None = None,
    removed: Mapping[Domain, Sequence[str]] | None = None,
) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        for names_by_domain, is_removed in ((live or {}, False), (removed or {}, True)):
            for domain, names in names_by_domain.items():
                for name in names:
                    user_topics.create_topic(
                        db,
                        user_id=user_id,
                        domain=domain,
                        name=name,
                        origin=models.TopicOrigin.USER,
                        removed=is_removed,
                    )
        db.commit()


def _add_analyzed_source(
    engine: sqlalchemy.Engine,
    *,
    user_id: int,
    kind: models.SourceKind = models.SourceKind.ARTICLE,
    title: str = GREATWORK_TITLE,
    url: str = GREATWORK_URL,
    analysis: dict[str, Any] | None = GREATWORK_ANALYSIS,
) -> uuid.UUID:
    """A ready, never-filed source with `analysis` as its current summary (no summary when None)."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        source = models.Source(
            id=source_id,
            user_id=user_id,
            url=url,
            normalized_url=f"{url}#{source_id}",
            title=title,
            kind=kind.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.READY)
        if analysis is not None:
            pipeline.write_artifact(
                db,
                source=source,
                kind=models.ArtifactKind.SUMMARY,
                content=analysis,
                model=llm.HAIKU,
                prompt_version="test",
            )
        db.commit()
    return source_id


def _enqueue_file_topic(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        user_topics.enqueue_file_topic(db, source=db.get_one(models.Source, source_id))
        db.commit()


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _topic(engine: sqlalchemy.Engine, topic_id: uuid.UUID | None) -> models.Topic:
    assert topic_id is not None
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Topic, topic_id)


def _topics(engine: sqlalchemy.Engine, user_id: int) -> list[models.Topic]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Topic).where(models.Topic.user_id == user_id)))


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _only_job(engine: sqlalchemy.Engine) -> models.Job:
    [job] = _jobs(engine)
    return job
