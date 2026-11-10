"""Cards from a chat, pure logic: the tool's validation, the transcript, the gist and the history line."""

from __future__ import annotations

import uuid

from archie_api.ask import card_routes, card_set_tools, context
from archie_db import models

CARD = {
    "kind": "concept",
    "question": "What is a JWT?",
    "answer": "A signed token with claims",
    "detail": ["The server checks the signature, not a session"],
}
# A card as stored before cards had detail.
OLD_CARD = {"kind": "concept", "question": "What is a JWT?", "answer": "A signed token with claims"}


def _propose(**changes: object) -> card_set_tools.ToolOutcome:
    tool_input = {"title": "JWTs", "cheat_sheet": "# JWTs\n\nSigned tokens.", "cards": [CARD], **changes}
    return card_set_tools.run(tool_use_id="t1", tool_input=tool_input, note_title=None)


def test_a_valid_card_set_is_a_proposal_and_a_bad_one_an_error_the_model_can_fix() -> None:
    """Fields are trimmed; too many cards, a kind chats don't make, a blank question or a long title come back as
    error results naming the field, with no proposal."""
    valid = _propose(title="  JWTs ", cards=[{**CARD, "question": " What is a JWT? "}])
    assert valid.proposal is not None and "is_error" not in valid.result
    assert valid.proposal.card_set.title == "JWTs"
    assert card_set_tools.cards_of(valid.proposal.card_set) == [CARD]

    # Detail lines are cleaned as stored: a line's own newline becomes a space and a blank line goes.
    messy = _propose(cards=[{**CARD, "detail": [" The server checks\nthe signature ", "  ", "No session"]}])
    assert messy.proposal is not None
    assert card_set_tools.cards_of(messy.proposal.card_set)[0]["detail"] == [
        "The server checks the signature",
        "No session",
    ]

    invalid = {
        "cards": _propose(cards=[CARD] * (card_set_tools.MAX_CARDS + 1)),
        "cards.0.kind": _propose(cards=[{**CARD, "kind": "quiz"}]),
        "cards.0.question": _propose(cards=[{**CARD, "question": "   "}]),
        "title": _propose(title="x" * (card_set_tools.MAX_TITLE_CHARACTERS + 1)),
    }
    for field, outcome in invalid.items():
        assert outcome.proposal is None
        assert outcome.result["is_error"] and outcome.result["content"].startswith(f"Invalid input: {field}:")


def test_a_chat_needs_a_cheat_sheet_but_a_notes_set_is_titled_after_the_note_without_one() -> None:
    """A free-standing chat's blank cheat sheet is an error; in a chat about a note the set takes the note's title (cut
    to the limit) and drops any cheat sheet the model wrote, so the empty one validates."""
    blank = _propose(cheat_sheet="  ")
    assert blank.proposal is None and blank.result["content"].startswith("Invalid input: cheat_sheet:")

    long_title = "Liquid staking " * 20
    tool_input = {"title": "Anything", "cheat_sheet": "# A sheet the note doesn't need", "cards": [CARD]}
    for_note = card_set_tools.run(tool_use_id="t1", tool_input=tool_input, note_title=long_title)
    assert for_note.proposal is not None and "is_error" not in for_note.result
    card_set = for_note.proposal.card_set
    assert (card_set.title, card_set.cheat_sheet) == (long_title[: card_set_tools.MAX_TITLE_CHARACTERS].strip(), "")

    no_cards = card_set_tools.run(tool_use_id="t1", tool_input={**tool_input, "cards": []}, note_title="Staking")
    assert no_cards.proposal is None and no_cards.result["content"].startswith("Invalid input: cards:")


