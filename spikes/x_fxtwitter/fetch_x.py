# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Spike: what does fxtwitter return for each kind of X share URL?

Run: uv run spikes/x_fxtwitter/fetch_x.py   (add --refresh to ignore the cache)
Raw JSON lands in spikes/x_fxtwitter/.cache/; a summary table prints at the end.
"""

import dataclasses
import json
import pathlib
import re
import sys
import time
from enum import StrEnum

import httpx

CACHE_DIR = pathlib.Path(__file__).parent / ".cache"
FX_BASE = "https://api.fxtwitter.com"
VX_BASE = "https://api.vxtwitter.com"
MAX_WALK_STEPS = 30
RETRIES = 3
STATUS_URL_PATTERN = re.compile(r"(?:x|twitter)\.com/(?P<handle>\w+)/(?:status|article)/(?P<post_id>\d+)")


class Kind(StrEnum):
    PLAIN = "plain"
    LONG = "long post"
    LONG_QUOTE = "long post + quote"
    THREAD_SHORT = "thread (3)"
    THREAD_MEDIUM = "thread (6)"
    THREAD_LONG = "thread (14)"
    QUOTE = "quote"
    MEDIA = "media"
    ARTICLE = "article"
    DEEP_REPLY = "reply"


@dataclasses.dataclass
class Sample:
    kind: Kind
    url: str
    note: str = ""


# Real public URLs found via web search + fxtwitter's own profile/search endpoints (Oct 2026).
SAMPLES = [
    Sample(Kind.PLAIN, "https://x.com/hwchase17/status/2116279214731395453?s=12"),
    Sample(Kind.LONG, "https://x.com/packyM/status/2115928664479310208?s=12"),
    Sample(Kind.LONG_QUOTE, "https://x.com/hwchase17/status/2116622802031710709?s=12"),
    Sample(Kind.THREAD_SHORT, "https://x.com/sama/status/2107691261776052633?s=12", "share the FIRST post"),
    Sample(Kind.THREAD_SHORT, "https://x.com/sama/status/2107691577015755196?s=12", "share the LAST post"),
    Sample(Kind.THREAD_MEDIUM, "https://x.com/levelsio/status/2116542410658324495?s=12"),
    Sample(Kind.THREAD_LONG, "https://x.com/rubenhassid/status/1931389580105925115?s=12", "Jun 2025, 14 posts"),
    Sample(Kind.QUOTE, "https://x.com/hwchase17/status/2116230499140251964?s=12"),
    Sample(Kind.MEDIA, "https://x.com/shcallaway/status/2116221631349850131?s=12", "image; turns out to head a 13-post thread"),
    Sample(Kind.ARTICLE, "https://x.com/hwchase17/status/2116553654857867330?s=12"),
    Sample(Kind.ARTICLE, "https://x.com/usetapestry/article/2033603974675227095", "article-only post, empty text, /article/ URL"),
    Sample(Kind.DEEP_REPLY, "https://x.com/packyM/status/2116232895308202061?s=12", "3 deep, 2 authors"),
    Sample(Kind.DEEP_REPLY, "https://x.com/hwchase17/status/2116576419010785421?s=12", "3 deep, 2 authors"),
]


@dataclasses.dataclass
class Summary:
    kind: Kind
    url: str
    http_status: int
    text_chars: int
    is_note_tweet: bool
    has_quote: bool
    quote_chars: int
    media_count: int
    has_article: bool
    article_chars: int
    thread_http_status: int
    thread_posts: int
    thread_chars: int
    replying_to_walk_posts: int
    vx_http_status: int
    vx_text_chars: int
    vx_reply_to_id: str | None


def parse_status_url(url: str) -> tuple[str, str]:
    match = STATUS_URL_PATTERN.search(url)
    if not match:
        raise ValueError(f"not a status URL: {url}")
    return match["handle"], match["post_id"]


def cached_get(client: httpx.Client, *, cache_name: str, url: str, refresh: bool) -> tuple[int, dict]:
    """GET with an on-disk cache; fxtwitter 404s transiently, so retry before giving up."""
    cache_path = CACHE_DIR / f"{cache_name}.json"
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text())
        return cached["http_status"], cached["body"]

    response = None
    for _ in range(RETRIES):
        try:
            response = client.get(url)
        except httpx.TransportError:
            time.sleep(1)
            continue
        if response.status_code == 200:
            break
        time.sleep(1)
    if response is None:
        return 0, {}

    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    cache_path.write_text(json.dumps({"http_status": response.status_code, "body": body}, indent=2))
    return response.status_code, body


def article_char_count(article: dict | None) -> int:
    if not article:
        return 0
    return sum(len(block.get("text", "")) for block in article.get("content", {}).get("blocks", []))


def count_replying_to_walk(client: httpx.Client, *, post: dict, refresh: bool) -> int:
    """Follow replying_to upward one /2/status call at a time; returns posts visited incl. the start."""
    visited = 1
    current = post
    while visited < MAX_WALK_STEPS:
        parent = current.get("replying_to")
        if not parent:
            return visited
        http_status, body = cached_get(
            client, cache_name=f"walk_{parent['status']}", url=f"{FX_BASE}/2/status/{parent['status']}", refresh=refresh
        )
        if http_status != 200:
            return visited
        current = body["status"]
        visited += 1
    return visited


def summarize(client: httpx.Client, sample: Sample, *, refresh: bool) -> Summary:
    handle, post_id = parse_status_url(sample.url)

    status_code, status_body = cached_get(
        client, cache_name=f"status_{post_id}", url=f"{FX_BASE}/2/status/{post_id}", refresh=refresh
    )
    thread_code, thread_body = cached_get(
        client, cache_name=f"thread_{post_id}", url=f"{FX_BASE}/2/thread/{post_id}", refresh=refresh
    )
    vx_code, vx_body = cached_get(
        client, cache_name=f"vx_{post_id}", url=f"{VX_BASE}/{handle}/status/{post_id}", refresh=refresh
    )

    post = status_body.get("status") or {}
    quote = post.get("quote") or {}
    thread = thread_body.get("thread") or []
    article = post.get("article")

    return Summary(
        kind=sample.kind,
        url=sample.url,
        http_status=status_code,
        text_chars=len(post.get("text", "")),
        is_note_tweet=bool(post.get("is_note_tweet")),
        has_quote=bool(quote),
        quote_chars=len(quote.get("text", "")),
        media_count=len((post.get("media") or {}).get("all", [])),
        has_article=bool(article),
        article_chars=article_char_count(article),
        thread_http_status=thread_code,
        thread_posts=len(thread),
        thread_chars=sum(len(item.get("text", "")) for item in thread),
        replying_to_walk_posts=count_replying_to_walk(client, post=post, refresh=refresh) if post else 0,
        vx_http_status=vx_code,
        vx_text_chars=len(vx_body.get("text", "")),
        vx_reply_to_id=vx_body.get("replyingToID"),
    )


def main() -> None:
    refresh = "--refresh" in sys.argv
    CACHE_DIR.mkdir(exist_ok=True)

    with httpx.Client(timeout=30, headers={"User-Agent": "archie-spike/0.1"}) as client:
        summaries = [summarize(client, sample, refresh=refresh) for sample in SAMPLES]

    for summary in summaries:
        print(json.dumps(dataclasses.asdict(summary), default=str))


if __name__ == "__main__":
    main()
