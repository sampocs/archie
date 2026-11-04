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


def test_0002_backfills_existing_m1_sources(test_database_url: str) -> None:
    """M1 `link` rows get a normalized_url equal to their url and become `unsupported`, with a fresh change_seq."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0001")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub) VALUES ('sub')"))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO sources (id, user_id, url, kind, state, intent, change_seq) "
                "SELECT gen_random_uuid(), id, 'https://example.com/old', 'link', 'inbox', 'queue', "
                "nextval('change_seq') "
                "FROM users"
            )
        )

        old_change_seq: int = connection.execute(sqlalchemy.text("SELECT change_seq FROM sources")).scalar_one()

    migrate.upgrade(test_database_url)

    with engine.connect() as connection:
        row = connection.execute(sqlalchemy.text("SELECT normalized_url, processing, change_seq FROM sources")).one()
    assert row.change_seq > old_change_seq
    assert (row.normalized_url, row.processing) == ("https://example.com/old", "unsupported")
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()
