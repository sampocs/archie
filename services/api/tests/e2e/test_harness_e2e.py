"""The live-stack harness cleans up after itself."""

import pytest
from archie_shared import config
from archie_testing import harness

pytestmark = pytest.mark.postgres


def test_authed_clients_are_closed_when_the_stack_stops(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every client `authed` handed out is closed on exit, so no connection outlives the stack."""
    monkeypatch.setenv(config.DATABASE_URL_ENV, migrated_database_url)
    monkeypatch.setenv(config.ARCHIE_ENV_ENV, "test")

    with harness.running_stack(database_url=migrated_database_url, start_worker=False) as stack:
        authed = stack.authed(stack.sign_in())
        assert not authed.is_closed

    assert authed.is_closed
