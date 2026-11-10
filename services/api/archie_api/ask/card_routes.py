"""Save or discard a card set Ask proposed: Save turns it into the chat's Library item and its review cards, or, in a
chat about a note, into the note's review cards.

Neither calls a model, so each runs in one transaction under the user's write lock. One chat has at most one live
item (kind `chat`, tied by `chat_conversation_id`): the first Save creates it, later ones update it. The item's primer
is the cheat sheet, its summary a gist of it, and its text the chat's transcript; it is ready at once and never goes
through the queue or the analyze/primer pipeline. Its cards are the kept ones: a Save in a chat that already saved
keeps an identical live card (and its review progress), adds the new ones, and retires the rest that were never
reviewed; a reviewed card is never retired, so the owner's review progress survives a reworded or dropped card.
A note's set follows the same card rules on the note itself: no chat item is made and nothing is written but cards.
Only cards saved from that chat can be retired there: the worker's cards and ones saved from another chat stay.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

import fastapi
import pydantic
import sqlalchemy
from archie_db import card_rows, changes, jobs, models, pipeline, versions
from sqlalchemy import orm

from archie_api import deps
from archie_api.ask import card_set_tools
from archie_api.sync import schemas

NO_CARD_SET = "card set not found"
NO_NOTE = "note not found"
CHAT_URL_PREFIX = "chat:"
MAX_GIST_CHARACTERS = 300
_SPEAKERS = {models.MessageRole.USER: "You", models.MessageRole.ASSISTANT: "Archie"}
# Markdown blocks that aren't prose: a heading, a table, a code fence, a rule, a quote or a list.
_NON_PROSE_STARTS = ("#", "|", "```", "---", "***", ">", "- ", "* ", "+ ")
_NUMBERED_START = re.compile(r"^\d+\.\s")

router = fastapi.APIRouter(prefix="/ask", tags=["ask"])


class SaveRequest(pydantic.BaseModel):
    """The indices of the proposal's cards the owner kept: at least one, each once."""

    kept: list[int] = pydantic.Field(min_length=1)

    @pydantic.field_validator("kept")
    @classmethod
    def _unique(cls, kept: list[int]) -> list[int]:
        if len(set(kept)) != len(kept):
            raise ValueError("an index appears more than once")
        return kept


@dataclass(frozen=True)
class TranscriptLine:
    """One message of the chat, as the transcript shows it."""

    role: models.MessageRole
    text: str


