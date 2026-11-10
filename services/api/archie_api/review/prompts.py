"""Prompts for the review routes: grading a recalled answer, and rewriting a card's answer around the learner's note."""

# ruff: noqa: E501  (the grading prompt is the eval's text, verbatim)

from __future__ import annotations

from typing import Any

from archie_db import card_rows
from archie_llm import cards

# The grader chosen in the short-answer eval (round 2, 2026-11-10), with the grading spike's numbers rule, `missing` and
# `confident` kept (spikes/card_grading/README.md) and a 1-shot block for a short answer.
GRADE_SYSTEM = """You grade a typed or dictated recall answer to a spaced-repetition flashcard.

The card has an accepted answer (short: the thing to recall) and sometimes "More": extra detail the learner sees afterwards. Grade ONLY against the accepted answer. "More" is background, never required: leaving it out never lowers a grade, and an answer that says something true from it is not wrong.

Judge the IDEA, not the wording. Be lenient on phrasing, word order, typos, missing punctuation, dictation errors and terseness: a two-word answer that names the idea is got_it. Be strict on the core idea: the answer must name what the accepted answer names and must not contradict it.

Grades:
- got_it: the answer carries the accepted answer's idea, in any words.
- partly: right as far as it goes but names only one of the accepted answer's essential parts, or is too vague to show the idea, or gives only true side facts from "More" that don't lead to the idea.
- missed: wrong, contradicts the accepted answer, off-topic, or blank / "I don't know".

An answer that doesn't use the accepted answer's words but shows the idea, by its reasoning or by saying something that plainly amounts to it, is got_it. For example, accepted "Too much capital chasing few great companies"; answer "only ~20 big exits a decade and more money doesn't make more great founders" is got_it, because it is the idea argued from its parts.

Numbers: right if within roughly the precision of the accepted answer (about 5% unless the card says "roughly"/"about", then about 15%). A wrong order of magnitude is missed.

`missing`: for partly and missed, ONE short sentence (under 20 words) saying what the answer lacked or got wrong, addressed to the learner without quoting the whole accepted answer. Empty string for got_it.

`confident`: false only if you genuinely cannot tell whether the answer matches the idea (ambiguous wording, answer might be right under another reading, or the accepted answer itself is unclear). Otherwise true. Do not mark a clear miss or a clear match as not confident.

Example
Question: Why does a fridge stay cold with the door closed?
Accepted answer: Sealed insulation; compressor removes leaked heat
More (not required):
- The seal and insulation keep most heat out
- The compressor only runs when enough heat leaks in
Answer: "cuz the seal keeps the cold in and the motor kicks on once in a while"
Grade: got_it (the seal and the compressor clearing leaked heat are the idea; wording is casual).
Answer: "The compressor keeps running."
Grade: partly, missing "It doesn't say the sealed insulation is what keeps heat out."
Answer: "the light turns off when you shut it"
Grade: missed, missing "The light has nothing to do with it; the seal and compressor keep it cold."
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

CARE_SYSTEM = f"""You rewrite the accepted answer of a spaced-repetition flashcard so it keeps what the learner says \
matters to them.

Use only what the card already says, in its accepted answer and its "More" detail lines: you may pick, shorten, \
reorder, or put the weight on what the learner's note names, but never add a fact, name, number or claim that isn't \
in it. The new answer follows the card rules' answer rule below; the detail stays as it is. Return the new accepted \
answer in `answer`.

{cards.CARD_RULES}"""

CARE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def grade_message(*, question: str, accepted: str, detail: str, answer: str) -> str:
    """The card (its detail under `More (not required):`, when it has any) and the learner's answer, quoted so the
    model reads it as data."""
    return f"Question: {question}\nAccepted answer: {accepted}\n{_more_block(detail)}Answer: {answer!r}"


def care_message(*, question: str, accepted: str, detail: str, note: str) -> str:
    """The card (with its detail, when it has any) and the learner's note, for the care rewrite."""
    return f"Question: {question}\nAccepted answer: {accepted}\n{_more_block(detail)}What the learner cares about: {note!r}"


def _more_block(detail: str) -> str:
    """A card's stored detail as `More (not required):` and one `- line` per line; "" when it has none."""
    lines = [line for line in detail.split(card_rows.DETAIL_SEPARATOR) if line.strip()]
    if not lines:
        return ""
    bullets = "".join(f"- {line}\n" for line in lines)
    return f"More (not required):\n{bullets}"
