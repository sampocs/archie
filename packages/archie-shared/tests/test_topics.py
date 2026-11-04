"""Unit tests for topic-name normalizing, the starter list and domain parsing (pure functions, no database)."""

from __future__ import annotations

import itertools

import pytest
from archie_shared import domains, topics
from archie_shared.domains import Domain


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Fed & Monetary Policy", "fed and monetary policy"),
        ("fed and monetary  policy", "fed and monetary policy"),
        ("US–China", "us china"),
        ("AI/ML engineering", "ai ml engineering"),
        ("  Rollups & L2s!", "rollups and l2s"),
    ],
)
def test_normalize_topic_name_ignores_case_ampersands_punctuation_and_spacing(name: str, expected: str) -> None:
    """Names that read the same compare equal."""
    assert topics.normalize_topic_name(name) == expected


def test_starter_topics_are_the_owner_topics_plus_the_extras() -> None:
    """The picker offers every owner pick plus exactly the three extras, and nothing for Other."""
    owner_names = {(domain, name) for domain, names in topics.OWNER_TOPICS.items() for name in names}
    starter_names = {(domain, name) for domain, names in topics.STARTER_TOPICS.items() for name in names}

    assert starter_names - owner_names == {
        (Domain.FINANCE, "Personal finance & taxes"),
        (Domain.FINANCE, "Insurance"),
        (Domain.SPORTS, "College football"),
    }
    assert owner_names <= starter_names
    assert Domain.OTHER not in topics.STARTER_TOPICS


def test_no_two_starter_topics_normalize_equal() -> None:
    """Seeding them all never collides with the per-user unique name rule."""
    names = [topics.normalize_topic_name(name) for name in itertools.chain(*topics.STARTER_TOPICS.values())]

    assert len(names) == len(set(names))


def test_parse_domain_matches_case_insensitively_and_falls_back_to_other() -> None:
    """A model's lower-cased domain is accepted; an invented one becomes Other."""
    assert domains.parse_domain("software engineering") is Domain.SOFTWARE_ENGINEERING
    assert domains.parse_domain("Tech") is Domain.OTHER


def test_is_starter_topic_compares_normalized_names_within_the_domain() -> None:
    """Insurance is a Finance starter, not a Macro one."""
    assert topics.is_starter_topic(domain=Domain.FINANCE, name="insurance") is True
    assert topics.is_starter_topic(domain=Domain.MACRO, name="Insurance") is False
