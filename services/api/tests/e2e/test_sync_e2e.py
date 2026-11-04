"""Sync through the real API: actions apply once and in order, and pulls never skip a row."""

import threading
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_shared import urls
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

PAGE_SIZE = 500
BATCH_SIZE = 50


def _add_source(url: str, *, action_id: uuid.UUID | None = None, intent: str = "queue", **extra: Any) -> dict[str, Any]:
    return {
        "id": str(action_id or uuid.uuid4()),
        "type": "add_source",
        "payload": {"id": str(uuid.uuid4()), "url": url, "intent": intent, **extra},
    }


def _retry_source(source_id: str) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": "retry_source", "payload": {"id": source_id}}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _pull_sources(authed: httpx.Client) -> dict[str, dict[str, Any]]:
    """Every source the caller can pull, by id."""
    rows = authed.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"]
    return {row["id"]: row for row in rows}


def _queued_jobs(live_stack: LiveStack) -> list[tuple[str, dict[str, Any]]]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return [(job.kind, job.payload) for job in db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id))]


def _set_processing(live_stack: LiveStack, *, source_id: str, processing: str, deleted: bool = False) -> None:
    """Put a source in a pipeline state the API alone can't reach (the worker would normally do this)."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get(models.Source, uuid.UUID(source_id))
        assert source is not None
        source.processing = processing
        if deleted:
            source.deleted_at = sqlalchemy.func.now()
        db.commit()


def _push_sources(authed: httpx.Client, *, count: int) -> None:
    for batch_start in range(0, count, BATCH_SIZE):
        urls = [f"https://example.com/{index}" for index in range(batch_start, batch_start + BATCH_SIZE)]
        actions = [_add_source(url) for url in urls]
        authed.post("/sync/push", json={"actions": actions}).raise_for_status()


def _pull_all_pages(authed: httpx.Client) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    position, more = 0, True
    while more:
        page = authed.get("/sync/pull", params={"since": position}).json()
        pages.append(page)
        position, more = page["position"], page["more"]
    return pages


def test_added_source_comes_back_in_a_pull(live_stack: LiveStack) -> None:
    """A pushed add_source appears in the next pull as a queued link, with a higher position."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")

    pushed = authed.post("/sync/push", json={"actions": [action]}).json()
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    assert pushed["results"] == [{"id": action["id"], "result": "applied", "reason": None}]
    assert [row["id"] for row in pulled["rows"]["sources"]] == [action["payload"]["id"]]
    assert pulled["rows"]["sources"][0]["state"] == "queued"
    assert pulled["position"] > 0


def test_an_article_url_starts_pending_with_a_fetch_content_job(live_stack: LiveStack) -> None:
    """An article or X link is classified, left pending, and queued for fetch_content (not fetch_title)."""
    authed = live_stack.authed(live_stack.sign_in())
    article = _add_source("https://example.com/a")
    post = _add_source("https://twitter.com/naval/status/123")

    _push(authed, article, post)
    sources = _pull_sources(authed)

    article_row, post_row = sources[article["payload"]["id"]], sources[post["payload"]["id"]]
    assert (article_row["kind"], article_row["processing"], article_row["state"]) == ("article", "pending", "queued")
    assert (post_row["kind"], post_row["processing"]) == ("x", "pending")
    assert _queued_jobs(live_stack) == [
        ("fetch_content", {"source_id": article["payload"]["id"]}),
        ("fetch_content", {"source_id": post["payload"]["id"]}),
    ]


@pytest.mark.parametrize(
    ("url", "kind"),
    [("https://www.youtube.com/watch?v=abc123", "youtube"), ("https://open.spotify.com/episode/abc123", "podcast")],
)
def test_a_youtube_video_or_podcast_episode_starts_the_pipeline(live_stack: LiveStack, url: str, kind: str) -> None:
    """Video and episode links are fetched like articles: pending with one fetch_content job and no error."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source(url)

    _push(authed, action)
    row = _pull_sources(authed)[action["payload"]["id"]]

    assert (row["kind"], row["processing"], row["processing_error"], row["sender"]) == (kind, "pending", None, None)
    assert _queued_jobs(live_stack) == [("fetch_content", {"source_id": action["payload"]["id"]})]


@pytest.mark.parametrize(
    ("url", "kind", "reason"),
    [
        ("https://open.spotify.com/show/abc123", "podcast", "Share an episode, not the show."),
        ("https://podcasts.apple.com/us/podcast/some-show/id123456", "podcast", "Share an episode, not the show."),
        ("https://www.youtube.com/@somechannel", "youtube", "Share a video, not the channel."),
        ("https://www.youtube.com/playlist?list=PL123", "youtube", "Share a video, not the playlist."),
    ],
)
def test_a_show_channel_or_playlist_link_is_unsupported_with_a_reason_and_only_gets_a_title(
    live_stack: LiveStack, url: str, kind: str, reason: str
) -> None:
    """Show, channel and playlist links can't be processed: unsupported, told why, and only the title is fetched."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source(url)

    _push(authed, action)
    row = _pull_sources(authed)[action["payload"]["id"]]

    assert (row["kind"], row["processing"], row["processing_error"]) == (kind, "unsupported", reason)
    assert _queued_jobs(live_stack) == [("fetch_title", {"source_id": action["payload"]["id"]})]


