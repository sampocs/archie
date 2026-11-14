"""The server checks behind `GET /problems`.

Every check reads one user's rows and returns the problems that are true right now; nothing is stored, and nothing
here logs a problem's text (job errors can carry page content). `find_problems` runs them all.
"""

from __future__ import annotations

import datetime
import statistics
import uuid
from dataclasses import dataclass
from enum import StrEnum

import sqlalchemy
from archie_db import briefs, models, senders
from sqlalchemy import orm

FAILURE_LOOKBACK = datetime.timedelta(days=7)
STALLED_AFTER = datetime.timedelta(hours=1)
QUIET_MIN_ISSUES = 4
QUIET_LOOKBACK = datetime.timedelta(days=180)
QUIET_GAP_MULTIPLE = 3
QUIET_MIN_SILENCE = datetime.timedelta(days=3)
NO_EMAIL_AFTER = datetime.timedelta(hours=48)
NO_BRIEF_AFTER = datetime.timedelta(hours=3)
MAX_DETAIL_LENGTH = 140

_ELLIPSIS = "…"
_DAILY_GAP = datetime.timedelta(days=1.5)
_EVERY_FEW_DAYS_GAP = datetime.timedelta(days=5)
_WEEKLY_GAP = datetime.timedelta(days=10)

# What the owner reads for each kind of job that keeps failing; any other kind gets a generic title.
JOB_TITLES: dict[str, str] = {
    models.JobKind.TRANSCRIBE: "Podcast imports failing",
    models.JobKind.FETCH_CONTENT: "Page imports failing",
    models.JobKind.ANALYZE: "Summaries failing",
    models.JobKind.PRIMER: "Primers failing",
    models.JobKind.UPDATE_BRIEF: "Briefs failing",
    models.JobKind.EMBED: "Search indexing failing",
}


@dataclass
class _SenderIssues:
    label: str
    arrivals: list[datetime.datetime]


class ProblemKind(StrEnum):
    """What a problem is about; the app words its own fixes by this."""

    FAILING_JOBS = "failing_jobs"
    WORKER_STALLED = "worker_stalled"
    QUIET_SENDER = "quiet_sender"
    NO_EMAIL = "no_email"
    NO_BRIEF = "no_brief"


@dataclass(frozen=True)
class Problem:
    """One thing that is wrong now: `key` is stable across requests, `since` is when the condition began."""

    kind: ProblemKind
    key: str
    title: str
    detail: str
    since: datetime.datetime


def find_problems(db: orm.Session, *, user_id: int, now: datetime.datetime) -> list[Problem]:
    """Every problem the user has right now, oldest first."""
    failing = failing_jobs(db, user_id=user_id, now=now)
    no_email_problems = no_email(db, user_id=user_id, now=now)
    # No email at all is the one cause behind every quiet sender, so it replaces them.
    quiet = [] if no_email_problems else quiet_senders(db, user_id=user_id, now=now)
    update_brief_failing = any(problem.key == _failing_key(models.JobKind.UPDATE_BRIEF) for problem in failing)

    problems = [
        *failing,
        *worker_stalled(db, user_id=user_id, now=now),
        *quiet,
        *no_email_problems,
        *([] if update_brief_failing else no_brief(db, user_id=user_id, now=now)),
    ]
    return sorted(problems, key=lambda problem: problem.since)


def failing_jobs(db: orm.Session, *, user_id: int, now: datetime.datetime) -> list[Problem]:
    """One problem per job kind whose jobs failed since its last success, within the look-back.

    Clears once a job of that kind is done.
    """
    window_start = now - FAILURE_LOOKBACK
    done_at = dict(
        db.execute(
            sqlalchemy.select(models.Job.kind, sqlalchemy.func.max(models.Job.created_at))
            .where(
                models.Job.user_id == user_id,
                models.Job.status == models.JobStatus.DONE.value,
                models.Job.created_at >= window_start,
            )
            .group_by(models.Job.kind)
        ).all()
    )
    failed = db.scalars(
        sqlalchemy.select(models.Job)
        .where(
            models.Job.user_id == user_id,
            models.Job.status == models.JobStatus.FAILED.value,
            models.Job.created_at >= window_start,
        )
        .order_by(models.Job.created_at, models.Job.id)
    ).all()

    counted: dict[str, list[models.Job]] = {}
    for job in failed:
        if job.created_at > done_at.get(job.kind, window_start):
            counted.setdefault(job.kind, []).append(job)

    return [_failing_problem(kind=kind, jobs=jobs) for kind, jobs in counted.items()]


