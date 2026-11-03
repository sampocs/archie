"""The title parser and page download in isolation; no database or network involved."""

from __future__ import annotations

import collections.abc

import httpx
import pytest
from archie_worker.handlers import fetch_title

_REAL_CLIENT = httpx.Client


def test_a_blank_og_title_falls_back_to_the_title_tag() -> None:
    """A whitespace-only og:title must not mask the <title>."""
    page = '<head><meta property="og:title" content="  \n "><title>Real  Title</title></head>'

    assert fetch_title.extract_title(page=page) == "Real Title"


def test_a_page_with_only_blank_candidates_has_no_title() -> None:
    """Nothing but whitespace is no title."""
    page = '<head><meta property="og:title" content=" "><title> </title></head>'

    assert fetch_title.extract_title(page=page) is None


def test_nul_characters_are_stripped_from_titles() -> None:
    """Postgres cannot store NUL; a candidate that is only NULs counts as blank and falls through."""
    page = '<head><meta property="og:title" content="\x00\x00"><title>Re\x00al Title</title></head>'

    assert fetch_title.extract_title(page=page) == "Real Title"


def test_a_long_title_is_truncated() -> None:
    """Titles are capped so a hostile page cannot store a huge string."""
    page = f"<title>{'x' * (fetch_title._MAX_TITLE_LENGTH + 100)}</title>"

    title = fetch_title.extract_title(page=page)

    assert title == "x" * fetch_title._MAX_TITLE_LENGTH


def test_a_trickling_server_hits_the_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx's timeout is per read, so only the deadline stops a server that never stalls long enough."""

    def trickle() -> collections.abc.Iterator[bytes]:
        while True:
            yield b"x"

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=trickle()))
    monkeypatch.setattr(fetch_title.httpx, "Client", lambda **kwargs: _REAL_CLIENT(transport=transport, **kwargs))
    clock = iter([0.0, 1.0, float(fetch_title._FETCH_TIMEOUT_SECONDS) + 1])
    monkeypatch.setattr(fetch_title.time, "monotonic", lambda: next(clock))

    with pytest.raises(TimeoutError):
        fetch_title.fetch_page(
            url="https://slow.example/",
            timeout_seconds=fetch_title._FETCH_TIMEOUT_SECONDS,
            max_bytes=fetch_title._MAX_BODY_BYTES,
        )
