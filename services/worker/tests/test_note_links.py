"""The links a note carries, found with plain regexes; no database or network involved."""

from __future__ import annotations

from archie_worker import note_links


def test_markdown_and_bare_links_in_order_without_duplicates() -> None:
    """A link seen twice (once as markdown, once bare, with tracking noise) is kept once, at its first place."""
    markdown = (
        "Read [the guide](https://example.com/guide?utm_source=x) first.\n"
        "Then https://example.org/post and again https://example.com/guide.\n"
    )

    assert note_links.links_in(markdown) == [
        note_links.NoteLink(
            url="https://example.com/guide?utm_source=x", text="the guide", kind=note_links.LinkKind.PAGE
        ),
        note_links.NoteLink(url="https://example.org/post", text=None, kind=note_links.LinkKind.PAGE),
    ]


def test_a_bare_link_before_a_markdown_link_keeps_note_order() -> None:
    """Markdown links are found first, but the result follows their position in the note."""
    markdown = "https://example.org/first then [second](https://example.com/second)"

    assert [link.url for link in note_links.links_in(markdown)] == [
        "https://example.org/first",
        "https://example.com/second",
    ]


def test_episode_links_are_spotify_apple_and_youtube() -> None:
    """Episodes are read by title and description only, so they must be told apart from pages."""
    links = note_links.links_in(
        "https://open.spotify.com/episode/abc https://podcasts.apple.com/us/podcast/x/id1?i=2 "
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ https://youtu.be/dQw4w9WgXcQ"
    )

    # The two YouTube forms are one video, so they are kept once.
    assert [link.kind for link in links] == [note_links.LinkKind.EPISODE] * 3


def test_a_blank_markdown_link_text_is_no_text() -> None:
    """`[](url)` has nothing to show as a title."""
    [link] = note_links.links_in("[ ](https://example.com/a)")

    assert link.text is None


def test_at_most_eight_links_and_trailing_punctuation_dropped() -> None:
    """A bare link ending a sentence loses its period or bracket."""
    links = note_links.links_in(" ".join(f"(https://example.com/{n})." for n in range(12)))

    assert [link.url for link in links] == [f"https://example.com/{n}" for n in range(8)]
