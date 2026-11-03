"""The auth-bypassing `/test/session` route exists only when `ARCHIE_ENV` is explicitly `dev` or `test`."""

import fastapi.testclient
import pytest
from archie_api import main
from archie_shared import config

_TEST_SESSION_PATH = "/test/session"


def _status_for_env(monkeypatch: pytest.MonkeyPatch, *, archie_env: str | None) -> int:
    if archie_env is None:
        monkeypatch.delenv(config.ARCHIE_ENV_ENV, raising=False)
    else:
        monkeypatch.setenv(config.ARCHIE_ENV_ENV, archie_env)

    client = fastapi.testclient.TestClient(main.create_app(), raise_server_exceptions=False)
    return client.post(_TEST_SESSION_PATH, json={}).status_code


@pytest.mark.parametrize("archie_env", [config.ArchieEnv.PROD, None, ""])
def test_the_test_route_is_absent_unless_env_is_explicit_dev_or_test(
    monkeypatch: pytest.MonkeyPatch, archie_env: str | None
) -> None:
    """A prod deploy, or one that forgot `ARCHIE_ENV`, must not expose the credential-free sign-in."""
    assert _status_for_env(monkeypatch, archie_env=archie_env) == 404


@pytest.mark.parametrize("archie_env", [config.ArchieEnv.DEV, config.ArchieEnv.TEST])
def test_the_test_route_is_mounted_for_dev_and_test(monkeypatch: pytest.MonkeyPatch, archie_env: str) -> None:
    """Routed means not 404; with no database configured the handler itself errors, which is fine here."""
    assert _status_for_env(monkeypatch, archie_env=archie_env) != 404
