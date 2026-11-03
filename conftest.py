"""Test-wide isolation: no test may read real credentials or reach the network.

A developer `.env` at the repo root holds live API keys. Without this guard, a settings test could
read it (printing a real key in an assertion diff) and a handler test could make a real, billed call.
Tests that need a setting set a fake one explicitly with `monkeypatch.setenv`; outside calls are
replayed from recorded cassettes, never made live.

The one exception is tests marked `@pytest.mark.postgres`: they keep real sockets so they can reach
the local test Postgres started by `make db-up` (and the e2e stack's own local server), but
credentials are still stripped, so they can only connect to what `TEST_DATABASE_URL` (never the
possibly-live `DATABASE_URL`) names.
"""

from __future__ import annotations

import _socket  # The real, unpatchable primitives `socket` wraps; see the postgres-marker branch below.
import os
import socket
from collections.abc import Iterator
from typing import NoReturn

import pytest
import sqlalchemy
from archie_db import migrate, session
from archie_shared import config

# Every env var carrying a credential, endpoint, or deployment switch. Cleared so a shell-exported
# value can't leak in.
_SECRET_ENV_VARS = (
    config.DATABASE_URL_ENV,
    config.OWNER_EMAILS_ENV,
    config.APPLE_AUDIENCE_ENV,
    config.ARCHIE_ENV_ENV,
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
)

NETWORK_REFUSED_MESSAGE = "Tests must not open network connections; replay a recorded cassette instead."

# Tests that need Postgres read this (never DATABASE_URL, which may point at a real database).
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
POSTGRES_MARKER = "postgres"


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker for tests that talk to the local test Postgres."""
    config.addinivalue_line("markers", f"{POSTGRES_MARKER}: needs {TEST_DATABASE_URL_ENV} (make db-up)")


@pytest.fixture(autouse=True)
def isolate_from_credentials_and_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip credentials, ignore `.env` files, and refuse every real network connection."""
    for name in _SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    # pydantic-settings reads `env_file` on every construction.
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)

    # Postgres tests connect to the local test database, so they keep real sockets. Restored from
    # the `_socket` C extension (never itself patched) rather than merely left alone, so this still
    # works when a marked test runs nested inside another test's patched state.
    if request.node.get_closest_marker(POSTGRES_MARKER) is not None:
        monkeypatch.setattr(socket, "getaddrinfo", _socket.getaddrinfo)
        monkeypatch.setattr(socket.socket, "connect", _socket.socket.connect)
        monkeypatch.setattr(socket.socket, "connect_ex", _socket.socket.connect_ex)
        return

    monkeypatch.setattr(socket, "getaddrinfo", _refuse_network)
    monkeypatch.setattr(socket.socket, "connect", _refuse_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse_network)


@pytest.fixture
def test_database_url(request: pytest.FixtureRequest) -> str:
    """The local test Postgres URL; skips when unset and insists the test carries the marker."""
    if request.node.get_closest_marker(POSTGRES_MARKER) is None:
        pytest.fail(f"tests using Postgres must be marked @pytest.mark.{POSTGRES_MARKER}")
    database_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not database_url:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is unset; run `make db-up` and `make test-db`")
    return database_url


# Emptied after every Postgres test so tests never see each other's rows.
# SCAFFOLD: sample table list; becomes ("applied_actions", "jobs", "sources", "sessions", "users") in plan Task 2.
_TRUNCATE_TABLES = ("sources",)


@pytest.fixture
def migrated_database_url(test_database_url: str) -> Iterator[str]:
    """The test database migrated to the latest schema; every table is emptied after the test."""
    migrate.upgrade(test_database_url)
    yield test_database_url

    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text(f"TRUNCATE {', '.join(_TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"))
    engine.dispose()


def _refuse_network(*args: object, **kwargs: object) -> NoReturn:
    # Raise even where the real call would return an errno (`connect_ex`) or an OSError: a loud,
    # non-OSError failure can't be mistaken for a flaky connection and quietly retried.
    raise RuntimeError(NETWORK_REFUSED_MESSAGE)
