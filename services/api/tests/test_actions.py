"""Every action type the phone can push has a handler, so none falls through to "not supported"."""

from __future__ import annotations

from archie_api.sync import actions, schemas


def test_every_action_type_has_a_handler() -> None:
    """A new `ActionType` without a `HANDLERS` entry would be rejected for every phone that sends it."""
    assert set(actions.HANDLERS) == set(schemas.ActionType)
