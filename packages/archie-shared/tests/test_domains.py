"""The app's domain list matches `Domain` name for name and in order (pure file read, no database)."""

from __future__ import annotations

import pathlib
import re

from archie_shared.domains import Domain

APP_DOMAINS_FILE = pathlib.Path(__file__).resolve().parents[3] / "app" / "src" / "topics" / "domains.ts"


def test_app_domains_match_the_shared_enum() -> None:
    """The phone stores and colors domains by these exact names, so a drift would mis-file or uncolor them."""
    source = APP_DOMAINS_FILE.read_text()
    block = source[source.index("DOMAINS = [") : source.index("] as const")]

    assert re.findall(r'"([^"]+)"', block) == [domain.value for domain in Domain]
