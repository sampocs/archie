"""The newsletter scrubber removes per-recipient identifiers, and its leak check catches the ones it once missed."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[3]
SCRIPT = REPO_ROOT / "scripts" / "scrub_newsletter_email.py"
FIXTURES = "services/api/tests/fixtures/newsletters"

_spec = importlib.util.spec_from_file_location("scrub_newsletter_email", SCRIPT)
assert _spec and _spec.loader
scrub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrub)


def test_a_scheme_less_referral_link_loses_its_query() -> None:
    """The plain-text part prints the referral link without a scheme."""
    scrubbed = scrub.scrub_text("Share: morningbrew.com/r/?kid=0a1b2c3d and https://example.com/a?kid=1#x")

    assert scrubbed == "Share: morningbrew.com/r/ and https://example.com/a"


def test_a_substack_open_pixel_is_replaced_whole() -> None:
    """The recipient id lives in the pixel's path, so dropping the query is not enough."""
    scrubbed = scrub.scrub_text('<img src="https://eotrx.substackcdn.com/o/abc123/p.gif">')

    assert scrubbed == f'<img src="{scrub.PLACEHOLDER_TRACKED_URL}">'


def test_the_leak_check_names_a_referral_id_and_an_open_pixel() -> None:
    """The leak check is the backstop when a scrub rule is missing."""
    leaks = scrub.leaked_pattern_names(b"morningbrew.com/r/?kid=1 https://eotrx.substackcdn.com/o/x/p.gif")

    assert leaks == ["referral id", "open pixel"]


@pytest.mark.parametrize("name", ["morning_brew", "substack_bytebytego"])
def test_the_committed_fixtures_pass_the_leak_check(name: str) -> None:
    """Nothing the scrubber knows to look for is left in a committed fixture."""
    assert scrub.leaked_pattern_names((REPO_ROOT / FIXTURES / f"{name}.eml").read_bytes()) == []
