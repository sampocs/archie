"""Search over the owner's passages: keyword (Postgres full text) and meaning (pgvector), merged by rank fusion.

`search_chunks` returns ranked passages (the chat's `search_library` tool uses them as they are); `best_per_item`
keeps each item's best passage for Library search. Only live items are searched: a deleted or merged source, a deleted
take, or a topic primer that is no longer current or whose topic was removed or merged never comes back.

Each passage carries its item's date: a source's `published_at` (else when it was saved), a topic primer version's or a
take's `created_at`. `published_after` / `published_before` keep only passages whose item date falls in those UTC days.
"""

from __future__ import annotations

import datetime
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm

from archie_db import models, vector

KEYWORD_CANDIDATES = 40
MEANING_CANDIDATES = 40
# Without a floor, meaning search returns the nearest chunks for any query, even gibberish. With text-embedding-3-small
# on real data the best hits for relevant queries measured cosine distance 0.41-0.52 and unrelated ones 0.68+.
MEANING_MAX_DISTANCE = 0.6
# Reciprocal rank fusion's damping constant: a chunk scores 1 / (RRF_K + rank) in each list it appears in.
RRF_K = 60
# Ask about this puts the item's own passages first among equals without hiding a much better match elsewhere.
ABOUT_BOOST = 1 / (RRF_K + 1)
PASSAGE_CHARACTERS = 220

# Words too common to place a passage on.
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "about",
        "did",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "on",
        "the",
        "that",
        "this",
        "to",
        "was",
        "what",
        "who",
        "why",
        "with",
    }
)
_TERM = re.compile(r"[\w']+")
# Postgres matches stems ("printing" finds "print"), so a term is located by its first letters.
_STEM_TRIM = 3
_MIN_STEM = 4

# The day an item belongs to, for the date filter and the chat's result titles.
_ITEM_DATE = "COALESCE(s.published_at, s.created_at, tp.created_at, k.created_at)"
_LIVE_CHUNKS = f"""
FROM chunks c
LEFT JOIN sources s ON s.id = c.source_id
LEFT JOIN topic_primers tp ON tp.id = c.topic_primer_id
LEFT JOIN topics t ON t.id = tp.topic_id
LEFT JOIN takes k ON k.id = c.take_id
WHERE c.user_id = :user_id
  AND (
    (c.source_id IS NOT NULL AND s.deleted_at IS NULL AND s.merged_into_id IS NULL)
    OR (c.topic_primer_id IS NOT NULL AND tp.is_current AND t.removed_at IS NULL AND t.merged_into_id IS NULL)
    OR (c.take_id IS NOT NULL AND k.deleted_at IS NULL)
  )
  AND (CAST(:published_from AS timestamptz) IS NULL OR {_ITEM_DATE} >= CAST(:published_from AS timestamptz))
  AND (CAST(:published_until AS timestamptz) IS NULL OR {_ITEM_DATE} < CAST(:published_until AS timestamptz))
"""
_COLUMNS = f"""
SELECT c.id, c.owner_kind, c.source_id, c.topic_primer_id, c.take_id, c.text, c.start_seconds,
       COALESCE(s.title, s.url, t.name, k.title) AS title, s.sender, {_ITEM_DATE} AS item_date
"""
_KEYWORD_SQL = sqlalchemy.text(
    _COLUMNS
    + _LIVE_CHUNKS
    + """
  AND c.tsv @@ websearch_to_tsquery('english', :query)
ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', :query)) DESC, c.id
LIMIT :limit
"""
)
_MEANING_SQL = sqlalchemy.text(
    _COLUMNS
    + _LIVE_CHUNKS
    + """
  AND c.embedding IS NOT NULL
  AND c.embedding <=> CAST(:embedding AS vector) <= :max_distance
ORDER BY c.embedding <=> CAST(:embedding AS vector), c.id
LIMIT :limit
"""
)


@dataclass(frozen=True)
class ItemRef:
    """A library item: a source, a topic primer (one version) or a take."""

    kind: models.SearchItemKind
    id: uuid.UUID


@dataclass(frozen=True)
class ChunkHit:
    """One ranked passage and the item it belongs to; `keyword_match` says the words matched, not only the meaning.

    `sender` is a newsletter's; `item_date` is the item's date (see the module docstring).
    """

    chunk_id: int
    item: ItemRef
    title: str
    sender: str | None
    item_date: datetime.datetime
    owner_kind: models.ChunkOwner
    text: str
    start_seconds: float | None
    score: float
    keyword_match: bool


