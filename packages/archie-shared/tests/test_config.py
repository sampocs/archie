"""The brief-rewrite debounce depends on the deployment: 15 minutes in prod, none for local and test runs."""

from __future__ import annotations

import datetime

import pytest
from archie_shared import config


@pytest.mark.parametrize(
    ("archie_env", "expected"),
    [
        ("prod", config.BRIEF_REWRITE_DELAY),
        ("dev", datetime.timedelta(0)),
        ("test", datetime.timedelta(0)),
        (None, datetime.timedelta(0)),
    ],
)
def test_the_brief_rewrite_delay_applies_only_in_prod(archie_env: str | None, expected: datetime.timedelta) -> None:
    """An unset `ARCHIE_ENV` counts as dev."""
    settings = config.Settings(archie_env=archie_env)

    assert settings.brief_rewrite_delay() == expected
    assert config.BRIEF_REWRITE_DELAY == datetime.timedelta(minutes=15)
