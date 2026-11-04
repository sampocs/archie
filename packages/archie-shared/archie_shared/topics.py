"""Starting topics: the starter list the picker offers and the owner's own picks (topic names aren't private)."""

from __future__ import annotations

import re

from archie_shared.domains import Domain

OWNER_TOPICS: dict[Domain, tuple[str, ...]] = {
    Domain.MACRO: (
        "Fed & monetary policy",
        "Interest rates & bonds",
        "Inflation",
        "Liquidity & the Fed's balance sheet",
        "Dollar & currencies",
        "Jobs & the labor market",
        "Government debt & deficits",
        "Recessions & the business cycle",
        "Macro & risk assets",
        "Tariffs & trade",
    ),
    Domain.FINANCE: (
        "Investing fundamentals",
        "Stocks & public markets",
        "Venture capital",
        "Private equity",
        "Banking",
        "Valuing companies",
        "IPOs & M&A",
    ),
    Domain.TRADING: (
        "Market structure",
        "Market making",
        "Derivatives & options",
        "Perpetual futures",
        "Liquidity & volume",
        "Risk management",
        "Trading strategies",
        "Quant trading",
    ),
    Domain.CRYPTO: (
        "Bitcoin",
        "Ethereum",
        "Rollups & L2s",
        "Cosmos & IBC",
        "Solana",
        "DeFi",
        "Stablecoins",
        "Staking & restaking",
        "Tokenomics",
        "Data availability & modular chains",
        "Zero knowledge",
        "Crypto regulation",
        "Crypto investing",
    ),
    Domain.STARTUPS: ("Startup ideas", "Product-market fit", "Growth & marketing", "Fundraising", "Founder lessons"),
    Domain.AI: (
        "AI products & agents",
        "Models & AI labs",
        "Chips & Nvidia",
        "Data centers & hyperscalers",
        "Energy & power",
        "AI business & economics",
        "AI policy & safety",
    ),
    Domain.POLITICS: (
        "US politics & elections",
        "The Trump administration",
        "Congress & legislation",
        "Regulation",
        "Courts & the law",
        "Political economy",
    ),
    Domain.GEOPOLITICS: (
        "US–China",
        "Taiwan & chips",
        "Russia & Ukraine",
        "Middle East",
        "Europe",
        "Trade wars & sanctions",
        "Defense & military",
        "Global institutions",
    ),
    Domain.SPORTS: (
        "NFL play schemes",
        "NFL contracts & the salary cap",
        "NFL draft & team building",
        "Quarterbacks",
        "Sports business",
    ),
    Domain.GEOGRAPHY: (
        "Countries & capitals",
        "Physical geography",
        "Population & cities",
        "Natural resources",
        "Borders & regions",
        "Climate",
    ),
    Domain.HISTORY: (
        "US history",
        "The world wars",
        "The Cold War",
        "Ancient history",
        "Economic & financial history",
        "History of technology",
        "Empires",
    ),
    Domain.SOFTWARE_ENGINEERING: (
        "Frontend & mobile",
        "Backend & APIs",
        "Data engineering & databases",
        "DevOps & cloud",
        "AI/ML engineering",
        "Languages & tools",
    ),
}

# Starter topics the owner didn't pick; the owner gets them as removed, so they can be restored.
STARTER_EXTRAS: dict[Domain, tuple[str, ...]] = {
    Domain.FINANCE: ("Personal finance & taxes", "Insurance"),
    Domain.SPORTS: ("College football",),
}

# What the picker offers, in domain order; Other has no starter topics.
STARTER_TOPICS: dict[Domain, tuple[str, ...]] = {
    domain: OWNER_TOPICS.get(domain, ()) + STARTER_EXTRAS.get(domain, ())
    for domain in Domain
    if domain in OWNER_TOPICS or domain in STARTER_EXTRAS
}

_NOT_LETTER_OR_DIGIT = re.compile(r"[\W_]+")


def normalize_topic_name(name: str) -> str:
    """The form topic names are compared in: case-folded, `&` read as "and", punctuation and spacing ignored."""
    return " ".join(_NOT_LETTER_OR_DIGIT.sub(" ", name.casefold().replace("&", " and ")).split())


def is_starter_topic(*, domain: Domain, name: str) -> bool:
    """Whether `name` is one of the starter topics of `domain` (compared normalized)."""
    wanted = normalize_topic_name(name)
    return any(normalize_topic_name(starter) == wanted for starter in STARTER_TOPICS.get(domain, ()))
