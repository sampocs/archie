"""The book lookup's own logic: which text is a Goodreads book link, and reading a book out of a page's JSON-LD."""

from __future__ import annotations

import pytest
from archie_api.books import lookup

FALLBACK_URL = "https://www.goodreads.com/book/show/1"
# A trimmed Goodreads page: a non-book JSON-LD block, a broken one, then the book with two authors.
PAGE = """<html><head>
<meta property="og:url" content="https://www.goodreads.com/book/show/1-the-book"/>
<script type="application/ld+json">{"@type": "WebSite", "name": "Goodreads"}</script>
<script type="application/ld+json">{not json</script>
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Book", "name": " Nudge ",
 "image": "https://images.example.com/nudge.jpg",
 "author": [{"@type": "Person", "name": "Richard H. Thaler"}, {"@type": "Person", "name": "Cass R. Sunstein"}]}
</script>
<script>var notJsonLd = {"@type": "Book", "name": "Wrong"};</script>
</head><body></body></html>"""


def test_a_pages_book_block_gives_title_every_author_cover_and_canonical_url() -> None:
    """The Book block wins over other JSON-LD; a broken block is skipped; the page has no year."""
    match = lookup.parse_goodreads_page(page=PAGE, fallback_url=FALLBACK_URL)

    assert match == lookup.BookMatch(
        title="Nudge",
        author="Richard H. Thaler, Cass R. Sunstein",
        year=None,
        cover_url="https://images.example.com/nudge.jpg",
        url="https://www.goodreads.com/book/show/1-the-book",
    )


def test_one_author_as_an_object_and_no_og_url_or_image() -> None:
    """A single author may be an object; without `og:url` the input URL is kept; no image means no cover."""
    book = '{"@type": "Book", "name": "Range", "author": {"name": "David Epstein"}}'
    page = f'<script type="application/ld+json">{book}</script>'

    match = lookup.parse_goodreads_page(page=page, fallback_url=FALLBACK_URL)

    assert (match.title, match.author, match.cover_url, match.url) == ("Range", "David Epstein", None, FALLBACK_URL)


def test_a_page_without_a_book_block_has_no_book() -> None:
    """Only other JSON-LD (or a Book with no name) is no book."""
    page = '<script type="application/ld+json">[{"@type": "WebSite"}, {"@type": "Book", "name": ""}]</script>'

    with pytest.raises(lookup.BookNotFoundError):
        lookup.parse_goodreads_page(page=page, fallback_url=FALLBACK_URL)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.goodreads.com/book/show/11468377-thinking-fast-and-slow", True),
        (" http://goodreads.com/book/show/1?ref=x ", True),
        ("https://www.goodreads.com/author/show/72401.Daniel_Kahneman", False),
        ("https://example.com/book/show/1", False),
        ("goodreads.com/book/show/1", False),
        ("Thinking, Fast and Slow", False),
    ],
)
def test_only_an_http_link_to_a_goodreads_book_page_is_read_as_one(text: str, expected: bool) -> None:
    """An author page, another host, a bare host or a title are all title searches."""
    assert lookup.is_goodreads_book_url(text) is expected
