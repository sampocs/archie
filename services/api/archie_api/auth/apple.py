"""Sign in with Apple: verify the identity token the phone gets from Apple and find or create its user."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
import sqlalchemy
from archie_db import models
from sqlalchemy import orm

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_JWKS_LIFESPAN_SECONDS = 86400

# Module-level so Apple's keys are fetched once and cached across requests; no network until first use.
_JWKS_CLIENT = jwt.PyJWKClient(APPLE_JWKS_URL, cache_keys=True, lifespan=_JWKS_LIFESPAN_SECONDS)


class InvalidAppleToken(Exception):
    """The identity token failed verification; the route maps this to 401."""


@dataclass(frozen=True)
class AppleIdentity:
    """Who Apple says signed in. Apple sends `email` only on a user's first sign-in to the app."""

    sub: str
    email: str | None


def get_jwks_client() -> jwt.PyJWKClient:
    """Apple's signing keys client; a FastAPI dependency so tests can swap the key source."""
    return _JWKS_CLIENT


def verify_identity_token(token: str, *, audience: str, jwks_client: jwt.PyJWKClient) -> AppleIdentity:
    """Check an Apple identity token's signature, issuer, audience and expiry; return who signed in."""
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=APPLE_ISSUER,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as error:
        # One narrow boundary: every PyJWT failure means "not a valid sign-in", which the route maps to 401.
        raise InvalidAppleToken(str(error)) from error
    return AppleIdentity(sub=claims["sub"], email=claims.get("email"))


def upsert_apple_user(db: orm.Session, *, identity: AppleIdentity, owner_emails: frozenset[str]) -> models.User:
    """Find or create the user for `identity` and refresh whitelisting; never commits.

    A later sign-in without an email keeps the stored one, so whitelisting is judged on the effective email.
    """
    user = db.scalars(sqlalchemy.select(models.User).where(models.User.apple_sub == identity.sub)).first()
    if user is None:
        user = models.User(apple_sub=identity.sub)
        db.add(user)

    if identity.email:
        user.email = identity.email
    user.is_whitelisted = user.email is not None and user.email.lower() in owner_emails

    db.flush()
    return user
