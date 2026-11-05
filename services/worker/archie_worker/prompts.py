"""Prompts, output schemas and user messages for the `analyze`, `primer`, `file_topic`, `clean_text` and
`update_brief` steps.

Bump the matching version whenever a prompt or the schema changes in a way that alters output: it is stored
on every artifact, so old versions stay attributable. A brief is rewritten on every newsletter and keeps no
prompt version.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from archie_db import models
from archie_shared.domains import Domain

from archie_worker import content, timestamps

ANALYZE_PROMPT_VERSION = "analyze-v2"
PRIMER_PROMPT_VERSION = "primer-v1"
TOPIC_PRIMER_PROMPT_VERSION = "topic-primer-v1"
CLEAN_TEXT_PROMPT_VERSION = "clean-text-v1"

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
the time of the marker nearest before where it comes up, copied exactly but without the brackets (12:14, 1:02:03), \
and null when the text has no markers. \
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

TOPIC_PRIMER_SYSTEM = f"""You write topic primers for a personal learning app. A topic primer gives the general \
background on one topic (for example "How the Fed works" for the topic "Fed & monetary policy"): the core concepts, \
how the machinery works, the key players, a little history, the rough numbers worth knowing, and the live debates. \
It is about the topic, not about any one source.

The user lists the titles of their own sources on the topic. Use them only to decide what to emphasize, never as \
material to summarize. Write for a smart beginner: friendly, no assumed jargon, a 5-8 minute read (roughly 900-1400 \
words). Use markdown with short sections and a title.

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


def topic_primer_message(*, domain: str, topic: str, source_titles: Sequence[str]) -> str:
    """The topic and its domain, then the user's source titles on it (for emphasis only)."""
    titles = "\n".join(f"- {title}" for title in source_titles) or "- (none yet)"
    return f"Domain: {domain}\nTopic: {topic}\n\nThe user's sources on this topic (for emphasis only):\n{titles}"


FILE_TOPIC_SYSTEM = """You file sources for a personal learning app into the user's own list of topics. Each topic \
sits under one domain.

Rules:
- Reuse one of the user's topics whenever one fits, even loosely. Copy its name exactly and set is_new to false.
- Only when none of them fits, propose a new topic and set is_new to true. Make it short (2-5 words) and reusable for \
many future sources, in the style of the user's topics. Never propose a near-duplicate of an existing or removed topic \
(no rewording, plural, abbreviation or synonym of one).
- Never propose a removed topic or anything close to one: the user removed those on purpose. If the only fit is a \
removed topic, reuse a broader existing topic or propose a different one.
- domain: the domain of the topic you chose (an existing topic's own domain when you reuse one).
- newsletter_kind: for a newsletter only, otherwise null. "news" is a digest of several short items; "essay" is one \
piece of writing worth reading whole.

The analysis hints (domain, topic, tags) come from an earlier step with a different domain list; treat them as hints."""

FILE_TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "enum": [domain.value for domain in Domain]},
        "topic": {"type": "string"},
        "is_new": {"type": "boolean"},
        "newsletter_kind": {
            "anyOf": [{"type": "string", "enum": [kind.value for kind in models.NewsletterKind]}, {"type": "null"}]
        },
    },
    "required": ["domain", "topic", "is_new", "newsletter_kind"],
    "additionalProperties": False,
}

_MAX_FILING_KEY_IDEAS = 8


def file_topic_message(
    *,
    kind: models.SourceKind,
    title: str | None,
    analysis: Mapping[str, Any],
    live_topics: Sequence[str],
    removed_topics: Sequence[str],
) -> str:
    """The source's summary and hints, then the user's topics as `domain › name` lines and the removed names."""
    summary = analysis["summary"]
    key_ideas = "\n".join(f"- {item['idea']}" for item in summary["key_ideas"][:_MAX_FILING_KEY_IDEAS])
    hints = f"domain {analysis['domain']}, topic {analysis['topic']}, tags {', '.join(analysis['tags'])}"
    live = "\n".join(f"- {line}" for line in live_topics) or "- (none yet)"
    removed = "\n".join(f"- {name}" for name in removed_topics) or "- (none)"
    return (
        f"Source kind: {kind.value}\nTitle: {title or '(none)'}\nAnalysis hints: {hints}\n\n"
        f"Gist: {summary['gist']}\nKey ideas:\n{key_ideas}\n\n"
        f"The user's topics (domain › name):\n{live}\n\n"
        f"Removed topics (never propose these or anything close):\n{removed}"
    )


