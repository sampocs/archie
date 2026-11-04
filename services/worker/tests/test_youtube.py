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
    ("error", "has_supadata_key", "expected_reason"),
    [
        (youtube_transcript_api.RequestBlocked(VIDEO_ID), False, errors.FailureReason.YOUTUBE_NEEDS_SETUP),
        (youtube_transcript_api.IpBlocked(VIDEO_ID), False, errors.FailureReason.YOUTUBE_NEEDS_SETUP),
        (youtube_transcript_api.RequestBlocked(VIDEO_ID), True, None),
        (youtube_transcript_api.IpBlocked(VIDEO_ID), True, None),
        (youtube_transcript_api.TranscriptsDisabled(VIDEO_ID), False, errors.FailureReason.NO_CAPTIONS),
        (youtube_transcript_api.TranscriptsDisabled(VIDEO_ID), True, errors.FailureReason.NO_CAPTIONS),
        (_no_transcript_found(), False, errors.FailureReason.NO_CAPTIONS),
        (youtube_transcript_api.VideoUnavailable(VIDEO_ID), False, errors.FailureReason.VIDEO_UNAVAILABLE),
        (youtube_transcript_api.AgeRestricted(VIDEO_ID), False, None),
        (RuntimeError("boom"), False, None),
    ],
)
def test_permanent_error_for_maps_each_library_failure(
    error: Exception, has_supadata_key: bool, expected_reason: errors.FailureReason | None
) -> None:
    """Blocks need setup only without a Supadata key, caption/video problems are permanent, the rest is retried."""
    permanent_error = youtube.permanent_error_for(error, has_supadata_key=has_supadata_key)

    assert (permanent_error.reason if permanent_error else None) == expected_reason
