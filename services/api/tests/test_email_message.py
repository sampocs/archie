"""Parsing the two real newsletters (scrubbed) and the edges of the message-id and recipient rules."""

from __future__ import annotations

import email.message
import pathlib

import pytest
from archie_api.ingest import email_message

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "newsletters"
MIN_WORDS = 300


def test_a_substack_post_yields_its_subject_sender_web_url_and_article_text() -> None:
    """List-Post gives the web URL; the HTML is reduced to article text."""
    parsed = email_message.parse((FIXTURES / "substack_bytebytego.eml").read_bytes())

    assert parsed.subject == "How Netflix Uses AI Agents for Performance Engineering"
    assert parsed.sender == "ByteByteGo"
    assert parsed.web_url == "https://blog.bytebytego.com/p/how-netflix-uses-ai-agents-for-performance"
    assert len(parsed.text.split()) >= MIN_WORDS
    assert "Recorder operates at 100 Hz sampling" in parsed.text
    assert "<div" not in parsed.text


def test_a_morning_brew_issue_takes_its_web_url_from_view_online_and_keeps_paragraphs_as_markdown() -> None:
    """With no List-Post or Substack line, the "View Online" link is the web URL; the text is markdown paragraphs."""
    parsed = email_message.parse((FIXTURES / "morning_brew.eml").read_bytes())

    assert parsed.subject == "☕ Putting it to a vote"
    assert parsed.sender == "Morning Brew"
    assert parsed.web_url == "https://example.invalid/tracked"
    assert len(parsed.text.split()) >= MIN_WORDS
    assert "<td" not in parsed.text
    # Markdown keeps the bold lead-ins and separates paragraphs with a blank line.
    assert "**Mission control:** Currently, Republicans control both chambers" in parsed.text
    assert "\n\n**It’s the economy, stupid.**" in parsed.text


def test_a_newsletter_table_row_of_short_cells_reads_as_one_line() -> None:
    """Morning Brew's market table comes through a row per line, not one figure per paragraph."""
    parsed = email_message.parse((FIXTURES / "morning_brew.eml").read_bytes())

    assert "Nasdaq · 25,164.32 · -1.07%" in parsed.text.splitlines()
    assert "10-Year · 4.894% · -4.0 bps" in parsed.text.splitlines()


@pytest.mark.parametrize(
    ("link", "web_url"),
    [
        ('<a href="https://example.com/web">View  in your\n browser</a>', "https://example.com/web"),
        ('<a href="https://example.com/web"><span>READ</span> online</a>', "https://example.com/web"),
        ('<a href="http://example.com/web">View Online</a>', None),
        ('<a href="https://example.com/web">View our sponsor online</a>', None),
    ],
)
def test_only_an_https_link_whose_text_names_the_web_version_is_the_web_url(link: str, web_url: str | None) -> None:
    """Link text matches case- and whitespace-insensitively among the known phrasings; http links are not taken."""
    message = email.message.EmailMessage()
    message["Subject"] = "Issue"
    message.set_content("Plain part.")
    message.add_alternative(f"<html><body><p>Hello</p>{link}</body></html>", subtype="html")

    assert email_message.parse(message.as_bytes()).web_url == web_url


def test_a_message_without_a_message_id_gets_a_stable_hash_id() -> None:
    """The fallback id is a hash of the bytes, so a redelivery still dedupes."""
    message = email.message.EmailMessage()
    message["From"] = "writer@example.com"
    message["Subject"] = "No id"
    message.set_content("Just a short plain note.")
    raw = message.as_bytes()

    first, second = email_message.parse(raw), email_message.parse(raw)

    assert first.message_id.startswith("sha256:")
    assert first.message_id == second.message_id
    assert first.sender == "writer@example.com"


def test_a_message_id_the_column_cannot_store_falls_back_to_the_hash_id() -> None:
    """An over-long or NUL-bearing Message-ID would fail the insert, so it is replaced by the hash id."""
    for message_id in (f"<{'a' * 1_200}@example.com>", "<abc\x00def@example.com>"):
        message = email.message.EmailMessage()
        message["Subject"] = "Odd id"
        message["Message-ID"] = message_id
        message.set_content("Just a short plain note.")

        assert email_message.parse(message.as_bytes()).message_id.startswith("sha256:")


