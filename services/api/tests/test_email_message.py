"""Parsing the two real newsletters (scrubbed) and the edges of the message-id and recipient rules."""

from __future__ import annotations

import email.message
import pathlib

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


def test_a_morning_brew_issue_has_no_web_url_but_readable_text() -> None:
    """An issue with no web link still parses to readable text."""
    parsed = email_message.parse((FIXTURES / "morning_brew.eml").read_bytes())

    assert parsed.subject == "☕ Putting it to a vote"
    assert parsed.sender == "Morning Brew"
    assert parsed.web_url is None
    assert len(parsed.text.split()) >= MIN_WORDS
    assert "<td" not in parsed.text


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
    assert email_message.local_part("AbC123+x@archiesecondbrain.com") == "abc123"
