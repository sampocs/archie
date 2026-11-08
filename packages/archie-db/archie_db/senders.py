"""Newsletter senders the owner allowed or blocked: who an email is from, and recording a decision.

A sender is a set of identifiers (registrable domain, full address, List-Id, display name), and an email matches
when any one of its identifiers belongs to a decided sender. Shared by the API (ingest and the `set_sender_status`
action) and the `archie-allow-sender` CLI. `record` and `resolve_pending` write synced rows, so their callers hold
the user's write lock (`changes.lock_user_writes`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import publicsuffixlist
import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, models, pipeline, source_rows

# Platforms and mailbox providers that many unrelated senders share: an email from one is identified by its full
# address, so the bare platform domain is never recorded or matched (allowing one Substack never allows another).
SHARED_SENDER_DOMAINS = frozenset(
    {
        "substack.com",
        "beehiiv.com",
        "ghost.io",
        "convertkit.com",
        "kit.com",
        "mcsv.net",
        "mcdlv.net",
        "mailchimpapp.com",
        "buttondown.email",
        "buttondown.com",
        "mailerlite.com",
        "sendgrid.net",
        "amazonses.com",
        "gmail.com",
        "googlemail.com",
        "google.com",
        "outlook.com",
        "hotmail.com",
        "yahoo.com",
        "icloud.com",
    }
)
MAX_ADDRESS_LENGTH = 320  # the width of `Source.sender_address`
MAX_VALUE_LENGTH = 998  # the width of `NewsletterSenderIdentifier.value` and `Source.list_id`

# Built once: the list ships in the package, so nothing is fetched.
_PUBLIC_SUFFIXES = publicsuffixlist.PublicSuffixList(only_icann=True)


@dataclass(frozen=True)
class SenderIdentifier:
    """One normalised thing an email can be matched to a sender by."""

    kind: models.IdentifierKind
    value: str


def normalize_name(name: str | None) -> str | None:
    """A display name trimmed, whitespace collapsed and lower-cased; None when empty."""
    return " ".join((name or "").split()).lower() or None


def normalize_list_id(list_id: str | None) -> str | None:
    """A `List-Id` header's `<...>` part (the whole trimmed value without brackets), lower-cased; None when empty."""
    value = (list_id or "").strip()
    if "<" in value and ">" in value:
        value = value[value.index("<") + 1 : value.index(">")]
    return value.strip().lower() or None


def registrable_domain(host: str) -> str | None:
    """The registrable domain of `host`, lower-cased; None for an IP, a host without a dot, or no suffix answer."""
    host = host.strip().lower().rstrip(".")
    if "." not in host or ":" in host or host.rsplit(".", maxsplit=1)[1].isdigit():
        return None
    return _PUBLIC_SUFFIXES.privatesuffix(host)


def identifiers_for(*, address: str | None, list_id: str | None, name: str | None) -> list[SenderIdentifier]:
    """Every identifier an email with this From address, List-Id and display name has (see the module docstring).

    The address counts as its registrable domain, or as itself when that domain is a shared platform; a value that
    can't be stored (too long) is left out.
    """
    identifiers: list[SenderIdentifier] = []

    full_address = (address or "").strip().lower()
    if "@" in full_address and len(full_address) <= MAX_ADDRESS_LENGTH:
        domain = registrable_domain(full_address.rpartition("@")[2])
        if domain in SHARED_SENDER_DOMAINS:
            identifiers.append(SenderIdentifier(kind=models.IdentifierKind.ADDRESS, value=full_address))
        elif domain is not None:
            identifiers.append(SenderIdentifier(kind=models.IdentifierKind.DOMAIN, value=domain))

    normalized_list_id = normalize_list_id(list_id)
    if normalized_list_id and len(normalized_list_id) <= MAX_VALUE_LENGTH:
        identifiers.append(SenderIdentifier(kind=models.IdentifierKind.LIST_ID, value=normalized_list_id))

    normalized_name = normalize_name(name)
    if normalized_name and len(normalized_name) <= MAX_VALUE_LENGTH:
        identifiers.append(SenderIdentifier(kind=models.IdentifierKind.NAME, value=normalized_name))
    return identifiers


def status_for(
    db: sqlalchemy.orm.Session, *, user_id: int, identifiers: Sequence[SenderIdentifier]
) -> models.SenderStatus | None:
    """`allowed` if any identifier belongs to an allowed sender, else `blocked` if any does to a blocked one, else None.

    Allowed wins: when identifiers disagree, the email is processed.
    """
    owners = _owning_senders(db, user_id=user_id, identifiers=identifiers)
    statuses = {owner.status for owner in owners}
    if models.SenderStatus.ALLOWED in statuses:
        return models.SenderStatus.ALLOWED
    if models.SenderStatus.BLOCKED in statuses:
        return models.SenderStatus.BLOCKED
    return None


