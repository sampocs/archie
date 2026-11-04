"""The fixed list of domains every source and topic belongs to; the app mirrors it in `app/src/topics/domains.ts`."""

from __future__ import annotations

from enum import StrEnum


class Domain(StrEnum):
    """A broad area of knowledge. The value is the display name: it is stored as is and shown by the app."""

    MACRO = "Macro"
    FINANCE = "Finance"
    TRADING = "Trading"
    CRYPTO = "Crypto"
    STARTUPS = "Startups"
    AI = "AI"
    POLITICS = "Politics"
    GEOPOLITICS = "Geopolitics"
    SPORTS = "Sports"
    GEOGRAPHY = "Geography"
    HISTORY = "History"
    SOFTWARE_ENGINEERING = "Software engineering"
    OTHER = "Other"


def parse_domain(raw: str) -> Domain:
    """`raw` as a Domain, matched case-insensitively; anything else (a model's invention) is Other."""
    wanted = raw.strip().casefold()
    return next((domain for domain in Domain if domain.value.casefold() == wanted), Domain.OTHER)