def test_nul_is_stripped_from_subject_sender_and_text() -> None:
    """Postgres text can't hold NUL, so parse removes it once for every caller."""
    raw = b"From: Wri\x00ter <writer@example.com>\nSubject: Hel\x00lo\n\nA short\x00 note.\n"

    parsed = email_message.parse(raw)

    assert (parsed.subject, parsed.sender, parsed.text) == ("Hello", "Writer", "A short note.")


def test_the_local_part_is_lower_cased_and_loses_its_plus_tag() -> None:
    """Recipient matching ignores case and +tag suffixes."""
    assert email_message.local_part("AbC123+x@example.com") == "abc123"


def test_html_with_an_xml_encoding_declaration_still_yields_its_text() -> None:
    """lxml refuses a str carrying an encoding declaration; the HTML then goes to trafilatura as it is."""
    words = " ".join(["word"] * 60)
    html = f'<?xml version="1.0" encoding="utf-8"?><html><body><p>{words}</p></body></html>'
    message = email.message.EmailMessage()
    message["Message-ID"] = "<xml-decl@example.com>"
    message.set_content(html, subtype="html")

    assert email_message.parse(message.as_bytes()).text.startswith("word word")


def test_a_tldr_signup_email_yields_its_unquoted_confirm_link() -> None:
    """TLDR writes `<a href=https://…>Confirm Signup</a>` with no quotes; the subject says confirm."""
    parsed = email_message.parse((FIXTURES / "tldr_confirm.eml").read_bytes())

    assert parsed.confirm_url == "https://example.com/confirm-signup"


def test_gmail_forwarding_confirmation_takes_the_vf_link_and_never_the_cancel_link() -> None:
    """Both links are in the plain text; only `vf-` confirms."""
    parsed = email_message.parse((FIXTURES / "gmail_forwarding.eml").read_bytes())

    assert parsed.confirm_url == "https://mail-settings.google.com/mail/vf-example"


def test_ordinary_newsletters_are_not_confirmations() -> None:
    """Morning Brew and the Substack post have no confirm link."""
    for name in ("morning_brew", "substack_bytebytego"):
        assert email_message.parse((FIXTURES / f"{name}.eml").read_bytes()).confirm_url is None


def _html_email(*, subject: str, link_text: str, href: str, sender: str = "writer@example.com") -> bytes:
    message = email.message.EmailMessage()
    message["From"] = sender
    message["Subject"] = subject
    message.set_content("Plain fallback.")
    message.add_alternative(f'<html><body><p>Hi.</p><a href="{href}">  {link_text}\n</a></body></html>', subtype="html")
    return message.as_bytes()


@pytest.mark.parametrize(
    ("subject", "link_text", "href", "expected"),
    [
        ("Your weekly issue", "Confirm subscription", "https://example.com/c", None),
        ("Please confirm", "Confirm subscription", "http://example.com/c", None),
        ("Please confirm", "Confirm subscription", "https://example.com/" + "a" * 2048, None),
        ("Please confirm", "Read the issue", "https://example.com/c", None),
        ("Please verify", "Verify   your\nEmail", "https://example.com/verify", "https://example.com/verify"),
        ("Activate now", "ACTIVATE", "https://example.com/go", "https://example.com/go"),
    ],
)
def test_a_generic_confirmation_needs_an_https_link_with_a_known_text_and_a_matching_subject(
    subject: str, link_text: str, href: str, expected: str | None
) -> None:
    """The subject keeps a stray link in a regular issue out; http, over-long and unknown-text links don't count."""
    parsed = email_message.parse(_html_email(subject=subject, link_text=link_text, href=href))

    assert parsed.confirm_url == expected


def test_a_forged_gmail_forwarding_subject_from_another_sender_is_not_a_confirmation() -> None:
    """The Gmail rule needs Google's From address as well as the subject."""
    message = email.message.EmailMessage()
    message["From"] = "someone@example.com"
    message["Subject"] = "Gmail Forwarding Confirmation"
    message.set_content("https://mail-settings.google.com/mail/vf-forged")

    assert email_message.parse(message.as_bytes()).confirm_url is None
