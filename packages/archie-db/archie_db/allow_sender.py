"""Allow a newsletter sender from the command line: `archie-allow-sender --email <email> --sender <value>`.

Newsletters from a sender nobody has allowed wait, unprocessed, for the owner's decision on the phone. This records
the decision ahead of time (for the owner's existing subscriptions after a deploy, or local test newsletters). It runs
inside the deployed container (see `docs/deploy.md`), where `DATABASE_URL` reaches the database; the email is passed
on the command line so it never lands in the repo.
"""

from __future__ import annotations

import argparse

import sqlalchemy
import sqlalchemy.orm
from archie_shared import config

from archie_db import changes, models, senders, session


class AllowSenderError(RuntimeError):
    """Raised when the sender value can't be allowed, or the email doesn't name exactly one user."""


def classify_sender(value: str, *, kind: models.IdentifierKind | None) -> list[senders.SenderIdentifier]:
    """The identifiers `value` stands for, normalised as ingest does.

    An explicit `kind` is taken as given (an address is then recorded as itself). Otherwise a value with `@` is
    an address, which stands for the identifiers an email from it would have: its domain, or itself when the domain is
    a shared platform; a value with a dot and no spaces is a domain (never a shared platform's); anything else is a
    display name.
    """
    value = value.strip()
    if kind is None and "@" in value:
        identifiers = senders.identifiers_for(address=value, list_id=None, name=None)
        if not identifiers:
            raise AllowSenderError(f"Not an email address with a usable domain: {value!r}")
        return identifiers

    if kind is None:
        kind = _guess_kind(value)
    if kind == models.IdentifierKind.ADDRESS:
        if "@" not in value:
            raise AllowSenderError(f"Not an email address: {value!r}")
        return [senders.SenderIdentifier(kind=kind, value=value.lower())]
    if kind == models.IdentifierKind.DOMAIN:
        return [_domain_identifier(value)]
    if kind == models.IdentifierKind.LIST_ID:
        list_id = senders.normalize_list_id(value)
        if list_id is None:
            raise AllowSenderError("The List-Id is empty.")
        return [senders.SenderIdentifier(kind=kind, value=list_id)]

    name = senders.normalize_name(value)
    if name is None:
        raise AllowSenderError("The sender name is empty.")
    return [senders.SenderIdentifier(kind=kind, value=name)]


def allow_sender(
    db: sqlalchemy.orm.Session, *, email: str, sender: str, kind: models.IdentifierKind | None = None
) -> list[senders.SenderIdentifier]:
    """Allow `sender` for the one user signed in as `email` (case-insensitive); returns the identifiers recorded."""
    identifiers = classify_sender(sender, kind=kind)

    users = db.scalars(
        sqlalchemy.select(models.User).where(sqlalchemy.func.lower(models.User.email) == email.strip().lower())
    ).all()
    if len(users) != 1:
        raise AllowSenderError(f"Expected exactly one user with that email, found {len(users)}.")
    user = users[0]

    changes.lock_user_writes(db, user.id)
    senders.record(
        db, user_id=user.id, identifiers=identifiers, status=models.SenderStatus.ALLOWED, label=sender.strip()
    )
    db.commit()
    return identifiers


def main(argv: list[str] | None = None) -> None:
    """CLI entry: `archie-allow-sender --email <email> --sender <value> [--kind domain|address|list_id|name]`."""
    parser = argparse.ArgumentParser(description="Allow a newsletter sender for a user.")
    parser.add_argument("--email", required=True, help="The email the user signed in with.")
    parser.add_argument("--sender", required=True, help="A domain, an email address, a List-Id or a display name.")
    parser.add_argument("--kind", choices=[kind.value for kind in models.IdentifierKind], help="Skip the guess.")
    args = parser.parse_args(argv)

    kind = models.IdentifierKind(args.kind) if args.kind else None
    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        identifiers = allow_sender(db, email=args.email, sender=args.sender, kind=kind)
    recorded = ", ".join(f"{identifier.kind}={identifier.value}" for identifier in identifiers)
    print(f"Allowed ({recorded}); waiting newsletters from them are now processed.")


def _guess_kind(value: str) -> models.IdentifierKind:
    if "." in value and " " not in value:
        return models.IdentifierKind.DOMAIN
    return models.IdentifierKind.NAME


def _domain_identifier(value: str) -> senders.SenderIdentifier:
    domain = senders.registrable_domain(value)
    if domain is None:
        raise AllowSenderError(f"Not a domain: {value!r}")
    if domain in senders.SHARED_SENDER_DOMAINS:
        raise AllowSenderError(
            f"{domain} is a shared sending platform: allowing it would allow everyone on it. "
            "Pass the sender's full address instead."
        )
    return senders.SenderIdentifier(kind=models.IdentifierKind.DOMAIN, value=domain)