def test_a_finished_source_starts_consumed(live_stack: LiveStack) -> None:
    """Intent finished starts the source consumed."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a", intent="finished")

    _push(authed, action)

    assert _pull_sources(authed)[action["payload"]["id"]]["state"] == "consumed"


def test_reaction_note_and_prep_me_are_stored_and_synced(live_stack: LiveStack) -> None:
    """Optional fields reach the row and the pull: reaction on a finished capture, prep_me on a queued one."""
    authed = live_stack.authed(live_stack.sign_in())
    finished = _add_source("https://example.com/a", intent="finished", reaction="mostly", note="good")
    queued = _add_source("https://example.com/b", prep_me=True)

    _push(authed, finished, queued)
    sources = _pull_sources(authed)

    finished_row, queued_row = sources[finished["payload"]["id"]], sources[queued["payload"]["id"]]
    assert (finished_row["reaction"], finished_row["note"], finished_row["prep_me"]) == ("mostly", "good", False)
    assert (queued_row["reaction"], queued_row["prep_me"]) == (None, True)
    assert (finished_row["processing_error"], finished_row["merged_into_id"]) == (None, None)


def test_a_capture_is_stored_for_the_pipeline(live_stack: LiveStack) -> None:
    """A Safari capture lands in source_captures and is never part of the pull."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a", capture={"title": "T", "text": "body text"})

    _push(authed, action)

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        capture = db.get(models.SourceCapture, uuid.UUID(action["payload"]["id"]))
        assert capture is not None
        assert (capture.title, capture.text) == ("T", "body text")
    assert "capture" not in _pull_sources(authed)[action["payload"]["id"]]


def test_a_capture_without_a_title_is_stored(live_stack: LiveStack) -> None:
    """The capture title is optional."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a", capture={"text": "body text"})

    assert _push(authed, action)[0]["result"] == "applied"

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        capture = db.get(models.SourceCapture, uuid.UUID(action["payload"]["id"]))
        assert capture is not None and capture.title is None


@pytest.mark.parametrize(
    ("extra", "intent", "reason"),
    [
        ({"reaction": "great"}, "finished", "reaction must be easy, mostly or lost"),
        ({"reaction": "easy"}, "queue", "reaction needs intent finished"),
        ({"prep_me": True}, "finished", "prep_me needs intent queue"),
        ({"note": "x" * 2001}, "queue", "note is longer than 2000 characters"),
        ({"capture": {"text": ""}}, "queue", "capture text is empty"),
        ({"capture": {"text": "  \n"}}, "queue", "capture text is empty"),
        ({"capture": {"text": "x" * 400_001}}, "queue", "capture text is longer than 400000 characters"),
        ({"capture": {"text": "ok", "title": "x" * 501}}, "queue", "capture title is longer than 500 characters"),
        ({"capture": {"title": "no text"}}, "queue", "payload needs id, url and intent"),
        ({"note": 5}, "queue", "payload needs id, url and intent"),
    ],
)
def test_each_invalid_capture_field_is_rejected_with_its_reason(
    live_stack: LiveStack, extra: dict[str, Any], intent: str, reason: str
) -> None:
    """Every validation rule rejects with a specific reason and leaves nothing behind."""
    authed = live_stack.authed(live_stack.sign_in())

    result = _push(authed, _add_source("https://example.com/a", intent=intent, **extra))[0]

    assert (result["result"], result["reason"]) == ("rejected", reason)
    assert _pull_sources(authed) == {}
    assert _queued_jobs(live_stack) == []


def test_boundary_values_are_accepted(live_stack: LiveStack) -> None:
    """A 2,000-character note, a 400,000-character capture and a 500-character title are all allowed."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a", note="x" * 2000, capture={"text": "x" * 400_000, "title": "x" * 500})

    assert _push(authed, action)[0]["result"] == "applied"


