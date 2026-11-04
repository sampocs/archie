"""`fetch_content` end to end: real jobs in a real Postgres, real handlers, HTTP replayed from recorded cassettes.

Re-record with `uv run pytest services/worker/tests/test_fetch_content_e2e.py --record-mode=once -m postgres`
after deleting a cassette.
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, jobs, models, pipeline, session
from archie_worker import errors, handlers, loop
from archie_worker.content import x
from archie_worker.handlers import fetch_title

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[vcr_module.cassette.Cassette]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

ARTICLE_URL = "https://www.paulgraham.com/greatwork.html"
ARTICLE_TITLE = "How to Do Great Work"
# example.com has about 20 words, under the 50 an article needs.
SHORT_PAGE_URL = "https://example.com/"
SAMA_THREAD_URL = "https://x.com/sama/status/2107691261776052633"
SAMA_THREAD_TEXT = "\n\n".join(
    [
        'looking up at the stars with extra awe tonight.\n\n"thy sea is so great and my boat is so small."',
        "thank you to the machines, and the structure of reality, for letting us understand a little more.",
        "and thank you to the untold number of people who put in the technical work, brick by brick over the "
        "generations, to get us to the point where such a wonder is possible.",
    ]
)
X_ARTICLE_URL = "https://x.com/hwchase17/status/2116553654857867330"
X_QUOTE_URL = "https://x.com/hwchase17/status/2116230499140251964"


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> Replay:
    """Returns `use_cassette(name)`: the recorded HTTP for one source, shared across tests.

    Replay-only unless pytest is given `--record-mode`, so a normal run can never reach the network.
    """
    recorder = vcr_module.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode=request.config.getoption("--record-mode") or "none",
        filter_headers=["authorization", "cookie", "set-cookie"],
        decode_compressed_response=True,
    )
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def test_an_article_page_becomes_a_text_artifact_and_queues_analysis(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The fetched page's main text is stored as text v1, the title is set, and analyze + primer are queued."""
    source_id = _add_source(engine, url=ARTICLE_URL, kind=models.SourceKind.ARTICLE)
    seq_before = _source(engine, source_id).change_seq

    with replay("article_greatwork"):
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    source = _source(engine, source_id)
    artifact = _only_artifact(engine, source_id)
    assert (artifact.kind, artifact.version, artifact.is_current) == (models.ArtifactKind.TEXT, 1, True)
    assert (artifact.model, artifact.prompt_version) == (None, None)
    assert len(artifact.content["text"].split()) > 5000
    assert "If you collected lists of techniques for doing great work" in artifact.content["text"]
    assert source.title == ARTICLE_TITLE
    assert source.processing == models.ProcessingStatus.PROCESSING
    assert source.change_seq > seq_before
    assert _queued_kinds(engine) == [models.JobKind.ANALYZE, models.JobKind.PRIMER]
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.DONE


