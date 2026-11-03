"""Pure text logic: cleaning a capture, and turning recorded fxtwitter responses into text."""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

from archie_worker.content import article, x

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# fxtwitter bodies copied out of the recorded cassettes (x_thread_sama, x_article, x_quote).
THREAD_FIXTURE = "fxtwitter_thread_sama.json"
ARTICLE_FIXTURE = "fxtwitter_article.json"
QUOTE_FIXTURE = "fxtwitter_quote.json"

CAPTION = "Photo: a long caption that the page repeats under every image"


def test_clean_capture_keeps_two_copies_of_a_repeated_line_and_drops_the_rest() -> None:
    """The third and later copies of a 20+ character line go; the first two stay where they were."""
    text = f"intro\n{CAPTION}\nmiddle\n{CAPTION}\n{CAPTION}\nend\n{CAPTION}"

    assert article.clean_capture(text) == f"intro\n{CAPTION}\nmiddle\n{CAPTION}\nend"


def test_clean_capture_keeps_short_lines_however_often_they_repeat() -> None:
    """Short lines ("Yes", headings) legitimately repeat; only long ones are treated as page chrome."""
    assert article.clean_capture("Yes\nYes\nYes\nYes") == "Yes\nYes\nYes\nYes"


def test_clean_capture_normalizes_whitespace_and_collapses_blank_runs() -> None:
    """Runs of spaces and tabs shrink to one space, and 3+ blank lines become a single blank line."""
    assert article.clean_capture("  one \t two  \n\n\n\n\nthree\n\n\nfour  ") == "one two\n\nthree\n\nfour"


def test_clean_capture_is_capped() -> None:
    """Text over 200,000 characters is cut to exactly that."""
    assert len(article.clean_capture("word " * 100_000)) == article.MAX_TEXT_LENGTH


def test_extract_finds_nothing_in_a_page_without_text() -> None:
    """A page with no main text is None rather than an empty result."""
    assert article.extract(html="<html><head></head><body></body></html>", url="https://example.com/") is None


def test_thread_text_keeps_the_authors_posts_in_order() -> None:
    """All three posts of the recorded sama thread, in order, titled by handle and the start of the first post."""
    result = x.thread_text(data=_load(THREAD_FIXTURE))

    assert result.text.split("\n\n")[-2:] == [
        "thank you to the machines, and the structure of reality, for letting us understand a little more.",
        "and thank you to the untold number of people who put in the technical work, brick by brick over the "
        "generations, to get us to the point where such a wonder is possible.",
    ]
    assert result.text.startswith("looking up at the stars with extra awe tonight.")
    assert result.title == f"@sama: {result.text[: x.TITLE_POST_LENGTH]}"


def test_thread_text_skips_other_authors_posts() -> None:
    """A reply's thread starts with other people's ancestors; only the shared post's author's posts are kept."""
    data = _load(THREAD_FIXTURE)
    # The recorded thread with a stranger's post spliced in front, as a reply's ancestor chain would be.
    stranger_post = copy.deepcopy(data["thread"][0])
    stranger_post["text"] = "a post by somebody else"
    stranger_post["author"]["screen_name"] = "somebody_else"
    data["thread"].insert(0, stranger_post)

    result = x.thread_text(data=data)

    assert "somebody else" not in result.text
    assert result.text == x.thread_text(data=_load(THREAD_FIXTURE)).text


def test_thread_text_uses_the_shared_post_when_there_is_no_thread() -> None:
    """Without a `thread` array (a single post), the shared post alone is the text."""
    data = _load(QUOTE_FIXTURE)
    del data["thread"]

    assert x.thread_text(data=data).text.startswith(data["status"]["text"])


def test_thread_text_includes_the_quoted_post() -> None:
    """A quote post adds `Quoting @handle: ...` after the author's own text."""
    data = _load(QUOTE_FIXTURE)
    quote = data["status"]["quote"]

    result = x.thread_text(data=data)

    assert result.text == f"{data['status']['text']}\n\nQuoting @{quote['author']['screen_name']}: {quote['text']}"


def test_thread_text_builds_an_x_article_from_its_title_and_blocks() -> None:
    """The Article's title is the source title and comes first in its section, followed by every non-blank block."""
    data = _load(ARTICLE_FIXTURE)
    article_data = data["status"]["article"]
    blocks = [block["text"] for block in article_data["content"]["blocks"] if block["text"].strip()]

    result = x.thread_text(data=data)

    assert result.title == article_data["title"]
    assert result.text == "\n\n".join([data["status"]["text"], article_data["title"], *blocks])


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())