def record(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    identifiers: Sequence[SenderIdentifier],
    status: models.SenderStatus,
    label: str,
) -> None:
    """Give the sender these identifiers `status`, then settle the user's pending newsletters.

    The senders that already own any identifier are merged into the oldest: each gets `status` (touched only if it
    changed) and the identifiers nobody owns yet are attached to the oldest. With no owner, one new sender is made.
    Repeating a call changes nothing.
    """
    owners = _owning_senders(db, user_id=user_id, identifiers=identifiers)

    if owners:
        kept = owners[0]
        for owner in owners:
            _set_status(owner, status=status)
    else:
        kept = models.NewsletterSender(
            id=uuid.uuid4(), user_id=user_id, label=label, status=status.value, change_seq=changes.next_change_seq()
        )
        db.add(kept)
        db.flush()

    owned = _owned_identifiers(db, user_id=user_id, identifiers=identifiers)
    db.add_all(
        models.NewsletterSenderIdentifier(
            sender_id=kept.id, user_id=user_id, kind=identifier.kind.value, value=identifier.value
        )
        for identifier in dict.fromkeys(identifiers)
        if identifier not in owned
    )
    db.flush()

    resolve_pending(db, user_id=user_id)


def set_status(db: sqlalchemy.orm.Session, *, sender: models.NewsletterSender, status: models.SenderStatus) -> None:
    """Set one sender's status (touched only if it changed), then settle the user's pending newsletters."""
    _set_status(sender, status=status)
    resolve_pending(db, user_id=sender.user_id)


def resolve_pending(db: sqlalchemy.orm.Session, *, user_id: int) -> None:
    """Re-check every live pending newsletter of the user against the senders now on file.

    Allowed: no longer pending, and processing starts (a capture is analyzed; without one the email is unreadable).
    Blocked: deleted. Unknown: left alone. Repeating it finds nothing more to change.
    """
    pending = db.scalars(
        sqlalchemy.select(models.Source)
        .where(
            models.Source.user_id == user_id,
            models.Source.sender_pending.is_(True),
            models.Source.deleted_at.is_(None),
        )
        .order_by(models.Source.created_at, models.Source.id)
    ).all()

    for source in pending:
        identifiers = identifiers_for(address=source.sender_address, list_id=source.list_id, name=source.sender)
        status = status_for(db, user_id=user_id, identifiers=identifiers)
        if status == models.SenderStatus.ALLOWED:
            _release(db, source=source)
        elif status == models.SenderStatus.BLOCKED:
            source_rows.soft_delete_source(db, source=source)


def _release(db: sqlalchemy.orm.Session, *, source: models.Source) -> None:
    source.sender_pending = False
    if db.get(models.SourceCapture, source.id) is None:
        source.processing = models.ProcessingStatus.FAILED.value
        source.processing_error = models.UNREADABLE_EMAIL_ERROR
        changes.touch(source)
        return

    source.processing = models.ProcessingStatus.PENDING.value
    changes.touch(source)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.FETCH_CONTENT])


def _set_status(sender: models.NewsletterSender, *, status: models.SenderStatus) -> None:
    if sender.status == status.value:
        return
    sender.status = status.value
    changes.touch(sender)


def _owning_senders(
    db: sqlalchemy.orm.Session, *, user_id: int, identifiers: Sequence[SenderIdentifier]
) -> list[models.NewsletterSender]:
    """The user's senders that own any of `identifiers`, oldest first."""
    if not identifiers:
        return []
    return list(
        db.scalars(
            sqlalchemy.select(models.NewsletterSender)
            .where(
                models.NewsletterSender.user_id == user_id,
                models.NewsletterSender.id.in_(
                    sqlalchemy.select(models.NewsletterSenderIdentifier.sender_id).where(
                        models.NewsletterSenderIdentifier.user_id == user_id, _any_identifier(identifiers)
                    )
                ),
            )
            .order_by(models.NewsletterSender.created_at, models.NewsletterSender.id)
        )
    )


def _owned_identifiers(
    db: sqlalchemy.orm.Session, *, user_id: int, identifiers: Sequence[SenderIdentifier]
) -> set[SenderIdentifier]:
    if not identifiers:
        return set()
    rows = db.execute(
        sqlalchemy.select(models.NewsletterSenderIdentifier.kind, models.NewsletterSenderIdentifier.value).where(
            models.NewsletterSenderIdentifier.user_id == user_id, _any_identifier(identifiers)
        )
    )
    return {SenderIdentifier(kind=models.IdentifierKind(kind), value=value) for kind, value in rows}


def _any_identifier(identifiers: Sequence[SenderIdentifier]) -> sqlalchemy.ColumnElement[bool]:
    return sqlalchemy.or_(
        *(
            sqlalchemy.and_(
                models.NewsletterSenderIdentifier.kind == identifier.kind.value,
                models.NewsletterSenderIdentifier.value == identifier.value,
            )
            for identifier in identifiers
        )
    )
