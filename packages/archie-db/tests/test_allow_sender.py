"""`archie-allow-sender`: each value becomes the identifiers an email from it would have; bad input is refused."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import allow_sender, models, session
from archie_shared import config

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


def _recorded(db: sqlalchemy.orm.Session) -> list[tuple[str, str, str, str]]:
    """(owner apple_sub, status, kind, value) of every identifier on file."""
    rows = db.execute(
        sqlalchemy.select(
            models.User.apple_sub,
            models.NewsletterSender.status,
            models.NewsletterSenderIdentifier.kind,
            models.NewsletterSenderIdentifier.value,
        )
        .join(models.NewsletterSender, models.NewsletterSender.id == models.NewsletterSenderIdentifier.sender_id)
        .join(models.User, models.User.id == models.NewsletterSender.user_id)
        .order_by(models.NewsletterSenderIdentifier.id)
    )
    return [(row.apple_sub, row.status, row.kind, row.value) for row in rows]


@pytest.mark.parametrize(
    ("sender", "kind", "value"),
    [
        ("MorningBrew.com", "domain", "morningbrew.com"),
        ("news.example.co.uk", "domain", "example.co.uk"),
        ("bytebytego@Substack.com", "address", "bytebytego@substack.com"),
        ("crew@mail.morningbrew.com", "domain", "morningbrew.com"),
        ("ByteByteGo", "name", "bytebytego"),
        ("  The  Hustle ", "name", "the hustle"),
    ],
)
def test_a_value_becomes_the_identifier_an_email_from_it_would_have(
    db: sqlalchemy.orm.Session, sender: str, kind: str, value: str
) -> None:
    """Guessed kinds follow ingest's rules: shared platforms by address, other domains by domain, no dot by name."""
    allow_sender.allow_sender(db, email="owner@example.com", sender=sender)

    assert _recorded(db) == [("owner", "allowed", kind, value)]


def test_an_explicit_kind_skips_the_guess(db: sqlalchemy.orm.Session) -> None:
    """A name with a dot would be guessed as a domain; `--kind name` keeps it a name."""
    allow_sender.allow_sender(
        db, email="owner@example.com", sender="Morning Brew Inc.", kind=models.IdentifierKind.NAME
    )
    allow_sender.allow_sender(
        db, email="owner@example.com", sender="<List.Example.Invalid>", kind=models.IdentifierKind.LIST_ID
    )

    assert _recorded(db) == [
        ("owner", "allowed", "name", "morning brew inc."),
        ("owner", "allowed", "list_id", "list.example.invalid"),
    ]


@pytest.mark.parametrize("sender", ["substack.com", "mail.beehiiv.com", "gmail.com"])
def test_a_shared_platform_domain_is_refused_and_nothing_is_recorded(db: sqlalchemy.orm.Session, sender: str) -> None:
    """Allowing the bare platform would allow everyone on it."""
    with pytest.raises(allow_sender.AllowSenderError, match="shared sending platform"):
        allow_sender.allow_sender(db, email="owner@example.com", sender=sender)

    assert _recorded(db) == []


def test_an_unknown_email_is_refused_and_nothing_is_recorded(db: sqlalchemy.orm.Session) -> None:
    """A typo in the email must not quietly do nothing."""
    with pytest.raises(allow_sender.AllowSenderError, match="found 0"):
        allow_sender.allow_sender(db, email="nobody@example.com", sender="morningbrew.com")

    assert _recorded(db) == []


def test_allowing_releases_a_waiting_newsletter_and_repeating_changes_nothing(db: sqlalchemy.orm.Session) -> None:
    """The CLI settles pending mail like the phone's Allow does, and a second run adds no job."""
    owner = db.scalars(sqlalchemy.select(models.User).where(models.User.apple_sub == "owner")).one()
    waiting = models.Source(
        id=uuid.uuid4(),
        user_id=owner.id,
        url="newsletter:waiting",
        normalized_url="newsletter:waiting",
        kind=models.SourceKind.NEWSLETTER.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.QUEUE.value,
        sender="Writer",
        sender_address="writer@example.com",
        sender_pending=True,
        processing=models.ProcessingStatus.READY.value,
        change_seq=1,
    )
    db.add_all([waiting, models.SourceCapture(source_id=waiting.id, title="Hi", text="Body")])
    db.commit()

    for _ in range(2):
        allow_sender.allow_sender(db, email="owner@example.com", sender="example.com")

    db.refresh(waiting)
    assert (waiting.sender_pending, waiting.processing) == (False, models.ProcessingStatus.PENDING.value)
    assert db.scalars(sqlalchemy.select(sqlalchemy.func.count(models.Job.id))).one() == 1


def test_the_command_reads_its_arguments_and_the_database_url(
    db: sqlalchemy.orm.Session, migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`main` wires `--email`, `--sender` and `--kind` through to the recorded identifier."""
    monkeypatch.setenv(config.DATABASE_URL_ENV, migrated_database_url)

    allow_sender.main(["--email", "Owner@example.com", "--sender", "morningbrew.com", "--kind", "name"])

    assert _recorded(db) == [("owner", "allowed", "name", "morningbrew.com")]
