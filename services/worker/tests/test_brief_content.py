"""The server's pass over the brief model's answer, and the text budget of its input, on hand-written content."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import pytest
from archie_shared.domains import Domain
from archie_worker import brief_content, prompts

NEWS_A = uuid.uuid4()
NEWS_B = uuid.uuid4()
UNKNOWN = uuid.uuid4()


def _story(headline: str, *, importance: int, source_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "headline": headline,
        "body": f"{headline} body.",
        "why": "",
        "detail": f"{headline} detail.",
        "importance": importance,
        "source_ids": [str(NEWS_A)] if source_ids is None else source_ids,
    }


def _assemble(domains: list[dict[str, Any]], *, also: list[dict[str, Any]] | None = None) -> brief_content.BriefContent:
    return brief_content.assemble({"domains": domains, "also": also or []}, news_ids={NEWS_A, NEWS_B}, essays=[])


def test_domains_follow_their_top_story_and_stories_their_importance() -> None:
    """Sports holds the 9, so it leads although the model listed it last; ties keep the model's order."""
    content = _assemble(
        [
            {"domain": "AI", "stories": [_story("ai-low", importance=3), _story("ai-high", importance=7)]},
            {"domain": "Sports", "stories": [_story("sports", importance=9)]},
            {"domain": "Macro", "stories": [_story("macro-first", importance=5), _story("macro-tie", importance=5)]},
        ]
    )

    assert [(group.domain, [story.headline for story in group.stories]) for group in content.domains] == [
        (Domain.SPORTS, ["sports"]),
        (Domain.AI, ["ai-high", "ai-low"]),
        (Domain.MACRO, ["macro-first", "macro-tie"]),
    ]


def test_only_the_ten_most_important_stories_are_shown_and_the_rest_become_also_lines() -> None:
    """Twelve stories: the two least important move to `also` as their headlines, ahead of the model's own lines."""
    stories = [_story(f"story-{importance}", importance=importance) for importance in range(1, 13)]
    content = _assemble(
        [{"domain": "AI", "stories": stories[:6]}, {"domain": "Macro", "stories": stories[6:]}],
        also=[{"text": "model line", "source_ids": [str(NEWS_B)]}],
    )

    shown = [story.headline for group in content.domains for story in group.stories]
    assert len(shown) == brief_content.MAX_STORIES == 10
    assert "story-1" not in shown and "story-2" not in shown
    assert [(line.text, line.source_ids) for line in content.also] == [
        ("story-2", [NEWS_A]),
        ("story-1", [NEWS_A]),
        ("model line", [NEWS_B]),
    ]


def test_unknown_source_ids_are_dropped_and_a_story_left_without_any_is_dropped() -> None:
    """An id that isn't a covered news newsletter goes; repeats and case or whitespace noise collapse to one."""
    content = _assemble(
        [
            {
                "domain": "AI",
                "stories": [
                    _story("mixed", importance=8, source_ids=[str(UNKNOWN), f" {str(NEWS_B).upper()} ", str(NEWS_B)]),
                    _story("only-unknown", importance=9, source_ids=[str(UNKNOWN), "not-an-id"]),
                ],
            }
        ],
        also=[{"text": "kept", "source_ids": [str(NEWS_A)]}, {"text": "dropped", "source_ids": [str(UNKNOWN)]}],
    )

    [group] = content.domains
    assert [(story.headline, story.source_ids) for story in group.stories] == [("mixed", [NEWS_B])]
    assert [line.text for line in content.also] == ["kept"]


def test_a_domain_left_without_stories_disappears_and_an_unknown_domain_is_other() -> None:
    """Two model entries that both resolve to Other merge into one group."""
    content = _assemble(
        [
            {"domain": "AI", "stories": [_story("gone", importance=9, source_ids=[str(UNKNOWN)])]},
            {"domain": "Gardening", "stories": [_story("garden", importance=4)]},
            {"domain": "Other", "stories": [_story("other", importance=6)]},
        ]
    )

    assert [(group.domain, [story.headline for story in group.stories]) for group in content.domains] == [
        (Domain.OTHER, ["other", "garden"])
    ]


@pytest.mark.parametrize(("raw", "stored"), [(0, 1), (-3, 1), (11, 10), (10, 10), (1, 1)])
def test_importance_is_clamped_to_one_through_ten(raw: int, stored: int) -> None:
    """The schema can't bound integers, so the server does."""
    [group] = _assemble([{"domain": "AI", "stories": [_story("s", importance=raw)]}]).domains

    assert group.stories[0].importance == stored


