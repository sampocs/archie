"""Books: looking a book up for the + sheet and the share sheet, and the one-off import of the owner's book notes."""

from __future__ import annotations

import re
import uuid
from typing import Annotated

import fastapi
import pydantic
import sqlalchemy
from archie_db import card_rows, changes, jobs, models, pipeline
from archie_shared import urls
from sqlalchemy import orm

from archie_api import deps
from archie_api.books import lookup
from archie_api.notes import routes as notes_routes
from archie_api.sync import book_actions, capture

BOOK_URL_PREFIX = "book:"
MAX_QUERY_LENGTH = 500
MAX_BOOKS_PER_IMPORT = 10
MAX_CARDS_PER_BOOK = 40
NO_BOOK_FOUND = "No book found"
LOOKUP_UNAVAILABLE = "Couldn't reach the book lookup"
# The kinds a hand-tuned book card may be: the ones the book cards writer makes.
IMPORTED_CARD_KINDS = frozenset({models.CardKind.CONCEPT, models.CardKind.MECHANISM, models.CardKind.NUMBER})

_NON_SLUG_CHARACTERS = re.compile(r"[^a-z0-9]+")

router = fastapi.APIRouter(prefix="/books", tags=["books"])


class LookupRequest(pydantic.BaseModel):
    """A book title, or a Goodreads book link."""

    query: str = pydantic.Field(min_length=1, max_length=MAX_QUERY_LENGTH)


class BookOut(pydantic.BaseModel):
    """The book a lookup found, for the owner to confirm."""

    title: str
    author: str | None
    year: int | None
    cover_url: str | None
    url: str


class ImportCardIn(pydantic.BaseModel):
    """One hand-tuned card, released into reviews at `available_at`."""

    kind: models.CardKind
    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)
    detail: list[str] = pydantic.Field(default_factory=list, max_length=card_rows.MAX_DETAIL_LINES)
    available_at: pydantic.AwareDatetime

    @pydantic.field_validator("kind")
    @classmethod
    def _writer_kind(cls, kind: models.CardKind) -> models.CardKind:
        if kind not in IMPORTED_CARD_KINDS:
            raise ValueError("kind must be concept, mechanism or number")
        return kind


class BookImportIn(pydantic.BaseModel):
    """One finished book with the owner's notes and cards; `url` and `image_url` come from a lookup when it matched."""

    title: str = pydantic.Field(min_length=1, max_length=book_actions.MAX_TITLE_LENGTH)
    author: str | None = pydantic.Field(default=None, max_length=book_actions.MAX_AUTHOR_LENGTH)
    url: str | None = None
    image_url: str | None = None
    notes_markdown: str = pydantic.Field(max_length=notes_routes.MAX_NOTE_MARKDOWN_LENGTH)
    cards: list[ImportCardIn] = pydantic.Field(default_factory=list, max_length=MAX_CARDS_PER_BOOK)

    @pydantic.field_validator("url", "image_url")
    @classmethod
    def _http_url(cls, url: str | None) -> str | None:
        reason = capture.validate_url(url) if url is not None else None
        if reason is not None:
            raise ValueError(reason)
        return url


class BookImportRequest(pydantic.BaseModel):
    """A batch of books."""

    books: list[BookImportIn] = pydantic.Field(min_length=1, max_length=MAX_BOOKS_PER_IMPORT)


class BookImportResponse(pydantic.BaseModel):
    """The ids of the books created, and the titles of those already imported (left as they were)."""

    created: list[uuid.UUID]
    skipped: list[str]


@router.post("/lookup")
def lookup_book(request: LookupRequest, user: Annotated[models.User, fastapi.Depends(deps.current_user)]) -> BookOut:
    """The book a title or Goodreads link names; 404 when there is none, 502 when the lookup can't be reached."""
    try:
        match = lookup.find_book(request.query)
    except lookup.BookNotFoundError:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=NO_BOOK_FOUND) from None
    except lookup.LookupUnavailableError:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_502_BAD_GATEWAY, detail=LOOKUP_UNAVAILABLE
        ) from None

    return BookOut(title=match.title, author=match.author, year=match.year, cover_url=match.cover_url, url=match.url)


@router.post("/import")
def import_books(
    request: BookImportRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> BookImportResponse:
    """Add finished books with their notes and hand-tuned cards, and queue their refreshers a minute apart.

    A book whose URL the user already has is skipped. Spends the owner's model keys, so only a whitelisted user may.
    """
    if not user.is_whitelisted:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail=deps.NEEDS_OWN_KEY)
    changes.lock_user_writes(db, user.id)

    created: list[models.Source] = []
    skipped: list[str] = []
    for book in request.books:
        url = book.url or f"{BOOK_URL_PREFIX}{_slug(book.title)}"
        normalized_url = urls.normalize_url(url) if book.url else url
        if _has_book(db, user=user, normalized_url=normalized_url):
            skipped.append(book.title)
            continue
        created.append(_create_book(db, user=user, book=book, url=url, normalized_url=normalized_url))

    # Spaced as note write-ups are, so a batch doesn't burst the model's rate limit.
    for index, source in enumerate(created):
        jobs.enqueue(
            db,
            kind=models.JobKind.WRITE_BOOK,
            user_id=user.id,
            payload={pipeline.SOURCE_ID_KEY: str(source.id)},
            max_attempts=pipeline.MAX_ATTEMPTS[models.JobKind.WRITE_BOOK],
            delay=notes_routes.WRITE_UP_SPACING * index,
        )

    db.commit()
    return BookImportResponse(created=[source.id for source in created], skipped=skipped)


def _slug(title: str) -> str:
    return _NON_SLUG_CHARACTERS.sub("-", title.lower()).strip("-")


def _has_book(db: orm.Session, *, user: models.User, normalized_url: str) -> bool:
    exists = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Source.user_id == user.id,
                models.Source.kind == models.SourceKind.BOOK.value,
                models.Source.normalized_url == normalized_url,
                models.Source.deleted_at.is_(None),
            )
        )
    )
    return bool(exists)


def _create_book(
    db: orm.Session, *, user: models.User, book: BookImportIn, url: str, normalized_url: str
) -> models.Source:
    """A finished book holding the notes, with its cards; processing until its refresher lands."""
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url=url,
        normalized_url=normalized_url,
        title=book.title,
        author=book.author,
        image_url=book.image_url,
        kind=models.SourceKind.BOOK.value,
        state=models.SourceState.CONSUMED.value,
        intent=models.SourceIntent.FINISHED.value,
        processing=models.ProcessingStatus.PROCESSING.value,
        note_markdown=book.notes_markdown,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()

    for card in book.cards:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=user.id,
                source_id=source.id,
                kind=card.kind.value,
                question=card.question.strip(),
                answer=card.answer.strip(),
                detail=card_rows.joined_detail(card.detail),
                available_at=card.available_at,
                change_seq=changes.next_change_seq(),
            )
        )
    db.flush()
    return source
