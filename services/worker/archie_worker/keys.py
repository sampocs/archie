"""Which API key pays for a user's model calls."""

from __future__ import annotations

from archie_db import models
from archie_shared import config

from archie_worker import errors


def anthropic_key_for(user: models.User) -> str:
    """The key that pays for this user's calls: the owner's for whitelisted users, otherwise they need their own."""
    if not user.is_whitelisted:
        raise errors.PermanentJobError(errors.FailureReason.NEEDS_API_KEY)

    return config.Settings().require_anthropic_api_key()