def test_a_duplicate_url_merges_into_the_existing_source(live_stack: LiveStack) -> None:
    """The same page shared again (tracking noise aside) is stored deleted and folded into the original."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    before = _pull_sources(authed)[original["payload"]["id"]]

    duplicate = _add_source("https://example.com/a/?utm_source=x", intent="finished", reaction="lost", note="n")
    result = _push(authed, duplicate)[0]
    sources = _pull_sources(authed)

    merged_row, kept = sources[duplicate["payload"]["id"]], sources[original["payload"]["id"]]
    assert result["result"] == "applied"
    assert merged_row["deleted_at"] is not None
    assert merged_row["merged_into_id"] == original["payload"]["id"]
    assert (kept["state"], kept["intent"]) == ("consumed", "finished")
    assert (kept["reaction"], kept["note"]) == ("lost", "n")
    assert kept["deleted_at"] is None and kept["merged_into_id"] is None
    assert kept["change_seq"] > before["change_seq"]
    assert len({kept["change_seq"], merged_row["change_seq"], before["change_seq"]}) == 3
    # The duplicate starts no second pipeline run.
    assert _queued_jobs(live_stack) == [("fetch_content", {"source_id": original["payload"]["id"]})]


def test_a_duplicate_never_moves_a_source_backwards(live_stack: LiveStack) -> None:
    """Re-sharing a finished source as queue leaves it consumed and finished, and never sets prep_me on it."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a", intent="finished", reaction="easy", note="keep", prep_me=False)
    _push(authed, original)

    _push(authed, _add_source("https://example.com/a", intent="queue", prep_me=True))
    kept = _pull_sources(authed)[original["payload"]["id"]]

    assert (kept["state"], kept["intent"]) == ("consumed", "finished")
    assert (kept["reaction"], kept["note"], kept["prep_me"]) == ("easy", "keep", False)


def test_a_duplicate_does_not_advance_a_source_the_user_is_already_reading(live_stack: LiveStack) -> None:
    """Only queued moves to consumed; an inbox source keeps its state when re-shared as finished."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        source = db.get(models.Source, uuid.UUID(original["payload"]["id"]))
        assert source is not None
        source.state = "inbox"
        db.commit()

    _push(authed, _add_source("https://example.com/a", intent="finished"))

    assert _pull_sources(authed)[original["payload"]["id"]]["state"] == "inbox"


def test_a_duplicate_stores_a_capture_only_when_the_source_has_none(live_stack: LiveStack) -> None:
    """The first capture wins; a later duplicate's capture is dropped."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    source_id = uuid.UUID(original["payload"]["id"])
    engine = session.engine_for(live_stack.database_url)

    _push(authed, _add_source("https://example.com/a?utm_medium=y", capture={"text": "first"}))
    _push(authed, _add_source("https://example.com/a?utm_medium=z", capture={"text": "second"}))

    with sqlalchemy.orm.Session(engine) as db:
        capture = db.get(models.SourceCapture, source_id)
        assert capture is not None and capture.text == "first"


def test_a_duplicate_of_a_failed_source_with_a_capture_restarts_it(live_stack: LiveStack) -> None:
    """Sharing a failed article again with a capture is a retry: the capture is stored and the steps queue again."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="failed")

    _push(authed, _add_source("https://example.com/a?utm_source=x", capture={"text": "body"}))

    assert _pull_sources(authed)[original["payload"]["id"]]["processing"] == "processing"
    assert _queued_jobs(live_stack) == [("fetch_content", {"source_id": original["payload"]["id"]})] * 2
    with sqlalchemy.orm.Session(session.engine_for(live_stack.database_url)) as db:
        capture = db.get(models.SourceCapture, uuid.UUID(original["payload"]["id"]))
        assert capture is not None and capture.text == "body"


def test_a_duplicate_of_a_failed_source_without_a_capture_does_not_restart_it(live_stack: LiveStack) -> None:
    """Without a capture there is nothing new to process, so a failed source stays failed but still moves forward."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="failed")
    before = _pull_sources(authed)[original["payload"]["id"]]

    _push(authed, _add_source("https://example.com/a?utm_source=x"))

    after = _pull_sources(authed)[original["payload"]["id"]]
    assert after["processing"] == "failed"
    assert len(_queued_jobs(live_stack)) == 1
    assert after["change_seq"] > before["change_seq"]


def test_a_duplicate_of_a_ready_source_does_not_reprocess_it(live_stack: LiveStack) -> None:
    """Only failed sources restart; a ready one keeps its processing status and gets no jobs."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="ready")

    _push(authed, _add_source("https://example.com/a?utm_source=x"))

    assert _pull_sources(authed)[original["payload"]["id"]]["processing"] == "ready"
    assert len(_queued_jobs(live_stack)) == 1


def test_a_deleted_source_is_not_a_duplicate_target(live_stack: LiveStack) -> None:
    """Sharing a URL whose earlier source was deleted creates a fresh source."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="ready", deleted=True)

    fresh = _add_source("https://example.com/a")
    _push(authed, fresh)

    row = _pull_sources(authed)[fresh["payload"]["id"]]
    assert (row["deleted_at"], row["merged_into_id"]) == (None, None)


