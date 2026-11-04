"""Prompts, the output schema and the user message for the `analyze` and `primer` steps.

Bump the matching version whenever a prompt or the schema changes in a way that alters output: it is stored
on every artifact, so old versions stay attributable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from archie_db import models

from archie_worker import content, timestamps

ANALYZE_PROMPT_VERSION = "analyze-v2"
PRIMER_PROMPT_VERSION = "primer-v1"

# The model never sees more than this many characters of the source's text; timed text carries markers, so it gets more.
MAX_TEXT_CHARACTERS = 200_000
MAX_TIMED_TEXT_CHARACTERS = 600_000

DOMAINS = [
    "AI",
    "Macro",
    "Crypto",
    "Startups",
    "Finance",
    "Tech",
    "History",
    "Security",
    "Sports",
    "Other",
]

# The reading voice is still to be designed, so this is a neutral stand-in shared by every step.
READING_VOICE = """Write in plain, conversational English for a smart reader who is new to the subject. Short \
sentences. Define any jargon the first time it appears. Prefer concrete examples and \
rough numbers ("~1 GW", not "1.07 GW")."""

# Replay contract: the recorded analyze cassettes match on only the first 60 characters of this prompt and still hold
# the v1 request and response bodies. Wording past character 60 is not covered by any recording until a timed-source
# analyze cassette is recorded.
ANALYZE_SYSTEM = f"""You process sources for a personal learning app. A source is an article, an X post or thread, or \
an episode (podcast or video) that the user consumed or plans to. A newsletter is an email digest; summarize its \
main stories. The user wants "level 2" knowledge of its subject: \
enough to hold a real conversation about it, including the vocabulary, how things work, the key players, rough \
numbers, and the current debates.

From the text, produce:
- summary: the gist in 2-3 sentences, the key ideas, and the numbers worth remembering. The text of an \
episode may carry markers like [12:14] or [1:02:03] at roughly one-minute intervals; give each key idea and number \
the marker nearest before where it comes up, copied exactly, and null when the text has no markers. \
Skip ads and sponsor reads.
- domain: the one broad domain the source belongs to.
- topic: a short, reusable topic name under that domain (e.g. "Stablecoins", "Fed policy", "NFL quarterbacks").
- tags: 3-8 short tags.
- concepts: the key concepts the source relies on or teaches, as short noun phrases.
- is_educational: true when the source teaches something worth remembering (how things work, history, ideas, numbers). \
false for pure entertainment such as banter, sports chat, jokes or gossip. A mostly entertaining source with real \
teaching in it (e.g. how a contract works, why a play scheme succeeds) is still true.
- cards: when is_educational is true, 3-5 open-recall review cards of kind concept, mechanism ("why does X cause Y") \
or number (a rough figure worth knowing). Each card asks ONE focused question, never a compound one with several \
parts. Each answer is what a good response would cover in 1-3 sentences. Avoid trivia that only matters to this one \
source. Cards come only from the educational stretches of a source: a mostly entertaining show with one educational \
segment gets cards for that segment; still 3-5. When is_educational is false, cards is an empty list.

{READING_VOICE}"""

PRIMER_SYSTEM = f"""You write primers for a personal learning app. A primer gives the background a source assumes its \
reader already has, so the source is easy to follow. It is not a summary of the source.

Read the text, work out which concepts, players, history, and numbers the author takes for granted, and explain those. \
Write for a smart beginner: friendly, no assumed jargon, a 5-8 minute read (roughly 900-1400 words). Use markdown with \
short sections and a title. Don't reveal the source's own conclusions or story beats.

{READING_VOICE}"""

CARD_KINDS = [models.CardKind.CONCEPT.value, models.CardKind.MECHANISM.value, models.CardKind.NUMBER.value]

_NULLABLE_TIMESTAMP = {"type": ["string", "null"]}

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "object",
            "properties": {
                "gist": {"type": "string"},
                "key_ideas": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"timestamp": _NULLABLE_TIMESTAMP, "idea": {"type": "string"}},
                        "required": ["timestamp", "idea"],
                        "additionalProperties": False,
                    },
                },
                "numbers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"timestamp": _NULLABLE_TIMESTAMP, "fact": {"type": "string"}},
                        "required": ["timestamp", "fact"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["gist", "key_ideas", "numbers"],
            "additionalProperties": False,
        },
        "domain": {"type": "string", "enum": DOMAINS},
        "topic": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "is_educational": {"type": "boolean"},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": CARD_KINDS},
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                },
                "required": ["kind", "question", "answer"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "domain", "topic", "tags", "concepts", "is_educational", "cards"],
    "additionalProperties": False,
}


def model_text(text_content: Mapping[str, Any]) -> str:
    """The text the model reads: timed segments with minute markers (capped at 600,000 characters), else plain text."""
    segments = content.segments_of(text_content)
    if segments:
        return timestamps.marked_text(segments)[:MAX_TIMED_TEXT_CHARACTERS]
    return text_content[content.TEXT_KEY][:MAX_TEXT_CHARACTERS]


def user_message(*, kind: models.SourceKind, title: str | None, url: str, text: str) -> str:
    """The source's details above its text (already capped by `model_text`) wrapped in `<text>` tags."""
    return f"Source kind: {kind.value}\nTitle: {title or '(none)'}\nURL: {url}\n\n<text>\n{text}\n</text>"