def test_an_existing_title_is_kept(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A title the source already has (typed or captured earlier) is not replaced by the page's."""
    source_id = _add_source(engine, url=ARTICLE_URL, kind=models.SourceKind.ARTICLE, title="My own title")

    with replay("article_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).title == "My own title"
    assert _only_artifact(engine, source_id).version == 1


def test_a_capture_is_cleaned_and_used_without_any_request(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The capture's title and cleaned text are used; the empty cassette raises on any request."""
    caption = "Photo: a long caption that the page repeats under every image"
    body = " ".join(f"word{index}" for index in range(60))
    source_id = _add_source(
        engine,
        url="https://paywalled.example/story",
        kind=models.SourceKind.ARTICLE,
        capture=("Captured title", f"{body}\n{caption}\n{caption}\n{caption}\n{caption}\n"),
    )

    with replay("no_requests") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 0
    text = _only_artifact(engine, source_id).content["text"]
    assert text == f"{body}\n{caption}\n{caption}"
    assert _source(engine, source_id).title == "Captured title"
    assert _queued_kinds(engine) == [models.JobKind.ANALYZE, models.JobKind.PRIMER]


def test_a_page_with_too_little_text_fails_the_job_once_and_the_source(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """example.com has under 50 words: one attempt, no artifact or follow-up jobs, and the source shows why."""
    source_id = _add_source(engine, url=SHORT_PAGE_URL, kind=models.SourceKind.ARTICLE)

    with replay("title_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _job(engine, models.JobKind.FETCH_CONTENT)
    assert (job.attempts, job.status, job.last_error) == (1, models.JobStatus.FAILED, errors.FailureReason.TEXT_MISSING)
    source = _source(engine, source_id)
    assert source.processing == models.ProcessingStatus.FAILED
    assert source.processing_error == errors.FailureReason.TEXT_MISSING
    assert _artifacts(engine, source_id) == []
    assert _queued_kinds(engine) == []


def test_a_short_capture_fails_like_a_short_page(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The 50-word minimum applies to captures too (the empty cassette raises on any request)."""
    source_id = _add_source(
        engine, url=SHORT_PAGE_URL, kind=models.SourceKind.ARTICLE, capture=("Short", "Only a few words here.")
    )

    with replay("no_requests"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).processing == models.ProcessingStatus.FAILED
    assert _job(engine, models.JobKind.FETCH_CONTENT).attempts == 1


def test_an_x_thread_keeps_every_post_of_the_author_in_order(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Sharing the first post of a 3-post thread stores all three, in order, titled by handle and first post."""
    source_id = _add_source(engine, url=SAMA_THREAD_URL, kind=models.SourceKind.X)

    with replay("x_thread_sama"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _only_artifact(engine, source_id).content["text"] == SAMA_THREAD_TEXT
    # The first 80 characters of the first post, with its line breaks collapsed like any title's.
    assert (
        _source(engine, source_id).title
        == '@sama: looking up at the stars with extra awe tonight. "thy sea is so great and my boa'
    )
    assert _queued_kinds(engine) == [models.JobKind.ANALYZE, models.JobKind.PRIMER]


def test_an_x_article_is_stored_with_its_title_and_body(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """An X Article's title becomes the source title and its blocks the text, well past the 279-character teaser."""
    source_id = _add_source(engine, url=X_ARTICLE_URL, kind=models.SourceKind.X)

    with replay("x_article"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).title == "New context engineering challenges in late 2026"
    assert len(_only_artifact(engine, source_id).content["text"]) > 5000


def test_an_x_quote_is_included(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A quote post stores the author's text and the quoted post's text."""
    source_id = _add_source(engine, url=X_QUOTE_URL, kind=models.SourceKind.X)

    with replay("x_quote"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    text = _only_artifact(engine, source_id).content["text"]
    assert "Quoting @nlarusstone: I hate to rain on everyone's parade" in text


@pytest.mark.parametrize(
    ("status", "fxtwitter_requests"),
    [(503, 3), (404, 3), (403, 1)],
    ids=["server-error-retried", "not-found-retried", "forbidden-not-retried"],
)
def test_x_falls_back_to_vxtwitter_when_fxtwitter_fails(
    engine: sqlalchemy.Engine,
    replay: Replay,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    fxtwitter_requests: int,
) -> None:
    """A recorded fxtwitter error (404 and 5xx are tried 3 times, others once) falls back to vxtwitter's post."""
    monkeypatch.setattr(x, "FXTWITTER_THREAD_URL", f"https://httpbin.org/status/{status}?post={{post_id}}")
    monkeypatch.setattr(x, "RETRY_DELAY_SECONDS", 0)
    source_id = _add_source(engine, url=SAMA_THREAD_URL, kind=models.SourceKind.X)

    with replay(f"x_fxtwitter_{status}") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == fxtwitter_requests + 1
    text = _only_artifact(engine, source_id).content["text"]
    assert text.startswith("looking up at the stars with extra awe tonight.")
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.DONE


def test_x_falls_back_to_vxtwitter_when_fxtwitter_answers_something_that_is_not_json(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded 200 HTML body from fxtwitter is not a thread, so vxtwitter's post is stored instead."""
    monkeypatch.setattr(x, "FXTWITTER_THREAD_URL", "https://httpbin.org/html?post={post_id}")
    source_id = _add_source(engine, url=SAMA_THREAD_URL, kind=models.SourceKind.X)

    with replay("x_fxtwitter_not_json") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 2
    text = _only_artifact(engine, source_id).content["text"]
    assert text.startswith("looking up at the stars with extra awe tonight.")
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.DONE


def test_x_falls_back_to_vxtwitter_when_fxtwitter_json_has_the_wrong_shape(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded 200 JSON body without a `status` post is not a thread, so vxtwitter's post is stored instead."""
    monkeypatch.setattr(x, "FXTWITTER_THREAD_URL", "https://httpbin.org/json?post={post_id}")
    source_id = _add_source(engine, url=SAMA_THREAD_URL, kind=models.SourceKind.X)

    with replay("x_fxtwitter_wrong_shape") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 2
    text = _only_artifact(engine, source_id).content["text"]
    assert text.startswith("looking up at the stars with extra awe tonight.")
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.DONE


def test_a_newsletter_without_a_capture_fails_at_once_without_fetching(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """A newsletter's URL is not a page: no request (the empty cassette raises on any), one attempt, email reason."""
    source_id = _add_source(engine, url="newsletter:<abc@mail.example>", kind=models.SourceKind.NEWSLETTER)

    with replay("no_requests"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _job(engine, models.JobKind.FETCH_CONTENT)
    assert (job.attempts, job.status) == (1, models.JobStatus.FAILED)
    assert _source(engine, source_id).processing_error == errors.FailureReason.NEWSLETTER_UNREADABLE


def test_a_short_newsletter_capture_fails_as_an_unreadable_email(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A newsletter capture under the word minimum is an unreadable email, not a page to share from Safari."""
    source_id = _add_source(
        engine,
        url="newsletter:<abc@mail.example>",
        kind=models.SourceKind.NEWSLETTER,
        capture=("Hi", "Only a few words here."),
    )

    with replay("no_requests"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).processing_error == errors.FailureReason.NEWSLETTER_UNREADABLE


def test_an_x_source_with_an_unparseable_url_fails_for_good(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """No post id means nothing to fetch (and no request): the job fails once with the text-missing reason."""
    source_id = _add_source(engine, url="https://x.com/sama", kind=models.SourceKind.X)

    with replay("no_requests"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).processing_error == errors.FailureReason.TEXT_MISSING
    assert _job(engine, models.JobKind.FETCH_CONTENT).attempts == 1


def test_a_server_error_from_the_page_is_retried(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A transient page failure is not permanent: the job is re-queued and the source stays processing."""
    source_id = _add_source(engine, url="https://httpbin.org/status/500", kind=models.SourceKind.ARTICLE)

    with replay("server_error"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _job(engine, models.JobKind.FETCH_CONTENT)
    assert (job.attempts, job.status) == (1, models.JobStatus.QUEUED)
    assert _source(engine, source_id).processing == models.ProcessingStatus.PROCESSING


@pytest.mark.parametrize("status", [401, 403, 404, 410, 451])
def test_a_blocked_or_missing_page_fails_for_good_without_a_retry(
    engine: sqlalchemy.Engine, replay: Replay, status: int
) -> None:
    """A paywall, block or missing page is not retried: one attempt, then the source fails as text-missing."""
    source_id = _add_source(engine, url=f"https://httpbin.org/status/{status}", kind=models.SourceKind.ARTICLE)

    with replay(f"page_status_{status}"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    job = _job(engine, models.JobKind.FETCH_CONTENT)
    assert (job.attempts, job.status) == (1, models.JobStatus.FAILED)
    assert _source(engine, source_id).processing_error == errors.FailureReason.TEXT_MISSING


def test_a_source_deleted_before_the_job_runs_is_left_alone(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """No request is made, nothing is written, and the tombstone keeps its change position."""
    source_id = _add_source(engine, url=ARTICLE_URL, kind=models.SourceKind.ARTICLE)
    _delete_source(engine, source_id)
    seq_before = _source(engine, source_id).change_seq

    with replay("no_requests"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert (source.processing, source.change_seq) == (models.ProcessingStatus.PENDING, seq_before)
    assert _artifacts(engine, source_id) == []
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.DONE


def test_a_source_deleted_during_the_fetch_gets_no_artifact(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user deletes the source while the page downloads: the fetched text is dropped and nothing is queued."""
    source_id = _add_source(engine, url=ARTICLE_URL, kind=models.SourceKind.ARTICLE)
    real_fetch_page = fetch_title.fetch_page

    def fetch_page_then_delete(*, url: str, timeout_seconds: float, max_bytes: int) -> str:
        page = real_fetch_page(url=url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
        _delete_source(engine, source_id)
        return page

    monkeypatch.setattr(fetch_title, "fetch_page", fetch_page_then_delete)

    with replay("article_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _artifacts(engine, source_id) == []
    assert _queued_kinds(engine) == []
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.DONE


def test_a_second_run_adds_version_two_of_the_text(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Running the step again (a retry) keeps v1 and makes v2 the current text."""
    source_id = _add_source(engine, url=ARTICLE_URL, kind=models.SourceKind.ARTICLE)
    with replay("article_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.FETCH_CONTENT])
        db.commit()
    with replay("article_greatwork"):
        while loop.run_one(engine, handlers=handlers.HANDLERS):
            pass

    versions = sorted((artifact.version, artifact.is_current) for artifact in _artifacts(engine, source_id))
    assert versions == [(1, False), (2, True)]


def _add_source(
    engine: sqlalchemy.Engine,
    *,
    url: str,
    kind: models.SourceKind,
    title: str | None = None,
    capture: tuple[str | None, str] | None = None,
) -> uuid.UUID:
    """A user's source, its optional capture and its queued `fetch_content` job, as the sync push will create them."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        db.add(
            models.Source(
                id=source_id,
                user_id=user.id,
                url=url,
                normalized_url=url,
                kind=kind.value,
                title=title,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        if capture is not None:
            db.add(models.SourceCapture(source_id=source_id, title=capture[0], text=capture[1]))
        jobs.enqueue(
            db,
            kind=models.JobKind.FETCH_CONTENT,
            user_id=user.id,
            payload={pipeline.SOURCE_ID_KEY: str(source_id)},
        )
        db.commit()
    return source_id


def _delete_source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.Source, source_id).deleted_at = sqlalchemy.func.now()
        db.commit()


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _artifacts(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> list[models.SourceArtifact]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(sqlalchemy.select(models.SourceArtifact).where(models.SourceArtifact.source_id == source_id))
        )


def _only_artifact(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.SourceArtifact:
    (artifact,) = _artifacts(engine, source_id)
    return artifact


def _job(engine: sqlalchemy.Engine, kind: models.JobKind) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        return db.execute(sqlalchemy.select(models.Job).where(models.Job.kind == kind.value)).scalar_one()


def _queued_kinds(engine: sqlalchemy.Engine) -> list[models.JobKind]:
    with sqlalchemy.orm.Session(engine) as db:
        kinds = db.scalars(
            sqlalchemy.select(models.Job.kind)
            .where(models.Job.status == models.JobStatus.QUEUED.value)
            .order_by(models.Job.id)
        )
        return [models.JobKind(kind) for kind in kinds]
