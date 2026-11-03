"""Apply Archie's Postgres migrations: `archie-db upgrade` and `archie-db downgrade`.

Migrations ship inside the package (`archie_db/migrations`), so no `alembic.ini` is needed; the URL comes
from `DATABASE_URL`.
"""

from __future__ import annotations

import argparse
from enum import StrEnum

import alembic.command
import alembic.config
from archie_shared import config

_SCRIPT_LOCATION = "archie_db:migrations"
_HEAD = "head"
_BASE = "base"


class MigrateCommand(StrEnum):
    """Which direction to migrate."""

    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"


def alembic_config(database_url: str) -> alembic.config.Config:
    """An Alembic config pointing at the packaged migrations and `database_url`."""
    alembic_settings = alembic.config.Config()
    alembic_settings.set_main_option("script_location", _SCRIPT_LOCATION)
    # ConfigParser interpolation treats `%` specially, and URL-encoded passwords contain it.
    alembic_settings.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return alembic_settings


def upgrade(database_url: str, revision: str = _HEAD) -> None:
    """Migrate the database up to `revision` (default: latest)."""
    alembic.command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str, revision: str = _BASE) -> None:
    """Migrate the database down to `revision` (default: empty)."""
    alembic.command.downgrade(alembic_config(database_url), revision)


def main(argv: list[str] | None = None) -> None:
    """CLI entry: `archie-db upgrade [--revision R]` or `archie-db downgrade [--revision R]`."""
    parser = argparse.ArgumentParser(description="Apply Archie's Postgres migrations.")
    parser.add_argument("command", choices=[command.value for command in MigrateCommand])
    parser.add_argument(
        "--revision", default=None, help="Target revision (default: head for upgrade, base for downgrade)."
    )
    args = parser.parse_args(argv)

    database_url = config.get_settings().require_database_url()
    if MigrateCommand(args.command) is MigrateCommand.UPGRADE:
        upgrade(database_url, revision=args.revision or _HEAD)
        return
    downgrade(database_url, revision=args.revision or _BASE)
