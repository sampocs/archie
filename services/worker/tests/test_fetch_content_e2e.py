"""`fetch_content` end to end: real jobs in a real Postgres, real handlers, HTTP replayed from recorded cassettes.

Re-record with `uv run pytest services/worker/tests/test_fetch_content_e2e.py --record-mode=once -m postgres`
after deleting a cassette. `url_title_from_missing_page` also holds one Haiku call (a fraction of a cent; needs
ANTHROPIC_API_KEY in the repo root .env).
"""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, jobs, models, pipeline, session
from archie_llm import llm
from archie_testing import recording
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
SHORT_PAGE_TITLE = "Example Domain"
# A made-up path with a descriptive slug: github.blog answers 404 for it, as it would for a page that was taken down.
MISSING_PAGE_TITLE = "How we rebuilt our merge queue for monorepos"
MISSING_PAGE_URL = "https://github.blog/engineering/how-we-rebuilt-our-merge-queue-for-monorepos/"
OG_IMAGE_ARTICLE_URL = "https://blog.bytebytego.com/p/how-netflix-uses-ai-agents-for-performance"
OG_IMAGE_ARTICLE_IMAGE = (
    "https://substackcdn.com/image/fetch/$s_!uk-_!,w_1200,h_675,c_fill,f_jpg,q_auto:good,fl_progressive:steep,g_auto/"
    "https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fpublic%2Fimages%2F"
    "aa461266-54bb-4caa-87bd-44e62109da52_2432x2038.png"
)
SAMA_AVATAR_URL = "https://pbs.twimg.com/profile_images/2046764873200394240/r7BxVezs_200x200.jpg"
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
    """Returns `use_cassette(name)`: the recorded HTTP for one source, shared across tests.

    Replay-only unless pytest is given `--record-mode`, so a normal run can never reach the network. Anthropic calls
    replay by model and system prompt.
    """
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
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
    assert source.image_url is None
    assert source.processing == models.ProcessingStatus.PROCESSING
    assert source.change_seq > seq_before
    assert _queued_kinds(engine) == [models.JobKind.EMBED, models.JobKind.ANALYZE, models.JobKind.PRIMER]
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.DONE