def test_a_notes_set_may_not_have_foundation_cards_but_a_chats_may() -> None:
    """Foundation cards are background a primer covers; a note has its write-up, so the model must correct them."""
    tool_input = {"title": "Staking", "cheat_sheet": "# Sheet", "cards": [{**CARD, "kind": "foundation"}]}

    for_note = card_set_tools.run(tool_use_id="t1", tool_input=tool_input, note_title="Staking")
    assert for_note.proposal is None and for_note.result["is_error"]
    assert "foundation" in for_note.result["content"]

    in_chat = card_set_tools.run(tool_use_id="t1", tool_input=tool_input, note_title=None)
    assert in_chat.proposal is not None


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

    numbered = "1. first step\n2. second\n\nA JWT is signed."
    assert card_routes.gist_of(numbered, title="JWTs") == "A JWT is signed."

    long_gist = card_routes.gist_of("word " * 100, title="JWTs")
    assert len(long_gist) <= card_routes.MAX_GIST_CHARACTERS and long_gist.endswith("d…")

    assert card_routes.gist_of("# Only a heading", title="JWTs") == "JWTs"


def test_a_stored_set_from_before_detail_reads_its_cards_with_none() -> None:
    """A set stored before cards had detail parses, each card with an empty detail; a newer one keeps its lines."""
    card_set = models.CardSetProposal(title="JWTs", cheat_sheet="", cards=[OLD_CARD, CARD], status="proposed")

    [old, new] = card_set_tools.stored_cards(card_set)

    assert (old.question, old.answer, old.detail) == (OLD_CARD["question"], OLD_CARD["answer"], [])
    assert new.detail == CARD["detail"]


def test_the_history_line_carries_an_open_set_and_only_names_a_replaced_one() -> None:
    """The model can rebuild an open, saved or discarded set with one change; a replaced one is just named."""
    card_set = models.CardSetProposal(
        title="JWTs", cheat_sheet="# JWTs", cards=[CARD], status=models.CardSetStatus.SAVED.value
    )

    assert context.card_set_note(card_set) == (
        "[cards proposed: JWTs — the owner saved it]\n<cheat_sheet>\n# JWTs\n</cheat_sheet>\n"
        "1. (concept) Q: What is a JWT?\n   A: A signed token with claims\n"
        "   - The server checks the signature, not a session"
    )
    card_set.status = models.CardSetStatus.REPLACED.value
    assert context.card_set_note(card_set) == "[cards proposed: JWTs — replaced by a later proposal]"


def test_the_history_line_of_a_notes_set_has_no_cheat_sheet() -> None:
    """A note's set has an empty cheat sheet, so its line goes straight from the status to the cards; a card without
    detail ends at its answer."""
    card_set = models.CardSetProposal(title="Staking", cheat_sheet="", cards=[OLD_CARD], status="proposed")

    assert context.card_set_note(card_set) == (
        "[cards proposed: Staking — waiting for the owner to save it]\n"
        "1. (concept) Q: What is a JWT?\n   A: A signed token with claims"
    )


def test_the_keep_ticks_line_names_the_kept_numbers_and_the_dropped_questions() -> None:
    """One kept card is "card 1"; several dropped ones are listed with their questions in order, however the kept
    indices came; a question's stored ticks read back, and an answer's segments hold none."""
    cards = [{**CARD, "question": f"Q{number}?"} for number in range(1, 5)]
    card_set = models.CardSetProposal(title="JWTs", cheat_sheet="", cards=cards, status="proposed")

    assert context.choice_line(kept=[0], card_set=card_set) == (
        "The owner kept card 1 of the proposed set and dropped 2 (“Q2?”), 3 (“Q3?”) and 4 (“Q4?”)."
    )
    assert context.choice_line(kept=[3, 1], card_set=card_set) == (
        "The owner kept cards 2 and 4 of the proposed set and dropped 1 (“Q1?”) and 3 (“Q3?”)."
    )

    choice = context.CardSetChoice(proposal_id=uuid.uuid4(), kept=(1, 3), card_count=4)
    assert context.stored_choice(choice.to_segments()) == choice
    answer_segments = [{"label": "background", "text": "A JWT is signed.", "citations": []}]
    assert context.stored_choice(answer_segments) is None and context.stored_choice(None) is None
