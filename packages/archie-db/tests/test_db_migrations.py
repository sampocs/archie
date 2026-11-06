"""Postgres-backed tests: the migrations build the schema the models describe, and reverse cleanly."""

from __future__ import annotations

import re

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


def test_0003_gives_existing_users_an_ingest_token(test_database_url: str) -> None:
    """Users that predate M3 each get a distinct 10-character lowercase-or-digit token."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0002")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub) VALUES ('sub-a'), ('sub-b')"))

    migrate.upgrade(test_database_url)

    with engine.connect() as connection:
        tokens = [row.ingest_token for row in connection.execute(sqlalchemy.text("SELECT ingest_token FROM users"))]
    assert len(set(tokens)) == 2
    assert all(re.fullmatch(r"[a-z0-9]{10}", token) for token in tokens)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()


def test_0004_backfills_queue_positions_and_read_markers(test_database_url: str) -> None:
    """Queued sources rank newest on top (-1 for the oldest, counting down).

    Every source counts its primer opened; only newsletters count as read.

    Each source also gets a newer change_seq, so phones pull the new columns.
    """
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0003")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub, ingest_token) VALUES ('sub', 'token')"))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO sources (id, user_id, url, normalized_url, kind, state, intent, created_at, change_seq) "
                "SELECT gen_random_uuid(), users.id, row.url, row.url, row.kind, row.state, 'queue', row.created_at, "
                "nextval('change_seq') "
                "FROM users, (VALUES "
                "('https://example.com/older', 'article', 'queued', now() - interval '2 days'), "
                "('https://example.com/newer', 'article', 'queued', now() - interval '1 day'), "
                "('newsletter:1', 'newsletter', 'inbox', now())"
                ") AS row (url, kind, state, created_at)"
            )
        )
        seq_rows = connection.execute(sqlalchemy.text("SELECT url, change_seq FROM sources")).all()
        old_change_seqs: dict[str, int] = {row.url: row.change_seq for row in seq_rows}

    migrate.upgrade(test_database_url)

    with engine.connect() as connection:
        rows = {
            row.url: row
            for row in connection.execute(
                sqlalchemy.text("SELECT url, queue_position, primer_opened_at, read_at, change_seq FROM sources")
            )
        }
    assert {url: row.queue_position for url, row in rows.items()} == {
        "https://example.com/older": -1,
        "https://example.com/newer": -2,
        "newsletter:1": None,
    }
    assert all(row.primer_opened_at is not None for row in rows.values())
    assert all(row.change_seq > old_change_seqs[url] for url, row in rows.items())
    assert [url for url, row in rows.items() if row.read_at is not None] == ["newsletter:1"]
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()


def test_0007_keeps_existing_cards_and_enforces_one_origin(test_database_url: str) -> None:
    """A pre-review card comes through as a new, unscheduled card; a card needs exactly one origin."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0006")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub, ingest_token) VALUES ('sub', 'token')"))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO sources (id, user_id, url, normalized_url, kind, state, intent, change_seq) "
                "SELECT '00000000-0000-0000-0000-000000000001', id, 'https://example.com/a', "
                "'https://example.com/a', 'article', 'inbox', 'queue', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO source_artifacts (id, user_id, source_id, kind, version, content, is_current, change_seq) "
                "SELECT '00000000-0000-0000-0000-000000000002', user_id, id, 'summary', 1, '{}', true, "
                "nextval('change_seq') FROM sources"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, artifact_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), user_id, source_id, id, 'concept', 'Q?', 'A.', nextval('change_seq') "
                "FROM source_artifacts"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.connect() as connection:
        card = connection.execute(sqlalchemy.text("SELECT fsrs_state, reps, due_at FROM cards")).one()
        cards_off: bool = connection.execute(sqlalchemy.text("SELECT cards_off FROM sources")).scalar_one()
    assert (card.fsrs_state, card.reps, card.due_at) == ("new", 0, None)
    assert cards_off is False

    # Both a source and a brief, then no origin at all: each breaks the one-origin CHECK.
    two_origins = (
        "INSERT INTO briefs (id, user_id, status, change_seq) "
        "SELECT '00000000-0000-0000-0000-000000000003', id, 'done', nextval('change_seq') FROM users; "
        "INSERT INTO cards (id, user_id, source_id, brief_id, kind, question, answer, change_seq) "
        "SELECT gen_random_uuid(), user_id, id, '00000000-0000-0000-0000-000000000003', 'quiz', 'Q?', 'A.', "
        "nextval('change_seq') FROM sources"
    )
    no_origin = (
        "INSERT INTO cards (id, user_id, kind, question, answer, change_seq) "
        "SELECT gen_random_uuid(), id, 'quiz', 'Q?', 'A.', nextval('change_seq') FROM users"
    )
    for statement in (two_origins, no_origin):
        with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as connection:
            for part in statement.split("; "):
                connection.execute(sqlalchemy.text(part))

    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()
