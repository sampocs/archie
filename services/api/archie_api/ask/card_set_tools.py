"""Ask's `propose_cards` tool: a cheat sheet and review cards from the chat, which the owner saves from the chat.

In a chat about a note the set is the note's own cards: it is titled after the note and has no cheat sheet, since the
note already has its write-up.

A proposal changes nothing: it is validated here, shown to the owner at once as a `cards` event carrying the row as
the phone will pull it, and stored with the answer by `save_proposals`, which marks the chat's earlier open proposals
`replaced`. The owner's Save goes through `archie_api.ask.card_routes`. A bad input goes back to the model as an
error result it can fix.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pydantic
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models

from archie_api.ask import edit_tools
from archie_api.sync import schemas

PROPOSE_CARDS = "propose_cards"
TOOL_NAMES = frozenset({PROPOSE_CARDS})

MAX_TITLE_CHARACTERS = 120
MAX_CHEAT_SHEET_CHARACTERS = 20_000
MAX_CARDS = 10
PROPOSED = "shown to the owner with Save and Discard; nothing is saved yet"
# The validation context key that lets a set have no cheat sheet: it is for a note, which has its write-up.
FOR_A_NOTE = "for_a_note"

# A chat's cards are about what it established; foundation cards are for background a primer covers.
CARD_KINDS = (
    models.CardKind.CONCEPT,
    models.CardKind.MECHANISM,
    models.CardKind.NUMBER,
    models.CardKind.FOUNDATION,
)

PROPOSE_CARDS_TOOL: dict[str, Any] = {
    "name": PROPOSE_CARDS,
    "description": (
        "Propose review cards and a cheat sheet from this chat, when the owner asks for cards. The owner sees them "
        "with Keep ticks and taps Save; nothing is saved before that. title: a short name for the cheat sheet "
        f"(at most {MAX_TITLE_CHARACTERS} characters). cheat_sheet: markdown, at most "
        f"{MAX_CHEAT_SHEET_CHARACTERS} characters, or empty in a chat about a note. cards: 1 to {MAX_CARDS}, "
        "each a question (at most "
        f"{edit_tools.MAX_QUESTION_CHARACTERS} characters) and its answer (at most "
        f"{edit_tools.MAX_ANSWER_CHARACTERS}). To change a proposal, call this again with the whole new set."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "cheat_sheet": {"type": "string"},
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": [kind.value for kind in CARD_KINDS]},
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                    },
                    "required": ["kind", "question", "answer"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "cheat_sheet", "cards"],
        "additionalProperties": False,
    },
    "strict": True,
}
TOOLS: list[dict[str, Any]] = [PROPOSE_CARDS_TOOL]


class CardIn(pydantic.BaseModel):
    """One proposed card."""

    kind: models.CardKind
    question: str = pydantic.Field(min_length=1, max_length=edit_tools.MAX_QUESTION_CHARACTERS)
    answer: str = pydantic.Field(min_length=1, max_length=edit_tools.MAX_ANSWER_CHARACTERS)

    @pydantic.field_validator("kind")
    @classmethod
    def _chat_kind(cls, kind: models.CardKind) -> models.CardKind:
        if kind not in CARD_KINDS:
            raise ValueError(f"kind must be one of {', '.join(allowed.value for allowed in CARD_KINDS)}")
        return kind

    @pydantic.field_validator("question", "answer")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("must not be blank")
        return text.strip()


class CardSetIn(pydantic.BaseModel):
    """A whole card set, as the tool (and the test seed route) takes it."""

    title: str = pydantic.Field(min_length=1, max_length=MAX_TITLE_CHARACTERS)
    cheat_sheet: str = pydantic.Field(max_length=MAX_CHEAT_SHEET_CHARACTERS)
    cards: list[CardIn] = pydantic.Field(min_length=1, max_length=MAX_CARDS)

    @pydantic.field_validator("title")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("must not be blank")
        return text.strip()

    @pydantic.field_validator("cheat_sheet")
    @classmethod
    def _cheat_sheet(cls, text: str, info: pydantic.ValidationInfo) -> str:
        """Required, unless the set is for a note (the `FOR_A_NOTE` context)."""
        if not text.strip() and not (info.context or {}).get(FOR_A_NOTE):
            raise ValueError("must not be blank")
        return text.strip()


@dataclass(frozen=True)
class Proposal:
    """A validated card set, kept until the answer is stored and shown to the owner at once as a `cards` event."""

    id: uuid.UUID
    card_set: CardSetIn
    # When the model proposed it; stored as the row's `created_at`, so rows saved together keep their order.
    created_at: datetime.datetime

    def to_event(self, *, conversation_id: uuid.UUID, message_id: uuid.UUID) -> dict[str, Any]:
        """The `cards` event's data: the row as the phone will pull it, positioned 0 until the answer is stored."""
        row = schemas.CardSetProposalOut(
            id=self.id,
            conversation_id=conversation_id,
            message_id=message_id,
            title=self.card_set.title,
            cheat_sheet=self.card_set.cheat_sheet,
            cards=cards_of(self.card_set),
            status=models.CardSetStatus.PROPOSED.value,
            saved_source_id=None,
            kept=None,
            created_at=self.created_at,
            updated_at=self.created_at,
            change_seq=0,
        )
        return row.model_dump(mode="json")


