"""Start a session for a user from the command line: `archie-issue-session --email <email>`.

The Bear import script runs on the owner's Mac and needs a session key; sign-in is Apple-only on the phone, so this
creates an ordinary, revocable session in the deployed container (see docs/deploy.md) and prints its key once.
"""

from __future__ import annotations

import argparse

import sqlalchemy
from archie_db import models, session
from archie_shared import config
from sqlalchemy import orm

from archie_api.auth import sessions


class IssueSessionError(RuntimeError):
    """Raised when the email doesn't name exactly one user."""


def issue_session(db: orm.Session, *, email: str) -> str:
    """A new session key for the one user signed in as `email` (case-insensitive)."""
    users = db.scalars(
        sqlalchemy.select(models.User).where(sqlalchemy.func.lower(models.User.email) == email.strip().lower())
    ).all()
    if len(users) != 1:
        raise IssueSessionError(f"Expected exactly one user with that email, found {len(users)}.")

    session_key = sessions.create_session(db, user_id=users[0].id)
    db.commit()
    return session_key


def main(argv: list[str] | None = None) -> None:
    """CLI entry: prints the new session key, the only time it is shown."""
    parser = argparse.ArgumentParser(description="Start a session for a user and print its key.")
    parser.add_argument("--email", required=True, help="The email the user signed in with.")
    args = parser.parse_args(argv)

    engine = session.engine_for(config.get_settings().require_database_url())
    with orm.Session(engine) as db:
        session_key = issue_session(db, email=args.email)
    print(f"Session key (shown once): {session_key}")
