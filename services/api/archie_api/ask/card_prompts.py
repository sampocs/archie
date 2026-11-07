"""The Make a card prompt: one review card drafted from one Ask answer, for the owner to edit before saving."""

from __future__ import annotations

from typing import Any

CARD_DRAFT_SYSTEM = """You draft one spaced-repetition review card from an answer the owner just read in Archie's \
Ask chat.

Pick the single most useful idea in the answer and write:
- question: one short, specific question (under 20 words) that the answer's idea answers. End it with "?".
- answer: the accepted answer in 1-2 plain sentences.
Use only what the answer says: never add a fact, name or number that isn't in it."""

CARD_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
    "required": ["question", "answer"],
    "additionalProperties": False,
}


def card_draft_message(*, question: str | None, answer: str) -> str:
    """The owner's question (when there is one) and the answer to draft from."""
    asked = f"<question>\n{question}\n</question>\n\n" if question else ""
    return f"{asked}<answer>\n{answer}\n</answer>"
