"""The card rules every card writer shares: the worker's summary, foundation, note, take and quiz cards, and Ask's
card sets and card edits.

Chosen by the owner from eval rounds on real notes, sources and a brief (2026-11-10): a short graded answer, and a
detail of a few bullet lines shown after answering and never graded. Tune it here; every writer picks it up. A writer
adds only what is its own (how many cards, which kinds, where the words may come from).
"""

from __future__ import annotations

from typing import Any

# The JSON schema of a card's `detail` in every structured card output: required, and may be empty.
DETAIL_SCHEMA: dict[str, Any] = {"type": "array", "items": {"type": "string"}}

CARD_RULES = """Each card has a question, an answer and a detail:
- question: ONE focused question with ONE thing to recall. Never join two asks with "and" ("What does X give you, \
and what can you lose?" is two cards, or pick one). Ask only what has a short answer. When the answer lists several \
items, say how many in the question ("What are the three main benefits of X?"), so the learner knows how many to \
recall.
- answer: the one thing to recall, in as few words as carry it: a phrase, not a sentence. Aim for 2-8 words, never \
more than 15. The learner is graded only on this, so it is what someone who knows the material would say off the top \
of their head. When two things are both essential, name both briefly ("Supply and demand"). A number card's answer is \
the rough figure with its unit.
- detail: 0-3 short bullet lines, each under 12 words (up to 5 if the owner asks for more detail). Shown after the \
learner answers, never graded. Each line must help explain the answer (the why or how behind it, or a contrast that \
makes it click); a further fact about the \
subject, however true, is not a reason for a line. No padding and no redundancy: never a line that restates the \
answer, is implied by it or repeats another line; that is trivia from this one source (who said it, when, a passing \
example or anecdote) rather than a lasting fact about the subject; or that is a side remark that doesn't help recall. \
So a plain fact or a number usually needs none and most whys need one; use two or three only when the explanation \
really has that many steps (A happens, so B, so C) or named parts (the three phases of a cycle). When in doubt, use \
fewer."""
