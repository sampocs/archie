# SCAFFOLD(exemplar): replaced by the real job loop's retry handling in archie_worker/loop.py (plan Task 7).
"""Retry policy — what happens to a job after one attempt at running it.

The worker loop never decides retries inline. It reports how an attempt went, and `decide` turns
that into the job's next state: done, back in the queue after a backoff, or failed for good. Keeping
the decision a pure function of the attempt makes the backoff schedule auditable in one place and
testable without a database or a clock.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum, auto

# Seconds to wait before attempt 2, 3, ...; the last value repeats if `max_attempts` outgrows it.
_BACKOFF_SECONDS = (10, 60, 300)


class AttemptResult(StrEnum):
    """How a single run of a job's handler ended."""

    SUCCEEDED = auto()
    FAILED = auto()


class NextStatus(StrEnum):
    """The job status the worker should write after an attempt."""

    DONE = auto()
    QUEUED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class Attempt:
    """One finished run of a job's handler.

    Args:
        result: Whether the handler succeeded.
        attempts_so_far: Attempts made including this one.
        max_attempts: Attempts allowed before the job fails for good.
        finished_at: When this attempt ended.
        cost_usd: What the attempt spent on model calls; None when it made none.
    """

    result: AttemptResult
    attempts_so_far: int
    max_attempts: int
    finished_at: datetime.datetime
    cost_usd: Decimal | None = None


@dataclass(frozen=True)
class Decision:
    """What the worker writes back to the job row.

    Args:
        status: The job's next status.
        next_run_at: When a re-queued job becomes due; None unless `status` is QUEUED.
    """

    status: NextStatus
    next_run_at: datetime.datetime | None = None


def decide(*, attempt: Attempt) -> Decision:
    """Turn one finished attempt into the job's next status.

    Success always ends the job. A failure re-queues it with the next backoff until the attempts
    run out, then fails it so it stops consuming worker time.
    """
    if attempt.result is AttemptResult.SUCCEEDED:
        return Decision(status=NextStatus.DONE)

    if attempt.attempts_so_far >= attempt.max_attempts:
        return Decision(status=NextStatus.FAILED)

    delay = datetime.timedelta(seconds=_backoff_seconds(attempts_so_far=attempt.attempts_so_far))
    return Decision(status=NextStatus.QUEUED, next_run_at=attempt.finished_at + delay)


def _backoff_seconds(*, attempts_so_far: int) -> int:
    """The wait after the `attempts_so_far`-th failure, holding at the longest step."""
    index = min(attempts_so_far, len(_BACKOFF_SECONDS)) - 1
    return _BACKOFF_SECONDS[index]
