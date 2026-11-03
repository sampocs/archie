"""Apply pushed actions: each exactly once, in order, under the user's write lock."""

from __future__ import annotations

import uuid
from urllib import parse

import pydantic
import sqlalchemy
from archie_db import changes, jobs, models
from sqlalchemy import exc, orm

from archie_api.sync import schemas

MAX_URL_LENGTH = 2048
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


class _AddSourcePayload(pydantic.BaseModel):
    id: uuid.UUID
    url: str
    intent: str


def apply_actions(db: orm.Session, *, user: models.User, actions: list[schemas.ActionIn]) -> list[schemas.ActionOut]:
    """Apply `actions` in order in one transaction and return one answer each.

    The advisory lock is transaction-scoped, so the whole batch must be one transaction: committing per action
    would release the lock and let another writer's positions interleave. A rejected action leaves nothing
    behind but its `applied_actions` row, because each action's writes sit in a savepoint.
    """
    changes.lock_user_writes(db, user.id)
    results = [_apply_action(db, user=user, action=action) for action in actions]
    db.commit()
    return results


def _apply_action(db: orm.Session, *, user: models.User, action: schemas.ActionIn) -> schemas.ActionOut:
    existing = db.get(models.AppliedAction, action.id)
    if existing is not None and existing.user_id == user.id:
        return schemas.ActionOut(id=action.id, result=models.ActionResult.DUPLICATE)

    # The action id is globally unique, so another user's id can't be recorded; refuse it without a row.
    if existing is not None:
        return schemas.ActionOut(id=action.id, result=models.ActionResult.REJECTED, reason="action id already used")

    try:
        with db.begin_nested():
            reason = _add_source(db, user=user, action=action)
            if reason is not None:
                _record(db, user=user, action=action, result=models.ActionResult.REJECTED, reason=reason)
                return schemas.ActionOut(id=action.id, result=models.ActionResult.REJECTED, reason=reason)

            _record(db, user=user, action=action, result=models.ActionResult.APPLIED, reason=None)
    except exc.IntegrityError:
        # Only another user inserting the same source id at the same instant gets here (the lock is per user).
        reason = "source id already exists"
        _record(db, user=user, action=action, result=models.ActionResult.REJECTED, reason=reason)
        return schemas.ActionOut(id=action.id, result=models.ActionResult.REJECTED, reason=reason)

    return schemas.ActionOut(id=action.id, result=models.ActionResult.APPLIED)


def _add_source(db: orm.Session, *, user: models.User, action: schemas.ActionIn) -> str | None:
    """Insert the source and its title job; returns the rejection reason, or None when applied."""
    try:
        payload = _AddSourcePayload.model_validate(action.payload)
    except pydantic.ValidationError:
        return "payload needs id, url and intent"

    reason = _validate_add_source(db, payload=payload)
    if reason is not None:
        return reason

    finished = payload.intent == models.SourceIntent.FINISHED
    state = models.SourceState.CONSUMED if finished else models.SourceState.QUEUED
    db.add(
        models.Source(
            id=payload.id,
            user_id=user.id,
            url=payload.url,
            kind=models.SourceKind.LINK.value,
            state=state.value,
            intent=payload.intent,
            change_seq=db.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one(),
        )
    )
    db.flush()
    jobs.enqueue(db, kind=models.JobKind.FETCH_TITLE, user_id=user.id, payload={"source_id": str(payload.id)})
    return None


def _validate_add_source(db: orm.Session, *, payload: _AddSourcePayload) -> str | None:
    """The reason this add_source can't be applied, or None."""
    if len(payload.url) > MAX_URL_LENGTH:
        return f"url is longer than {MAX_URL_LENGTH} characters"

    parts = parse.urlsplit(payload.url)
    if parts.scheme not in _ALLOWED_URL_SCHEMES or not parts.netloc:
        return "url must be http or https"

    if payload.intent not in set(models.SourceIntent):
        return "intent must be finished or queue"

    # Even the caller's own id is refused: a retry carries the same action id, so a new one is a client bug.
    if db.get(models.Source, payload.id) is not None:
        return "source id already exists"
    return None


def _record(
    db: orm.Session, *, user: models.User, action: schemas.ActionIn, result: models.ActionResult, reason: str | None
) -> None:
    db.add(models.AppliedAction(action_id=action.id, user_id=user.id, result=result.value, reason=reason))
    db.flush()
