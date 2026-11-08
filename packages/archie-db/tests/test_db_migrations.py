"""Postgres-backed tests: the migrations build the schema the models describe, and reverse cleanly."""

from __future__ import annotations

import importlib.util
import pathlib
import re
from typing import Any

import alembic.autogenerate
import alembic.migration
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import migrate, models, senders, session

pytestmark = pytest.mark.postgres


# Alembic reflects pgvector's `vector` as an unknown type and skips comparing it (plan Decision 1).
@pytest.mark.filterwarnings("ignore:Did not recognize type 'vector':sqlalchemy.exc.SAWarning")
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


def test_0010_keeps_existing_cards_and_allows_exactly_one_origin_including_a_take(test_database_url: str) -> None:
    """A scheduled source card survives 0010 unchanged; a take card is allowed; one with a source and a take isn't."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0009")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub, ingest_token) VALUES ('sub', 'token')"))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO sources (id, user_id, url, normalized_url, kind, state, intent, change_seq) "
                "SELECT '00000000-0000-0000-0000-000000000001', id, 'https://example.com/a', "
                "'https://example.com/a', 'article', 'consumed', 'finished', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, kind, question, answer, fsrs_state, stability, reps, "
                "change_seq) SELECT '00000000-0000-0000-0000-000000000002', user_id, id, 'concept', 'Q?', 'A.', "
                "'review', 3.5, 2, nextval('change_seq') FROM sources"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.connect() as connection:
        card = connection.execute(
            sqlalchemy.text("SELECT source_id, fsrs_state, stability, reps, take_id, take_version_id FROM cards")
        ).one()
    assert (str(card.source_id), card.fsrs_state, card.stability, card.reps) == (
        "00000000-0000-0000-0000-000000000001",
        "review",
        3.5,
        2,
    )
    assert (card.take_id, card.take_version_id) == (None, None)

    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO takes (id, user_id, kind, title, current_version, change_seq) "
                "SELECT '00000000-0000-0000-0000-000000000003', id, 'opinion', 'T', 1, nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, take_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), user_id, id, 'take', 'Q?', 'A.', nextval('change_seq') FROM takes"
            )
        )

    # A source and a take on one card breaks the one-origin CHECK.
    with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, take_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), takes.user_id, sources.id, takes.id, 'take', 'Q?', 'A.', "
                "nextval('change_seq') FROM takes, sources"
            )
        )

    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()


def test_0011_keeps_cards_allows_a_conversation_origin_and_indexes_chunk_words(test_database_url: str) -> None:
    """A pre-M7 card survives; a card needs exactly one of five origins; `tsv` is generated; embeddings round-trip."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0010")
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
                "INSERT INTO cards (id, user_id, source_id, kind, question, answer, fsrs_state, reps, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000c1', id, '00000000-0000-0000-0000-000000000001', "
                "'concept', 'Q?', 'A.', 'review', 2, nextval('change_seq') FROM users"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.begin() as connection:
        card = connection.execute(sqlalchemy.text("SELECT fsrs_state, reps, conversation_id FROM cards")).one()
        assert (card.fsrs_state, card.reps, card.conversation_id) == ("review", 2, None)

        connection.execute(
            sqlalchemy.text(
                "INSERT INTO conversations (id, user_id, title, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000a1', id, 'Q', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, conversation_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000a1', 'concept', 'Q?', 'A.', "
                "nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO chunks (user_id, owner_kind, source_id, chunk_index, text) "
                "SELECT id, 'source_text', '00000000-0000-0000-0000-000000000001', 0, "
                "'Stablecoins settle payments without a bank' FROM users"
            )
        )
        matched: int = connection.execute(
            sqlalchemy.text("SELECT count(*) FROM chunks WHERE tsv @@ websearch_to_tsquery('english', 'stablecoin')")
        ).scalar_one()
        assert matched == 1

    with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, conversation_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-000000000001', "
                "'00000000-0000-0000-0000-0000000000a1', 'concept', 'Q?', 'A.', nextval('change_seq') FROM users"
            )
        )

    with sqlalchemy.orm.Session(engine) as db:
        chunk = db.scalars(sqlalchemy.select(models.Chunk)).one()
        chunk.embedding = [0.5] + [0.0] * (models.EMBEDDING_DIMENSIONS - 1)
        db.commit()
        db.expire_all()
        stored = db.scalars(sqlalchemy.select(models.Chunk)).one().embedding
        assert stored is not None and stored[0] == 0.5 and len(stored) == models.EMBEDDING_DIMENSIONS

    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()