def worker_stalled(db: orm.Session, *, user_id: int, now: datetime.datetime) -> list[Problem]:
    """A single problem when a job is overdue by more than the threshold: the worker is not taking jobs."""
    cutoff = now - STALLED_AFTER
    overdue = db.execute(
        sqlalchemy.select(models.Job.kind, models.Job.status, models.Job.next_run_at, models.Job.started_at).where(
            models.Job.user_id == user_id,
            sqlalchemy.or_(
                sqlalchemy.and_(models.Job.status == models.JobStatus.QUEUED.value, models.Job.next_run_at < cutoff),
                sqlalchemy.and_(models.Job.status == models.JobStatus.RUNNING.value, models.Job.started_at < cutoff),
            ),
        )
    ).all()
    if not overdue:
        return []

    # A queued job is overdue from its due time, a running one from when it started.
    stalled = sorted(
        (
            (job.next_run_at if job.status == models.JobStatus.QUEUED.value else job.started_at, job.kind)
            for job in overdue
        ),
    )
    oldest_at, oldest_kind = stalled[0]
    return [
        Problem(
            kind=ProblemKind.WORKER_STALLED,
            key=ProblemKind.WORKER_STALLED.value,
            title="Background work has stopped",
            detail=f"{len(stalled)} {_plural(len(stalled), 'job')} waiting · oldest is {oldest_kind.replace('_', ' ')}",
            since=oldest_at + STALLED_AFTER,
        )
    ]


def quiet_senders(db: orm.Session, *, user_id: int, now: datetime.datetime) -> list[Problem]:
    """One problem per allowed sender who used to write regularly and has been silent for much longer than usual."""
    problems = []
    for sender_id, issues in _recent_issues_by_sender(db, user_id=user_id, now=now).items():
        arrivals = issues.arrivals
        if len(arrivals) < QUIET_MIN_ISSUES:
            continue

        usual_gap = _median_gap(arrivals)
        threshold = max(QUIET_GAP_MULTIPLE * usual_gap, QUIET_MIN_SILENCE)
        silence = now - arrivals[-1]
        if silence <= threshold:
            continue

        problems.append(
            Problem(
                kind=ProblemKind.QUIET_SENDER,
                key=f"{ProblemKind.QUIET_SENDER.value}:{sender_id}",
                title=f"{issues.label} has gone quiet",
                detail=f"Last issue {silence.days} {_plural(silence.days, 'day')} ago · usually {_cadence(usual_gap)}",
                since=arrivals[-1] + threshold,
            )
        )
    return problems


def no_email(db: orm.Session, *, user_id: int, now: datetime.datetime) -> list[Problem]:
    """A single problem when the user has allowed senders but no newsletter has arrived for the threshold."""
    first_allowed = db.scalar(
        sqlalchemy.select(sqlalchemy.func.min(models.NewsletterSender.created_at)).where(
            models.NewsletterSender.user_id == user_id,
            models.NewsletterSender.status == models.SenderStatus.ALLOWED.value,
        )
    )
    if first_allowed is None:
        return []

    last_arrival = db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(models.Source.created_at)).where(
            models.Source.user_id == user_id, models.Source.kind == models.SourceKind.NEWSLETTER.value
        )
    )
    # Before any mail has ever arrived, the wait starts when the first sender was allowed.
    quiet_since = last_arrival or first_allowed
    if now - quiet_since <= NO_EMAIL_AFTER:
        return []

    silence = now - quiet_since
    return [
        Problem(
            kind=ProblemKind.NO_EMAIL,
            key=ProblemKind.NO_EMAIL.value,
            title="No newsletters are arriving",
            detail=f"Nothing in {silence.days * 24 + silence.seconds // 3600} hours",
            since=quiet_since + NO_EMAIL_AFTER,
        )
    ]


def _oldest_briefed_news(db: orm.Session, *, user_id: int) -> datetime.datetime | None:
    """When the oldest news in the open brief arrived; anything not filed as an essay counts as news, as the worker
    treats it. None without an open brief or when it holds no news."""
    open_brief = briefs.open_brief(db, user_id=user_id)
    if open_brief is None or not open_brief.source_ids:
        return None
    return db.scalar(
        sqlalchemy.select(sqlalchemy.func.min(models.Source.created_at)).where(
            models.Source.id.in_(open_brief.source_ids),
            models.Source.newsletter_kind.is_distinct_from(models.NewsletterKind.ESSAY.value),
        )
    )


