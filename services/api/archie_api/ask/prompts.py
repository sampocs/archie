"""Ask's system prompt and tools. The fixed rules come first, so every chat's prompt shares its first 60 characters."""

from __future__ import annotations

import datetime
from typing import Any

ASK_SYSTEM = """You are Archie's Ask, answering the owner's questions from their own library first. Archie is \
their personal library of the articles, newsletters, podcasts and videos they saved, with Archie's summaries and \
primers of them, topic primers, and the owner's own takes.

How to answer:
- Search the owner's library with search_library first, unless the question plainly isn't about anything they could \
have saved (small talk, arithmetic). Search again with other words if the first search finds nothing useful.
- Call tools without writing anything first; don't announce your searches.
- Base library claims only on search results, so they carry citations.
- Each library result's title gives the day the owner saved it and, when that was another day, when it was \
published. For a question about a time ("yesterday", "this week", "on Tuesday"), work the days out from today's date \
and pass search_library's saved_* or published_* bounds.
- Then add background knowledge only where the library doesn't cover the question, in its own paragraph and without \
citations. Never present background knowledge as coming from the library.
- Search the web for recent or fast-changing facts (prices, office holders, this year's numbers), when the owner asks \
you to look something up, and whenever this prompt says a web search is required. Base web claims only on web \
results.
- Keep answers short and in plain language: a few short paragraphs at most. Define a technical term the first time \
you use it. No headings, and no bullet lists unless the owner asks for a list.
- If neither the library nor the web has the answer and you don't know it, say so plainly.
- Write plain paragraphs: no headings, no bold section titles; a short list only when it really helps."""

WEB_REQUIRED = "A web search is required for this question: search the web before you answer."

ABOUT_INTRO = (
    "This chat is about one item in the owner's library, described below. Searches rank its passages first; "
    "answer about it unless the owner clearly asks about something else."
)


def _day_bound(description: str) -> dict[str, str]:
    # `date` is one of the string formats strict tool use supports.
    return {"type": "string", "format": "date", "description": f"{description} YYYY-MM-DD, in the owner's time zone."}


SEARCH_LIBRARY_TOOL: dict[str, Any] = {
    "name": "search_library",
    "description": (
        "Search the owner's saved library: article and newsletter text, podcast and video transcripts, Archie's "
        "summaries and primers of them, topic primers, and the owner's own takes. Call this first for any question "
        "the owner's reading could bear on. Returns up to 8 passages to cite. For a question about a time "
        '("yesterday", "this week", "on Tuesday"), also pass day bounds so only items from those days come back: '
        'saved_* for when the owner saved or got it ("what did I save this week", "yesterday\'s newsletters"), '
        'published_* for when it came out ("articles published this year"). For newsletters the two are the same day.'
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, in a few words."},
            "saved_after": _day_bound("Only items the owner saved or got on or after this day."),
            "saved_before": _day_bound("Only items the owner saved or got on or before this day."),
            "published_after": _day_bound("Only items that came out on or after this day."),
            "published_before": _day_bound("Only items that came out on or before this day."),
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
    "eager_input_streaming": True,
}

# The current web search tool for Sonnet 5.5; three searches per request keeps an answer quick and cheap. Direct calls
# only: a search run from inside dynamic filtering's code reaches the model as code output, which can't be cited, so
# the answer would lose its web label and link chips.
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 3,
    "allowed_callers": ["direct"],
}


def system_prompt(*, about: str | None, web_required: bool, now: datetime.datetime) -> str:
    """The rules and today's date, then the about item (Ask about this), then the web requirement if the globe was on.

    `now` is in the owner's zone, which the prompt names. The date comes after the fixed rules, so the prompt's first 60
    characters (what cassettes replay by) never change.
    """
    parts = [ASK_SYSTEM, f"Today is {now:%A} {now.day} {now:%B %Y} ({now.tzinfo})."]
    if about:
        parts.append(f"{ABOUT_INTRO}\n<about>\n{about}\n</about>")
    if web_required:
        parts.append(WEB_REQUIRED)
    return "\n\n".join(parts)