def test_another_users_source_is_not_a_duplicate_target(live_stack: LiveStack) -> None:
    """Duplicate detection is per user."""
    first = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    second = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    _push(first, _add_source("https://example.com/a"))

    mine = _add_source("https://example.com/a")
    _push(second, mine)

    assert _pull_sources(second)[mine["payload"]["id"]]["merged_into_id"] is None


def test_retry_source_restarts_a_failed_source_from_fetching(live_stack: LiveStack) -> None:
    """A failed source with no text goes back to processing and queues fetch_content."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="failed")
    before = _pull_sources(authed)[original["payload"]["id"]]

    result = _push(authed, _retry_source(original["payload"]["id"]))[0]
    row = _pull_sources(authed)[original["payload"]["id"]]

    assert result["result"] == "applied"
    assert (row["processing"], row["processing_error"]) == ("processing", None)
    assert row["change_seq"] > before["change_seq"]
    assert _queued_jobs(live_stack)[1:] == [("fetch_content", {"source_id": original["payload"]["id"]})]


def test_retry_source_skips_fetching_when_the_text_exists(live_stack: LiveStack) -> None:
    """With the text already stored, a retry queues only the generation steps that have no output."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    source_id = uuid.UUID(original["payload"]["id"])
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="failed")
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, authed.get("/me").json()["user_id"])
        db.add(_artifact(db, source_id=source_id, kind="text", version=1))
        db.commit()

    _push(authed, _retry_source(original["payload"]["id"]))

    assert _queued_jobs(live_stack)[1:] == [
        ("analyze", {"source_id": original["payload"]["id"]}),
        ("primer", {"source_id": original["payload"]["id"]}),
    ]


@pytest.mark.parametrize("processing", ["ready", "pending", "processing", "unsupported"])
def test_retry_source_is_rejected_unless_the_source_failed(live_stack: LiveStack, processing: str) -> None:
    """Only a failed source can be retried; any other status is rejected and queues nothing."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing=processing)

    result = _push(authed, _retry_source(original["payload"]["id"]))[0]

    assert (result["result"], result["reason"]) == ("rejected", "source is not failed")
    assert len(_queued_jobs(live_stack)) == 1


def test_retry_source_is_rejected_for_a_deleted_source(live_stack: LiveStack) -> None:
    """A deleted source can't be retried even if its processing failed."""
    authed = live_stack.authed(live_stack.sign_in())
    original = _add_source("https://example.com/a")
    _push(authed, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="failed", deleted=True)

    result = _push(authed, _retry_source(original["payload"]["id"]))[0]

    assert (result["result"], result["reason"]) == ("rejected", "source is not failed")


def test_retry_source_is_rejected_for_another_users_source_and_unknown_ids(live_stack: LiveStack) -> None:
    """Retrying someone else's failed source, or an id that doesn't exist, changes nothing."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    intruder = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    original = _add_source("https://example.com/a")
    _push(owner, original)
    _set_processing(live_stack, source_id=original["payload"]["id"], processing="failed")

    results = _push(intruder, _retry_source(original["payload"]["id"]), _retry_source(str(uuid.uuid4())))

    assert [(result["result"], result["reason"]) for result in results] == [("rejected", "source is not failed")] * 2
    assert _pull_sources(owner)[original["payload"]["id"]]["processing"] == "failed"
    assert len(_queued_jobs(live_stack)) == 1


def test_retry_source_with_a_malformed_payload_is_rejected(live_stack: LiveStack) -> None:
    """A retry without a valid id is rejected with a reason, not a 500."""
    authed = live_stack.authed(live_stack.sign_in())
    action = {"id": str(uuid.uuid4()), "type": "retry_source", "payload": {"id": "not-a-uuid"}}

    result = _push(authed, action)[0]

    assert (result["result"], result["reason"]) == ("rejected", "payload needs id")


def test_a_retried_action_is_applied_once(live_stack: LiveStack) -> None:
    """Pushing the same action id twice returns duplicate and leaves one source."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")

    authed.post("/sync/push", json={"actions": [action]})
    second = authed.post("/sync/push", json={"actions": [action]}).json()
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    assert second["results"][0]["result"] == "duplicate"
    assert len(pulled["rows"]["sources"]) == 1


def test_a_rejected_action_does_not_block_later_ones(live_stack: LiveStack) -> None:
    """A non-http URL is rejected with a reason; the next action in the batch still applies."""
    authed = live_stack.authed(live_stack.sign_in())
    bad, good = _add_source("ftp://example.com"), _add_source("https://example.com/ok")

    results = authed.post("/sync/push", json={"actions": [bad, good]}).json()["results"]

    assert results[0]["result"] == "rejected" and results[0]["reason"]
    assert results[1]["result"] == "applied"


