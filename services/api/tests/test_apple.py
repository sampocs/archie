"""Apple identity tokens are accepted only when signed by Apple's key, for us, unexpired; users are upserted."""

import datetime
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
import sqlalchemy
from archie_api.auth import apple
from archie_db import models
from archie_db import session as db_session
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import orm

AUDIENCE = "com.sampocs.archie"


class _FixedKeyClient(jwt.PyJWKClient):
    """A real `PyJWKClient` whose key lookup returns one local key instead of fetching Apple's."""

    def __init__(self, public_key: rsa.RSAPublicKey) -> None:
        super().__init__(apple.APPLE_JWKS_URL)
        self._signing_key = jwt.PyJWK.from_json(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        return self._signing_key


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def apple_key() -> rsa.RSAPrivateKey:
    """A throwaway RSA key standing in for Apple's signing key."""
    return _new_key()


def _mint(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    claims: dict[str, Any] = {
        "iss": apple.APPLE_ISSUER,
        "aud": AUDIENCE,
        "sub": "apple-user-1",
        "email": "me@example.com",
        "exp": datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(minutes=10),
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


def _verify(apple_key: rsa.RSAPrivateKey, token: str) -> apple.AppleIdentity:
    return apple.verify_identity_token(token, audience=AUDIENCE, jwks_client=_FixedKeyClient(apple_key.public_key()))


def test_a_good_token_returns_sub_and_email(apple_key: rsa.RSAPrivateKey) -> None:
    """A good token returns sub and email."""
    assert _verify(apple_key, _mint(apple_key)) == apple.AppleIdentity(sub="apple-user-1", email="me@example.com")


def test_a_token_without_an_email_has_none(apple_key: rsa.RSAPrivateKey) -> None:
    """A token without an email has none."""
    identity = _verify(apple_key, _mint(apple_key, email=None))

    assert identity.email is None


def test_a_token_signed_with_another_key_is_rejected(apple_key: rsa.RSAPrivateKey) -> None:
    """A token signed with another key is rejected."""
    with pytest.raises(apple.InvalidAppleToken):
        _verify(apple_key, _mint(_new_key()))


def test_the_wrong_audience_is_rejected(apple_key: rsa.RSAPrivateKey) -> None:
    """The wrong audience is rejected."""
    with pytest.raises(apple.InvalidAppleToken):
        _verify(apple_key, _mint(apple_key, aud="com.someone.else"))


def test_an_expired_token_is_rejected(apple_key: rsa.RSAPrivateKey) -> None:
    """An expired token is rejected."""
    expired = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(minutes=1)

    with pytest.raises(apple.InvalidAppleToken):
        _verify(apple_key, _mint(apple_key, exp=expired))


def test_the_wrong_issuer_is_rejected(apple_key: rsa.RSAPrivateKey) -> None:
    """The wrong issuer is rejected."""
    with pytest.raises(apple.InvalidAppleToken):
        _verify(apple_key, _mint(apple_key, iss="https://evil.example.com"))


class _RecordingKeyClient(jwt.PyJWKClient):
    """A real `PyJWKClient` that records any attempt to fetch keys (parsing the token header comes first, and is free)."""

    def __init__(self) -> None:
        super().__init__(apple.APPLE_JWKS_URL)
        self.key_lookups = 0

    def fetch_data(self) -> Any:
        self.key_lookups += 1
        return super().fetch_data()

    def get_signing_keys(self, refresh: bool = False) -> Any:
        self.key_lookups += 1
        return super().get_signing_keys(refresh=refresh)


def test_a_malformed_token_is_rejected_without_fetching_keys() -> None:
    """A malformed token is rejected without fetching keys."""
    client = _RecordingKeyClient()

    with pytest.raises(apple.InvalidAppleToken):
        apple.verify_identity_token("not-a-jwt", audience=AUDIENCE, jwks_client=client)

    assert client.key_lookups == 0


@pytest.mark.postgres
class TestUpsertAppleUser:
    """Finding or creating the user behind an Apple identity."""

    @pytest.fixture
    def db(self, migrated_database_url: str) -> Iterator[orm.Session]:
        """A session on an empty users table, rolled back afterwards."""
        with orm.Session(db_session.engine_for(migrated_database_url)) as db:
            db.execute(sqlalchemy.delete(models.User))
            yield db
            db.rollback()

    def test_first_sign_in_creates_a_whitelisted_owner(self, db: orm.Session) -> None:
        """First sign in creates a whitelisted owner."""
        identity = apple.AppleIdentity(sub="s1", email="Owner@Example.com")

        user = apple.upsert_apple_user(db, identity=identity, owner_emails=frozenset({"owner@example.com"}))

        assert (user.email, user.is_whitelisted) == ("Owner@Example.com", True)

    def test_other_emails_are_not_whitelisted(self, db: orm.Session) -> None:
        """Other emails are not whitelisted."""
        identity = apple.AppleIdentity(sub="s2", email="stranger@example.com")

        user = apple.upsert_apple_user(db, identity=identity, owner_emails=frozenset({"owner@example.com"}))

        assert user.is_whitelisted is False

    def test_a_later_sign_in_without_email_keeps_the_stored_email_and_whitelisting(self, db: orm.Session) -> None:
        """A later sign in without email keeps the stored email and whitelisting."""
        owners = frozenset({"owner@example.com"})
        first = apple.upsert_apple_user(
            db, identity=apple.AppleIdentity(sub="s3", email="owner@example.com"), owner_emails=owners
        )

        second = apple.upsert_apple_user(db, identity=apple.AppleIdentity(sub="s3", email=None), owner_emails=owners)

        assert second.id == first.id
        assert (second.email, second.is_whitelisted) == ("owner@example.com", True)
