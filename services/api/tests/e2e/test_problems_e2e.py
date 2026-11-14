"""`GET /problems` through the real API: each check appears when its condition is seeded and clears when it is fixed.

Everything is seeded through the database with invented senders (example.com, example.org, example.net) and invented
job errors; times are set relative to now so the thresholds are crossed or not by a wide margin.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api import test_routes
from archie_api.problems import checks
from archie_db import changes, models, senders, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres


def _ago(**delta: float) -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(**delta)


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _problems(authed: httpx.Client) -> dict[str, dict[str, Any]]:
    """The user's problems by key."""
    response = authed.get("/problems")
    assert response.status_code == 200
    return {problem["key"]: problem for problem in response.json()["problems"]}


def _insert_job(
    live_stack: LiveStack,
    *,
    user_id: int,
    kind: models.JobKind,
    status: models.JobStatus,
    created_at: datetime.datetime | None = None,
    next_run_at: datetime.datetime | None = None,
    started_at: datetime.datetime | None = None,
    last_error: str | None = None,
) -> None:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        job = models.Job(kind=kind.value, payload={}, user_id=user_id, status=status.value, last_error=last_error)
        if created_at is not None:
            job.created_at = created_at
        if next_run_at is not None:
            job.next_run_at = next_run_at
        job.started_at = started_at
        db.add(job)
        db.commit()
    engine.dispose()


def _allow_sender(
    live_stack: LiveStack, *, user_id: int, address: str, label: str, created_at: datetime.datetime | None = None
) -> None:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        senders.record(
            db,
            user_id=user_id,
            identifiers=senders.identifiers_for(address=address, list_id=None, name=None),
            status=models.SenderStatus.ALLOWED,
            label=label,
        )
        if created_at is not None:
            db.execute(
                sqlalchemy.update(models.NewsletterSender)
                .where(models.NewsletterSender.user_id == user_id)
                .values(created_at=created_at)
            )
        db.commit()
    engine.dispose()


