"""Apply pushed actions: each exactly once, in order, under the user's write lock."""

from __future__ import annotations

from typing import Protocol

from archie_db import changes, models
from sqlalchemy import exc, orm

from archie_api.sync import (
    brief_actions,
    capture,
    collection_actions,
    episodes,
    review_actions,
    schemas,
    source_actions,
    topic_actions,
)

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
    schemas.ActionType.QUEUE_PRIMER: source_actions.queue_primer,
    schemas.ActionType.REQUEST_PRIMER: source_actions.request_primer,
    schemas.ActionType.RETURN_TO_INBOX: source_actions.return_to_inbox,
    schemas.ActionType.SET_READ: source_actions.set_read,
    schemas.ActionType.SET_PRIMER_OPENED: source_actions.set_primer_opened,
    schemas.ActionType.SNOOZE: source_actions.snooze,
    schemas.ActionType.SET_QUEUE_POSITION: source_actions.set_queue_position,
    schemas.ActionType.GO_DEEPER: source_actions.go_deeper,
    schemas.ActionType.READ_LATER: source_actions.read_later,
    schemas.ActionType.DELETE_SOURCE: source_actions.delete_source,
    schemas.ActionType.SET_PREP_ME: source_actions.set_prep_me,
    schemas.ActionType.SET_FAVORITE: source_actions.set_favorite,
    schemas.ActionType.CHOOSE_EPISODE: episodes.choose_episode,
    schemas.ActionType.ADD_TOPIC: topic_actions.add_topic,
    schemas.ActionType.RENAME_TOPIC: topic_actions.rename_topic,
    schemas.ActionType.MERGE_TOPIC: topic_actions.merge_topic,
    schemas.ActionType.REMOVE_TOPIC: topic_actions.remove_topic,
    schemas.ActionType.RESTORE_TOPIC: topic_actions.restore_topic,
    schemas.ActionType.REQUEST_TOPIC_PRIMER: topic_actions.request_topic_primer,
    schemas.ActionType.SET_SOURCE_TOPIC: topic_actions.set_source_topic,
    schemas.ActionType.CHOOSE_TOPICS: topic_actions.choose_topics,
    schemas.ActionType.FINISH_BRIEF: brief_actions.finish_brief,
    # Review
    schemas.ActionType.REVIEW_CARD: review_actions.review_card,
    schemas.ActionType.DROP_CARD: review_actions.drop_card,
    schemas.ActionType.SET_CARDS_OFF: review_actions.set_cards_off,
    schemas.ActionType.REQUEST_NEWS_QUIZ: review_actions.request_news_quiz,
    # Collections
    schemas.ActionType.CREATE_COLLECTION: collection_actions.create_collection,
    schemas.ActionType.UPDATE_COLLECTION: collection_actions.update_collection,
    schemas.ActionType.ADD_COLLECTION_ITEM: collection_actions.add_collection_item,
    schemas.ActionType.UPDATE_COLLECTION_ITEM: collection_actions.update_collection_item,
}


def apply_actions(db: orm.Session, *, user: models.User, actions: list[schemas.ActionIn]) -> list[schemas.ActionOut]:
    """Apply `actions` in order in one transaction and return one answer each.

    The advisory lock is transaction-scoped, so the whole batch must be one transaction: committing per action
    would release the lock and let another writer's positions interleave. A rejected action leaves nothing
    behind but its `applied_actions` row, because each action's writes sit in a savepoint. Handlers must validate
    everything before their first write: a handler that returns a reason does not undo what it already wrote.
    """
    changes.lock_user_writes(db, user.id)

    # `user` was loaded before the lock, so a concurrent batch may have set this since; re-read it once here (not in
    # the handler, where a refresh would overwrite this batch's own pending `func.now()`).
    db.refresh(user, attribute_names=["topics_chosen_at"])
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