@router.post("/card-sets/{proposal_id}/save")
def save(
    proposal_id: uuid.UUID,
    body: SaveRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.CardSetProposalOut:
    """Write the card set to the chat's item (created on the first Save), or to the note the chat is about, with the
    kept cards; 409 unless open, 404 when the note is gone."""
    changes.lock_user_writes(db, user.id)
    proposal = _open_proposal(db, user=user, proposal_id=proposal_id)
    if any(index < 0 or index >= len(proposal.cards) for index in body.kept):
        raise fastapi.HTTPException(status_code=422, detail="a kept index is out of range")

    item = _about_note(db, proposal=proposal) or _written_chat_item(db, user=user, proposal=proposal)
    _keep_cards(db, item=item, proposal=proposal, kept=body.kept)

    proposal.saved_source_id = item.id
    proposal.kept = sorted(body.kept)
    _set_status(proposal, models.CardSetStatus.SAVED)
    return _committed(db, proposal)


@router.post("/card-sets/{proposal_id}/discard")
def discard(
    proposal_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.CardSetProposalOut:
    """Set an open card set aside for good; 409 unless open."""
    changes.lock_user_writes(db, user.id)
    proposal = _open_proposal(db, user=user, proposal_id=proposal_id)

    _set_status(proposal, models.CardSetStatus.DISCARDED)
    return _committed(db, proposal)


def transcript(lines: Sequence[TranscriptLine]) -> str:
    """The chat as markdown: each message as `**You:** …` or `**Archie:** …`, a blank line between them."""
    return "\n\n".join(f"**{_SPEAKERS[line.role]}:** {line.text.strip()}" for line in lines if line.text.strip())


def gist_of(cheat_sheet: str, *, title: str) -> str:
    """The cheat sheet's first prose paragraph on one line, cut at a word to `MAX_GIST_CHARACTERS`; else the title."""
    blocks = (block.strip() for block in cheat_sheet.split("\n\n"))
    prose = (block for block in blocks if block and not _is_non_prose(block))
    paragraph = next(prose, title)
    text = " ".join(paragraph.split())
    if len(text) <= MAX_GIST_CHARACTERS:
        return text
    cut = text[: MAX_GIST_CHARACTERS - 1].rsplit(" ", 1)[0]
    return f"{cut}…"


def _is_non_prose(block: str) -> bool:
    return block.startswith(_NON_PROSE_STARTS) or bool(_NUMBERED_START.match(block))


def _open_proposal(db: orm.Session, *, user: models.User, proposal_id: uuid.UUID) -> models.CardSetProposal:
    """The user's still-open card set in a live chat: 404 when it isn't theirs or the chat is gone, 409 when decided."""
    proposal = db.get(models.CardSetProposal, proposal_id)
    conversation = db.get(models.Conversation, proposal.conversation_id) if proposal is not None else None
    if proposal is None or proposal.user_id != user.id or conversation is None or conversation.deleted_at is not None:
        raise fastapi.HTTPException(status_code=404, detail=NO_CARD_SET)
    if proposal.status != models.CardSetStatus.PROPOSED:
        raise fastapi.HTTPException(status_code=409, detail=f"card set is {proposal.status}")
    return proposal


def _about_note(db: orm.Session, *, proposal: models.CardSetProposal) -> models.Source | None:
    """The note the chat is about, cards turned back on, or None for any other chat; a deleted note is a 404."""
    conversation = db.get_one(models.Conversation, proposal.conversation_id)
    source = db.get(models.Source, conversation.about_source_id) if conversation.about_source_id is not None else None
    if source is None or source.kind != models.SourceKind.NOTE:
        return None
    if source.deleted_at is not None:
        raise fastapi.HTTPException(status_code=404, detail=NO_NOTE)

    # Saving is the owner asking for these cards, as for a chat item.
    source.cards_off = False
    changes.touch(source)
    return source


def _written_chat_item(db: orm.Session, *, user: models.User, proposal: models.CardSetProposal) -> models.Source:
    """The chat's item with the set's cheat sheet, gist and transcript written to it."""
    item, existed = _chat_item(db, user=user, proposal=proposal)
    _write_artifacts(db, item=item, proposal=proposal, existed=existed)
    return item


def _chat_item(db: orm.Session, *, user: models.User, proposal: models.CardSetProposal) -> tuple[models.Source, bool]:
    """The chat's live item, retitled, or a new one; and whether it already existed."""
    existing = db.scalars(
        sqlalchemy.select(models.Source).where(
            models.Source.user_id == user.id, models.Source.chat_conversation_id == proposal.conversation_id
        )
    ).one_or_none()

    # Saving is the owner asking for these cards, so it turns cards back on for an item they had turned off.
    if existing is not None and existing.deleted_at is None:
        existing.title = proposal.title
        existing.cards_off = False
        changes.touch(existing)
        return existing, True

    # The owner deleted the chat's item: it stays deleted, and frees the chat for a new one.
    if existing is not None:
        existing.chat_conversation_id = None
        changes.touch(existing)
        db.flush()

    url = f"{CHAT_URL_PREFIX}{proposal.conversation_id}"
    item = models.Source(
        id=uuid.uuid4(),
        user_id=user.id,
        url=url,
        normalized_url=url,
        title=proposal.title,
        kind=models.SourceKind.CHAT.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.FINISHED.value,
        processing=models.ProcessingStatus.READY.value,
        chat_conversation_id=proposal.conversation_id,
        change_seq=changes.next_change_seq(),
    )
    db.add(item)
    db.flush()
    return item, False


def _write_artifacts(db: orm.Session, *, item: models.Source, proposal: models.CardSetProposal, existed: bool) -> None:
    """The cheat sheet as the primer, its gist as the summary and the chat as the text, then queue it for search."""
    # An update is the owner choosing the new set in the chat, so it becomes current even over a version they edited
    # (`hands_back`), without being labelled as one of their chat edits.
    summary = {"gist": gist_of(proposal.cheat_sheet, title=proposal.title), "key_ideas": [], "numbers": []}
    contents: dict[models.ArtifactKind, dict[str, Any]] = {
        models.ArtifactKind.PRIMER: {"markdown": proposal.cheat_sheet},
        models.ArtifactKind.SUMMARY: {"summary": summary},
        models.ArtifactKind.TEXT: {"text": transcript(_transcript_lines(db, conversation_id=proposal.conversation_id))},
    }
    for kind, content in contents.items():
        pipeline.write_artifact(
            db, source=item, kind=kind, content=content, model=None, prompt_version=None, hands_back=existed
        )
    jobs.enqueue_embed(db, user_id=item.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=item.id)


def _transcript_lines(db: orm.Session, *, conversation_id: uuid.UUID) -> list[TranscriptLine]:
    """The chat's complete messages, oldest first (a failed answer is left out)."""
    messages = db.scalars(
        sqlalchemy.select(models.Message)
        .where(
            models.Message.conversation_id == conversation_id,
            models.Message.status == models.MessageStatus.COMPLETE.value,
        )
        .order_by(models.Message.created_at, models.Message.id)
    ).all()
    return [TranscriptLine(role=models.MessageRole(message.role), text=message.text) for message in messages]


def _keep_cards(db: orm.Session, *, item: models.Source, proposal: models.CardSetProposal, kept: list[int]) -> None:
    """Make the chat's cards on the item the kept ones: identical ones stay as they are, new ones are added, and unkept
    ones are retired unless reviewed (a reviewed card is never retired, so its FSRS progress survives).

    Only cards saved from this proposal's chat are retired; on a note the worker's cards and other chats' cards stay.
    Identical cards (same question and answer) are matched against every live card on the item, so nothing is
    duplicated. A matched card from this chat takes the proposal's detail as its next version (the owner may have asked
    to change only the detail lines), keeping its schedule; a matched card the worker or another chat made keeps its own
    detail. A new card gets the proposal's detail."""
    proposed = card_set_tools.stored_cards(proposal)
    kept_cards = [proposed[index] for index in sorted(kept)]
    wanted = {(card.question, card.answer) for card in kept_cards}
    live = db.scalars(
        sqlalchemy.select(models.Card).where(models.Card.source_id == item.id, models.Card.deleted_at.is_(None))
    ).all()
    have = {(card.question, card.answer): card for card in live}

    chat_messages = sqlalchemy.select(models.Message.id).where(
        models.Message.conversation_id == proposal.conversation_id
    )
    chat_message_ids = set(db.scalars(chat_messages).all())
    retired = [
        card.id
        for card in live
        if card.message_id in chat_message_ids
        and (card.question, card.answer) not in wanted
        and card.reps == 0
        and card.last_review_at is None
    ]
    if retired:
        card_rows.retire_cards(db, models.Card.id.in_(retired))

    for card in kept_cards:
        detail = card_rows.joined_detail(card.detail)
        matched = have.get((card.question, card.answer))
        if matched is not None:
            _update_detail(db, matched=matched, detail=detail, chat_message_ids=chat_message_ids)
            continue

        created = models.Card(
            id=uuid.uuid4(),
            user_id=item.user_id,
            source_id=item.id,
            message_id=proposal.message_id,
            kind=card.kind.value,
            question=card.question,
            answer=card.answer,
            detail=detail,
            change_seq=changes.next_change_seq(),
        )
        have[(card.question, card.answer)] = created
        db.add(created)


def _update_detail(db: orm.Session, *, matched: models.Card, detail: str, chat_message_ids: set[uuid.UUID]) -> None:
    """Write `detail` as the matched card's next version when this chat made the card and its detail changed."""
    if matched.message_id not in chat_message_ids or matched.detail == detail:
        return

    versions.write(
        db,
        target=versions.Target(kind=models.EditTarget.CARD, id=matched.id),
        content={
            versions.QUESTION_KEY: matched.question,
            versions.ANSWER_KEY: matched.answer,
            versions.DETAIL_KEY: detail,
        },
        origin=models.VersionOrigin.CHAT_EDIT,
        instruction=None,
        derived_from=None,
    )


def _set_status(proposal: models.CardSetProposal, status: models.CardSetStatus) -> None:
    """Change the status with a fresh position, so phones pull the new state."""
    proposal.status = status.value
    proposal.updated_at = sqlalchemy.func.now()
    proposal.change_seq = changes.next_change_seq()


def _committed(db: orm.Session, proposal: models.CardSetProposal) -> schemas.CardSetProposalOut:
    db.commit()
    db.refresh(proposal)
    return schemas.CardSetProposalOut.model_validate(proposal)
