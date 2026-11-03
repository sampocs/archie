# SCAFFOLD(exemplar): replaced by the worker e2e tests in services/worker/tests/test_worker_e2e.py (plan Task 7).
"""Tests for the retry policy — how a finished attempt maps to a job's next status."""

import datetime

from archie_worker import retry_policy
from archie_worker.retry_policy import Attempt, AttemptResult, NextStatus

# A fixed clock, so backoff assertions are exact.
FINISHED_AT = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=datetime.UTC)


def test_a_successful_attempt_ends_the_job() -> None:
    """Success marks the job done whatever attempt it was."""
    attempt = Attempt(result=AttemptResult.SUCCEEDED, attempts_so_far=3, max_attempts=3, finished_at=FINISHED_AT)

    decision = retry_policy.decide(attempt=attempt)

    assert decision.status is NextStatus.DONE
    assert decision.next_run_at is None


def test_a_later_failure_waits_longer_than_an_earlier_one() -> None:
    """Each failure pushes the next run further out, so a down site isn't hammered."""
    first = Attempt(result=AttemptResult.FAILED, attempts_so_far=1, max_attempts=5, finished_at=FINISHED_AT)
    second = Attempt(result=AttemptResult.FAILED, attempts_so_far=2, max_attempts=5, finished_at=FINISHED_AT)

    first_decision = retry_policy.decide(attempt=first)
    second_decision = retry_policy.decide(attempt=second)

    assert first_decision.next_run_at is not None and second_decision.next_run_at is not None
    assert FINISHED_AT < first_decision.next_run_at < second_decision.next_run_at


def test_backoff_holds_at_the_longest_step_past_the_schedule() -> None:
    """With more attempts allowed than backoff steps, later waits repeat the last step."""
    fourth = Attempt(result=AttemptResult.FAILED, attempts_so_far=4, max_attempts=6, finished_at=FINISHED_AT)
    fifth = Attempt(result=AttemptResult.FAILED, attempts_so_far=5, max_attempts=6, finished_at=FINISHED_AT)

    assert retry_policy.decide(attempt=fourth).next_run_at == retry_policy.decide(attempt=fifth).next_run_at


def test_the_last_allowed_failure_fails_the_job() -> None:
    """Once attempts run out, the job stops instead of re-queuing."""
    attempt = Attempt(result=AttemptResult.FAILED, attempts_so_far=3, max_attempts=3, finished_at=FINISHED_AT)

    decision = retry_policy.decide(attempt=attempt)

    assert decision.status is NextStatus.FAILED
    assert decision.next_run_at is None
