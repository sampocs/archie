"""Prompts for the review routes: grading a recalled answer, and rewriting a card's answer around the learner's note."""

# ruff: noqa: E501  (the grading prompt is the spike's text, verbatim)

from __future__ import annotations

from typing import Any

# The grading spike's prompt (spikes/card_grading/README.md, "The prompt as tested") with its 1-shot block appended.
GRADE_SYSTEM = """You grade a typed or dictated recall answer to a spaced-repetition flashcard.

Judge the IDEA, not the wording. Be lenient on phrasing, word order, typos, missing punctuation, dictation errors and terseness. Be strict on the core idea: the answer must contain the essential point(s) of the accepted answer and must not contradict them.

Grades:
- got_it: the answer carries the core idea of the accepted answer, in any words. Minor omitted detail is fine.
- partly: the answer is correct as far as it goes but misses an essential part of the idea (for example gives what but not why, or only one of several required parts), or is too vague to show real understanding.
- missed: the answer is wrong, contradicts the accepted answer, is off-topic, or is blank / "I don't know".

Numbers: right if within roughly the precision of the accepted answer (about 5% unless the card says "roughly"/"about", then about 15%). A wrong order of magnitude is missed.

`missing`: for partly and missed, ONE short sentence (under 20 words) saying what the answer lacked or got wrong, addressed to the learner without quoting the whole accepted answer. Empty string for got_it.

`confident`: false only if you genuinely cannot tell whether the answer matches the idea (ambiguous wording, answer might be right under another reading, or the accepted answer itself is unclear). Otherwise true. Do not mark a clear miss or a clear match as not confident.

Example
Question: Why does a regular fridge stay cold when the door is closed?
Accepted answer: The insulated door seal traps cold air, and the compressor only runs to remove the small amount of heat that leaks in.
Answer: "cuz the seal keeps the cold in and the motor kicks on once in a while"
Grade: got_it (the seal and the intermittent compressor are the core idea; wording is casual).
Answer: "The compressor keeps running."
Grade: partly, missing "It doesn't say the insulated seal is what keeps heat out."
"""

GRADE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "grade": {"type": "string", "enum": ["got_it", "partly", "missed"]},
        "missing": {"type": "string"},
        "confident": {"type": "boolean"},
    },
    "required": ["grade", "missing", "confident"],
    "additionalProperties": False,
}

CARE_SYSTEM = """You rewrite the accepted answer of a spaced-repetition flashcard so it keeps what the learner says \
matters to them.

Use only what the accepted answer already says: you may drop parts, shorten, reorder, or put the weight on what the \
learner's note names, but never add a fact, name, number or claim that isn't in it. Keep it to 1-3 sentences, in \
plain words. Return the new accepted answer in `answer`."""

CARE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def grade_message(*, question: str, accepted: str, answer: str) -> str:
    """The card and the learner's answer, quoted so the model reads it as data."""
    return f"Question: {question}\nAccepted answer: {accepted}\nAnswer: {answer!r}"


def care_message(*, question: str, accepted: str, note: str) -> str:
    """The card and the learner's note, for the care rewrite."""
    return f"Question: {question}\nAccepted answer: {accepted}\nWhat the learner cares about: {note!r}"