def test_each_invalid_add_source_is_rejected_with_a_reason(live_stack: LiveStack) -> None:
    """Over-long URLs, hostless URLs, unknown intents and malformed payloads are rejected; retries are duplicates."""
    authed = live_stack.authed(live_stack.sign_in())
    too_long = _add_source("https://example.com/" + "a" * 2048)
    hostless = _add_source("https:///path")
    bad_intent = _add_source("https://example.com/a", intent="someday")
    malformed = {"id": str(uuid.uuid4()), "type": "add_source", "payload": {"url": "https://example.com"}}
    batch = [too_long, hostless, bad_intent, malformed]

    first = authed.post("/sync/push", json={"actions": batch}).json()["results"]
    retried = authed.post("/sync/push", json={"actions": batch}).json()["results"]

    assert [result["result"] for result in first] == ["rejected"] * 4
    assert all(result["reason"] for result in first)
    assert [result["result"] for result in retried] == ["duplicate"] * 4
    assert authed.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def test_a_reused_source_id_is_rejected_even_for_the_same_user(live_stack: LiveStack) -> None:
    """Re-adding an existing source id under a new action id is rejected and leaves the row alone."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")
    authed.post("/sync/push", json={"actions": [action]})

    again = {**action, "id": str(uuid.uuid4())}
    result = authed.post("/sync/push", json={"actions": [again]}).json()["results"][0]

    assert result["result"] == "rejected"
    assert len(authed.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"]) == 1


def test_a_source_id_owned_by_another_user_is_rejected(live_stack: LiveStack) -> None:
    """Reusing someone else's source id is rejected instead of overwriting their row."""
    first = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    second = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    action = _add_source("https://example.com/a")
    first.post("/sync/push", json={"actions": [action]})

    stolen = {**action, "id": str(uuid.uuid4())}
    result = second.post("/sync/push", json={"actions": [stolen]}).json()["results"][0]

    assert result["result"] == "rejected"
    assert second.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []
    assert first.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"][0]["url"] == "https://example.com/a"


def test_a_pull_only_returns_the_callers_rows(live_stack: LiveStack) -> None:
    """Another user's sources never appear in a pull."""
    first = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    second = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    first.post("/sync/push", json={"actions": [_add_source("https://example.com/a")]})

    assert second.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def test_more_than_fifty_actions_are_refused(live_stack: LiveStack) -> None:
    """A push over the batch limit is a 422 and applies nothing."""
    authed = live_stack.authed(live_stack.sign_in())

    response = authed.post("/sync/push", json={"actions": [_add_source("https://example.com/a")] * 51})

    assert response.status_code == 422


def test_pull_does_not_skip_a_row_committed_after_a_later_one(live_stack: LiveStack) -> None:
    """A write holding the user's lock blocks a push, so the pull position can never jump past it."""
    session_key = live_stack.sign_in()
    authed = live_stack.authed(session_key)
    engine = session.engine_for(live_stack.database_url)
    user_id = authed.get("/me").json()["user_id"]

    # Writer A: takes the lock and a position, and stays uncommitted.
    slow_writer = sqlalchemy.orm.Session(engine)
    # Writer B: a push through the API, which must wait for A. It gets its own client for the longer timeout.
    pusher = httpx.Client(base_url=live_stack.base_url, headers={"Authorization": f"Bearer {session_key}"}, timeout=10)
    # Closing in finally releases the advisory lock even when an assertion fails, so later tests can't hang.
    try:
        changes.lock_user_writes(slow_writer, user_id)
        slow_source_id = uuid.uuid4()
        slow_writer.add(
            models.Source(
                id=slow_source_id,
                user_id=user_id,
                url="https://example.com/slow",
                normalized_url="https://example.com/slow",
                kind="link",
                state="queued",
                intent="queue",
                change_seq=slow_writer.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one(),
            )
        )
        slow_writer.flush()

        push_thread = threading.Thread(
            target=lambda: pusher.post("/sync/push", json={"actions": [_add_source("https://example.com/fast")]})
        )
        push_thread.start()
        push_thread.join(timeout=0.5)
        assert push_thread.is_alive()

        mid = authed.get("/sync/pull", params={"since": 0}).json()
        assert mid["rows"]["sources"] == []

        slow_writer.commit()
        push_thread.join(timeout=5)
        assert not push_thread.is_alive()
        final_rows = authed.get("/sync/pull", params={"since": mid["position"]}).json()["rows"]["sources"]
    finally:
        slow_writer.close()
        pusher.close()

    assert len(final_rows) == 2
    assert str(slow_source_id) in {row["id"] for row in final_rows}


