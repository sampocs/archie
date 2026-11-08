"""Who an email is from: the identifiers an address, List-Id and display name give, with their real edge cases."""

from __future__ import annotations

import pytest
from archie_db import models, senders

DOMAIN = models.IdentifierKind.DOMAIN
ADDRESS = models.IdentifierKind.ADDRESS
LIST_ID = models.IdentifierKind.LIST_ID
NAME = models.IdentifierKind.NAME


def _identifiers(*, address: str | None, list_id: str | None = None, name: str | None = None) -> set[tuple[str, str]]:
    found = senders.identifiers_for(address=address, list_id=list_id, name=name)
    return {(identifier.kind, identifier.value) for identifier in found}


def test_a_subdomain_of_a_multi_part_suffix_reduces_to_the_registrable_domain() -> None:
    """`mail.example.co.uk` belongs to `example.co.uk`, not `co.uk`; the address is upper case in the wild."""
    assert _identifiers(address="News@Mail.Example.co.uk") == {(DOMAIN, "example.co.uk")}


def test_a_shared_platform_sender_is_identified_by_its_full_address_never_its_domain() -> None:
    """Allowing ByteByteGo must not allow every other Substack."""
    found = _identifiers(address="ByteByteGo@substack.com", list_id="<bytebytego.substack.com>", name="ByteByteGo")

    assert found == {(ADDRESS, "bytebytego@substack.com"), (LIST_ID, "bytebytego.substack.com"), (NAME, "bytebytego")}
    assert (DOMAIN, "substack.com") not in found


def test_a_subdomain_of_a_shared_platform_is_still_shared() -> None:
    """The check is on the registrable domain, so `mail.beehiiv.com` can't sneak a bare platform domain in."""
    assert _identifiers(address="writer@mail.beehiiv.com") == {(ADDRESS, "writer@mail.beehiiv.com")}


def test_a_mailbox_provider_address_is_identified_by_the_address() -> None:
    """Everyone with a Gmail address would otherwise count as one sender."""
    assert _identifiers(address="Person@Gmail.com") == {(ADDRESS, "person@gmail.com")}


@pytest.mark.parametrize("address", [None, "", "no-at-sign", "user@localhost", "user@192.168.1.10", "user@[::1]"])
def test_an_address_without_a_registrable_domain_gives_no_identifier(address: str | None) -> None:
    """No `@`, a host without a dot, or an IP has nothing to identify by."""
    assert _identifiers(address=address) == set()


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("<Bytebytego.Substack.com>", "bytebytego.substack.com"),
        ("The Hustle <thehustle.example.com> ", "thehustle.example.com"),
        ("  Plain.Example.Com ", "plain.example.com"),
    ],
)
def test_a_list_id_keeps_the_part_in_brackets_or_the_whole_value_lower_cased(header: str, expected: str) -> None:
    """RFC 2919 puts the id in `<...>`, optionally after a description; some senders omit the brackets."""
    assert senders.normalize_list_id(header) == expected


def test_an_empty_list_id_is_absent() -> None:
    """A blank or empty-bracket header gives nothing to match."""
    assert [senders.normalize_list_id(value) for value in ("", "  ", "<>", None)] == [None] * 4


def test_a_display_name_is_trimmed_collapsed_and_lower_cased() -> None:
    """The same newsletter's name varies in case and spacing between issues."""
    assert senders.normalize_name("  Morning \t Brew  ") == "morning brew"
    assert senders.normalize_name("   ") is None


def test_every_identifier_of_a_full_email_is_kept() -> None:
    """Domain, List-Id and name together are what lenient matching ORs over."""
    found = _identifiers(address="crew@morningbrew.com", list_id="<mb.example.invalid>", name="Morning Brew")

    assert found == {(DOMAIN, "morningbrew.com"), (LIST_ID, "mb.example.invalid"), (NAME, "morning brew")}
