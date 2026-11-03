"""X posts: fetch a post's thread from fxtwitter (vxtwitter as a fallback) and turn it into text."""

from __future__ import annotations

import time
from typing import Any

import httpx
from archie_shared import logging

from archie_worker import content

FXTWITTER_THREAD_URL = "https://api.fxtwitter.com/2/thread/{post_id}"
VXTWITTER_STATUS_URL = "https://api.vxtwitter.com/i/status/{post_id}"

FETCH_TRIES = 3
# Module constants so tests can zero the delay instead of waiting out each retry.
RETRY_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 10.0
# fxtwitter's Cloudflare answers 403 to httpx's default User-Agent; any named client is let through.
USER_AGENT = "archie-worker/0.1"

TITLE_POST_LENGTH = 80
# fxtwitter answers 404 sporadically for valid posts (see spikes/x_fxtwitter/RESULTS.md); those succeed on retry.
_RETRYABLE_STATUSES = frozenset({404})

_logger = logging.get_logger(logging.LoggerName.WORKER, "x")


def fetch_thread(*, post_id: str) -> content.ExtractedText:
    """Text of the shared post's thread: fxtwitter with retries, then vxtwitter's single post; raises if both fail."""
    try:
        return thread_text(data=_get_json_with_retries(url=FXTWITTER_THREAD_URL.format(post_id=post_id)))
    except httpx.HTTPError as error:
        _logger.warning("fxtwitter failed for post %s (%r); trying vxtwitter", post_id, error)

    return _single_post_text(data=_get_json(url=VXTWITTER_STATUS_URL.format(post_id=post_id)))


def thread_text(*, data: dict[str, Any]) -> content.ExtractedText:
    """The text of an fxtwitter `/2/thread` response: the shared post's author's posts, in thread order.

    A reply's thread also holds other authors' ancestors, which are skipped. Each post contributes its
    text, then its quoted post as `Quoting @handle: ...`, then an X Article as its title and body blocks.
    The title is the Article's, else `@handle: ` and the first 80 characters of the first post.
    """
    shared_post = data["status"]
    handle = shared_post["author"]["screen_name"]
    thread = data.get("thread") or [shared_post]
    posts = [post for post in thread if post["author"]["screen_name"] == handle] or [shared_post]

    paragraphs = [paragraph for post in posts for paragraph in _post_paragraphs(post=post)]
    first_article = posts[0].get("article")
    title = first_article["title"] if first_article else f"@{handle}: {posts[0]['text'][:TITLE_POST_LENGTH]}"
    return content.ExtractedText(title=title, text="\n\n".join(paragraphs))


def _post_paragraphs(*, post: dict[str, Any]) -> list[str]:
    paragraphs = [post["text"]]

    quote = post.get("quote")
    if quote:
        paragraphs.append(f"Quoting @{quote['author']['screen_name']}: {quote['text']}")

    article = post.get("article")
    if article:
        paragraphs.extend([article["title"], *(block["text"] for block in article["content"]["blocks"])])

    return [paragraph for paragraph in paragraphs if paragraph.strip()]


def _single_post_text(*, data: dict[str, Any]) -> content.ExtractedText:
    """Text of a vxtwitter post: its text and quoted post (vxtwitter has no unrolled thread)."""
    handle = data["user_screen_name"]
    paragraphs = [data["text"]]

    quoted = data.get("qrt")
    if quoted:
        paragraphs.append(f"Quoting @{quoted['user_screen_name']}: {quoted['text']}")

    return content.ExtractedText(
        title=f"@{handle}: {data['text'][:TITLE_POST_LENGTH]}",
        text="\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip()),
    )


def _get_json_with_retries(*, url: str) -> dict[str, Any]:
    """GET `url` up to `FETCH_TRIES` times, `RETRY_DELAY_SECONDS` apart, retrying a 404, a 5xx or a timeout."""
    for _ in range(FETCH_TRIES - 1):
        try:
            return _get_json(url=url)
        except (httpx.TimeoutException, httpx.HTTPStatusError) as error:
            if not _is_retryable(error):
                raise
            _logger.info("Retrying %s after %r", url, error)
            time.sleep(RETRY_DELAY_SECONDS)

    return _get_json(url=url)


def _is_retryable(error: httpx.TimeoutException | httpx.HTTPStatusError) -> bool:
    if isinstance(error, httpx.TimeoutException):
        return True
    status = error.response.status_code
    return status in _RETRYABLE_STATUSES or status >= 500


def _get_json(*, url: str) -> dict[str, Any]:
    response = httpx.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
    )
    response.raise_for_status()
    return response.json()