def test_stored_json_carries_ids_as_strings_and_domains_by_name() -> None:
    """The column holds plain JSON in the contract's shape, essays included."""
    essay = brief_content.Essay(source_id=NEWS_B, pitch="Worth it.")
    content = brief_content.assemble(
        {"domains": [{"domain": "Software engineering", "stories": [_story("s", importance=5)]}], "also": []},
        news_ids={NEWS_A},
        essays=[essay],
    )

    assert content.to_json() == {
        "domains": [
            {
                "domain": "Software engineering",
                "stories": [
                    {
                        "headline": "s",
                        "body": "s body.",
                        "why": "",
                        "detail": "s detail.",
                        "importance": 5,
                        "source_ids": [str(NEWS_A)],
                    }
                ],
            }
        ],
        "also": [],
        "essays": [{"source_id": str(NEWS_B), "pitch": "Worth it."}],
    }


def test_the_newest_newsletters_get_full_text_until_the_budget_is_spent() -> None:
    """Lengths oldest first: the newest two fit in 150,000; the third doesn't, so it and the oldest are summaries."""
    full, summary = prompts.BriefInput.FULL, prompts.BriefInput.SUMMARY

    assert _choose([10_000, 30_000, 100_000, 30_000]) == [summary, summary, full, full]
    assert _choose([30_000] * 5) == [full] * 5
    assert _choose([]) == []


def test_an_older_issue_that_would_fit_after_a_long_one_still_gets_its_summary() -> None:
    """Once the budget is hit, every older newsletter is a summary, even a short one."""
    assert _choose([10, 140_000, 20_000]) == [
        prompts.BriefInput.SUMMARY,
        prompts.BriefInput.SUMMARY,
        prompts.BriefInput.FULL,
    ]


def test_newsletters_older_than_the_summary_budget_are_omitted_even_when_short() -> None:
    """Five fill the text budget; the sixth's summary fits 60,000, the seventh's doesn't, and the tiny eighth is out."""
    full, summary, omitted = prompts.BriefInput.FULL, prompts.BriefInput.SUMMARY, prompts.BriefInput.OMITTED

    choices = prompts.choose_brief_inputs(
        text_lengths=[30_000] * 8, summary_lengths=[5, 40_000, 30_000, 1_000, 1_000, 1_000, 1_000, 1_000]
    )

    assert choices == [omitted, omitted, summary, full, full, full, full, full]


def _choose(text_lengths: list[int]) -> list[prompts.BriefInput]:
    """The choices when every summary is 1,000 characters."""
    return prompts.choose_brief_inputs(text_lengths=text_lengths, summary_lengths=[1_000] * len(text_lengths))


def test_the_brief_message_lists_domains_topics_and_each_newsletter_with_its_id() -> None:
    """A summarized newsletter says so, and its summary reads as gist, key ideas and numbers."""
    analysis = {
        "summary": {
            "gist": "The gist.",
            "key_ideas": [{"timestamp": None, "idea": "An idea."}],
            "numbers": [{"timestamp": None, "fact": "A number."}],
        }
    }
    received_at = datetime.datetime(2026, 11, 2, 7, 0, tzinfo=datetime.UTC)
    message = prompts.brief_message(
        newsletters=[
            prompts.BriefNewsletter(
                source_id=str(NEWS_A),
                sender="Morning Brew",
                subject="Old issue",
                received_at=received_at,
                text=prompts.summary_text(analysis),
                is_summary=True,
            ),
            prompts.BriefNewsletter(
                source_id=str(NEWS_B),
                sender=None,
                subject=None,
                received_at=received_at,
                text="Full text.",
                is_summary=False,
            ),
        ],
        live_topics=["AI › Agents"],
    )

    assert message.startswith(f"Domains: {', '.join(domain.value for domain in Domain)}\n")
    assert "- AI › Agents" in message
    assert (
        f'<newsletter id="{NEWS_A}">\nSender: Morning Brew\nSubject: Old issue\nDate: Monday 2026-11-02\n'
        "Given as: its summary\n\nThe gist.\n\nKey ideas:\n- An idea.\n\nNumbers:\n- A number.\n</newsletter>"
    ) in message
    assert f'<newsletter id="{NEWS_B}">\nSender: (unknown)\nSubject: (none)\n' in message
    assert "Given as: its full text\n\nFull text.\n</newsletter>" in message