CLEAN_TEXT_SYSTEM = """You tidy newsletter emails for a personal learning app. The user reads the newsletter's \
stories; everything around them is clutter.

The email's paragraphs are numbered like [12]. List the numbers of the paragraphs to drop:
- ads, sponsor notes and "sponsored by" blocks, product recommendations and affiliate disclaimers
- referral and "share the newsletter" blocks
- trivia, quizzes, puzzles and their answers, word of the day
- sign-offs, author credits, footers, "forwarded to you? sign up" lines, unsubscribe and legal boilerplate

Keep every paragraph that belongs to a story, including its headline, section label and photo credit, and the \
opening note. When unsure, keep it. Never rewrite anything: answer only with paragraph numbers."""

CLEAN_TEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"drop": {"type": "array", "items": {"type": "integer"}}},
    "required": ["drop"],
    "additionalProperties": False,
}


def clean_text_message(*, title: str | None, paragraphs: Sequence[str]) -> str:
    """The newsletter's subject, then its paragraphs numbered from 1 as `[n] paragraph`, blank-line separated."""
    numbered = "\n\n".join(f"[{number}] {paragraph}" for number, paragraph in enumerate(paragraphs, start=1))
    return f"Subject: {title or '(none)'}\n\n<email>\n{numbered}\n</email>"


# Each news newsletter's text is cut to this many characters in the brief's one call.
MAX_BRIEF_TEXT_CHARACTERS = 30_000
# The call's whole newsletter text stays under this: the newest issues get their text until it is spent, older ones
# are given as their summary.
MAX_BRIEF_TOTAL_CHARACTERS = 150_000
# Summaries given in place of text stay under this too; newsletters older than that are left out of the call (and the
# brief) until a later one, so the call's input never grows with the backlog.
MAX_BRIEF_SUMMARY_CHARACTERS = 60_000
# The model writes at most this many stories in full; its output must fit the token limit with every newsletter
# covered. The server keeps `brief_content.MAX_STORIES` of them.
MAX_MODEL_STORIES = 12

BRIEF_SYSTEM = f"""You write the newsletter brief for a personal learning app: a two-minute read that tells the user \
the stories people are talking about, so they don't have to read every newsletter. The brief is read, not browsed: \
every story must stand on its own.

The user message lists the domains, the user's own topics, and the newsletters, each with its id. An older newsletter \
may be given as its summary instead of its full text. From the newsletters, produce:
- domains: the stories, grouped under the listed domain each belongs to. One story is one piece of news; when \
several newsletters cover the same news, write it once and list all of their ids.
  - headline: one complete sentence that states the news itself, never a teaser.
  - body: one or two sentences on what happened.
  - why: one sentence on why it matters; empty when that is obvious from the body.
  - detail: a longer paragraph (4-6 sentences) with the background, players and numbers, for a reader who wants more.
  - importance: 1-10, how much a well-informed person would be expected to know this story today. News that will be \
talked about everywhere scores high; minor deals, small updates and curiosities score low. A story on one of the \
user's topics may score a little higher.
  - source_ids: the ids of the newsletters that cover the story, copied exactly.
- also: one-line items for small news that is worth a mention but not a story, each with its newsletter ids. Write \
at most {MAX_MODEL_STORIES} stories in full, the most important ones; put every other news item here as a one-line \
item with its ids rather than as a story.

Skip ads, sponsor content, promotions, trivia, quizzes, polls and the newsletters' own housekeeping. Never add facts \
that are not in the newsletters.

{READING_VOICE}"""

