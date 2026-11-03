"""Session resolution rules that an e2e call can't observe: the `last_used_at` throttle and revocation."""

import datetime

import pytest
import sqlalchemy
from archie_api.auth import sessions
from archie_db import models
from archie_db import session as db_session
from sqlalchemy import orm

pytestmark = pytest.mark.postgres


def _last_used_at(db: orm.Session) -> datetime.datetime:
    db.expire_all()
    return db.scalars(sqlalchemy.select(models.Session.last_used_at)).one()


def test_last_used_at_is_refreshed_only_when_stale(migrated_database_url: str) -> None:
    """A fresh session is left alone; one unused for over an hour is touched."""
    engine = db_session.engine_for(migrated_database_url)
    with orm.Session(engine) as db:
        user = models.User(apple_sub="throttle")
        db.add(user)
        db.flush()
        raw_key = sessions.create_session(db, user_id=user.id)
        db.commit()
        fresh = _last_used_at(db)

        assert sessions.resolve_session(db, raw_key=raw_key) is not None
        assert _last_used_at(db) == fresh

        stale = fresh - sessions.SESSION_TOUCH_INTERVAL - datetime.timedelta(minutes=1)
        db.execute(sqlalchemy.update(models.Session).values(last_used_at=stale))
        db.commit()

        assert sessions.resolve_session(db, raw_key=raw_key) is not None
        assert db.dirty
        db.commit()
        assert _last_used_at(db) > stale
    engine.dispose()


def test_a_revoked_session_does_not_resolve(migrated_database_url: str) -> None:
    """Revoking is permanent, and revoking twice is harmless."""
    engine = db_session.engine_for(migrated_database_url)
    with orm.Session(engine) as db:
        user = models.User(apple_sub="revoked")
        db.add(user)
        db.flush()
        raw_key = sessions.create_session(db, user_id=user.id)

        sessions.revoke_session(db, raw_key=raw_key)
        sessions.revoke_session(db, raw_key=raw_key)

        assert sessions.resolve_session(db, raw_key=raw_key) is None
    engine.dispose()
