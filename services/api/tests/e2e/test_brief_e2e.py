"""The newsletter brief through the real API: Done (`finish_brief`) and which briefs a pull sends."""

import datetime
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api.sync import brief_actions, rows
from archie_db import briefs, changes, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a fresh user."""
    return live_stack.authed(live_stack.sign_in())


def test_done_briefs_only_the_shown_inbox_newsletters_and_queues_the_next_brief(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Of the brief's newsletters, the shown inbox one is briefed; a queued one and an unshown one are left alone."""
    user_id = _user_id(authed)
    shown = _add_newsletter(live_stack, user_id=user_id)
    queued = _add_newsletter(live_stack, user_id=user_id, state=models.SourceState.QUEUED)
    unshown = _add_newsletter(live_stack, user_id=user_id)
    brief_id = _add_brief(live_stack, user_id=user_id, source_ids=[shown, queued, unshown])

    [result] = _push(authed, _finish(brief_id, source_ids=[shown, queued]))

    assert result["result"] == models.ActionResult.APPLIED.value
    states = {row["id"]: row["state"] for row in _rows(authed)["sources"]}
    assert states == {
        str(shown): models.SourceState.BRIEFED.value,
        str(queued): models.SourceState.QUEUED.value,
        str(unshown): models.SourceState.INBOX.value,
    }
    [brief] = _rows(authed)["briefs"]
    assert (brief["id"], brief["status"]) == (str(brief_id), models.BriefStatus.DONE.value)
    assert brief["done_at"] is not None
    # The unshown newsletter is still unbriefed, so it starts the next brief.
    assert _brief_job_payloads(live_stack, user_id=user_id) == [{briefs.USER_ID_KEY: user_id}]


