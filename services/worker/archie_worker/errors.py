"""Failures a handler can signal to the loop, and the reasons users are shown."""

from __future__ import annotations

from enum import StrEnum


class FailureReason(StrEnum):
    """User-facing text stored as a source's `processing_error` when its pipeline fails."""

    TEXT_MISSING = "Couldn't read this page. Share it from Safari to capture it."
    NEEDS_API_KEY = "Add your own API key in Settings (coming soon)."
    GAVE_UP = "Processing failed. Tap Retry."


class PermanentJobError(Exception):
    """Raised by a handler when retrying cannot help; the loop fails the job at once and shows `reason` to the user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
