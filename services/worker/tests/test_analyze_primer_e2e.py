"""Analyze and primer end to end: real jobs in a real Postgres, Anthropic replayed from recorded real responses.

Re-record with `uv run pytest services/worker/tests/test_analyze_primer_e2e.py --record-mode=once -m postgres`
after deleting a cassette (about a dollar-cent each; needs ANTHROPIC_API_KEY in the repo root .env).
- `analyze_greatwork` / `primer_greatwork`: Paul Graham's "How to Do Great Work" (an educational essay).
- `analyze_banter`: a sports-banter transcript, which the model should call entertainment.
- `analyze_unauthorized`: a real 401, recorded by sending a wrong key.
- `primer_refusal`: the one hand-edited cassette, see the comment at its top.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, jobs, models, pipeline, session
from archie_llm import llm
from archie_shared import config
from archie_shared.domains import Domain
from archie_testing import recording
from archie_worker import errors, handlers, loop, prompts

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[object]]

TESTS_DIR = pathlib.Path(__file__).parent
CASSETTE_DIR = TESTS_DIR / "cassettes"
GREATWORK_TEXT = (TESTS_DIR / "fixtures" / "greatwork.txt").read_text()
BANTER_TEXT = (TESTS_DIR / "fixtures" / "sports_banter.txt").read_text()
GREATWORK_URL = "https://www.paulgraham.com/greatwork.html"
GREATWORK_TITLE = "How to Do Great Work"
INVALID_API_KEY = "sk-ant-invalid"

MIN_CARDS = 3
MAX_CARDS = 5
MIN_FOUNDATION_CARDS = 2
CARE_NOTE = "how incentives shape what people work on"
DROP_QUESTION = "What year did Paul Graham write this essay?"


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


@pytest.fixture(autouse=True)
def no_embed_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Analyze and primer queue `embed`; `test_embed_e2e` covers that, and here it would take a loop turn."""
    monkeypatch.setattr(jobs, "enqueue_embed", lambda db, **kwargs: None)


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


def test_analyze_writes_a_summary_and_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """An educational essay gets a summary naming a known domain, 3-5 cards tied to it, and a costed Haiku call."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [summary] = _artifacts(engine, source_id, models.ArtifactKind.SUMMARY)
    assert summary.is_current
    assert summary.version == 1
    assert summary.model == llm.HAIKU
    assert summary.prompt_version == prompts.ANALYZE_PROMPT_VERSION
    assert summary.content["summary"]["gist"].strip()
    assert summary.content["domain"] in prompts.DOMAINS
    assert summary.content["is_educational"] is True
    # The essay has no timestamps, so the model must not invent them.
    assert all(idea["timestamp"] is None for idea in summary.content["summary"]["key_ideas"])

    cards = _cards(engine, source_id)
    assert MIN_CARDS <= len(cards) <= MAX_CARDS
    assert all(card.artifact_id == summary.id and card.deleted_at is None for card in cards)
    assert all(card.kind in prompts.CARD_KINDS and card.question.strip() and card.answer.strip() for card in cards)
    assert len({card.change_seq for card in cards}) == len(cards)
    assert _only_job(engine).status == models.JobStatus.DONE.value
    assert [(call.step, call.model) for call in _llm_calls(engine)] == [(models.JobKind.ANALYZE.value, llm.HAIKU)]
    assert _source(engine, source_id).processing == models.ProcessingStatus.PROCESSING.value


def test_newsletter_analyze_writes_a_summary_but_no_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Even when the model calls a newsletter educational, it gets a summary only: no cards, no primer, ready."""
    source_id = _add_source(engine, text=GREATWORK_TEXT, kind=models.SourceKind.NEWSLETTER)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    # The cassette's response is educational with cards, so only the newsletter rule can keep them out.
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [summary] = _artifacts(engine, source_id, models.ArtifactKind.SUMMARY)
    assert summary.content["is_educational"] is True
    assert _cards(engine, source_id) == []
    assert _artifacts(engine, source_id, models.ArtifactKind.PRIMER) == []
    assert _source(engine, source_id).processing == models.ProcessingStatus.READY.value
    # A ready inbox newsletter is one the brief now covers.
    assert [job.kind for job in _jobs(engine)] == [models.JobKind.ANALYZE.value, models.JobKind.UPDATE_BRIEF.value]


