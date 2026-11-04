"""Give a user a chosen newsletter address: `archie-set-ingest-address --email <email> --address news`.

Every user gets a random address at signup. The owner's existing subscriptions already point at `news@`, so this
replaces their random token with a readable one. It runs inside the deployed container (see `docs/deploy.md`),
where `DATABASE_URL` reaches the database; the email is passed on the command line so it never lands in the repo.
"""

from __future__ import annotations

import argparse
import re

import sqlalchemy
import sqlalchemy.orm
from archie_shared import config

from archie_db import models, session

# The API lower-cases a recipient and drops a `+tag`, so neither may appear; `.`, `_` and `-` only between characters,
# since mail servers reject a local part that starts or ends with one or doubles a dot.
_ADDRESS_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_MAX_ADDRESS_LENGTH = 16


class IngestAddressError(RuntimeError):
    """Raised when the address is malformed or taken, or the email doesn't name exactly one user."""


def set_ingest_address(db: sqlalchemy.orm.Session, *, email: str, address: str) -> str:
    """Point `address@<domain>` at the one user signed in as `email` (case-insensitive); returns the token it replaced.

    The replaced token's address stops receiving mail at once.
    """
    if len(address) > _MAX_ADDRESS_LENGTH or not _ADDRESS_PATTERN.fullmatch(address):
        raise IngestAddressError(
            f"Address must be 1-{_MAX_ADDRESS_LENGTH} lowercase letters, digits, '.', '_' or '-': {address!r}"
        )

    users = db.scalars(
        sqlalchemy.select(models.User).where(sqlalchemy.func.lower(models.User.email) == email.strip().lower())
    ).all()
    if len(users) != 1:
        raise IngestAddressError(f"Expected exactly one user with that email, found {len(users)}.")
    user = users[0]

    holder = db.scalars(sqlalchemy.select(models.User).where(models.User.ingest_token == address)).one_or_none()
    if holder is not None and holder.id != user.id:
        raise IngestAddressError(f"Address {address!r} already belongs to user {holder.id}.")

    previous_token = user.ingest_token
    user.ingest_token = address
    db.commit()
    return previous_token


def main(argv: list[str] | None = None) -> None:
    """CLI entry: `archie-set-ingest-address --email <email> --address <local part>`."""
    parser = argparse.ArgumentParser(description="Give a user a chosen newsletter address.")
    parser.add_argument("--email", required=True, help="The email the user signed in with.")
    parser.add_argument("--address", required=True, help="The part before @, e.g. news.")
    args = parser.parse_args(argv)

    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        previous_token = set_ingest_address(db, email=args.email, address=args.address)
    print(f"Newsletters to {args.address}@ now go to that user; {previous_token}@ no longer receives mail.")
