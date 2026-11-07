"""Editing tools' pure logic: find/replace application and the history lines that tell the model about edits."""

from __future__ import annotations

import pytest
from archie_api.ask import context, edit_tools
from archie_db import models


def test_replacements_apply_in_order_and_each_must_match_exactly_once() -> None:
    """A later find sees the earlier replacement; a missing or repeated find is an error naming it."""
    text = "## Rates\nThe Fed sets rates.\nBanks follow."

    assert (
        edit_tools.apply_replacements(
            text,
            replacements=[("sets rates", "sets short-term rates"), ("short-term rates.\n", "short-term rates.\n\n")],
        )
        == "## Rates\nThe Fed sets short-term rates.\n\nBanks follow."
    )
    assert (
        edit_tools.apply_replacements(text, replacements=[("\nBanks follow.", "")]) == "## Rates\nThe Fed sets rates."
    )

    with pytest.raises(edit_tools.ToolInputError, match="isn't in the current text"):
        edit_tools.apply_replacements(text, replacements=[("The ECB", "x")])
    with pytest.raises(edit_tools.ToolInputError, match="appears 2 times"):
        edit_tools.apply_replacements(text, replacements=[("es", "x")])


def test_history_adds_the_cited_items_and_the_edits_after_an_answer() -> None:
    """The model sees which items an earlier answer cited and what became of the edits it proposed."""
    segments = [
        {
            "label": "library",
            "text": "Fees compound.",
            "citations": [
                {
                    "kind": "library",
                    "title": "Index funds",
                    "source_id": "s1",
                    "topic_primer_id": None,
                    "take_id": None,
                },
                {
                    "kind": "library",
                    "title": "Index funds",
                    "source_id": "s1",
                    "topic_primer_id": None,
                    "take_id": None,
                },
                {"kind": "web", "title": "Vanguard", "url": "https://vanguard.com"},
            ],
        }
    ]
    notes = context.citation_notes(segments)
    assert notes == ["[cited: Index funds — source s1]"]

    rows = [
        context.HistoryMessage(
            role=models.MessageRole.USER, text="Drop the fees idea", status=models.MessageStatus.COMPLETE
        ),
        context.HistoryMessage(
            role=models.MessageRole.ASSISTANT,
            text="Here's the edit.",
            status=models.MessageStatus.COMPLETE,
            notes=("[edit proposed: Drop the fees idea — summary s1 — the owner applied it]",),
        ),
    ]
    assert context.history_messages(rows)[-1] == {
        "role": "assistant",
        "content": "Here's the edit.\n\n[edit proposed: Drop the fees idea — summary s1 — the owner applied it]",
    }
