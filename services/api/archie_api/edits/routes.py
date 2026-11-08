"""Apply, undo and discard an edit Ask proposed, and restore an earlier version of anything editable.

None of these calls a model, so each runs in one transaction under the user's write lock: read, check, write. Apply
writes the proposal's `after` as the target's next version only while the target is still at the version the edit
was proposed against; otherwise the proposal goes stale and nothing is written. Undo restores that version only while
the edit's own version is still current. Repeating a finished action returns the proposal unchanged.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import fastapi
import pydantic
import sqlalchemy
from archie_db import changes, models, versions
from sqlalchemy import orm

from archie_api import deps
from archie_api.sync import schemas

NO_EDIT = "edit not found"
CHANGED_SINCE = "changed since"
ALREADY_CURRENT = "already current"
NOT_FOUND = "not found"
NO_VERSION = "version not found"

router = fastapi.APIRouter(tags=["edits"])


class RestoreRequest(pydantic.BaseModel):
    """Which version of which target to save again as the newest."""

    target_kind: models.EditTarget
    target_id: uuid.UUID
    version: int = pydantic.Field(ge=1)


class RestoreResponse(pydantic.BaseModel):
    """The target's new current version (a copy of the one restored)."""

    version: int


@router.post("/ask/edits/{proposal_id}/apply")
def apply(
    proposal_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.EditProposalOut:
    """Write the edit as the target's next version, or mark it stale when the target moved on or is gone."""
    changes.lock_user_writes(db, user.id)
    proposal = _owned_proposal(db, user=user, proposal_id=proposal_id)
    if proposal.status == models.EditStatus.APPLIED:
        return schemas.EditProposalOut.model_validate(proposal)
    _require_status(proposal, models.EditStatus.PROPOSED)

    target = _live_target(db, user=user, proposal=proposal)
    if target is None or versions.current(db, target=target).version != proposal.base_version:
        _set_status(proposal, models.EditStatus.STALE)
        return _committed(db, proposal)

    proposal.applied_version = versions.write(
        db,
        target=target,
        content=proposal.after,
        origin=models.VersionOrigin.CHAT_EDIT,
        instruction=proposal.description,
        derived_from=proposal.base_version,
    )
    _set_status(proposal, models.EditStatus.APPLIED)
    return _committed(db, proposal)


@router.post("/ask/edits/{proposal_id}/undo")
def undo(
    proposal_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.EditProposalOut:
    """Restore the version the edit was made against, while the edit's own version is still current."""
    changes.lock_user_writes(db, user.id)
    proposal = _owned_proposal(db, user=user, proposal_id=proposal_id)
    if proposal.status == models.EditStatus.UNDONE:
        return schemas.EditProposalOut.model_validate(proposal)
    _require_status(proposal, models.EditStatus.APPLIED)

    target = _live_target(db, user=user, proposal=proposal)
    if target is None or versions.current(db, target=target).version != proposal.applied_version:
        raise fastapi.HTTPException(status_code=409, detail=CHANGED_SINCE)

    restored = versions.restore(db, target=target, version=proposal.base_version, is_undo=True)
    # base_version existed when the edit was applied, so the restore cannot miss it.
    assert restored is not None
    _set_status(proposal, models.EditStatus.UNDONE)
    return _committed(db, proposal)


@router.post("/ask/edits/{proposal_id}/discard")
def discard(
    proposal_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.EditProposalOut:
    """Set a proposed edit aside for good."""
    changes.lock_user_writes(db, user.id)
    proposal = _owned_proposal(db, user=user, proposal_id=proposal_id)
    if proposal.status == models.EditStatus.DISCARDED:
        return schemas.EditProposalOut.model_validate(proposal)
    _require_status(proposal, models.EditStatus.PROPOSED)

    _set_status(proposal, models.EditStatus.DISCARDED)
    return _committed(db, proposal)


@router.post("/versions/restore")
def restore(
    body: RestoreRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> RestoreResponse:
    """Save an earlier version of a summary, primer, topic primer, take or card again as the newest one."""
    changes.lock_user_writes(db, user.id)
    target = versions.resolve(db, user_id=user.id, kind=body.target_kind, item_id=body.target_id)
    if target is None:
        raise fastapi.HTTPException(status_code=404, detail=NOT_FOUND)
    if versions.current(db, target=target).version == body.version:
        raise fastapi.HTTPException(status_code=409, detail=ALREADY_CURRENT)

    new_version = versions.restore(db, target=target, version=body.version)
    if new_version is None:
        raise fastapi.HTTPException(status_code=404, detail=NO_VERSION)
    db.commit()
    return RestoreResponse(version=new_version)


def _owned_proposal(db: orm.Session, *, user: models.User, proposal_id: uuid.UUID) -> models.EditProposal:
    """The user's proposal in a live chat, or 404."""
    proposal = db.get(models.EditProposal, proposal_id)
    conversation = db.get(models.Conversation, proposal.conversation_id) if proposal is not None else None
    if proposal is None or proposal.user_id != user.id or conversation is None or conversation.deleted_at is not None:
        raise fastapi.HTTPException(status_code=404, detail=NO_EDIT)
    return proposal


def _require_status(proposal: models.EditProposal, status: models.EditStatus) -> None:
    if proposal.status != status:
        raise fastapi.HTTPException(status_code=409, detail=f"edit is {proposal.status}")


def _live_target(db: orm.Session, *, user: models.User, proposal: models.EditProposal) -> versions.Target | None:
    return versions.resolve(
        db, user_id=user.id, kind=models.EditTarget(proposal.target_kind), item_id=proposal.target_id
    )


def _set_status(proposal: models.EditProposal, status: models.EditStatus) -> None:
    """Change the status with a fresh position, so phones pull the new state."""
    proposal.status = status.value
    proposal.updated_at = sqlalchemy.func.now()
    proposal.change_seq = changes.next_change_seq()


def _committed(db: orm.Session, proposal: models.EditProposal) -> schemas.EditProposalOut:
    db.commit()
    db.refresh(proposal)
    return schemas.EditProposalOut.model_validate(proposal)
