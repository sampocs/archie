"""The per-user lock makes change positions commit in increasing order, so a pull can never skip a row."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session

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
    try:
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
        assert second_seq == [], "second writer must not take a position while the first holds the lock"

        first.commit()
        thread.join(timeout=5)
    finally:
        first.close()
        engine.dispose()

    assert second_seq
    assert second_seq[0] > first_seq
