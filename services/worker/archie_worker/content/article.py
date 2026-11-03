"""Article text: cleaning a Safari capture and extracting the main text from a fetched page."""

from __future__ import annotations

import collections
import re

import trafilatura

from archie_worker import content
from archie_worker.handlers import fetch_title

MAX_TEXT_LENGTH = 200_000

# Shorter lines (headings, "Yes", "Share") legitimately repeat; only long ones are page chrome or captions.
_MIN_REPEATED_LINE_LENGTH = 20
_MAX_LINE_REPEATS = 2
_BLANK_RUNS = re.compile(r"\n{3,}")


def clean_capture(text: str) -> str:
    """Normalize a Safari `innerText` capture: tidy whitespace, drop over-repeated lines, cap the length.

    `innerText` repeats captions and share bars, so a line of 20+ characters is kept for its first two
    occurrences only. Three or more blank lines collapse to one blank line.
    """
    lines = (" ".join(line.split()) for line in text.splitlines())

    seen: collections.Counter[str] = collections.Counter()
    kept: list[str] = []
    for line in lines:
        seen[line] += 1
        if len(line) >= _MIN_REPEATED_LINE_LENGTH and seen[line] > _MAX_LINE_REPEATS:
            continue
        kept.append(line)

    collapsed = _BLANK_RUNS.sub("\n\n", "\n".join(kept)).strip()
    return collapsed[:MAX_TEXT_LENGTH]


def extract(*, html: str, url: str) -> content.ExtractedText | None:
    """The page's main text and title, or None when trafilatura finds no main text.

    The title falls back to the og:title / <title> reader used for `fetch_title`.
    """
    text = trafilatura.extract(html, url=url, output_format="txt", include_comments=False)
    if not text:
        return None

    metadata = trafilatura.extract_metadata(html, default_url=url)
    title = (metadata.title if metadata is not None else None) or fetch_title.extract_title(page=html)
    return content.ExtractedText(title=title, text=text[:MAX_TEXT_LENGTH])
