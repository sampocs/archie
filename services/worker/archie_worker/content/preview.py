"""A saved post's preview: X and YouTube use their own lookups, any other link its og:title and og:image."""

from __future__ import annotations

import httpx
from archie_db import models
from archie_shared import urls

from archie_worker import content, errors
from archie_worker.content import x, youtube
from archie_worker.handlers import fetch_title

_PAGE_TIMEOUT_SECONDS = 15
_PAGE_MAX_BYTES = 2_000_000
_TOO_MANY_REQUESTS = 429


def fetch(*, url: str, kind: models.CollectionItemKind) -> content.LinkPreview:
    """The post's preview; raises PermanentJobError when retrying can't help, anything else when it might."""
    post_id = urls.x_post_id(url) if kind == models.CollectionItemKind.X else None
    if post_id is not None:
        return x.fetch_post_preview(post_id=post_id)

    video_id = urls.youtube_video_id(url) if kind == models.CollectionItemKind.YOUTUBE else None
    if video_id is not None:
        return youtube.fetch_preview(video_id=video_id)

    # A profile or channel link (no post or video id) is previewed like any page.
    return _page_preview(url=url)


def _page_preview(*, url: str) -> content.LinkPreview:
    try:
        page = fetch_title.fetch_page(url=url, timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if 400 <= status < 500 and status != _TOO_MANY_REQUESTS:
            raise errors.PermanentJobError(errors.FailureReason.PREVIEW_UNAVAILABLE) from error
        raise

    return content.LinkPreview(
        title=fetch_title.extract_title(page=page),
        author=None,
        image_url=fetch_title.extract_image(page=page, base_url=url),
        duration_seconds=None,
    )
