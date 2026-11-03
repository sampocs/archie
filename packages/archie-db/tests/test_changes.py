"""The per-user lock makes change positions commit in increasing order, so a pull can never skip a row."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session

pytestmark = pytest.mark.postgres


def test_second_writer_waits_for_first_so_positions_commit_in_order(migrated_database_url: str) -> None:
    """While writer A holds the lock uncommitted, writer B cannot take a position, so B's position is larger."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as setup:
        user = models.User(apple_sub="sub-1")
        setup.add(user)
        setup.commit()
        user_id = user.id

    first = sqlalchemy.orm.Session(engine)
    changes.lock_user_writes(first, user_id)
    first_seq = first.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one()

    second_seq: list[int] = []

    def write_second() -> None:
        with sqlalchemy.orm.Session(engine) as second:
            changes.lock_user_writes(second, user_id)
            second_seq.append(second.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one())
            second.commit()

    thread = threading.Thread(target=write_second)
    thread.start()
    thread.join(timeout=0.5)
    assert thread.is_alive(), "second writer should be blocked by the first writer's lock"

    first.commit()
    thread.join(timeout=5)
    first.close()
    engine.dispose()

    assert second_seq
    assert second_seq[0] > first_seq


def test_enqueue_creates_a_due_queued_job_that_rolls_back_with_the_caller(migrated_database_url: str) -> None:
    """The job is queued with defaults and vanishes if the caller's transaction rolls back."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub="sub-2")
        db.add(user)
        db.commit()

        job = jobs.enqueue(db, kind=models.JobKind.FETCH_TITLE, user_id=user.id, payload={"source_id": "abc"})
        db.refresh(job)
        assert (job.status, job.attempts, job.max_attempts) == (models.JobStatus.QUEUED, 0, 3)
        assert job.payload == {"source_id": "abc"}
        db.rollback()

        assert db.scalar(sqlalchemy.select(sqlalchemy.func.count()).select_from(models.Job)) == 0
    engine.dispose()
