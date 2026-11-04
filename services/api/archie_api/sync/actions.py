"""Apply pushed actions: each exactly once, in order, under the user's write lock."""

from __future__ import annotations

from typing import Protocol

from archie_db import changes, models
from sqlalchemy import exc, orm

from archie_api.sync import capture, schemas, source_actions

_ACTION_ID_USED = "action id already used"
NOT_SUPPORTED = "action not supported yet"


class ActionHandler(Protocol):
    """One action type's handler: returns the rejection reason, or None when applied (validate before writing)."""

    def __call__(self, db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
        """Apply the action for `user`, or return why it is rejected."""
        ...


# Each action type's handler; later work registers its types here.
HANDLERS: dict[schemas.ActionType, ActionHandler] = {
    schemas.ActionType.ADD_SOURCE: capture.add_source,
    schemas.ActionType.RETRY_SOURCE: capture.retry_source,
    schemas.ActionType.FINISH_SOURCE: source_actions.finish_source,
    schemas.ActionType.SET_PREP_ME: source_actions.set_prep_me,
    schemas.ActionType.SET_READ: source_actions.set_read,
    schemas.ActionType.SET_PRIMER_OPENED: source_actions.set_primer_opened,
    schemas.ActionType.SNOOZE: source_actions.snooze,
    schemas.ActionType.SET_QUEUE_POSITION: source_actions.set_queue_position,
    schemas.ActionType.GO_DEEPER: source_actions.go_deeper,
    schemas.ActionType.READ_LATER: source_actions.read_later,
    schemas.ActionType.DELETE_SOURCE: source_actions.delete_source,
}


def apply_actions(db: orm.Session, *, user: models.User, actions: list[schemas.ActionIn]) -> list[schemas.ActionOut]:
    """Apply `actions` in order in one transaction and return one answer each.

    The advisory lock is transaction-scoped, so the whole batch must be one transaction: committing per action
    would release the lock and let another writer's positions interleave. A rejected action leaves nothing
    behind but its `applied_actions` row, because each action's writes sit in a savepoint. Handlers must validate
    everything before their first write: a handler that returns a reason does not undo what it already wrote.
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
        return schemas.ActionOut(id=action.id, result=models.ActionResult.REJECTED, reason=_ACTION_ID_USED)

    try:
        with db.begin_nested():
            reason = _dispatch(db, user=user, action=action)
            if reason is not None:
                _record(db, user=user, action=action, result=models.ActionResult.REJECTED, reason=reason)
                return schemas.ActionOut(id=action.id, result=models.ActionResult.REJECTED, reason=reason)

            _record(db, user=user, action=action, result=models.ActionResult.APPLIED, reason=None)
    except exc.IntegrityError:
        # The lock is per user, so another user racing us on a unique key gets here: the same source or topic id,
        # or the same (globally unique) action id. In the action-id case the winner owns the row, so we record nothing.
        if db.get(models.AppliedAction, action.id) is not None:
            return schemas.ActionOut(id=action.id, result=models.ActionResult.REJECTED, reason=_ACTION_ID_USED)

        reason = "source id already exists" if action.type == schemas.ActionType.ADD_SOURCE else "id already exists"
        _record(db, user=user, action=action, result=models.ActionResult.REJECTED, reason=reason)
        return schemas.ActionOut(id=action.id, result=models.ActionResult.REJECTED, reason=reason)

    return schemas.ActionOut(id=action.id, result=models.ActionResult.APPLIED)


def _dispatch(db: orm.Session, *, user: models.User, action: schemas.ActionIn) -> str | None:
    """Run the action's handler; returns the rejection reason, or None when applied."""
    handler = HANDLERS.get(action.type)
    if handler is None:
        return NOT_SUPPORTED
    return handler(db, user=user, payload=action.payload)


def _record(
    db: orm.Session, *, user: models.User, action: schemas.ActionIn, result: models.ActionResult, reason: str | None
) -> None:
    db.add(models.AppliedAction(action_id=action.id, user_id=user.id, result=result.value, reason=reason))
    db.flush()
