"""Turn a raw RFC 822 email into the few fields a newsletter source needs.

The message is outside input: it is parsed as data, its HTML is reduced to markdown by trafilatura (headings and
paragraphs kept), and nothing in it is ever executed or followed.
"""

from __future__ import annotations

import email
import email.message
import email.policy
import email.utils
import hashlib
import html.parser
import re
from dataclasses import dataclass

import lxml.etree
import lxml.html
import trafilatura

MAX_TEXT_LENGTH = 400_000
MIN_HTML_WORDS = 50
# A table row this short (all cells together) is a line of figures, like a market ticker, not page layout.
MAX_JOINED_ROW_WORDS = 12
_CELL_SEPARATOR = " · "
_ROW_JOIN_BLOCKERS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "style", "script"})

_WEB_URL_IN_LIST_POST = re.compile(r"<(https://[^>\s]+)>")
_WEB_URL_IN_BODY = re.compile(r"View this post on the web at (https://\S+)")
# The text of a newsletter's "open the web version" link, compared lower-cased with whitespace collapsed.
_WEB_VERSION_LINK_TEXTS = frozenset(
    {"view online", "view in browser", "view in your browser", "read online", "view this email in your browser"}
)
_HTTPS_PREFIX = "https://"
_ANCHOR_TAG = "a"
_HREF_ATTRIBUTE = "href"
_MESSAGE_ID_FALLBACK_PREFIX = "sha256:"
MAX_MESSAGE_ID_LENGTH = 998  # the width of the `Source.newsletter_message_id` column


@dataclass(frozen=True)
class ParsedEmail:
    """What the ingest endpoint reads from an email."""

    subject: str | None
    sender: str | None
    message_id: str
    web_url: str | None
    text: str


def parse(raw: bytes) -> ParsedEmail:
    """Parse `raw` into a `ParsedEmail`; never raises on a malformed message, it just yields less."""
    message = email.message_from_bytes(raw, policy=email.policy.default)
    plain = _body_text(message, subtype="plain")
    html = _body_text(message, subtype="html")

    return ParsedEmail(
        subject=_header_text(message, "Subject"),
        sender=_sender(message),
        message_id=_message_id(message, raw=raw),
        web_url=_web_url(message, plain=plain, html=html),
        text=_without_nul(_readable_text(html=html, plain=plain)[:MAX_TEXT_LENGTH]),
    )


def local_part(recipient: str) -> str:
    """The lower-cased text before `@`, without a `+tag` suffix."""
    return recipient.partition("@")[0].partition("+")[0].strip().lower()


def _without_nul(value: str) -> str:
    # Postgres text can't hold NUL, and outside mail can contain anything.
    return value.replace("\x00", "")


def _header_text(message: email.message.Message, name: str) -> str | None:
    value = message[name]
    if value is None:
        return None
    text = _without_nul(str(value)).strip()
    return text or None


def _sender(message: email.message.Message) -> str | None:
    """The From display name, else its bare address."""
    from_header = _header_text(message, "From")
    if from_header is None:
        return None

    display_name, address = email.utils.parseaddr(from_header)
    return display_name.strip() or address or from_header


def _message_id(message: email.message.Message, *, raw: bytes) -> str:
    """The Message-ID without angle brackets; a hash of the bytes when absent or unstorable, so redelivery dedupes."""
    # Read the raw header: _header_text would strip a NUL, and an id that had one is not trusted.
    message_id = str(message["Message-ID"] or "").strip("<> ")
    if message_id and len(message_id) <= MAX_MESSAGE_ID_LENGTH and "\x00" not in message_id:
        return message_id
    return _MESSAGE_ID_FALLBACK_PREFIX + hashlib.sha256(raw).hexdigest()


def _web_url(message: email.message.Message, *, plain: str, html: str) -> str | None:
    """The post's page on the web, from the first of these that has one.

    The List-Post URL, then Substack's "View this post on the web" line, then an HTML link reading "View Online" or
    the like (https only).
    """
    list_post = _WEB_URL_IN_LIST_POST.search(_header_text(message, "List-Post") or "")
    if list_post:
        return list_post.group(1)

    in_body = _WEB_URL_IN_BODY.search(plain)
    if in_body:
        return in_body.group(1)
    return _web_version_link(html) if html else None


def _web_version_link(html_text: str) -> str | None:
    """The https target of the first link whose text names the web version."""
    finder = _WebVersionLinkFinder()
    finder.feed(html_text)
    finder.close()
    return finder.url


class _WebVersionLinkFinder(html.parser.HTMLParser):
    """Collects each link's text and keeps the first https one whose text names the web version."""

    def __init__(self) -> None:
        super().__init__()
        self.url: str | None = None
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != _ANCHOR_TAG:
            return
        self._href = dict(attrs).get(_HREF_ATTRIBUTE)
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != _ANCHOR_TAG or self._href is None:
            return

        link_text = " ".join("".join(self._text).split()).lower()
        href = self._href.strip()
        if self.url is None and link_text in _WEB_VERSION_LINK_TEXTS and href.startswith(_HTTPS_PREFIX):
            self.url = href
        self._href = None


def _body_text(message: email.message.Message, *, subtype: str) -> str:
    """The first text part of `subtype`, decoded; empty when there is none or it can't be decoded."""
    assert isinstance(message, email.message.EmailMessage)
    part = message.get_body(preferencelist=(subtype,))
    if part is None:
        return ""
    try:
        return str(part.get_content())
    except (LookupError, UnicodeDecodeError):
        # An unknown or wrong charset in outside mail only costs this part, not the whole message.
        return ""


def _readable_text(*, html: str, plain: str) -> str:
    """The HTML reduced to markdown when that yields a real article, else the plain part."""
    extracted = (
        trafilatura.extract(_with_short_rows_joined(html), output_format="markdown", include_comments=False)
        if html.strip()
        else None
    )
    if extracted and len(extracted.split()) >= MIN_HTML_WORDS:
        return extracted.strip()
    return plain.strip()


def _with_short_rows_joined(html: str) -> str:
    """The HTML with each short multi-cell table row turned into one cell, so its figures read as one line.

    Email layouts are tables, and trafilatura gives every cell its own paragraph, which turns a market ticker into
    one number per line. Rows are visited innermost first, so a row holding a nested table sees its flattened text.
    """
    try:
        root = lxml.html.document_fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        # No elements at all, or an XML encoding declaration lxml refuses in a str: trafilatura copes on its own.
        return html
    for row in reversed(list(root.iter("tr"))):
        _join_short_row(row)
    return lxml.html.tostring(root, encoding="unicode")


def _join_short_row(row: lxml.html.HtmlElement) -> None:
    """Replace `row`'s cells with one paragraph of their texts when there are at least two and they are short."""
    # Headings would lose their markdown, and style or script text isn't text at all.
    if any(element.tag in _ROW_JOIN_BLOCKERS for element in row.iter()):
        return

    texts = [" ".join(cell.text_content().split()) for cell in row if cell.tag in ("td", "th")]
    filled = [text for text in texts if text]
    joined = _CELL_SEPARATOR.join(filled)
    if len(filled) < 2 or len(joined.split()) > MAX_JOINED_ROW_WORDS:
        return

    for child in list(row):
        row.remove(child)
    cell = lxml.html.Element("td")
    paragraph = lxml.html.Element("p")
    paragraph.text = joined
    cell.append(paragraph)
    row.append(cell)
