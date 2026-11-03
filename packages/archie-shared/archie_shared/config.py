"""Environment-sourced configuration via pydantic settings.

Everything deployment-specific — the database URL, which emails belong to the owner, the Apple
audience — is read from the environment only, never hardcoded. A local `.env` file (see
`.env.example`) is loaded if present, purely as a developer convenience.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict

# Env var holding the Postgres connection URL (local Docker in development, Railway's in prod).
DATABASE_URL_ENV = "DATABASE_URL"
OWNER_EMAILS_ENV = "OWNER_EMAILS"
APPLE_AUDIENCE_ENV = "APPLE_AUDIENCE"
ARCHIE_ENV_ENV = "ARCHIE_ENV"
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"


class ConfigError(RuntimeError):
    """Raised when required environment configuration is missing or invalid."""


class ArchieEnv(StrEnum):
    """Which deployment this process runs as; test-only routes need `DEV` or `TEST` set explicitly."""

    PROD = "prod"
    DEV = "dev"
    TEST = "test"


class Settings(BaseSettings):
    """Environment-sourced settings; field names map to their upper-cased env vars.

    All fields are optional here so importing/constructing never fails; each caller validates
    only the subset it needs through a `require_*` accessor with a clear error.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str | None = None
    owner_emails: str | None = None
    apple_audience: str | None = None
    archie_env: str | None = None
    anthropic_api_key: str | None = None

    def require_database_url(self) -> str:
        """Return the Postgres URL, raising a clear error if it is missing."""
        database_url = self.database_url
        if not database_url:
            raise ConfigError(f"Missing Postgres configuration: {DATABASE_URL_ENV} (see .env.example).")
        return database_url

    def require_apple_audience(self) -> str:
        """Return the audience Apple identity tokens must carry, raising a clear error if it is missing."""
        apple_audience = self.apple_audience
        if not apple_audience:
            raise ConfigError(f"Missing Apple configuration: {APPLE_AUDIENCE_ENV} (see .env.example).")
        return apple_audience

    def require_anthropic_api_key(self) -> str:
        """Return the Anthropic API key, raising a clear error if it is missing."""
        anthropic_api_key = self.anthropic_api_key
        if not anthropic_api_key:
            raise ConfigError(f"Missing Anthropic configuration: {ANTHROPIC_API_KEY_ENV} (see .env.example).")
        return anthropic_api_key

    def owner_email_set(self) -> frozenset[str]:
        """The owner's emails, trimmed and lower-cased; empty when `OWNER_EMAILS` is unset.

        An empty set is a valid configuration, not an error: nobody gets the owner's API keys.
        """
        if not self.owner_emails:
            return frozenset()
        return frozenset(email.strip().lower() for email in self.owner_emails.split(",") if email.strip())

    def env(self) -> ArchieEnv:
        """The deployment this process runs as, defaulting to `DEV` when `ARCHIE_ENV` is unset."""
        if not self.archie_env:
            return ArchieEnv.DEV

        normalized = self.archie_env.strip().lower()
        if normalized not in ArchieEnv:
            raise ConfigError(f"{ARCHIE_ENV_ENV} must be one of {', '.join(ArchieEnv)}, not {self.archie_env!r}.")
        return ArchieEnv(normalized)


def get_settings() -> Settings:
    """Build a `Settings` instance from the current environment (and `.env` if present)."""
    return Settings()