def no_brief(db: orm.Session, *, user_id: int, now: datetime.datetime) -> list[Problem]:
    """A single problem when news newsletters have waited past the threshold with no brief covering them.

    Not a problem while an `update_brief` job is queued or running: the brief is on its way. News older than the
    oldest news the open brief covers isn't counted either: the worker defers the oldest news when its budget is spent,
    and it waits until the brief is Done. The brief's own `since` can't mark that line, since it also counts essays,
    which are never deferred.
    """
    cutoff = now - NO_BRIEF_AFTER
    deferred_before = _oldest_briefed_news(db, user_id=user_id)
    briefed: set[uuid.UUID] = set()
    for source_ids in db.scalars(sqlalchemy.select(models.Brief.source_ids).where(models.Brief.user_id == user_id)):
        briefed.update(source_ids)

    uncovered = [
        newsletter
        for newsletter in _newsletters_awaiting_brief(db, user_id=user_id)
        if newsletter.created_at < cutoff
        and newsletter.id not in briefed
        and (deferred_before is None or newsletter.created_at >= deferred_before)
    ]
    if not uncovered:
        return []

    update_pending = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.user_id == user_id,
                models.Job.kind == models.JobKind.UPDATE_BRIEF.value,
                models.Job.status.in_([models.JobStatus.QUEUED.value, models.JobStatus.RUNNING.value]),
            )
        )
    )
    if update_pending:
        return []

    return [
        Problem(
            kind=ProblemKind.NO_BRIEF,
            key=ProblemKind.NO_BRIEF.value,
            title="Your brief isn't updating",
            detail=f"{len(uncovered)} news {_plural(len(uncovered), 'newsletter')} not in the brief yet",
            since=min(newsletter.created_at for newsletter in uncovered) + NO_BRIEF_AFTER,
        )
    ]


def _failing_key(job_kind: models.JobKind | str) -> str:
    return f"{ProblemKind.FAILING_JOBS.value}:{job_kind}"


def _failing_problem(*, kind: str, jobs: list[models.Job]) -> Problem:
    """The problem for `jobs` (oldest first), all failed jobs of one kind."""
    title = JOB_TITLES.get(kind, f"{kind} jobs failing")
    count_text = f"{len(jobs)} failed"
    newest_error = jobs[-1].last_error
    detail = f"{count_text} · {_first_line(newest_error)}" if newest_error and newest_error.strip() else count_text
    return Problem(
        kind=ProblemKind.FAILING_JOBS,
        key=_failing_key(kind),
        title=title,
        detail=_clip(detail),
        since=jobs[0].created_at,
    )


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0].strip()


def _clip(text: str) -> str:
    if len(text) <= MAX_DETAIL_LENGTH:
        return text
    return text[: MAX_DETAIL_LENGTH - len(_ELLIPSIS)].rstrip() + _ELLIPSIS


def _newsletters_awaiting_brief(db: orm.Session, *, user_id: int) -> list[models.Source]:
    """The user's ready, live inbox newsletters that are news, by the rule the brief itself uses to pick them."""
    return [
        newsletter
        for newsletter in briefs.covered_newsletters(db, user_id=user_id)
        if newsletter.newsletter_kind == models.NewsletterKind.NEWS.value
    ]


def _recent_issues_by_sender(
    db: orm.Session, *, user_id: int, now: datetime.datetime
) -> dict[uuid.UUID, _SenderIssues]:
    """The arrival times (oldest first) of recent newsletters from each allowed sender, matched as ingest matches.

    Deleted newsletters count: the owner deleting an issue does not mean it never arrived.
    """
    by_identifier = senders.allowed_senders_by_identifier(db, user_id=user_id)
    newsletters = db.scalars(
        sqlalchemy.select(models.Source)
        .where(
            models.Source.user_id == user_id,
            models.Source.kind == models.SourceKind.NEWSLETTER.value,
            models.Source.confirm_url.is_(None),
            models.Source.sender_pending.is_(False),
            models.Source.created_at >= now - QUIET_LOOKBACK,
        )
        .order_by(models.Source.created_at, models.Source.id)
    )

    by_sender: dict[uuid.UUID, _SenderIssues] = {}
    for newsletter in newsletters:
        identifiers = senders.identifiers_for(
            address=newsletter.sender_address, list_id=newsletter.list_id, name=newsletter.sender
        )
        owners = [by_identifier[identifier] for identifier in identifiers if identifier in by_identifier]
        if not owners:
            continue

        owner = min(owners, key=lambda sender: (sender.created_at, sender.id))
        by_sender.setdefault(owner.id, _SenderIssues(label=owner.label, arrivals=[])).arrivals.append(
            newsletter.created_at
        )
    return by_sender


def _median_gap(arrivals: list[datetime.datetime]) -> datetime.timedelta:
    gaps = [(later - earlier).total_seconds() for earlier, later in zip(arrivals, arrivals[1:], strict=False)]
    return datetime.timedelta(seconds=statistics.median(gaps))


def _cadence(gap: datetime.timedelta) -> str:
    if gap < _DAILY_GAP:
        return "daily"
    if gap < _EVERY_FEW_DAYS_GAP:
        return "every few days"
    if gap < _WEEKLY_GAP:
        return "weekly"
    return f"every {max(2, round(gap.days / 7))} weeks"


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"
