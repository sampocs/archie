"""Choosing a user's newsletter address: the right user gets it, and a taken or malformed address is refused."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import ingest_address, models, session

pytestmark = pytest.mark.postgres


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session over a database holding the owner (with an email) and another user."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as db_session:
        db_session.add_all([models.User(apple_sub="owner", email="Owner@Example.com"), models.User(apple_sub="other")])
        db_session.commit()
        yield db_session
    engine.dispose()


def test_the_user_with_that_email_gets_the_address(db: sqlalchemy.orm.Session) -> None:
    """The email matches case-insensitively, the address replaces their random token, and re-running is harmless."""
    ingest_address.set_ingest_address(db, email="owner@example.com", address="news")
    ingest_address.set_ingest_address(db, email="owner@example.com", address="news")

    owner = db.scalars(sqlalchemy.select(models.User).where(models.User.apple_sub == "owner")).one()
    assert owner.ingest_token == "news"


def test_an_address_another_user_holds_is_refused(db: sqlalchemy.orm.Session) -> None:
    """Taking someone else's address would silently reroute their newsletters."""
    other = db.scalars(sqlalchemy.select(models.User).where(models.User.apple_sub == "other")).one()

    with pytest.raises(ingest_address.IngestAddressError, match="already belongs"):
        ingest_address.set_ingest_address(db, email="owner@example.com", address=other.ingest_token)


@pytest.mark.parametrize("address", ["News", "news+tag", "", "a" * 17, "news.", "a..b", "-news"])
def test_an_address_the_api_could_never_match_is_refused(db: sqlalchemy.orm.Session, address: str) -> None:
    """Upper case and `+` are folded away when mail arrives, mail servers reject stray dots, and the column holds 16."""
    with pytest.raises(ingest_address.IngestAddressError, match="Address must be"):
        ingest_address.set_ingest_address(db, email="owner@example.com", address=address)


def test_an_unknown_email_is_refused(db: sqlalchemy.orm.Session) -> None:
    """A typo in the email must not quietly do nothing."""
    with pytest.raises(ingest_address.IngestAddressError, match="found 0"):
        ingest_address.set_ingest_address(db, email="nobody@example.com", address="news")
