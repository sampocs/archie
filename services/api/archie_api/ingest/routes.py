"""`POST /ingest/email`: the Cloudflare Email Worker hands over a raw email; it becomes an Inbox newsletter source."""

from __future__ import annotations

import hmac
import logging
import uuid
from typing import Annotated

import fastapi
import sqlalchemy
from archie_db import changes, models, pipeline
from archie_shared import config, urls
from sqlalchemy import orm

from archie_api import deps
from archie_api.ingest import email_message

INGEST_MAX_BYTES = 10 * 1024 * 1024
MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 500
MAX_SENDER_LENGTH = 320
UNREADABLE_EMAIL_ERROR = "Couldn't read this email."

_ACCEPTED = {"status": "accepted"}
_NEWSLETTER_URL_PREFIX = "newsletter:"

logger = logging.getLogger(__name__)
router = fastapi.APIRouter(prefix="/ingest", tags=["ingest"])


def require_ingest_secret(x_ingest_secret: Annotated[str | None, fastapi.Header()] = None) -> None:
    """401 unless the shared secret matches; an unset `INGEST_SECRET` rejects everything."""
    expected = config.get_settings().ingest_secret
    if not expected or not x_ingest_secret:
        raise _unauthorized()
    if not hmac.compare_digest(x_ingest_secret.encode(), expected.encode()):
        raise _unauthorized()


async def capped_body(request: fastapi.Request, _: Annotated[None, fastapi.Depends(require_ingest_secret)]) -> bytes:
    """The request body, refused with 413 once it exceeds `INGEST_MAX_BYTES` (declared length first, then counted)."""
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > INGEST_MAX_BYTES:
        raise _too_large()

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > INGEST_MAX_BYTES:
            raise _too_large()
    return bytes(body)


@router.post("/email", status_code=fastapi.status.HTTP_202_ACCEPTED)
def ingest_email(
    body: Annotated[bytes, fastapi.Depends(capped_body)],
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    x_ingest_to: Annotated[str, fastapi.Header()] = "",
) -> dict[str, str]:
    """Create a newsletter source for the recipient; duplicates and unknown recipients are accepted and dropped."""
    parsed = email_message.parse(body)
    recipient_local_part = email_message.local_part(x_ingest_to)

    user = find_recipient(db, local_part=recipient_local_part)
    if user is None:
        logger.info("Dropped email for unknown recipient %s", recipient_local_part)
        return _ACCEPTED

    changes.lock_user_writes(db, user.id)
    already_delivered = db.scalars(
        sqlalchemy.select(models.Source.id).where(
            models.Source.user_id == user.id, models.Source.newsletter_message_id == parsed.message_id
        )
    ).first()
    if already_delivered is not None:
        return _ACCEPTED

    _insert_newsletter(db, user=user, parsed=parsed)
    db.commit()
    return _ACCEPTED


def find_recipient(db: orm.Session, *, local_part: str) -> models.User | None:
    """The user whose ingest token is `local_part`, else the oldest user whose email the alias map names."""
    by_token = db.scalars(sqlalchemy.select(models.User).where(models.User.ingest_token == local_part)).one_or_none()
    if by_token is not None:
        return by_token

    alias_email = config.get_settings().ingest_alias_map().get(local_part)
    if alias_email is None:
        return None
    return db.scalars(
        sqlalchemy.select(models.User)
        .where(sqlalchemy.func.lower(models.User.email) == alias_email)
        .order_by(models.User.id)
        .limit(1)
    ).one_or_none()


def _insert_newsletter(db: orm.Session, *, user: models.User, parsed: email_message.ParsedEmail) -> None:
    """Add the source and its captured text, and queue fetch_content (which only has to analyze a capture)."""
    text, subject = parsed.text, parsed.subject
    web_url = parsed.web_url if parsed.web_url and len(parsed.web_url) <= MAX_URL_LENGTH else None
    url = web_url or f"{_NEWSLETTER_URL_PREFIX}{parsed.message_id}"
    readable = bool(text.strip())

    source = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        kind=models.SourceKind.NEWSLETTER.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.QUEUE.value,
        url=url,
        normalized_url=urls.normalize_url(web_url) if web_url else url,
        title=subject[:MAX_TITLE_LENGTH] if subject else None,
        sender=parsed.sender[:MAX_SENDER_LENGTH] if parsed.sender else None,
        newsletter_message_id=parsed.message_id,
        processing=(models.ProcessingStatus.PENDING if readable else models.ProcessingStatus.FAILED).value,
        processing_error=None if readable else UNREADABLE_EMAIL_ERROR,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()

    if not readable:
        return
    db.add(models.SourceCapture(source_id=source.id, title=subject, text=text))
    db.flush()
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.FETCH_CONTENT])


def _unauthorized() -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=fastapi.status.HTTP_401_UNAUTHORIZED, detail="invalid ingest secret")


def _too_large() -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=fastapi.status.HTTP_413_CONTENT_TOO_LARGE, detail="email is larger than 10 MB"
    )