_SOURCE_IDS = {"type": "array", "items": {"type": "string"}}

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "domains": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "enum": [domain.value for domain in Domain]},
                    "stories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "headline": {"type": "string"},
                                "body": {"type": "string"},
                                "why": {"type": "string"},
                                "detail": {"type": "string"},
                                "importance": {"type": "integer"},
                                "source_ids": _SOURCE_IDS,
                            },
                            "required": ["headline", "body", "why", "detail", "importance", "source_ids"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["domain", "stories"],
                "additionalProperties": False,
            },
        },
        "also": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "source_ids": _SOURCE_IDS},
                "required": ["text", "source_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["domains", "also"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class BriefNewsletter:
    """One news newsletter as the brief's call reads it: its text, or its summary when `is_summary`."""

    source_id: str
    sender: str | None
    subject: str | None
    received_at: datetime.datetime
    text: str
    is_summary: bool


class BriefInput(StrEnum):
    """How one news newsletter goes into the brief's call."""

    FULL = "full"
    SUMMARY = "summary"
    OMITTED = "omitted"


def choose_brief_inputs(*, text_lengths: Sequence[int], summary_lengths: Sequence[int]) -> list[BriefInput]:
    """How each newsletter (lengths oldest first, text already capped) goes into the call.

    Walking from the newest: each is `FULL` while the running text total fits `MAX_BRIEF_TOTAL_CHARACTERS`; after the
    first that doesn't, each is a `SUMMARY` while the running summary total fits `MAX_BRIEF_SUMMARY_CHARACTERS`; after
    the first that doesn't, it and every older one are `OMITTED` (deferred, not dropped).
    """
    choices: list[BriefInput] = []
    text_total = 0
    summary_total = 0
    for text_length, summary_length in zip(reversed(text_lengths), reversed(summary_lengths), strict=True):
        previous = choices[-1] if choices else BriefInput.FULL

        if previous == BriefInput.FULL and text_total + text_length <= MAX_BRIEF_TOTAL_CHARACTERS:
            text_total += text_length
            choices.append(BriefInput.FULL)
        elif previous != BriefInput.OMITTED and summary_total + summary_length <= MAX_BRIEF_SUMMARY_CHARACTERS:
            summary_total += summary_length
            choices.append(BriefInput.SUMMARY)
        else:
            choices.append(BriefInput.OMITTED)
    return list(reversed(choices))


def summary_text(analysis: Mapping[str, Any]) -> str:
    """A summary artifact as the brief reads it in place of the text: the gist, then the key ideas and numbers."""
    summary = analysis["summary"]
    key_ideas = "\n".join(f"- {item['idea']}" for item in summary["key_ideas"]) or "- (none)"
    numbers = "\n".join(f"- {item['fact']}" for item in summary["numbers"]) or "- (none)"
    return f"{summary['gist']}\n\nKey ideas:\n{key_ideas}\n\nNumbers:\n{numbers}"


def brief_message(*, newsletters: Sequence[BriefNewsletter], live_topics: Sequence[str]) -> str:
    """The domains, the user's topics as `domain › name` lines, then each newsletter in `<newsletter>` tags.

    Each carries its id, sender, subject and date, and says when it is given as its summary.
    """
    domain_names = ", ".join(domain.value for domain in Domain)
    topics = "\n".join(f"- {line}" for line in live_topics) or "- (none yet)"
    issues = "\n\n".join(
        f'<newsletter id="{newsletter.source_id}">\n'
        f"Sender: {newsletter.sender or '(unknown)'}\n"
        f"Subject: {newsletter.subject or '(none)'}\n"
        f"Date: {newsletter.received_at:%A %Y-%m-%d}\n"
        f"{'Given as: its summary' if newsletter.is_summary else 'Given as: its full text'}\n\n"
        f"{newsletter.text}\n</newsletter>"
        for newsletter in newsletters
    )
    return f"Domains: {domain_names}\n\nThe user's topics (domain › name):\n{topics}\n\n{issues}"
