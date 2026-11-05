"""The newsletter brief's action: Done. Returns a reason or None.

The caller holds the user's write lock; every check runs before the first write (see `actions.apply_actions`).
"""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import briefs, changes, models
from sqlalchemy import orm

from archie_api.sync import rows

NO_BRIEF = "brief not found"
NOT_OPEN = "brief is not open"
# Only guards the payload size; a brief can cover a long backlog of newsletters.
MAX_FINISHED_SOURCE_IDS = 5000


class _FinishBriefPayload(pydantic.BaseModel):
    id: uuid.UUID
    # The newsletters the phone showed in the brief; a rewrite that landed after it was drawn may cover more.
    source_ids: list[uuid.UUID] = pydantic.Field(max_length=MAX_FINISHED_SOURCE_IDS)


def finish_brief(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Close the open brief and mark the newsletters the phone showed in it briefed, if they are still in the inbox.

    Only the given ids are marked, so Done never briefs a newsletter the user hasn't seen; ids that aren't the user's
    inbox newsletters (queued, consumed, deleted or another user's) are ignored. When the brief covered newsletters
    the phone didn't show, or unbriefed ones are waiting, the next brief's rewrite is queued so it holds just those.
    """
    parsed = rows.parse(_FinishBriefPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    brief = db.get(models.Brief, parsed.id)
    if brief is None or brief.user_id != user.id:
        return NO_BRIEF
    if brief.status != models.BriefStatus.OPEN:
        return NOT_OPEN

    _mark_briefed(db, user=user, source_ids=parsed.source_ids)
    brief.status = models.BriefStatus.DONE.value
    brief.done_at = sqlalchemy.func.now()
    brief.updated_at = sqlalchemy.func.now()
    brief.change_seq = changes.next_change_seq()

    has_unshown = bool(set(brief.source_ids) - set(parsed.source_ids))
    if has_unshown or briefs.covered_newsletters(db, user_id=user.id):
        briefs.enqueue_update(db, user_id=user.id)
    return None


def _mark_briefed(db: orm.Session, *, user: models.User, source_ids: list[uuid.UUID]) -> None:
    covered_in_inbox = db.scalars(
        sqlalchemy.select(models.Source).where(
            models.Source.id.in_(source_ids),
            models.Source.user_id == user.id,
            models.Source.kind == models.SourceKind.NEWSLETTER.value,
            models.Source.state == models.SourceState.INBOX.value,
            models.Source.deleted_at.is_(None),
        )
    )
    for source in covered_in_inbox:
        source.state = models.SourceState.BRIEFED.value
        changes.touch(source)
