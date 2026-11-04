"""Which caption-library failures are permanent, and what each one tells the user."""

from __future__ import annotations

import pytest
import youtube_transcript_api
from archie_worker import errors
from archie_worker.content import youtube

VIDEO_ID = "e0gVE3YxZs8"


def _no_transcript_found() -> youtube_transcript_api.NoTranscriptFound:
    # The library only reads the transcript list when it renders its message, which these tests never do.
    return youtube_transcript_api.NoTranscriptFound(VIDEO_ID, ["en"], None)


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (youtube_transcript_api.RequestBlocked(VIDEO_ID), errors.FailureReason.YOUTUBE_NEEDS_SETUP),
        (youtube_transcript_api.IpBlocked(VIDEO_ID), errors.FailureReason.YOUTUBE_NEEDS_SETUP),
        (youtube_transcript_api.TranscriptsDisabled(VIDEO_ID), errors.FailureReason.NO_CAPTIONS),
        (_no_transcript_found(), errors.FailureReason.NO_CAPTIONS),
        (youtube_transcript_api.VideoUnavailable(VIDEO_ID), errors.FailureReason.VIDEO_UNAVAILABLE),
        (youtube_transcript_api.AgeRestricted(VIDEO_ID), None),
        (RuntimeError("boom"), None),
    ],
)
def test_permanent_error_for_maps_each_library_failure(
    error: Exception, expected_reason: errors.FailureReason | None
) -> None:
    """Blocks need setup, caption/video problems are permanent, the rest is retried."""
    permanent_error = youtube.permanent_error_for(error)

    assert (permanent_error.reason if permanent_error else None) == expected_reason
