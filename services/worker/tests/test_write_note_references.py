"""What `write_note` reads from a note's links, with invented pages served in place of the network."""

from __future__ import annotations

import datetime

import pytest
from archie_worker import note_links, prompts
from archie_worker.handlers import fetch_title, write_note

# Invented, article prose long enough for trafilatura to treat as a main text.
_PARAGRAPHS = "".join(
    f"<p>Paragraph {number} explains how validators lock a deposit, are chosen to propose blocks, and lose part of it "
    f"when they sign conflicting messages, which is why attacking the network is expensive. Detail {number * 7}.</p>"
    for number in range(400)
)
_ARTICLE = f"<html><head><title>Long page</title></head><body><article>{_PARAGRAPHS}</article></body></html>"
_EMPTY_PAGE = '<html><head><meta property="og:title" content="Only a title"></head><body></body></html>'


def _serve(monkeypatch: pytest.MonkeyPatch, pages: dict[str, str]) -> None:
    monkeypatch.setattr(fetch_title, "fetch_page", lambda *, url, **_: pages[url])


def _page_links(count: int) -> list[note_links.NoteLink]:
    return [
        note_links.NoteLink(url=f"https://example.com/{number}", text=None, kind=note_links.LinkKind.PAGE)
        for number in range(count)
    ]


def test_pages_never_pass_the_total_reference_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each page is cut to what is left of the total, so the sum lands exactly on the cap, not past it."""
    monkeypatch.setattr(write_note, "_MAX_TOTAL_REFERENCE_CHARACTERS", 50_000)
    links = _page_links(5)
    _serve(monkeypatch, {link.url: _ARTICLE for link in links})

    result = write_note._references(links)

    lengths = [len(reference.text) for reference in result.prompt]
    assert lengths == [20_000, 20_000, 10_000]


def test_a_page_with_no_article_keeps_its_fetched_title_but_adds_no_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """The source entry still shows the page's own title; the prompt gets no empty reference."""
    [link] = _page_links(1)
    _serve(monkeypatch, {link.url: _EMPTY_PAGE})

    result = write_note._references([link])

    assert result.prompt == []
    assert write_note._source_entries([link], result.titles) == [{"url": link.url, "title": "Only a title"}]


def test_a_link_with_no_title_anywhere_is_listed_by_its_host() -> None:
    """The last fallback: no fetched title and no link text."""
    link = note_links.NoteLink(url="https://www.example.com/a", text=None, kind=note_links.LinkKind.PAGE)

    assert write_note._source_entries([link], {}) == [{"url": link.url, "title": "example.com"}]


def test_quotes_in_a_reference_url_cannot_break_out_of_its_tag() -> None:
    """The URL sits in an attribute, so a double quote in it is neutralised as in the title."""
    reference = prompts.NoteReference(
        url='https://example.com/a"b', title='A "title"', kind=note_links.LinkKind.PAGE, text="body"
    )

    message = prompts.note_write_up_message(
        today=datetime.date(2026, 1, 1),
        title=None,
        tags=[],
        edited_on=None,
        markdown="m",
        references=[reference],
    )

    assert '<reference url="https://example.com/a%22b" title="A \'title\'"' in message
