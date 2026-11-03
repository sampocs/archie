"""`current_user` commits only when resolving the session actually changed something."""

import datetime

import pytest
import sqlalchemy
from archie_api import deps
from archie_api.auth import sessions
from archie_db import models
from archie_db import session as db_session
from sqlalchemy import orm

pytestmark = pytest.mark.postgres


def _commit_count_after_auth(migrated_database_url: str, *, stale: bool, monkeypatch: pytest.MonkeyPatch) -> int:
    engine = db_session.engine_for(migrated_database_url)
    with orm.Session(engine) as db:
        user = models.User(apple_sub="commits")
        db.add(user)
        db.flush()
        raw_key = sessions.create_session(db, user_id=user.id)
        if stale:
            stale_at = datetime.datetime.now(tz=datetime.UTC) - sessions.SESSION_TOUCH_INTERVAL * 2
            db.execute(sqlalchemy.update(models.Session).values(last_used_at=stale_at))
        db.commit()

        commits: list[None] = []
        real_commit = db.commit
        monkeypatch.setattr(db, "commit", lambda: (commits.append(None), real_commit())[1])

        assert deps.current_user(db=db, raw_key=raw_key).apple_sub == "commits"
        if stale:
            db.expire_all()
            assert db.scalars(sqlalchemy.select(models.Session.last_used_at)).one() > stale_at
    engine.dispose()
    return len(commits)


def test_a_fresh_session_costs_no_commit(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing was touched, so there is nothing to commit (and no expired user to reload)."""
    assert _commit_count_after_auth(migrated_database_url, stale=False, monkeypatch=monkeypatch) == 0


def test_a_stale_session_touch_is_committed(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refreshed `last_used_at` must land even though the route itself only reads."""
    assert _commit_count_after_auth(migrated_database_url, stale=True, monkeypatch=monkeypatch) == 1