def test_an_article_with_og_image_gets_artwork_and_its_date(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The page's og:image becomes the source's absolute image_url, and its publication day its published_at."""
    source_id = _add_source(engine, url=OG_IMAGE_ARTICLE_URL, kind=models.SourceKind.ARTICLE)

    with replay("article_og_image"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).image_url == OG_IMAGE_ARTICLE_IMAGE
    assert _source(engine, source_id).published_at == datetime.datetime(2026, 11, 3, 12, tzinfo=datetime.UTC)


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
    assert _queued_kinds(engine) == [models.JobKind.EMBED, models.JobKind.ANALYZE, models.JobKind.PRIMER]


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


def test_a_short_article_capture_falls_back_to_the_page(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A capture that only caught the author box is replaced by the readable page, which titles the source."""
    source_id = _add_source(
        engine,
        url=ARTICLE_URL,
        kind=models.SourceKind.ARTICLE,
        capture=("Captured title - The Blog", "Jane Doe\n@jdoe-example\nDistinguished Engineer\n"),
    )

    with replay("article_greatwork") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 1
    assert len(_only_artifact(engine, source_id).content["text"].split()) > 1000
    source = _source(engine, source_id)
    assert source.processing != models.ProcessingStatus.FAILED
    assert source.title == "How to Do Great Work"


def test_a_short_capture_of_a_short_page_fails_but_keeps_the_captured_title(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """Both under the 50-word minimum: the job fails once, and the row shows Safari's title rather than the URL."""
    source_id = _add_source(
        engine, url=SHORT_PAGE_URL, kind=models.SourceKind.ARTICLE, capture=("Short title", "Only a few words here.")
    )

    with replay("title_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.processing == models.ProcessingStatus.FAILED
    assert source.processing_error == errors.FailureReason.TEXT_MISSING
    assert source.title == "Short title"
    assert _job(engine, models.JobKind.FETCH_CONTENT).attempts == 1


def test_an_x_thread_keeps_every_post_of_the_author_in_order(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """Sharing the first post of a 3-post thread stores all three, in order, titled by handle and first post."""
    source_id = _add_source(engine, url=SAMA_THREAD_URL, kind=models.SourceKind.X)

    with replay("x_thread_sama"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _only_artifact(engine, source_id).content["text"] == SAMA_THREAD_TEXT
    assert _source(engine, source_id).image_url == SAMA_AVATAR_URL
    # The first 80 characters of the first post, with its line breaks collapsed like any title's.
    assert (
        _source(engine, source_id).title
        == '@sama: looking up at the stars with extra awe tonight. "thy sea is so great and my boa'
    )
    assert _queued_kinds(engine) == [models.JobKind.EMBED, models.JobKind.ANALYZE, models.JobKind.PRIMER]


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


def test_a_short_page_keeps_its_own_title_when_the_job_fails(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The page was fetched but too short: its title survives the failure, and no model is asked (none is recorded)."""
    source_id = _add_source(engine, url=SHORT_PAGE_URL, kind=models.SourceKind.ARTICLE, is_whitelisted=True)

    with replay("title_page") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.processing_error == errors.FailureReason.TEXT_MISSING
    assert source.title == SHORT_PAGE_TITLE
    assert cassette.play_count == 1
    assert _llm_steps(engine) == []


def test_a_missing_page_without_any_title_gets_one_from_its_url(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A 404 leaves no page title and there is no capture: Haiku writes the title from the URL's slug."""
    source_id = _add_source(engine, url=MISSING_PAGE_URL, kind=models.SourceKind.ARTICLE, is_whitelisted=True)

    with replay("url_title_from_missing_page") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.processing == models.ProcessingStatus.FAILED
    assert source.processing_error == errors.FailureReason.TEXT_MISSING
    assert source.title == MISSING_PAGE_TITLE
    assert _job(engine, models.JobKind.FETCH_CONTENT).attempts == 1
    assert cassette.play_count == 2
    assert _llm_steps(engine) == [llm.URL_TITLE_STEP]


@pytest.mark.parametrize("has_capture", [False, True], ids=["existing-title", "capture-title"])
def test_a_source_with_a_title_makes_no_model_call(
    engine: sqlalchemy.Engine, replay: Replay, has_capture: bool
) -> None:
    """A title the source already has, or Safari's captured one, is the title: the URL is not sent to a model."""
    source_id = _add_source(
        engine,
        url=MISSING_PAGE_URL,
        kind=models.SourceKind.ARTICLE,
        title=None if has_capture else "My own title",
        capture=("Captured title", "Only a few words here.") if has_capture else None,
        is_whitelisted=True,
    )

    # The cassette holds a Haiku answer too, so a model request would show as a second play.
    with replay("url_title_from_missing_page") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).title == ("Captured title" if has_capture else "My own title")
    assert cassette.play_count == 1
    assert _llm_steps(engine) == []


def test_a_missing_page_without_a_key_still_fails_as_text_missing(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A user without an API key gets no model title and the same failure as before, not a needs-key one."""
    source_id = _add_source(engine, url=MISSING_PAGE_URL, kind=models.SourceKind.ARTICLE)

    with replay("url_title_from_missing_page") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.processing_error == errors.FailureReason.TEXT_MISSING
    assert source.title is None
    assert cassette.play_count == 1


def test_a_failed_model_call_leaves_the_title_empty_and_the_failure_unchanged(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The title is a nicety: an Anthropic error is logged, the job still fails once as text-missing."""

    def refuse(*args: object, **kwargs: object) -> llm.Completion:
        raise llm.ModelOutputError("no usable answer")

    monkeypatch.setattr(llm, "complete", refuse)
    source_id = _add_source(engine, url=MISSING_PAGE_URL, kind=models.SourceKind.ARTICLE, is_whitelisted=True)

    with replay("url_title_from_missing_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    source = _source(engine, source_id)
    assert source.processing_error == errors.FailureReason.TEXT_MISSING
    assert source.title is None
    assert _job(engine, models.JobKind.FETCH_CONTENT).attempts == 1


def test_a_source_deleted_during_the_title_call_is_left_alone(
    engine: sqlalchemy.Engine, replay: Replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user deletes the source while Haiku writes its title: the title is dropped, the job still fails."""
    source_id = _add_source(engine, url=MISSING_PAGE_URL, kind=models.SourceKind.ARTICLE, is_whitelisted=True)
    real_complete = llm.complete

    def complete_then_delete(*args: Any, **kwargs: Any) -> llm.Completion:
        completion = real_complete(*args, **kwargs)
        _delete_source(engine, source_id)
        return completion

    monkeypatch.setattr(llm, "complete", complete_then_delete)

    with replay("url_title_from_missing_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).title is None
    assert _job(engine, models.JobKind.FETCH_CONTENT).status == models.JobStatus.FAILED


def test_an_x_source_that_fails_gets_no_url_title(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """X posts are out of scope: an unparseable X URL fails as before without asking a model for a title."""
    source_id = _add_source(engine, url="https://x.com/sama", kind=models.SourceKind.X, is_whitelisted=True)

    with replay("no_requests"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _source(engine, source_id).title is None
    assert _llm_steps(engine) == []


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
    is_whitelisted: bool = False,
) -> uuid.UUID:
    """A user's source, its optional capture and its queued `fetch_content` job, as the sync push will create them."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}", is_whitelisted=is_whitelisted)
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


def _llm_steps(engine: sqlalchemy.Engine) -> list[str]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.LlmCall.step).order_by(models.LlmCall.id)))


def _queued_kinds(engine: sqlalchemy.Engine) -> list[models.JobKind]:
    with sqlalchemy.orm.Session(engine) as db:
        kinds = db.scalars(
            sqlalchemy.select(models.Job.kind)
            .where(models.Job.status == models.JobStatus.QUEUED.value)
            .order_by(models.Job.id)
        )
        return [models.JobKind(kind) for kind in kinds]