def _insert_newsletter(
    live_stack: LiveStack,
    *,
    user_id: int,
    address: str,
    created_at: datetime.datetime,
    newsletter_kind: models.NewsletterKind = models.NewsletterKind.ESSAY,
) -> uuid.UUID:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        source_id = uuid.uuid4()
        db.add(
            models.Source(
                id=source_id,
                user_id=user_id,
                kind=models.SourceKind.NEWSLETTER.value,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                url=f"newsletter:{source_id}",
                normalized_url=f"newsletter:{source_id}",
                sender_address=address,
                newsletter_message_id=str(source_id),
                newsletter_kind=newsletter_kind.value,
                processing=models.ProcessingStatus.READY.value,
                created_at=created_at,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()
    return source_id


def _insert_brief(
    live_stack: LiveStack, *, user_id: int, source_ids: list[uuid.UUID], since: datetime.datetime | None = None
) -> None:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Brief(
                id=uuid.uuid4(),
                user_id=user_id,
                status=models.BriefStatus.OPEN.value,
                source_ids=source_ids,
                since=since,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()


def _issues(live_stack: LiveStack, *, user_id: int, address: str, days_ago: list[float]) -> None:
    for days in days_ago:
        _insert_newsletter(live_stack, user_id=user_id, address=address, created_at=_ago(days=days))


def test_a_user_with_nothing_wrong_has_no_problems(live_stack: LiveStack) -> None:
    """An empty list, not an error."""
    authed = live_stack.authed(live_stack.sign_in())

    assert authed.get("/problems").json() == {"problems": []}


def test_problems_need_a_session(live_stack: LiveStack) -> None:
    """No session, no answer."""
    assert live_stack.client.get("/problems").status_code == 401


def test_failing_jobs_count_failures_since_the_last_success_and_clear_when_one_succeeds(
    live_stack: LiveStack,
) -> None:
    """Failures within 7 days and after the last done job count, one problem per kind; a done job clears it."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    long_error = "Anthropic said no. " + "x" * 300

    def analyze_job(
        status: models.JobStatus, *, created_at: datetime.datetime | None = None, error: str | None = None
    ) -> None:
        _insert_job(
            live_stack,
            user_id=user_id,
            kind=models.JobKind.ANALYZE,
            status=status,
            created_at=created_at,
            last_error=error,
        )

    # Outside the look-back, and before a success: neither counts.
    analyze_job(models.JobStatus.FAILED, created_at=_ago(days=9), error="ancient")
    analyze_job(models.JobStatus.FAILED, created_at=_ago(days=3), error="before done")
    analyze_job(models.JobStatus.DONE, created_at=_ago(days=2))
    analyze_job(models.JobStatus.FAILED, created_at=_ago(days=1), error="first\nsecond")
    analyze_job(models.JobStatus.FAILED, created_at=_ago(hours=1), error=long_error)
    # Another kind with only failures, and a kind with no title of its own.
    _insert_job(live_stack, user_id=user_id, kind=models.JobKind.TRANSCRIBE, status=models.JobStatus.FAILED)
    _insert_job(live_stack, user_id=user_id, kind=models.JobKind.NAME_CHAT, status=models.JobStatus.FAILED)

    problems = _problems(authed)

    analyze = problems["failing_jobs:analyze"]
    assert (analyze["kind"], analyze["title"]) == ("failing_jobs", "Summaries failing")
    assert analyze["detail"].startswith("2 failed · Anthropic said no. xxx")
    assert len(analyze["detail"]) == checks.MAX_DETAIL_LENGTH
    assert analyze["since"].startswith(_ago(days=1).date().isoformat())
    assert problems["failing_jobs:transcribe"]["title"] == "Podcast imports failing"
    assert problems["failing_jobs:transcribe"]["detail"] == "1 failed"
    assert problems["failing_jobs:name_chat"]["title"] == "name_chat jobs failing"

    analyze_job(models.JobStatus.DONE)

    assert "failing_jobs:analyze" not in _problems(authed)
    assert "failing_jobs:transcribe" in _problems(authed)


def test_a_failed_job_keeps_only_the_first_line_of_its_error(live_stack: LiveStack) -> None:
    """A multi-line error is cut to its first line in the detail."""
    authed = live_stack.authed(live_stack.sign_in())
    _insert_job(
        live_stack,
        user_id=_user_id(authed),
        kind=models.JobKind.PRIMER,
        status=models.JobStatus.FAILED,
        last_error="Credit balance is too low\nrequest id req_example_1",
    )

    assert _problems(authed)["failing_jobs:primer"]["detail"] == "1 failed · Credit balance is too low"


def test_a_stalled_worker_shows_overdue_jobs_and_clears_once_they_are_taken(live_stack: LiveStack) -> None:
    """Queued jobs overdue past the threshold, or running ones started before it, count; recent ones do not."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    # Not yet overdue: a job due 30 minutes ago, one started 20 minutes ago.
    _insert_job(
        live_stack,
        user_id=user_id,
        kind=models.JobKind.EMBED,
        status=models.JobStatus.QUEUED,
        next_run_at=_ago(minutes=30),
    )
    _insert_job(
        live_stack,
        user_id=user_id,
        kind=models.JobKind.EMBED,
        status=models.JobStatus.RUNNING,
        started_at=_ago(minutes=20),
    )
    assert authed.get("/problems").json() == {"problems": []}

    _insert_job(
        live_stack,
        user_id=user_id,
        kind=models.JobKind.PRIMER,
        status=models.JobStatus.QUEUED,
        next_run_at=_ago(hours=5),
    )
    _insert_job(
        live_stack,
        user_id=user_id,
        kind=models.JobKind.ANALYZE,
        status=models.JobStatus.RUNNING,
        started_at=_ago(hours=2),
    )

    stalled = _problems(authed)["worker_stalled"]

    assert stalled["kind"] == "worker_stalled"
    assert stalled["detail"] == "2 jobs waiting · oldest is primer"
    assert stalled["since"] < _ago(hours=3).isoformat()

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        db.execute(sqlalchemy.update(models.Job).where(models.Job.user_id == user_id).values(status="done"))
        db.commit()
    engine.dispose()

    assert authed.get("/problems").json() == {"problems": []}


def test_a_quiet_sender_appears_after_a_long_silence_and_clears_when_an_issue_arrives(live_stack: LiveStack) -> None:
    """Silence past 3 x the median gap flags the sender; a new issue clears it; too few issues are never judged."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    _allow_sender(live_stack, user_id=user_id, address="daily@example.com", label="Example Daily")
    _allow_sender(live_stack, user_id=user_id, address="other@example.org", label="Example Other")
    # Daily issues that stopped 10 days ago (more than 3 x the 1-day gap); a third sender with too few issues to judge.
    _issues(live_stack, user_id=user_id, address="daily@example.com", days_ago=[14, 13, 12, 11, 10])
    _issues(live_stack, user_id=user_id, address="other@example.org", days_ago=[30, 20, 0.5])

    quiet = _problems(authed)

    assert [problem["kind"] for problem in quiet.values()] == ["quiet_sender"]
    [problem] = quiet.values()
    assert problem["title"] == "Example Daily has gone quiet"
    assert problem["detail"] == "Last issue 10 days ago · usually daily"
    assert problem["since"].startswith(_ago(days=7).date().isoformat())

    _insert_newsletter(live_stack, user_id=user_id, address="daily@example.com", created_at=_ago(hours=1))

    assert authed.get("/problems").json() == {"problems": []}


def test_a_sender_within_three_times_its_usual_gap_or_three_days_is_not_quiet(live_stack: LiveStack) -> None:
    """Both limits matter: the 3 x gap for a slow sender, the 3-day floor for a fast one."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    _allow_sender(live_stack, user_id=user_id, address="weekly@example.com", label="Example Weekly")
    # A weekly sender 20 days silent is within 3 x 7 days; the daily sender is 2.5 days silent, within the 3-day floor.
    _issues(live_stack, user_id=user_id, address="weekly@example.com", days_ago=[48, 41, 34, 27, 20])
    _allow_sender(live_stack, user_id=user_id, address="daily@example.org", label="Example Daily")
    _issues(live_stack, user_id=user_id, address="daily@example.org", days_ago=[6.5, 5.5, 4.5, 3.5, 2.5])
    _insert_newsletter(live_stack, user_id=user_id, address="fresh@example.net", created_at=_ago(hours=1))

    assert authed.get("/problems").json() == {"problems": []}


def test_deleting_a_senders_latest_issues_does_not_make_it_quiet(live_stack: LiveStack) -> None:
    """A deleted issue was still received, so the sender's silence is measured from it."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    _allow_sender(live_stack, user_id=user_id, address="daily@example.com", label="Example Daily")
    _issues(live_stack, user_id=user_id, address="daily@example.com", days_ago=[6.5, 5.5, 4.5, 3.5, 2.5, 1.5, 0.5])
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        db.execute(
            sqlalchemy.update(models.Source)
            .where(models.Source.user_id == user_id, models.Source.created_at >= _ago(days=3))
            .values(deleted_at=datetime.datetime.now(tz=datetime.UTC))
        )
        db.commit()
    engine.dispose()

    assert authed.get("/problems").json() == {"problems": []}


def test_no_email_replaces_quiet_senders_and_clears_when_a_newsletter_arrives(live_stack: LiveStack) -> None:
    """Two days without any mail is one problem that stands in for the quiet-sender rows."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    _allow_sender(live_stack, user_id=user_id, address="daily@example.com", label="Example Daily")
    _issues(live_stack, user_id=user_id, address="daily@example.com", days_ago=[14, 13, 12, 11, 10])

    problems = _problems(authed)

    assert list(problems) == ["no_email"]
    assert problems["no_email"]["title"] == "No newsletters are arriving"
    assert problems["no_email"]["since"].startswith(_ago(days=8).date().isoformat())

    _insert_newsletter(live_stack, user_id=user_id, address="daily@example.com", created_at=_ago(hours=1))

    assert "no_email" not in _problems(authed)


def test_no_email_waits_out_the_first_two_days_after_a_sender_is_allowed(live_stack: LiveStack) -> None:
    """With no mail ever, the wait starts when the sender was allowed."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    _allow_sender(live_stack, user_id=user_id, address="new@example.com", label="Example New")

    assert authed.get("/problems").json() == {"problems": []}

    _allow_sender(live_stack, user_id=user_id, address="new@example.com", label="Example New", created_at=_ago(days=5))

    assert list(_problems(authed)) == ["no_email"]


def test_no_email_needs_an_allowed_sender(live_stack: LiveStack) -> None:
    """A user who never allowed a sender is not missing mail."""
    authed = live_stack.authed(live_stack.sign_in())

    assert authed.get("/problems").json() == {"problems": []}


def test_no_brief_appears_for_an_old_uncovered_news_newsletter_and_clears_when_a_brief_covers_it(
    live_stack: LiveStack,
) -> None:
    """Only news newsletters older than 3 hours and in no brief count; a brief covering them clears it."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    news = models.NewsletterKind.NEWS
    # Too recent, and an essay (which a brief covers but this check ignores): neither counts.
    _insert_newsletter(
        live_stack, user_id=user_id, address="a@example.com", created_at=_ago(hours=1), newsletter_kind=news
    )
    _insert_newsletter(live_stack, user_id=user_id, address="a@example.com", created_at=_ago(hours=6))
    assert authed.get("/problems").json() == {"problems": []}

    waiting = _insert_newsletter(
        live_stack, user_id=user_id, address="a@example.com", created_at=_ago(hours=5), newsletter_kind=news
    )

    problem = _problems(authed)["no_brief"]

    assert problem["kind"] == "no_brief"
    assert problem["detail"] == "1 news newsletter not in the brief yet"
    assert problem["since"].startswith(_ago(hours=2).isoformat()[:13])

    _insert_brief(live_stack, user_id=user_id, source_ids=[waiting])

    assert authed.get("/problems").json() == {"problems": []}


def test_no_brief_ignores_newsletters_the_open_brief_defers_on_purpose(live_stack: LiveStack) -> None:
    """News older than the open brief's `since` waits until the brief is Done; newer uncovered news is flagged."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    news = models.NewsletterKind.NEWS
    _insert_newsletter(
        live_stack, user_id=user_id, address="a@example.com", created_at=_ago(hours=9), newsletter_kind=news
    )
    briefed_at = _ago(hours=6)
    briefed = _insert_newsletter(
        live_stack, user_id=user_id, address="a@example.com", created_at=briefed_at, newsletter_kind=news
    )
    _insert_brief(live_stack, user_id=user_id, source_ids=[briefed], since=briefed_at)

    assert authed.get("/problems").json() == {"problems": []}

    _insert_newsletter(
        live_stack, user_id=user_id, address="a@example.com", created_at=_ago(hours=4), newsletter_kind=news
    )

    assert _problems(authed)["no_brief"]["detail"] == "1 news newsletter not in the brief yet"


def test_no_brief_waits_for_a_queued_update_and_defers_to_failing_jobs(live_stack: LiveStack) -> None:
    """A queued update_brief means the brief is coming; a failing one is reported by failing_jobs alone."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    _insert_newsletter(
        live_stack,
        user_id=user_id,
        address="a@example.com",
        created_at=_ago(hours=5),
        newsletter_kind=models.NewsletterKind.NEWS,
    )
    _insert_job(live_stack, user_id=user_id, kind=models.JobKind.UPDATE_BRIEF, status=models.JobStatus.QUEUED)
    assert authed.get("/problems").json() == {"problems": []}

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        db.execute(sqlalchemy.update(models.Job).where(models.Job.user_id == user_id).values(status="failed"))
        db.commit()
    engine.dispose()

    assert list(_problems(authed)) == ["failing_jobs:update_brief"]


def test_problems_never_include_another_users_rows(live_stack: LiveStack) -> None:
    """Every check is scoped to the signed-in user."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="other-user"))
    other_id = _user_id(other)
    _insert_job(live_stack, user_id=other_id, kind=models.JobKind.ANALYZE, status=models.JobStatus.FAILED)
    _insert_job(
        live_stack,
        user_id=other_id,
        kind=models.JobKind.EMBED,
        status=models.JobStatus.QUEUED,
        next_run_at=_ago(hours=5),
    )
    _allow_sender(live_stack, user_id=other_id, address="daily@example.com", label="Example Daily")
    _issues(live_stack, user_id=other_id, address="daily@example.com", days_ago=[14, 13, 12, 11, 10])
    _insert_newsletter(
        live_stack,
        user_id=other_id,
        address="daily@example.com",
        created_at=_ago(hours=5),
        newsletter_kind=models.NewsletterKind.NEWS,
    )
    mine = live_stack.authed(live_stack.sign_in(apple_sub="my-user"))
    _allow_sender(live_stack, user_id=_user_id(mine), address="daily@example.com", label="Example Daily")
    _issues(live_stack, user_id=_user_id(mine), address="daily@example.com", days_ago=[3, 2, 1, 0.5])

    assert mine.get("/problems").json() == {"problems": []}
    assert {"failing_jobs:analyze", "worker_stalled"} <= set(_problems(other))


def test_the_dev_route_seeds_a_failed_analyze_job_for_the_signed_in_user(live_stack: LiveStack) -> None:
    """The dev route gives the caller, and only the caller, a failed analyze job with the invented error."""
    authed = live_stack.authed(live_stack.sign_in())
    bystander = live_stack.authed(live_stack.sign_in(apple_sub="bystander"))

    assert authed.post("/test/failed-job").status_code == 204

    problem = _problems(authed)["failing_jobs:analyze"]
    assert problem["title"] == "Summaries failing"
    assert problem["detail"] == f"1 failed · {test_routes.SEEDED_JOB_ERROR.splitlines()[0]}"
    assert bystander.get("/problems").json() == {"problems": []}