@dataclass(frozen=True)
class ToolOutcome:
    """The tool's result block for the model, and the proposal it made, if any."""

    result: dict[str, Any]
    proposal: Proposal | None = None


def run(*, tool_use_id: str, tool_input: object, note_title: str | None) -> ToolOutcome:
    """Validate a `propose_cards` call; a bad input is an error result the model can act on.

    In a chat about a note (`note_title` given) the set is titled after the note and any cheat sheet is dropped: Save
    puts only the cards on the note.
    """
    for_note = (
        {**tool_input, "title": note_title[:MAX_TITLE_CHARACTERS], "cheat_sheet": ""}
        if note_title is not None and isinstance(tool_input, dict)
        else tool_input
    )
    if note_title is not None and _has_foundation_card(tool_input):
        return _error_outcome(
            tool_use_id=tool_use_id,
            text="cards: a note's cards must not be foundation; use concept, mechanism or number",
        )
    try:
        card_set = CardSetIn.model_validate(for_note, context={FOR_A_NOTE: note_title is not None})
    except pydantic.ValidationError as error:
        return _error_outcome(tool_use_id=tool_use_id, text=edit_tools.error_text(error))

    proposal = Proposal(id=uuid.uuid4(), card_set=card_set, created_at=datetime.datetime.now(tz=datetime.UTC))
    payload = {"proposal_id": str(proposal.id), "status": PROPOSED}
    return ToolOutcome(
        result={"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(payload)}, proposal=proposal
    )


def _error_outcome(*, tool_use_id: str, text: str) -> ToolOutcome:
    return ToolOutcome(result={"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": text})


def _has_foundation_card(tool_input: object) -> bool:
    cards = tool_input.get("cards") if isinstance(tool_input, dict) else None
    if not isinstance(cards, list):
        return False
    return any(isinstance(card, dict) and card.get("kind") == models.CardKind.FOUNDATION for card in cards)


def save_proposals(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    proposals: Sequence[Proposal],
) -> None:
    """Store the answer's card sets; each replaces every earlier still-open card set in the chat.

    The model re-proposes the whole set on every change, so only the newest is open. The caller holds the user's
    write lock and has added the answer row.
    """
    for proposal in proposals:
        add_proposal(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            proposal_id=proposal.id,
            card_set=proposal.card_set,
            created_at=proposal.created_at,
        )


def add_proposal(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    proposal_id: uuid.UUID,
    card_set: CardSetIn,
    created_at: datetime.datetime,
) -> models.CardSetProposal:
    """Mark the chat's open card sets replaced and add this one, open; the caller holds the user's write lock."""
    db.execute(
        sqlalchemy.update(models.CardSetProposal)
        .where(
            models.CardSetProposal.conversation_id == conversation_id,
            models.CardSetProposal.status == models.CardSetStatus.PROPOSED.value,
        )
        .values(
            status=models.CardSetStatus.REPLACED.value,
            updated_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
    )
    row = models.CardSetProposal(
        id=proposal_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        title=card_set.title,
        cheat_sheet=card_set.cheat_sheet,
        cards=cards_of(card_set),
        status=models.CardSetStatus.PROPOSED.value,
        created_at=created_at,
        updated_at=created_at,
        change_seq=changes.next_change_seq(),
    )
    db.add(row)
    db.flush()
    return row


def cards_of(card_set: CardSetIn) -> list[dict[str, str]]:
    """The set's cards in their stored shape."""
    return [{"kind": card.kind.value, "question": card.question, "answer": card.answer} for card in card_set.cards]