def test_unparseable_urls_are_rejected_without_blocking_later_actions(live_stack: LiveStack) -> None:
    """A malformed or NUL-bearing url is a rejection, not a 500, so a retried batch can't wedge the outbox."""
    authed = live_stack.authed(live_stack.sign_in())
    actions = [
        _add_source("http://[::1"),
        _add_source("https://example.com/\u0000"),
        _add_source("https://example.com/ok"),
    ]

    response = authed.post("/sync/push", json={"actions": actions})

    assert response.status_code == 200
    assert [(result["result"], result["reason"]) for result in response.json()["results"]] == [
        ("rejected", "url is not a valid URL"),
        ("rejected", "url is not a valid URL"),
        ("applied", None),
    ]


def test_another_users_action_id_is_rejected_and_leaves_the_owner_untouched(live_stack: LiveStack) -> None:
    """Action ids are global: B reusing A's id is refused, and A's pull is unchanged."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    intruder = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    action = _add_source("https://example.com/a")
    owner.post("/sync/push", json={"actions": [action]})
    before = owner.get("/sync/pull", params={"since": 0}).json()

    stolen = _add_source("https://example.com/b", action_id=uuid.UUID(action["id"]))
    result = intruder.post("/sync/push", json={"actions": [stolen]}).json()["results"]

    assert result == [{"id": action["id"], "result": "rejected", "reason": "action id already used"}]
    assert owner.get("/sync/pull", params={"since": 0}).json() == before
    assert intruder.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def _race_push_against_uncommitted_insert(
    live_stack: LiveStack, *, rival_row: Any, pushed_action: dict[str, Any], pusher_key: str
) -> dict[str, Any]:
    """Push while another transaction holds an uncommitted row with a clashing key, then let it commit.

    The push passes its existence checks (the rival is uncommitted), blocks on the unique index, and hits an
    IntegrityError once the rival commits. Returns the push's single result.
    """
    engine = session.engine_for(live_stack.database_url)
    rival = sqlalchemy.orm.Session(engine)
    pusher = httpx.Client(base_url=live_stack.base_url, headers={"Authorization": f"Bearer {pusher_key}"}, timeout=10)
    responses: list[httpx.Response] = []
    try:
        rival.add(rival_row)
        rival.flush()

        push_thread = threading.Thread(
            target=lambda: responses.append(pusher.post("/sync/push", json={"actions": [pushed_action]}))
        )
        push_thread.start()
        push_thread.join(timeout=0.5)
        assert push_thread.is_alive()

        rival.commit()
        push_thread.join(timeout=5)
        assert not push_thread.is_alive()
    finally:
        rival.close()
        pusher.close()

    assert responses[0].status_code == 200
    return responses[0].json()["results"][0]


def test_two_users_racing_on_one_action_id_rejects_the_loser(live_stack: LiveStack) -> None:
    """The unique index on action ids decides the race; the loser is told so and records nothing."""
    winner_key = live_stack.sign_in(apple_sub="user-a")
    loser_key = live_stack.sign_in(apple_sub="user-b")
    winner_id = live_stack.authed(winner_key).get("/me").json()["user_id"]
    action = _add_source("https://example.com/b")

    result = _race_push_against_uncommitted_insert(
        live_stack,
        rival_row=models.AppliedAction(action_id=uuid.UUID(action["id"]), user_id=winner_id, result="applied"),
        pushed_action=action,
        pusher_key=loser_key,
    )

    assert result == {"id": action["id"], "result": "rejected", "reason": "action id already used"}
    assert live_stack.authed(loser_key).get("/sync/pull", params={"since": 0}).json()["rows"]["sources"] == []


def test_two_users_racing_on_one_source_id_rejects_the_loser(live_stack: LiveStack) -> None:
    """The unique index on source ids decides the race; the loser's action is recorded as rejected."""
    winner_key = live_stack.sign_in(apple_sub="user-a")
    loser_key = live_stack.sign_in(apple_sub="user-b")
    winner_id = live_stack.authed(winner_key).get("/me").json()["user_id"]
    action = _add_source("https://example.com/b")
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as seq_db:
        change_seq = seq_db.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one()
        seq_db.commit()
    rival_source = models.Source(
        id=uuid.UUID(action["payload"]["id"]),
        user_id=winner_id,
        url="https://example.com/a",
        normalized_url="https://example.com/a",
        kind="link",
        state="queued",
        intent="queue",
        change_seq=change_seq,
    )

    result = _race_push_against_uncommitted_insert(
        live_stack, rival_row=rival_source, pushed_action=action, pusher_key=loser_key
    )

    assert result == {"id": action["id"], "result": "rejected", "reason": "source id already exists"}
    retried = live_stack.authed(loser_key).post("/sync/push", json={"actions": [action]}).json()["results"]
    assert retried[0]["result"] == "duplicate"


