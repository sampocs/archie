"""Ask's system prompt and tools. The fixed rules come first, so every chat's prompt shares its first 60 characters."""

from __future__ import annotations

from typing import Any

ASK_SYSTEM = """You are Archie's Ask, answering the owner's questions from their own library first. Archie is \
their personal library of the articles, newsletters, podcasts and videos they saved, with Archie's summaries and \
primers of them, topic primers, and the owner's own takes.

How to answer:
- Search the owner's library with search_library first, unless the question plainly isn't about anything they could \
have saved (small talk, arithmetic). Search again with other words if the first search finds nothing useful.
- Call tools without writing anything first; don't announce your searches.
- Base library claims only on search results, so they carry citations.
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

SEARCH_LIBRARY_TOOL: dict[str, Any] = {
    "name": "search_library",
    "description": (
        "Search the owner's saved library: article and newsletter text, podcast and video transcripts, Archie's "
        "summaries and primers of them, topic primers, and the owner's own takes. Call this first for any question "
        "the owner's reading could bear on. Returns up to 8 passages to cite."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to look for, in a few words."}},
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


def system_prompt(*, about: str | None, web_required: bool) -> str:
    """The rules, then the about item (for Ask about this), then the web requirement when the globe was on."""
    parts = [ASK_SYSTEM]
    if about:
        parts.append(f"{ABOUT_INTRO}\n<about>\n{about}\n</about>")
    if web_required:
        parts.append(WEB_REQUIRED)
    return "\n\n".join(parts)