def test_0013_keeps_versions_with_their_defaults_and_cascades_proposals(test_database_url: str) -> None:
    """Rows written before 0013 get origin archie/owner and card version 1; proposals and card versions cascade."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0012")
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
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-000000000001', 'primer', 1, "
                "'{\"markdown\": \"## A\"}', true, nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, kind, question, answer, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000c1', id, '00000000-0000-0000-0000-000000000001', "
                "'concept', 'Q?', 'A.', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO takes (id, user_id, kind, title, current_version, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000d1', id, 'opinion', 'T', 1, nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO take_versions (id, user_id, take_id, version, body, raw_body, cleaned, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000d1', 1, 'B', 'B', false, "
                "nextval('change_seq') FROM users"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.begin() as connection:
        assert connection.execute(sqlalchemy.text("SELECT origin FROM source_artifacts")).scalar_one() == "archie"
        assert connection.execute(sqlalchemy.text("SELECT version FROM cards")).scalar_one() == 1
        assert connection.execute(sqlalchemy.text("SELECT origin FROM take_versions")).scalar_one() == "owner"

        connection.execute(
            sqlalchemy.text(
                "INSERT INTO card_versions (id, user_id, card_id, version, question, answer, origin, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000c1', 1, 'Q?', 'A.', 'archie', "
                "nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO conversations (id, user_id, title, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000a1', id, 'Q', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO messages (id, user_id, conversation_id, role, text, status, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000b1', id, '00000000-0000-0000-0000-0000000000a1', "
                "'assistant', 'A', 'complete', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO edit_proposals (id, user_id, conversation_id, message_id, target_kind, target_id, title, "
                "description, base_version, before, after, status, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000a1', "
                "'00000000-0000-0000-0000-0000000000b1', 'card', '00000000-0000-0000-0000-0000000000c1', 'Q?', "
                '\'Say B\', 1, \'{"question": "Q?", "answer": "A."}\', '
                '\'{"question": "Q?", "answer": "B."}\', '
                "'proposed', nextval('change_seq') FROM users"
            )
        )

        connection.execute(sqlalchemy.text("DELETE FROM conversations"))
        connection.execute(sqlalchemy.text("DELETE FROM cards"))
        assert connection.execute(sqlalchemy.text("SELECT count(*) FROM edit_proposals")).scalar_one() == 0
        assert connection.execute(sqlalchemy.text("SELECT count(*) FROM card_versions")).scalar_one() == 0

    migrate.downgrade(test_database_url, "0012")
    migrate.upgrade(test_database_url)

    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()


def test_0014_keeps_existing_sources_with_no_confirm_url(test_database_url: str) -> None:
    """A source stored before 0014 keeps its row and reads as not a confirmation; the new column takes a link."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0013")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub, ingest_token) VALUES ('sub', 'token')"))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO sources (id, user_id, url, normalized_url, kind, state, intent, change_seq) "
                "SELECT gen_random_uuid(), users.id, 'newsletter:1', 'newsletter:1', 'newsletter', 'inbox', 'queue', "
                "nextval('change_seq') FROM users"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.begin() as connection:
        rows = connection.execute(sqlalchemy.text("SELECT url, confirm_url FROM sources")).all()
        assert [(row.url, row.confirm_url) for row in rows] == [("newsletter:1", None)]
        connection.execute(sqlalchemy.text("UPDATE sources SET confirm_url = 'https://example.com/confirm'"))
        assert connection.execute(sqlalchemy.text("SELECT confirm_url FROM sources")).scalar_one() == (
            "https://example.com/confirm"
        )
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()