def test_pull_pages_until_more_is_false(live_stack: LiveStack) -> None:
    """With more rows than one page, following positions returns every row exactly once."""
    authed = live_stack.authed(live_stack.sign_in())
    _push_sources(authed, count=550)

    pages = _pull_all_pages(authed)

    seen = [row["id"] for page in pages for row in page["rows"]["sources"]]
    assert [len(page["rows"]["sources"]) for page in pages] == [PAGE_SIZE, 50]
    assert len(seen) == 550 and len(set(seen)) == 550


def test_a_pull_of_exactly_one_page_ends_with_an_empty_page(live_stack: LiveStack) -> None:
    """At exactly 500 rows the first page says more, and the follow-up is empty with the position unchanged."""
    authed = live_stack.authed(live_stack.sign_in())
    _push_sources(authed, count=PAGE_SIZE)

    pages = _pull_all_pages(authed)

    assert [(len(page["rows"]["sources"]), page["more"]) for page in pages] == [(PAGE_SIZE, True), (0, False)]
    assert pages[1]["position"] == pages[0]["position"]


def _artifact(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID, kind: str, version: int) -> models.SourceArtifact:
    source = db.get(models.Source, source_id)
    assert source is not None
    return models.SourceArtifact(
        id=uuid.uuid4(),
        user_id=source.user_id,
        source_id=source_id,
        kind=kind,
        version=version,
        content={"text": "t"},
        is_current=version == 1,
        change_seq=db.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one(),
    )


def test_pull_pages_across_sources_artifacts_and_cards(live_stack: LiveStack) -> None:
    """With changed rows in all three tables, pages hold 500 rows in total and every row appears exactly once."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = authed.get("/me").json()["user_id"]
    engine = session.engine_for(live_stack.database_url)
    expected: set[str] = set()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)

        def next_seq() -> int:
            return db.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one()

        # Interleaved so every page boundary cuts through all three tables.
        for index in range(220):
            source = models.Source(
                id=uuid.uuid4(),
                user_id=user_id,
                url=f"https://example.com/{index}",
                normalized_url=f"https://example.com/{index}",
                kind="article",
                state="queued",
                intent="queue",
                change_seq=next_seq(),
            )
            artifact = models.SourceArtifact(
                id=uuid.uuid4(),
                user_id=user_id,
                source_id=source.id,
                kind="summary",
                version=1,
                content={"headline": str(index)},
                is_current=True,
                change_seq=next_seq(),
            )
            card = models.Card(
                id=uuid.uuid4(),
                user_id=user_id,
                source_id=source.id,
                artifact_id=artifact.id,
                kind="concept",
                question="q",
                answer="a",
                change_seq=next_seq(),
            )
            db.add(source)
            db.flush()
            db.add(artifact)
            db.flush()
            db.add(card)
            expected |= {str(source.id), str(artifact.id), str(card.id)}
        # Text artifacts are server-only: they take a position but must never be pulled.
        db.flush()
        text_source = db.scalars(sqlalchemy.select(models.Source)).first()
        assert text_source is not None
        db.add(_artifact(db, source_id=text_source.id, kind="text", version=1))
        db.commit()

    pages = _pull_all_pages(authed)

    row_ids = [
        row["id"] for page in pages for table in ("sources", "artifacts", "cards") for row in page["rows"][table]
    ]
    page_sizes = [sum(len(rows) for rows in page["rows"].values()) for page in pages]
    positions = [page["position"] for page in pages]
    assert page_sizes == [PAGE_SIZE, 160]
    assert len(row_ids) == 660 and set(row_ids) == expected
    assert positions == sorted(positions)
    assert [page["more"] for page in pages] == [True, False]
    first_artifact = next(row for page in pages for row in page["rows"]["artifacts"])
    assert set(first_artifact) == {
        "id",
        "source_id",
        "kind",
        "version",
        "content",
        "is_current",
        "created_at",
        "change_seq",
    }


def _insert_m1_link(
    live_stack: LiveStack, *, user_id: int, url: str, kind: models.SourceKind = models.SourceKind.LINK
) -> uuid.UUID:
    """Insert an `unsupported` source as M1 (kind `link`) or M2 (a real kind, no error) left it."""
    source_id = uuid.uuid4()
    # M1 stored the URL as shared (migration 0002); only M2 kinds were normalized.
    normalized_url = url if kind == models.SourceKind.LINK else urls.normalize_url(url)
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        db.add(
            models.Source(
                id=source_id,
                user_id=user_id,
                url=url,
                normalized_url=normalized_url,
                kind=kind.value,
                state=models.SourceState.QUEUED.value,
                intent=models.SourceIntent.QUEUE.value,
                processing=models.ProcessingStatus.UNSUPPORTED.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    return source_id


def test_sharing_an_m1_article_link_classifies_it_and_starts_the_pipeline(live_stack: LiveStack) -> None:
    """A fresh share of an M1 `link` row's page re-classifies it and queues fetch_content instead of staying stuck."""
    authed = live_stack.authed(live_stack.sign_in())
    url = "https://example.com/old"
    source_id = _insert_m1_link(live_stack, user_id=authed.get("/me").json()["user_id"], url=url)
    before = _pull_sources(authed)[str(source_id)]

    result = _push(authed, _add_source(url))[0]
    row = _pull_sources(authed)[str(source_id)]

    assert result["result"] == "applied"
    assert (row["kind"], row["processing"]) == ("article", "pending")
    assert row["change_seq"] > before["change_seq"]
    assert _queued_jobs(live_stack) == [("fetch_content", {"source_id": str(source_id)})]


