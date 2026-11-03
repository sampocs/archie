"""Postgres-backed tests: the migrations build the schema the models describe, and reverse cleanly."""

from __future__ import annotations

import alembic.autogenerate
import alembic.migration
import pytest
import sqlalchemy
from archie_db import migrate, models, session

pytestmark = pytest.mark.postgres


def test_models_match_the_migrations(migrated_database_url: str) -> None:
    """Autogenerate finds no difference between the ORM models and the migrated schema."""
    engine = session.engine_for(migrated_database_url)
    with engine.connect() as connection:
        context = alembic.migration.MigrationContext.configure(connection)
        differences = alembic.autogenerate.compare_metadata(context, models.Base.metadata)
    engine.dispose()

    assert differences == []


def test_downgrade_then_upgrade_round_trips(test_database_url: str) -> None:
    """`downgrade` removes every model table and `upgrade` restores them."""
    tables = set(models.Base.metadata.tables)
    migrate.upgrade(test_database_url)
    migrate.downgrade(test_database_url)
    engine = session.engine_for(test_database_url)
    assert not tables & set(sqlalchemy.inspect(engine).get_table_names())

    migrate.upgrade(test_database_url)

    assert tables <= set(sqlalchemy.inspect(engine).get_table_names())
    engine.dispose()
