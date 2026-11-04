"""Auth through the real API: a session key works until logout, and nothing works without one."""

import pytest
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres


def test_a_valid_session_key_is_accepted(live_stack: LiveStack) -> None:
    """The key from sign-in reaches a protected route as the same user each time."""
    authed = live_stack.authed(live_stack.sign_in(apple_sub="alice"))

    first = authed.get("/me")
    second = live_stack.authed(live_stack.sign_in(apple_sub="alice")).get("/me")

    assert first.status_code == 200
    assert second.json() == first.json()


def test_the_bearer_scheme_is_case_insensitive(live_stack: LiveStack) -> None:
    """RFC 7235 auth schemes are case-insensitive, so `bearer <key>` signs in too."""
    session_key = live_stack.sign_in()

    response = live_stack.client.get("/me", headers={"Authorization": f"bearer {session_key}"})

    assert response.status_code == 200


def test_requests_without_a_session_key_are_rejected(live_stack: LiveStack) -> None:
    """A protected route returns 401 with no header, a non-Bearer scheme, a token-less Bearer, and an unknown key."""
    session_key = live_stack.sign_in()

    assert live_stack.client.get("/me").status_code == 401
    assert live_stack.client.get("/me", headers={"Authorization": f"Basic {session_key}"}).status_code == 401
    assert live_stack.client.get("/me", headers={"Authorization": "Bearer"}).status_code == 401
    assert live_stack.authed("not-a-real-key").get("/me").status_code == 401


def test_logout_revokes_the_session_key(live_stack: LiveStack) -> None:
    """After logout, the same key is rejected, but another session of the same user still works."""
    session_key = live_stack.sign_in()
    other_session = live_stack.authed(live_stack.sign_in())
    authed = live_stack.authed(session_key)

    assert authed.post("/auth/logout").status_code == 204
    assert authed.get("/me").status_code == 401
    assert other_session.get("/me").status_code == 200


def test_apple_sign_in_rejects_an_invalid_token(live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch) -> None:
    """A token that isn't a valid Apple identity token gets 401 and no session."""
    monkeypatch.setenv("APPLE_AUDIENCE", "com.sampocs.archie")

    response = live_stack.client.post("/auth/apple", json={"identity_token": "not-a-jwt"})

    assert response.status_code == 401


def test_me_has_no_ingest_address_without_a_domain(live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch) -> None:
    """With INGEST_EMAIL_DOMAIN unset the newsletter address isn't offered."""
    monkeypatch.delenv("INGEST_EMAIL_DOMAIN", raising=False)
    authed = live_stack.authed(live_stack.sign_in())

    assert authed.get("/me").json()["ingest_address"] is None


def test_me_returns_the_users_ingest_address(live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the domain set, /me gives `<10-char token>@<domain>`, stable across calls."""
    monkeypatch.setenv("INGEST_EMAIL_DOMAIN", "example.com")
    authed = live_stack.authed(live_stack.sign_in(apple_sub="newsletter-reader"))

    address = authed.get("/me").json()["ingest_address"]
    token, _, domain = address.partition("@")

    assert (len(token), domain) == (10, "example.com")
    assert authed.get("/me").json()["ingest_address"] == address