def test_done_with_a_newsletter_that_arrived_after_the_brief_queues_the_next_brief(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A ready newsletter not in the brief stays in the inbox and gets its own brief; queued once, however many."""
    user_id = _user_id(authed)
    covered = _add_newsletter(live_stack, user_id=user_id)
    later = _add_newsletter(live_stack, user_id=user_id)
    brief_id = _add_brief(live_stack, user_id=user_id, source_ids=[covered])
    _queue_rewrite(live_stack, user_id=user_id)

    _push(authed, _finish(brief_id, source_ids=[covered]))

    states = {row["id"]: row["state"] for row in _rows(authed)["sources"]}
    assert (states[str(covered)], states[str(later)]) == (
        models.SourceState.BRIEFED.value,
        models.SourceState.INBOX.value,
    )
    assert len(_brief_job_payloads(live_stack, user_id=user_id)) == 1


def test_done_with_everything_shown_and_nothing_waiting_queues_no_rewrite(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A newsletter still processing isn't waiting yet: it queues the rewrite itself once it is ready."""
    user_id = _user_id(authed)
    covered = _add_newsletter(live_stack, user_id=user_id)
    _add_newsletter(live_stack, user_id=user_id, processing=models.ProcessingStatus.PROCESSING)
    brief_id = _add_brief(live_stack, user_id=user_id, source_ids=[covered])

    _push(authed, _finish(brief_id, source_ids=[covered]))

    assert _brief_job_payloads(live_stack, user_id=user_id) == []


def test_done_ignores_ids_that_are_not_the_users_inbox_newsletters(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Another user's newsletter, the user's article and an unknown id are never briefed."""
    user_id = _user_id(authed)
    other_id = _user_id(live_stack.authed(live_stack.sign_in(apple_sub="mallory")))
    others = _add_newsletter(live_stack, user_id=other_id)
    article = _add_newsletter(live_stack, user_id=user_id, kind=models.SourceKind.ARTICLE)
    brief_id = _add_brief(live_stack, user_id=user_id, source_ids=[])

    [result] = _push(authed, _finish(brief_id, source_ids=[others, article, uuid.uuid4()]))

    assert result["result"] == models.ActionResult.APPLIED.value
    assert _state(live_stack, others) == models.SourceState.INBOX.value
    assert _state(live_stack, article) == models.SourceState.INBOX.value


def test_done_is_refused_for_a_brief_that_is_not_open_or_not_the_users(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A done brief, another user's brief and a payload without source ids change nothing."""
    user_id = _user_id(authed)
    newsletter = _add_newsletter(live_stack, user_id=user_id)
    done = _add_brief(live_stack, user_id=user_id, source_ids=[newsletter], status=models.BriefStatus.DONE)
    other_id = _user_id(live_stack.authed(live_stack.sign_in(apple_sub="mallory")))
    others = _add_brief(live_stack, user_id=other_id, source_ids=[])

    results = _push(
        authed,
        _finish(done, source_ids=[newsletter]),
        _finish(others, source_ids=[newsletter]),
        _action("finish_brief", {"id": str(done), "version": 3}),
    )

    assert [(result["result"], result["reason"]) for result in results] == [
        (models.ActionResult.REJECTED.value, brief_actions.NOT_OPEN),
        (models.ActionResult.REJECTED.value, brief_actions.NO_BRIEF),
        (models.ActionResult.REJECTED.value, rows.MALFORMED),
    ]
    assert _state(live_stack, newsletter) == models.SourceState.INBOX.value
    assert _brief_job_payloads(live_stack, user_id=user_id) == []


def test_a_pull_sends_the_open_brief_and_done_briefs_from_the_last_week(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A brief done eight days ago is left out; the open one and one done six days ago come with every field."""
    user_id = _user_id(authed)
    newsletter = _add_newsletter(live_stack, user_id=user_id)
    _add_brief(live_stack, user_id=user_id, source_ids=[], status=models.BriefStatus.DONE, done_days_ago=8)
    recent = _add_brief(live_stack, user_id=user_id, source_ids=[], status=models.BriefStatus.DONE, done_days_ago=6)
    open_id = _add_brief(live_stack, user_id=user_id, source_ids=[newsletter])

    pulled = {row["id"]: row for row in _rows(authed)["briefs"]}

    assert set(pulled) == {str(recent), str(open_id)}
    assert pulled[str(open_id)] | {"created_at": None, "updated_at": None, "change_seq": None} == {
        "id": str(open_id),
        "status": models.BriefStatus.OPEN.value,
        "content": _CONTENT,
        "source_ids": [str(newsletter)],
        "since": "2026-11-01T08:00:00Z",
        "version": 3,
        "created_at": None,
        "updated_at": None,
        "done_at": None,
        "change_seq": None,
    }


_CONTENT: dict[str, Any] = {"domains": [], "also": [], "essays": []}
_SINCE = datetime.datetime(2026, 11, 1, 8, 0, tzinfo=datetime.UTC)


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _finish(brief_id: uuid.UUID, *, source_ids: list[uuid.UUID]) -> dict[str, Any]:
    return _action("finish_brief", {"id": str(brief_id), "source_ids": [str(source_id) for source_id in source_ids]})


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _add_newsletter(
    live_stack: LiveStack,
    *,
    user_id: int,
    state: models.SourceState = models.SourceState.INBOX,
    processing: models.ProcessingStatus = models.ProcessingStatus.READY,
    kind: models.SourceKind = models.SourceKind.NEWSLETTER,
) -> uuid.UUID:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=f"https://example.com/{uuid.uuid4()}",
            normalized_url=f"https://example.com/{uuid.uuid4()}",
            kind=kind.value,
            state=state.value,
            intent=models.SourceIntent.QUEUE.value,
            processing=processing.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.commit()
        return source.id


def _add_brief(
    live_stack: LiveStack,
    *,
    user_id: int,
    source_ids: list[uuid.UUID],
    status: models.BriefStatus = models.BriefStatus.OPEN,
    done_days_ago: int = 0,
) -> uuid.UUID:
    """A brief at version 3; a done one finished `done_days_ago` days ago."""
    engine = session.engine_for(live_stack.database_url)
    done_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=done_days_ago)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        brief = models.Brief(
            id=uuid.uuid4(),
            user_id=user_id,
            status=status.value,
            content=_CONTENT,
            source_ids=source_ids,
            since=_SINCE,
            version=3,
            done_at=done_at if status == models.BriefStatus.DONE else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(brief)
        db.commit()
        return brief.id


def _queue_rewrite(live_stack: LiveStack, *, user_id: int) -> None:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        briefs.enqueue_update(db, user_id=user_id)
        db.commit()


def _brief_job_payloads(live_stack: LiveStack, *, user_id: int) -> list[dict[str, Any]]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return [
            job.payload
            for job in db.scalars(
                sqlalchemy.select(models.Job).where(
                    models.Job.kind == models.JobKind.UPDATE_BRIEF.value, models.Job.user_id == user_id
                )
            )
        ]


def _state(live_stack: LiveStack, source_id: uuid.UUID) -> str:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id).state