def search_chunks(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    query: str,
    query_embedding: Sequence[float] | None,
    limit: int,
    boost: ItemRef | None = None,
    match_any: bool = False,
    published_after: datetime.date | None = None,
    published_before: datetime.date | None = None,
) -> list[ChunkHit]:
    """The user's best `limit` passages for `query`, best first; meaning search runs only with `query_embedding`.

    Meaning search keeps only passages within `MEANING_MAX_DISTANCE` of the query, so unrelated queries find nothing.

    Keyword search needs every word unless `match_any`, which needs any one (more matched words still rank higher).

    `published_after` / `published_before` (both inclusive, UTC days) keep only items dated within them.
    """
    common = {
        "user_id": user_id,
        "published_from": _start_of(published_after),
        "published_until": _start_of(published_before + datetime.timedelta(days=1) if published_before else None),
    }
    keyword_query = " or ".join(_TERM.findall(query)) if match_any else query
    keyword_rows = (
        db.execute(_KEYWORD_SQL, {**common, "query": keyword_query, "limit": KEYWORD_CANDIDATES}).all()
        if keyword_query.strip()
        else []
    )
    meaning_rows = (
        db.execute(
            _MEANING_SQL,
            {
                **common,
                "embedding": vector.to_literal(query_embedding),
                "max_distance": MEANING_MAX_DISTANCE,
                "limit": MEANING_CANDIDATES,
            },
        ).all()
        if query_embedding is not None
        else []
    )
    return _fuse(keyword_rows=keyword_rows, meaning_rows=meaning_rows, boost=boost)[:limit]


def best_per_item(hits: Sequence[ChunkHit], *, limit: int) -> list[ChunkHit]:
    """Each item once, by its best passage, keeping the order of `hits` (best first)."""
    best: dict[ItemRef, ChunkHit] = {}
    for hit in hits:
        best.setdefault(hit.item, hit)
    return list(best.values())[:limit]


def passage(text: str, *, query: str, keyword_match: bool) -> str:
    """About 220 characters of `text` around the first query term it contains, or its start for a meaning-only hit."""
    flat = " ".join(text.split())
    if len(flat) <= PASSAGE_CHARACTERS:
        return flat

    position = _first_term_position(flat, query=query) if keyword_match else None
    if position is None:
        return flat[:PASSAGE_CHARACTERS].rstrip() + "…"

    # A third of the window before the term, so the reader sees what leads into it.
    start = max(0, min(position - PASSAGE_CHARACTERS // 3, len(flat) - PASSAGE_CHARACTERS))
    end = start + PASSAGE_CHARACTERS
    snippet = flat[start:end].strip()
    return f"{'…' if start > 0 else ''}{snippet}{'…' if end < len(flat) else ''}"


def _fuse(
    *,
    keyword_rows: Sequence[sqlalchemy.Row[Any]],
    meaning_rows: Sequence[sqlalchemy.Row[Any]],
    boost: ItemRef | None,
) -> list[ChunkHit]:
    """Reciprocal rank fusion over the two candidate lists, plus the about boost; ties fall to the lower chunk id."""
    scores: dict[int, float] = {}
    rows: dict[int, sqlalchemy.Row[Any]] = {}
    for rank, row in enumerate(keyword_rows, start=1):
        scores[row.id] = scores.get(row.id, 0.0) + 1 / (RRF_K + rank)
        rows[row.id] = row
    for rank, row in enumerate(meaning_rows, start=1):
        scores[row.id] = scores.get(row.id, 0.0) + 1 / (RRF_K + rank)
        rows[row.id] = row

    keyword_ids = {row.id for row in keyword_rows}
    hits = []
    for chunk_id, row in rows.items():
        item = _item_of(row)
        score = scores[chunk_id] + (ABOUT_BOOST if item == boost else 0.0)
        hits.append(
            ChunkHit(
                chunk_id=chunk_id,
                item=item,
                title=row.title,
                sender=row.sender,
                item_date=row.item_date,
                owner_kind=models.ChunkOwner(row.owner_kind),
                text=row.text,
                start_seconds=row.start_seconds,
                score=score,
                keyword_match=chunk_id in keyword_ids,
            )
        )
    return sorted(hits, key=lambda hit: (-hit.score, hit.chunk_id))


def _start_of(day: datetime.date | None) -> datetime.datetime | None:
    return datetime.datetime.combine(day, datetime.time(), tzinfo=datetime.UTC) if day is not None else None


def _item_of(row: sqlalchemy.Row[Any]) -> ItemRef:
    if row.source_id is not None:
        return ItemRef(kind=models.SearchItemKind.SOURCE, id=row.source_id)
    if row.topic_primer_id is not None:
        return ItemRef(kind=models.SearchItemKind.TOPIC_PRIMER, id=row.topic_primer_id)
    return ItemRef(kind=models.SearchItemKind.TAKE, id=row.take_id)


def _first_term_position(text: str, *, query: str) -> int | None:
    lowered = text.lower()
    positions = []
    for term in _TERM.findall(query.lower()):
        if term in _STOP_WORDS:
            continue
        stem = term if len(term) <= _MIN_STEM else term[: max(_MIN_STEM, len(term) - _STEM_TRIM)]
        found = re.search(rf"\b{re.escape(stem)}", lowered)
        if found is not None:
            positions.append(found.start())
    return min(positions, default=None)