def test_a_newsletter_analyzed_after_going_deeper_gets_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Once the user went deeper the newsletter is consumed, and the re-run analyze gives it cards."""
    source_id = _add_source(engine, text=GREATWORK_TEXT, kind=models.SourceKind.NEWSLETTER)
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get(models.Source, source_id)
        assert source is not None
        source.state = models.SourceState.CONSUMED.value
        db.commit()
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert MIN_CARDS <= len(_cards(engine, source_id)) <= MAX_CARDS


def test_analyze_and_primer_together_make_the_source_ready(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The primer is stored as markdown from Sonnet, and the second of the two steps flips the source to ready."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE, models.JobKind.PRIMER)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    assert _source(engine, source_id).processing == models.ProcessingStatus.PROCESSING.value
    seq_before_ready = _source(engine, source_id).change_seq

    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [primer] = _artifacts(engine, source_id, models.ArtifactKind.PRIMER)
    assert primer.is_current
    assert primer.model == llm.SONNET
    assert primer.prompt_version == prompts.PRIMER_PROMPT_VERSION == "primer-v2"
    assert primer.content["markdown"].strip().startswith("#")
    assert "<foundation_cards>" not in primer.content["markdown"]

    source = _source(engine, source_id)
    assert source.processing == models.ProcessingStatus.READY.value
    assert source.change_seq > seq_before_ready
    assert {job.status for job in _jobs(engine)} == {models.JobStatus.DONE.value}
    assert [call.step for call in _llm_calls(engine)] == [models.JobKind.ANALYZE.value, models.JobKind.PRIMER.value]


def test_a_requested_newsletter_primer_returns_the_newsletter_to_ready(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """A summarized newsletter is processing while its requested primer is written, and ready once it lands."""
    source_id = _add_source(engine, text=GREATWORK_TEXT, kind=models.SourceKind.NEWSLETTER)
    _enqueue(engine, source_id, models.JobKind.ANALYZE, models.JobKind.PRIMER)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
        db.commit()

    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [primer] = _artifacts(engine, source_id, models.ArtifactKind.PRIMER)
    assert primer.is_current
    assert _source(engine, source_id).processing == models.ProcessingStatus.READY.value


def test_a_newsletter_stays_processing_while_its_primer_is_queued_behind_analyze(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """Analyze alone must not return a newsletter to ready while its primer job waits; the primer does."""
    source_id = _add_source(engine, text=GREATWORK_TEXT, kind=models.SourceKind.NEWSLETTER)
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
        db.commit()
    _enqueue(engine, source_id, models.JobKind.ANALYZE, models.JobKind.PRIMER)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    assert _source(engine, source_id).processing == models.ProcessingStatus.PROCESSING.value

    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    assert _source(engine, source_id).processing == models.ProcessingStatus.READY.value


def test_analyze_queues_filing_for_a_user_who_has_chosen_topics(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A never-filed source of a user with topics gets a `file_topic` job after its analyze."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _choose_topics(engine, source_id)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [analyze, filing] = _jobs(engine)
    assert (analyze.kind, analyze.status) == (models.JobKind.ANALYZE.value, models.JobStatus.DONE.value)
    assert (filing.kind, filing.status) == (models.JobKind.FILE_TOPIC.value, models.JobStatus.QUEUED.value)
    assert filing.payload == {pipeline.SOURCE_ID_KEY: str(source_id)}


def test_a_new_newsletter_is_filed_before_its_brief_is_rewritten(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """`file_topic` is queued ahead of `update_brief`, so the brief knows whether the newsletter is news or an essay."""
    source_id = _add_source(engine, text=GREATWORK_TEXT, kind=models.SourceKind.NEWSLETTER)
    _choose_topics(engine, source_id)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert [job.kind for job in _jobs(engine)] == [
        models.JobKind.ANALYZE.value,
        models.JobKind.FILE_TOPIC.value,
        models.JobKind.UPDATE_BRIEF.value,
    ]


def test_reanalyzing_a_filed_source_does_not_refile_it(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A source that already has a domain keeps its filing: no `file_topic` job is queued."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _choose_topics(engine, source_id, filed_domain=Domain.STARTUPS)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert [job.kind for job in _jobs(engine)] == [models.JobKind.ANALYZE.value]
    assert _source(engine, source_id).domain == Domain.STARTUPS.value


def test_entertainment_gets_a_summary_but_no_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Banter is summarized and marked not educational; no card is inserted."""
    source_id = _add_source(engine, text=BANTER_TEXT, kind=models.SourceKind.PODCAST, title="Sunday Reaction Show")
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    with replay("analyze_banter"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [summary] = _artifacts(engine, source_id, models.ArtifactKind.SUMMARY)
    assert summary.content["is_educational"] is False
    assert summary.content["summary"]["gist"].strip()
    assert _cards(engine, source_id) == []


def test_a_second_analyze_adds_a_version_and_replaces_the_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Re-running keeps summary v1 (no longer current), makes v2 current, retires v1's cards and inserts v2's."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    first_cards = _cards(engine, source_id)
    first_card_seqs = {card.id: card.change_seq for card in first_cards}

    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    first, second = _artifacts(engine, source_id, models.ArtifactKind.SUMMARY)
    assert (first.version, first.is_current) == (1, False)
    assert (second.version, second.is_current) == (2, True)

    cards = _cards(engine, source_id)
    retired = [card for card in cards if card.artifact_id == first.id]
    live = [card for card in cards if card.artifact_id == second.id]
    assert {card.id for card in retired} == set(first_card_seqs)
    assert all(card.deleted_at is not None and card.change_seq > first_card_seqs[card.id] for card in retired)
    assert MIN_CARDS <= len(live) <= MAX_CARDS
    assert all(card.deleted_at is None for card in live)
    assert len(cards) == len(retired) + len(live)


def test_a_rerun_that_finds_no_teaching_retires_the_old_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """If the new summary is not educational, the previous version's cards still go and none are added."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    # The banter recording stands in for the model changing its mind about this source.
    with replay("analyze_banter"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    live = [card for card in _cards(engine, source_id) if card.deleted_at is None]
    assert live == []
    assert len(_cards(engine, source_id)) >= MIN_CARDS


def test_a_user_without_the_owners_keys_fails_at_once_without_a_model_call(engine: sqlalchemy.Engine) -> None:
    """A non-whitelisted user's job is failed after one attempt, the source shows why, and nothing is billed."""
    source_id = _add_source(engine, text=GREATWORK_TEXT, is_whitelisted=False)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    # No cassette: a request would raise, since recorded mode "none" refuses the network.
    loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _only_job(engine)
    assert (job.attempts, job.status, job.last_error) == (
        1,
        models.JobStatus.FAILED.value,
        errors.FailureReason.NEEDS_API_KEY,
    )
    source = _source(engine, source_id)
    assert source.processing == models.ProcessingStatus.FAILED.value
    assert source.processing_error == errors.FailureReason.NEEDS_API_KEY
    assert _llm_calls(engine) == []
    assert _artifacts(engine, source_id, models.ArtifactKind.SUMMARY) == []


def test_an_api_error_is_retried_and_writes_nothing(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded 401 re-queues the job with its error kept; no artifact, card or cost row appears."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    # Set after the autouse fixture so recording sends a wrong key while replay is unaffected.
    monkeypatch.setenv(config.ANTHROPIC_API_KEY_ENV, INVALID_API_KEY)

    with replay("analyze_unauthorized"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _only_job(engine)
    assert (job.attempts, job.status) == (1, models.JobStatus.QUEUED.value)
    assert job.last_error is not None
    assert "401" in job.last_error or "authentication" in job.last_error.lower()
    assert _artifacts(engine, source_id, models.ArtifactKind.SUMMARY) == []
    assert _cards(engine, source_id) == []
    assert _llm_calls(engine) == []
    assert _source(engine, source_id).processing == models.ProcessingStatus.PROCESSING.value


def test_a_refused_primer_falls_back_to_opus(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Sonnet stops on a refusal, so Opus writes the primer; both calls are costed, the first as a refusal."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.PRIMER)

    with replay("primer_refusal"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [primer] = _artifacts(engine, source_id, models.ArtifactKind.PRIMER)
    assert primer.model == llm.OPUS
    assert primer.content["markdown"].strip()
    assert [(call.model, call.stop_reason) for call in _llm_calls(engine)] == [
        (llm.SONNET, "refusal"),
        (llm.OPUS, "end_turn"),
    ]
    assert _only_job(engine).status == models.JobStatus.DONE.value


@pytest.mark.parametrize("step", [models.JobKind.ANALYZE, models.JobKind.PRIMER])
def test_a_source_deleted_before_the_step_runs_is_left_alone(engine: sqlalchemy.Engine, step: models.JobKind) -> None:
    """No model call and no write for a tombstone; the job still completes."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, step)
    _delete_source(engine, source_id)
    seq_before = _source(engine, source_id).change_seq

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).change_seq == seq_before
    assert _artifacts(engine, source_id, models.ArtifactKind.SUMMARY) == []
    assert _artifacts(engine, source_id, models.ArtifactKind.PRIMER) == []
    assert _llm_calls(engine) == []
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_a_source_deleted_during_the_model_call_gets_nothing_written(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user deleting mid-call wins: the spend is recorded but no artifact or card is written."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    real_complete = llm.complete

    def complete_then_delete(*args: object, **kwargs: object) -> llm.Completion:
        completion = real_complete(*args, **kwargs)  # type: ignore[arg-type]
        _delete_source(engine, source_id)
        return completion

    monkeypatch.setattr(llm, "complete", complete_then_delete)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _artifacts(engine, source_id, models.ArtifactKind.SUMMARY) == []
    assert _cards(engine, source_id) == []
    assert len(_llm_calls(engine)) == 1
    assert _only_job(engine).status == models.JobStatus.DONE.value


def test_a_missing_text_artifact_is_retried(engine: sqlalchemy.Engine) -> None:
    """Without fetched text the job raises so the loop retries, and makes no model call."""
    source_id = _add_source(engine, text=None)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _only_job(engine)
    assert (job.attempts, job.status) == (1, models.JobStatus.QUEUED.value)
    assert _llm_calls(engine) == []


def test_user_message_wraps_the_text_below_the_source_details() -> None:
    """The source's details come first, then the text inside <text> tags."""
    message = prompts.user_message(kind=models.SourceKind.ARTICLE, title=None, url="https://example.com/a", text="body")

    assert message.startswith("Source kind: article\nTitle: (none)\nURL: https://example.com/a")
    assert message.endswith("<text>\nbody\n</text>")


def test_model_text_caps_untimed_text() -> None:
    """Only the first 200,000 characters of untimed text reach the model."""
    text = prompts.model_text({"text": "§" * (prompts.MAX_TEXT_CHARACTERS + 50)})

    assert text.count("§") == 200_000


def test_a_primer_writes_two_or_three_foundation_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The primer's foundation cards are stored on the source, tied to the primer artifact, and cut from its text."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.PRIMER)

    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [primer] = _artifacts(engine, source_id, models.ArtifactKind.PRIMER)
    assert primer.prompt_version == "primer-v2"
    assert "<foundation_cards>" not in primer.content["markdown"]
    assert "</foundation_cards>" not in primer.content["markdown"]

    cards = _live_cards(engine, source_id)
    assert MIN_FOUNDATION_CARDS <= len(cards) <= prompts.MAX_FOUNDATION_CARDS
    assert all(card.kind == models.CardKind.FOUNDATION.value for card in cards)
    assert all(card.artifact_id == primer.id and card.question.strip() and card.answer.strip() for card in cards)
    assert len({card.change_seq for card in cards}) == len(cards)


def test_a_rewritten_primer_replaces_only_its_foundation_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A second primer retires the first one's foundation cards and adds its own; the summary's cards stay."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE, models.JobKind.PRIMER)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    summary_cards = {card.id: card.change_seq for card in _live_cards(engine, source_id, foundation=False)}
    first_foundation = {card.id: card.change_seq for card in _live_cards(engine, source_id, foundation=True)}

    _enqueue(engine, source_id, models.JobKind.PRIMER)
    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    _first, second = _artifacts(engine, source_id, models.ArtifactKind.PRIMER)
    retired = [card for card in _cards(engine, source_id) if card.id in first_foundation]
    assert all(card.deleted_at is not None and card.change_seq > first_foundation[card.id] for card in retired)
    live_foundation = _live_cards(engine, source_id, foundation=True)
    assert MIN_FOUNDATION_CARDS <= len(live_foundation) <= prompts.MAX_FOUNDATION_CARDS
    assert all(card.artifact_id == second.id for card in live_foundation)
    assert {card.id: card.change_seq for card in _live_cards(engine, source_id, foundation=False)} == summary_cards


def test_reanalyzing_keeps_the_primers_foundation_cards(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A re-run analyze replaces only the summary's cards: foundation cards belong to the primer."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE, models.JobKind.PRIMER)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    first_summary_cards = {card.id for card in _live_cards(engine, source_id, foundation=False)}
    foundation = {card.id: card.change_seq for card in _live_cards(engine, source_id, foundation=True)}

    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert {card.id: card.change_seq for card in _live_cards(engine, source_id, foundation=True)} == foundation
    live_summary_cards = {card.id for card in _live_cards(engine, source_id, foundation=False)}
    assert MIN_CARDS <= len(live_summary_cards) <= MAX_CARDS
    assert live_summary_cards.isdisjoint(first_summary_cards)


def test_a_source_with_cards_off_gets_its_summary_and_primer_but_no_cards(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """While the user has cards off, analyze writes no summary cards and the primer no foundation cards."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, source_id).cards_off = True
        db.commit()
    _enqueue(engine, source_id, models.JobKind.ANALYZE, models.JobKind.PRIMER)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    [summary] = _artifacts(engine, source_id, models.ArtifactKind.SUMMARY)
    assert summary.content["is_educational"] is True
    [_primer] = _artifacts(engine, source_id, models.ArtifactKind.PRIMER)
    assert _cards(engine, source_id) == []


def test_card_steps_tell_the_model_the_users_card_preferences(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Analyze and primer both send the user's latest care and drop notes with the source's text."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _add_preferences(engine, source_id)
    _enqueue(engine, source_id, models.JobKind.ANALYZE, models.JobKind.PRIMER)
    sent_messages: list[str] = []
    real_complete = llm.complete

    def recording_complete(*args: object, **kwargs: object) -> llm.Completion:
        sent_messages.append(str(kwargs["user_message"]))
        return real_complete(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(llm, "complete", recording_complete)

    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    with replay("primer_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert len(sent_messages) == 2
    for message in sent_messages:
        assert "</text>\n\n<card_preferences>" in message
        assert f"- cares about: {CARE_NOTE}" in message
        assert f"- doesn't want cards like: {DROP_QUESTION}" in message


def test_split_primer_output_cuts_the_cards_block_and_caps_it() -> None:
    """A valid block leaves the primer's markdown and at most three cards."""
    cards = [{"question": f"Q{index}?", "answer": f"A{index}."} for index in range(4)]
    text = f"# Primer\n\nBody.\n\n<foundation_cards>{json.dumps(cards)}</foundation_cards>\n"

    output = prompts.split_primer_output(text)

    assert output.markdown == "# Primer\n\nBody."
    assert [(card.question, card.answer) for card in output.foundation_cards] == [
        ("Q0?", "A0."),
        ("Q1?", "A1."),
        ("Q2?", "A2."),
    ]


def test_split_primer_output_keeps_a_tag_mentioned_mid_text_before_the_real_block() -> None:
    """The block is the last opening tag, so an earlier mention stays in the markdown with the body after it."""
    cards = [{"question": "Q?", "answer": "A."}]
    body = "# P\n\nWe use a <foundation_cards> tag here.\n\nMore body."
    text = f"{body}\n\n<foundation_cards>{json.dumps(cards)}</foundation_cards>"

    output = prompts.split_primer_output(text)

    assert output.markdown == body
    assert [(card.question, card.answer) for card in output.foundation_cards] == [("Q?", "A.")]


def test_split_primer_output_drops_text_after_the_closing_tag() -> None:
    """Chatter after the block neither hides the cards nor leaves the raw tag in the markdown."""
    cards = [{"question": "Q?", "answer": "A."}]
    text = f"# P\n\nBody.\n\n<foundation_cards>{json.dumps(cards)}</foundation_cards>\n\nHope this helps!"

    output = prompts.split_primer_output(text)

    assert output.markdown == "# P\n\nBody."
    assert [(card.question, card.answer) for card in output.foundation_cards] == [("Q?", "A.")]


def test_split_primer_output_keeps_a_primer_without_cards_whole() -> None:
    """An older recording, or a model that left the block out, keeps all its text and has no cards."""
    text = "# Primer\n\nBody with <foundation_cards> mentioned mid-text.\n\nMore."

    output = prompts.split_primer_output(text)

    assert output == prompts.PrimerOutput(markdown=text, foundation_cards=[])


@pytest.mark.parametrize(
    "block",
    ['[{"question": "Q?", "answer": "A."', '[{"question": "", "answer": "A."}]', '{"question": "Q?"}'],
    ids=["broken-json", "empty-question", "not-a-list"],
)
def test_split_primer_output_drops_a_malformed_block(block: str) -> None:
    """A malformed block costs the cards, never the primer."""
    output = prompts.split_primer_output(f"# Primer\n\nBody.\n<foundation_cards>{block}</foundation_cards>")

    assert output == prompts.PrimerOutput(markdown="# Primer\n\nBody.", foundation_cards=[])


def test_preferences_block_is_empty_without_notes() -> None:
    """A user who said nothing about cards adds nothing to the message."""
    assert prompts.preferences_block([]) == ""


def test_preferences_block_lists_each_note_in_order() -> None:
    """Care notes and dropped questions each get their own line, in the order given."""
    block = prompts.preferences_block(
        [
            card_rows.PreferenceNote(kind=models.CardPreferenceKind.CARE, note=CARE_NOTE),
            card_rows.PreferenceNote(kind=models.CardPreferenceKind.DROP, note=DROP_QUESTION),
        ]
    )

    assert block.startswith("\n\n<card_preferences>\n")
    expected_lines = f"- cares about: {CARE_NOTE}\n- doesn't want cards like: {DROP_QUESTION}"
    assert block.endswith(f"{expected_lines}\n</card_preferences>")


def _add_source(
    engine: sqlalchemy.Engine,
    *,
    text: str | None,
    kind: models.SourceKind = models.SourceKind.ARTICLE,
    title: str = GREATWORK_TITLE,
    is_whitelisted: bool = True,
) -> uuid.UUID:
    """A user with a processing source, plus a current text artifact unless `text` is None."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        source = models.Source(
            id=source_id,
            user_id=user.id,
            url=GREATWORK_URL,
            normalized_url=GREATWORK_URL,
            title=title,
            kind=kind.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
        if text is not None:
            pipeline.write_artifact(
                db,
                source=source,
                kind=models.ArtifactKind.TEXT,
                content={"text": text},
                model=None,
                prompt_version=None,
            )
        db.commit()
    return source_id


def _choose_topics(engine: sqlalchemy.Engine, source_id: uuid.UUID, *, filed_domain: Domain | None = None) -> None:
    """Mark the source's user as having chosen topics, and the source as filed under `filed_domain` if given."""
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        changes.lock_user_writes(db, source.user_id)
        db.get_one(models.User, source.user_id).topics_chosen_at = sqlalchemy.func.now()
        if filed_domain is not None:
            source.domain = filed_domain.value
        db.commit()


def _add_preferences(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    """A care note and a dropped card's question for the source's user."""
    with sqlalchemy.orm.Session(engine) as db:
        user_id = db.get_one(models.Source, source_id).user_id
        db.add(models.CardPreference(user_id=user_id, kind=models.CardPreferenceKind.CARE.value, note=CARE_NOTE))
        db.add(models.CardPreference(user_id=user_id, kind=models.CardPreferenceKind.DROP.value, note=DROP_QUESTION))
        db.commit()


def _enqueue(engine: sqlalchemy.Engine, source_id: uuid.UUID, *steps: models.JobKind) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        for step in steps:
            jobs.enqueue(db, kind=step, user_id=source.user_id, payload={pipeline.SOURCE_ID_KEY: str(source_id)})
        db.commit()


def _delete_source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, source_id).deleted_at = sqlalchemy.func.now()
        db.commit()


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _artifacts(
    engine: sqlalchemy.Engine, source_id: uuid.UUID, kind: models.ArtifactKind
) -> list[models.SourceArtifact]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.SourceArtifact)
                .where(models.SourceArtifact.source_id == source_id, models.SourceArtifact.kind == kind.value)
                .order_by(models.SourceArtifact.version)
            )
        )


def _cards(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> list[models.Card]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Card).where(models.Card.source_id == source_id)))


def _live_cards(
    engine: sqlalchemy.Engine, source_id: uuid.UUID, *, foundation: bool | None = None
) -> list[models.Card]:
    """The source's live cards; only foundation cards (True) or only the summary's (False) when asked."""
    live = [card for card in _cards(engine, source_id) if card.deleted_at is None]
    if foundation is None:
        return live
    return [card for card in live if (card.kind == models.CardKind.FOUNDATION.value) == foundation]


def _llm_calls(engine: sqlalchemy.Engine) -> list[models.LlmCall]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall).order_by(models.LlmCall.id)))


def _jobs(engine: sqlalchemy.Engine) -> list[models.Job]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def _only_job(engine: sqlalchemy.Engine) -> models.Job:
    [job] = _jobs(engine)
    return job