def test_0015_keeps_existing_sources_and_allows_live_newsletter_display_names(test_database_url: str) -> None:
    """Existing sources get no address and aren't pending; live newsletters' display names become allowed senders.

    Names that differ only in case or spacing make one sender (labelled by the oldest spelling), a deleted newsletter's
    and a confirmation's names make none, and each user gets their own.
    """
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0014")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO users (apple_sub, ingest_token) VALUES ('one', 'token-one'), ('two', 'token-two')"
            )
        )
        _insert_newsletter_0014(connection, apple_sub="one", sender=" Morning  Brew", created_at="2026-01-02")
        _insert_newsletter_0014(connection, apple_sub="one", sender="morning brew", created_at="2026-01-03")
        _insert_newsletter_0014(connection, apple_sub="one", sender="Deleted One", deleted=True)
        _insert_newsletter_0014(connection, apple_sub="one", sender="Confirm Co", confirm_url="https://example.com/c")
        _insert_newsletter_0014(connection, apple_sub="two", sender="Morning Brew")

    migrate.upgrade(test_database_url)

    with engine.begin() as connection:
        sources = connection.execute(
            sqlalchemy.text("SELECT sender_address, list_id, sender_pending FROM sources")
        ).all()
        assert {(row.sender_address, row.list_id, row.sender_pending) for row in sources} == {(None, None, False)}

        senders = connection.execute(
            sqlalchemy.text(
                "SELECT users.apple_sub, newsletter_senders.label, newsletter_senders.status, "
                "newsletter_sender_identifiers.kind, newsletter_sender_identifiers.value "
                "FROM newsletter_senders "
                "JOIN newsletter_sender_identifiers ON sender_id = newsletter_senders.id "
                "JOIN users ON users.id = newsletter_senders.user_id ORDER BY users.apple_sub"
            )
        ).all()
        assert [tuple(row) for row in senders] == [
            ("one", " Morning  Brew", "allowed", "name", "morning brew"),
            ("two", "Morning Brew", "allowed", "name", "morning brew"),
        ]
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()


@pytest.mark.parametrize(
    "name",
    [
        " Morning  Brew",
        "The   Hustle ",
        "TLDR",
        "Milk Road Daily",
        "  mixed Case\tTabs ",
        "\tLeading",
        "Morning\xa0Brew",
        "Trailing\n",
        "Wide\u3000\u2003Gap\x85End\x1c",
    ],
)
def test_the_backfill_sql_normalises_a_name_as_the_python_does(test_database_url: str, name: str) -> None:
    """Backfilled `name` identifiers must equal what ingest computes for the same display name."""
    migrate.upgrade(test_database_url)
    engine = session.engine_for(test_database_url)
    with engine.connect() as connection:
        in_sql: str = connection.execute(
            sqlalchemy.text(f"SELECT {_migration_0015().normalised_name_sql('CAST(:name AS text)')}"),
            {"name": name},
        ).scalar_one()
    engine.dispose()

    assert in_sql == senders.normalize_name(name)


def _migration_0015() -> Any:
    """The 0015 migration module, to run the exact normalising SQL its backfill uses."""
    path = pathlib.Path(migrate.__file__).parent / "migrations" / "versions" / "0015_newsletter_senders.py"
    spec = importlib.util.spec_from_file_location("migration_0015", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _insert_newsletter_0014(
    connection: sqlalchemy.Connection,
    *,
    apple_sub: str,
    sender: str,
    created_at: str = "2026-01-01",
    deleted: bool = False,
    confirm_url: str | None = None,
) -> None:
    connection.execute(
        sqlalchemy.text(
            "INSERT INTO sources (id, user_id, url, normalized_url, kind, state, intent, sender, confirm_url, "
            "created_at, deleted_at, change_seq) "
            "SELECT gen_random_uuid(), users.id, :url, :url, 'newsletter', 'inbox', 'queue', :sender, :confirm_url, "
            "CAST(:created_at AS timestamptz), "
            "CASE WHEN :deleted THEN now() END, nextval('change_seq') FROM users WHERE apple_sub = :apple_sub"
        ),
        {
            "url": f"newsletter:{apple_sub}:{sender}",
            "sender": sender,
            "confirm_url": confirm_url,
            "created_at": created_at,
            "deleted": deleted,
            "apple_sub": apple_sub,
        },
    )
