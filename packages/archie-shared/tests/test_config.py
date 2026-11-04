"""Unit tests for settings parsing."""

from __future__ import annotations

from archie_shared import config


def test_ingest_alias_map_skips_malformed_entries_and_folds_case() -> None:
    """Both sides are trimmed and lower-cased; entries lacking `=` or a side are dropped."""
    settings = config.Settings(ingest_aliases=" News=A@X.com, test=a@x.com ,broken,=nobody@x.com,empty=, ")

    assert settings.ingest_alias_map() == {"news": "a@x.com", "test": "a@x.com"}


def test_ingest_alias_map_empty_when_unset() -> None:
    """Unset aliases mean no aliases."""
    assert config.Settings(ingest_aliases=None).ingest_alias_map() == {}
