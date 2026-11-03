"""Turning a source's page, capture or post into the plain text the pipeline reads."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedText:
    """A source's readable text and, when one was found, its title."""

    title: str | None
    text: str
