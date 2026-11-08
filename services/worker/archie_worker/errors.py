"""Failures a handler can signal to the loop, and the reasons users are shown."""

from __future__ import annotations

from enum import StrEnum


class FailureReason(StrEnum):
    """User-facing text stored as a source's `processing_error` when its pipeline fails."""

    TEXT_MISSING = "Couldn't read this page. Share it from Safari to capture it."
    # Same text as the `models.UNREADABLE_EMAIL_ERROR`, which marks an email the API already found unreadable.
    NEWSLETTER_UNREADABLE = "Couldn't read this email."
    NEEDS_API_KEY = "Add your own API key in Settings (coming soon)."
    GAVE_UP = "Processing failed. Tap Retry."
    SPOTIFY_ONLY = "This show is only on Spotify, so Archie can't get its audio."
    EPISODE_NOT_FOUND = "Couldn't find this episode's audio. If the show is only on Spotify, Archie can't get it."
    EPISODE_TOO_LONG = "This episode is too long to transcribe"
    AUDIO_UNREADABLE = "Couldn't read this episode's audio."
    TRANSCRIPTION_NOT_SET_UP = "Transcription isn't set up on the server."
    YOUTUBE_NEEDS_SETUP = "YouTube transcripts need setup on the server (a Supadata key)."
    NO_CAPTIONS = "This video has no captions."
    VIDEO_UNAVAILABLE = "This video isn't available."
    PREVIEW_UNAVAILABLE = "Couldn't load a preview for this link."


class PermanentJobError(Exception):
    """Raised by a handler when retrying cannot help; the loop fails the job at once and shows `reason` to the user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RetryLaterError(Exception):
    """Raised by a handler when a service asked to be retried later; the loop re-queues the job after `after_seconds`.

    It still counts as an attempt, so the job can give up if the service keeps refusing.
    """

    def __init__(self, *, reason: str, after_seconds: float) -> None:
        super().__init__(reason)
        self.reason = reason
        self.after_seconds = after_seconds
