"""The links in a note's Markdown: what the write-up reads for reference, and lists as the note's sources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from archie_shared import urls

MAX_NOTE_LINKS = 8

_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"https?://[^\s<>\[\]()\"']+")
_TRAILING_PUNCTUATION = ".,;:!?"


class LinkKind(StrEnum):
    """How a link is read: a page's article text, or an episode's title and description only."""

    PAGE = "page"
    EPISODE = "episode"


@dataclass(frozen=True)
class NoteLink:
    """A link in a note, with its Markdown link text when it had one."""

    url: str
    text: str | None
    kind: LinkKind


def links_in(markdown: str) -> list[NoteLink]:
    """The note's distinct links in the order they appear, at most `MAX_NOTE_LINKS`.

    Markdown links and bare URLs both count. A link repeated (even with tracking parameters, or as the other YouTube
    form) is kept once, as first written.
    """
    found: list[tuple[int, NoteLink]] = []
    for match in _MARKDOWN_LINK.finditer(markdown):
        found.append((match.start(), _link(url=match.group(2), text=match.group(1).strip() or None)))

    # Blanked out (not cut) so the bare scan never re-finds a markdown link's URL and positions stay true.
    remaining = _MARKDOWN_LINK.sub(lambda match: " " * len(match.group(0)), markdown)
    for match in _BARE_URL.finditer(remaining):
        found.append((match.start(), _link(url=match.group(0).rstrip(_TRAILING_PUNCTUATION), text=None)))

    distinct: dict[str, NoteLink] = {}
    for _, link in sorted(found, key=lambda entry: entry[0]):
        distinct.setdefault(_identity(link.url), link)
    return list(distinct.values())[:MAX_NOTE_LINKS]


def _link(*, url: str, text: str | None) -> NoteLink:
    return NoteLink(url=url, text=text, kind=LinkKind.EPISODE if _is_episode(url) else LinkKind.PAGE)


def _is_episode(url: str) -> bool:
    return urls.youtube_video_id(url) is not None or urls.detect_kind(url) == urls.UrlKind.PODCAST


def _identity(url: str) -> str:
    """The de-dup key: the normalized URL, or the video id so YouTube's two URL forms match."""
    video_id = urls.youtube_video_id(url)
    return f"youtube:{video_id}" if video_id else urls.normalize_url(url)
