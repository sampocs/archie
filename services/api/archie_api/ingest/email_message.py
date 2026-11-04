"""Turn a raw RFC 822 email into the few fields a newsletter source needs.

The message is outside input: it is parsed as data, its HTML is reduced to text by trafilatura, and nothing in it is
ever executed or followed.
"""

from __future__ import annotations

import email
import email.message
import email.policy
import email.utils
import hashlib
import re
from dataclasses import dataclass

import trafilatura

MAX_TEXT_LENGTH = 400_000
MIN_HTML_WORDS = 50

_WEB_URL_IN_LIST_POST = re.compile(r"<(https://[^>\s]+)>")
_WEB_URL_IN_BODY = re.compile(r"View this post on the web at (https://\S+)")
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
        web_url=_web_url(message, plain=plain),
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


def _web_url(message: email.message.Message, *, plain: str) -> str | None:
    """The post's page on the web: the List-Post URL, else the "View this post on the web" line."""
    list_post = _WEB_URL_IN_LIST_POST.search(_header_text(message, "List-Post") or "")
    if list_post:
        return list_post.group(1)

    in_body = _WEB_URL_IN_BODY.search(plain)
    return in_body.group(1) if in_body else None


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
    """The HTML reduced to text when that yields a real article, else the plain part."""
    extracted = trafilatura.extract(html, output_format="txt", include_comments=False) if html else None
    if extracted and len(extracted.split()) >= MIN_HTML_WORDS:
        return extracted.strip()
    return plain.strip()