def test_sharing_an_m1_youtube_link_classifies_it_and_starts_the_pipeline(live_stack: LiveStack) -> None:
    """An M1 link to a YouTube video is re-classified and queues fetch_content."""
    authed = live_stack.authed(live_stack.sign_in())
    url = "https://youtube.com/watch?v=abc123"
    source_id = _insert_m1_link(live_stack, user_id=authed.get("/me").json()["user_id"], url=url)
    before = _pull_sources(authed)[str(source_id)]

    _push(authed, _add_source(url))
    row = _pull_sources(authed)[str(source_id)]

    assert (row["kind"], row["processing"]) == ("youtube", "pending")
    assert row["change_seq"] > before["change_seq"]
    assert _queued_jobs(live_stack) == [("fetch_content", {"source_id": str(source_id)})]


def test_sharing_an_m1_spotify_show_link_classifies_it_but_leaves_it_unsupported(live_stack: LiveStack) -> None:
    """An M1 link to a show is re-classified only: it stays unsupported and queues no fetch."""
    authed = live_stack.authed(live_stack.sign_in())
    url = "https://open.spotify.com/show/abc123"
    source_id = _insert_m1_link(live_stack, user_id=authed.get("/me").json()["user_id"], url=url)
    before = _pull_sources(authed)[str(source_id)]

    _push(authed, _add_source(url))
    row = _pull_sources(authed)[str(source_id)]

    assert (row["kind"], row["processing"]) == ("podcast", "unsupported")
    assert row["processing_error"] == "Share an episode, not the show."
    assert row["change_seq"] > before["change_seq"]
    assert "fetch_content" not in [kind for kind, _ in _queued_jobs(live_stack)]


def test_sharing_an_m2_unsupported_youtube_video_starts_the_pipeline(live_stack: LiveStack) -> None:
    """M2 stored every YouTube share as unsupported with no error; sharing the video again now processes it."""
    authed = live_stack.authed(live_stack.sign_in())
    url = "https://www.youtube.com/watch?v=abc123"
    source_id = _insert_m1_link(
        live_stack, user_id=authed.get("/me").json()["user_id"], url=url, kind=models.SourceKind.YOUTUBE
    )

    _push(authed, _add_source(url))
    row = _pull_sources(authed)[str(source_id)]

    assert (row["kind"], row["processing"], row["processing_error"]) == ("youtube", "pending", None)
    assert _queued_jobs(live_stack) == [("fetch_content", {"source_id": str(source_id)})]


def test_sharing_an_m2_unsupported_spotify_show_link_leaves_it_unsupported(live_stack: LiveStack) -> None:
    """A show link M2 left unsupported stays so on a re-share, with no fetch queued."""
    authed = live_stack.authed(live_stack.sign_in())
    url = "https://open.spotify.com/show/abc123"
    source_id = _insert_m1_link(
        live_stack, user_id=authed.get("/me").json()["user_id"], url=url, kind=models.SourceKind.PODCAST
    )

    _push(authed, _add_source(url))
    row = _pull_sources(authed)[str(source_id)]

    assert (row["kind"], row["processing"]) == ("podcast", "unsupported")
    assert row["processing_error"] == "Share an episode, not the show."
    assert _queued_jobs(live_stack) == []


def test_sharing_an_m1_youtube_channel_link_says_why_it_is_unsupported(live_stack: LiveStack) -> None:
    """An M1 link to a channel is re-classified and shown the channel reason."""
    authed = live_stack.authed(live_stack.sign_in())
    url = "https://youtube.com/@somechannel"
    source_id = _insert_m1_link(live_stack, user_id=authed.get("/me").json()["user_id"], url=url)

    _push(authed, _add_source(url))
    row = _pull_sources(authed)[str(source_id)]

    assert (row["kind"], row["processing"], row["processing_error"]) == (
        "youtube",
        "unsupported",
        "Share a video, not the channel.",
    )
    assert _queued_jobs(live_stack) == []
