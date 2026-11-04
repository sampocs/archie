"""Scrub a real newsletter email into a fixture that is safe to commit to the public repo.

Usage: `uv run python -I scripts/scrub_newsletter_email.py <in.eml> <out.eml>`

The input is untrusted data: it is parsed, never executed. Headers are cut down to a short allow-list, tracking links
and query strings (also on scheme-less links) are removed, open-tracking pixels are replaced, the Message-ID becomes a
hash, every address becomes `reader@example.invalid`, and the result is refused (exit 1) if a
known leak pattern survives.
"""

from __future__ import annotations

import email
import email.message
import email.policy
import hashlib
import pathlib
import re
import sys
from urllib import parse

KEPT_HEADERS = frozenset(
    {
        "from",
        "to",
        "subject",
        "date",
        "message-id",
        "mime-version",
        "content-type",
        "content-transfer-encoding",
        "list-post",
        "list-id",
    }
)
PLACEHOLDER_ADDRESS = "reader@example.invalid"
PLACEHOLDER_TRACKED_URL = "https://example.invalid/tracked"
PLACEHOLDER_UNSUBSCRIBE = "<https://example.invalid/unsubscribe>"

TRACKER_HOST_SUFFIXES = ("link.morningbrew.com", "list-manage.com", "sailthru.com")
TRACKER_HOST_PREFIXES = ("click.", "links.")
# Substack's open-tracking pixel carries a per-recipient id in its path, so the whole URL goes.
TRACKER_HOSTS = frozenset({"eotrx.substackcdn.com"})
SUBSTACK_REDIRECT_PREFIX = "/redirect"

# A URL with a scheme, or a scheme-less `host.tld/path?query` (e.g. a referral link printed as plain text).
URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>\\)\]]+"
    r"|(?<![\w@./-])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}/[^\s\"'<>\\)\]]*\?[^\s\"'<>\\)\]]*"
)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Each entry is (name reported on failure, pattern); the matched text is never printed.
LEAK_PATTERNS = (
    ("base64 json token", re.compile(r"eyJ")),
    ("token query", re.compile(r"token=")),
    ("archie address", re.compile(r"archiesecondbrain")),
    ("sailthru address", re.compile(r"@sailthru")),
    ("mailgun", re.compile(r"mailgun", re.IGNORECASE)),
    ("sailthru job id", re.compile(r"\?j=")),
    ("utm parameter", re.compile(r"utm_")),
    ("referral id", re.compile(r"kid=")),
    ("open pixel", re.compile(r"eotrx")),
)


def scrub_url(url: str) -> str:
    """Replace a tracker URL outright; otherwise drop the query string and fragment."""
    # urlsplit only finds the host of a scheme-less URL after `//`.
    parts = parse.urlsplit(url if "://" in url else f"//{url}")
    host = (parts.hostname or "").lower()

    is_tracker = (
        host in TRACKER_HOSTS
        or host.endswith(TRACKER_HOST_SUFFIXES)
        or host.startswith(TRACKER_HOST_PREFIXES)
        or (host.startswith("email.mg") and host.endswith(".substack.com"))
        or (host.endswith("substack.com") and parts.path.startswith(SUBSTACK_REDIRECT_PREFIX))
    )
    if is_tracker:
        return PLACEHOLDER_TRACKED_URL
    scrubbed = parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return scrubbed if parts.scheme else scrubbed.removeprefix("//")


def scrub_text(text: str) -> str:
    """Scrub every URL and address in a body part."""
    without_urls = URL_PATTERN.sub(lambda match: scrub_url(match.group(0)), text)
    return EMAIL_PATTERN.sub(PLACEHOLDER_ADDRESS, without_urls)


def scrub_message(message: email.message.EmailMessage) -> None:
    """Cut the headers to the allow-list and scrub the text and html parts, in place."""
    for name in {header.lower() for header in message.keys()} - KEPT_HEADERS:
        del message[name]

    del message["To"]
    message["To"] = PLACEHOLDER_ADDRESS
    message["List-Unsubscribe"] = PLACEHOLDER_UNSUBSCRIBE

    # A Message-ID names the sender's mail system and embeds its per-delivery ids; a hash keeps it unique and stable.
    original_id = str(message["Message-ID"])
    message.replace_header("Message-ID", f"<{hashlib.sha256(original_id.encode()).hexdigest()[:24]}@example.invalid>")

    for part in message.walk():
        subtype = part.get_content_subtype()
        if part.get_content_maintype() != "text" or subtype not in {"plain", "html"}:
            continue
        part.set_content(scrub_text(part.get_content()), subtype=subtype, charset="utf-8")


def leaked_pattern_names(output: bytes) -> list[str]:
    """Names of the leak patterns still present in `output`."""
    text = output.decode("utf-8", errors="replace")
    return [name for name, pattern in LEAK_PATTERNS if pattern.search(text)]


def main(argv: list[str]) -> int:
    """Scrub `argv[1]` into `argv[2]`; exit 1 (after writing) when a leak pattern survives."""
    if len(argv) != 3:
        print(__doc__)
        return 2

    source_path, target_path = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    message = email.message_from_bytes(source_path.read_bytes(), policy=email.policy.default)
    assert isinstance(message, email.message.EmailMessage)
    scrub_message(message)

    output = message.as_bytes()
    target_path.write_bytes(output)

    leaks = leaked_pattern_names(output)
    if leaks:
        print(f"Refusing {target_path}: still contains {', '.join(leaks)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
