"""Cards from a chat, pure logic: the tool's validation, the transcript, the gist and the history line."""

from __future__ import annotations

import uuid

from archie_api.ask import card_routes, card_set_tools, context
from archie_db import models

CARD = {"kind": "concept", "question": "What is a JWT?", "answer": "A signed token that carries its claims."}


def _propose(**changes: object) -> card_set_tools.ToolOutcome:
    tool_input = {"title": "JWTs", "cheat_sheet": "# JWTs\n\nSigned tokens.", "cards": [CARD], **changes}
    return card_set_tools.run(tool_use_id="t1", tool_input=tool_input)


def test_a_valid_card_set_is_a_proposal_and_a_bad_one_an_error_the_model_can_fix() -> None:
    """Fields are trimmed; too many cards, a kind chats don't make, a blank question or a long title come back as
    error results naming the field, with no proposal."""
    valid = _propose(title="  JWTs ", cards=[{**CARD, "question": " What is a JWT? "}])
    assert valid.proposal is not None and "is_error" not in valid.result
    assert valid.proposal.card_set.title == "JWTs"
    assert card_set_tools.cards_of(valid.proposal.card_set) == [CARD]

    invalid = {
        "cards": _propose(cards=[CARD] * (card_set_tools.MAX_CARDS + 1)),
        "cards.0.kind": _propose(cards=[{**CARD, "kind": "quiz"}]),
        "cards.0.question": _propose(cards=[{**CARD, "question": "   "}]),
        "title": _propose(title="x" * (card_set_tools.MAX_TITLE_CHARACTERS + 1)),
    }
    for field, outcome in invalid.items():
        assert outcome.proposal is None
        assert outcome.result["is_error"] and outcome.result["content"].startswith(f"Invalid input: {field}:")


def test_the_cards_event_is_the_row_as_pulled_before_it_has_a_position() -> None:
    """The event names the answer it will be saved on and has every pulled field, open and unpositioned."""
    outcome = _propose()
    assert outcome.proposal is not None
    conversation_id, message_id = uuid.uuid4(), uuid.uuid4()

    event = outcome.proposal.to_event(conversation_id=conversation_id, message_id=message_id)

    assert (event["conversation_id"], event["message_id"]) == (str(conversation_id), str(message_id))
    assert (event["status"], event["saved_source_id"], event["kept"], event["change_seq"]) == (
        "proposed",
        None,
        None,
        0,
    )
    assert event["cards"] == [CARD] and event["created_at"] == event["updated_at"]


def test_the_transcript_names_each_speaker_and_skips_empty_messages() -> None:
    """`**You:**` and `**Archie:**` turns, trimmed, a blank line apart."""
    lines = [
        card_routes.TranscriptLine(role=models.MessageRole.USER, text=" JWT vs session? "),
        card_routes.TranscriptLine(role=models.MessageRole.ASSISTANT, text="   "),
        card_routes.TranscriptLine(role=models.MessageRole.ASSISTANT, text="A JWT is signed."),
    ]

    assert card_routes.transcript(lines) == "**You:** JWT vs session?\n\n**Archie:** A JWT is signed."


def test_the_gist_is_the_first_prose_paragraph_cut_at_a_word() -> None:
    """Headings, tables and lists are skipped; a long paragraph is cut under the limit with an ellipsis; a sheet with
    no prose falls back to the title."""
    sheet = "# JWTs\n\n## Basics\n\n- a list\n\n| a | b |\n|---|---|\n\nA JWT is\nsigned.\n\nMore."
    assert card_routes.gist_of(sheet, title="JWTs") == "A JWT is signed."

    long_gist = card_routes.gist_of("word " * 100, title="JWTs")
    assert len(long_gist) <= card_routes.MAX_GIST_CHARACTERS and long_gist.endswith("d…")

    assert card_routes.gist_of("# Only a heading", title="JWTs") == "JWTs"


def test_the_history_line_carries_an_open_set_and_only_names_a_replaced_one() -> None:
    """The model can rebuild an open, saved or discarded set with one change; a replaced one is just named."""
    card_set = models.CardSetProposal(
        title="JWTs", cheat_sheet="# JWTs", cards=[CARD], status=models.CardSetStatus.SAVED.value
    )

    assert context.card_set_note(card_set) == (
        "[cards proposed: JWTs — the owner saved it]\n<cheat_sheet>\n# JWTs\n</cheat_sheet>\n"
        "1. (concept) Q: What is a JWT?\n   A: A signed token that carries its claims."
    )
    card_set.status = models.CardSetStatus.REPLACED.value
    assert context.card_set_note(card_set) == "[cards proposed: JWTs — replaced by a later proposal]"
