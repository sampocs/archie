"""Ask's editing tools: read what can be edited, find cards, and propose edits the owner applies from the chat.

The model reads a target's exact current content with `read_item`, finds cards with `find_cards`, and proposes a
change with one of the three `propose_*` tools. A proposal changes nothing: it is validated here, shown to the owner
as an `edit` event, and stored with the answer by `save_proposals`; the owner's Apply goes through
`archie_api.edits.routes`. Each tool reads in its own short session between model rounds, so no transaction spans a
model call. A bad input goes back to the model as an error result it can fix.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pydantic
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, search, versions

from archie_api.sync import take_actions

READ_ITEM = "read_item"
FIND_CARDS = "find_cards"
PROPOSE_SUMMARY_EDIT = "propose_summary_edit"
PROPOSE_TEXT_EDIT = "propose_text_edit"
PROPOSE_CARD_EDIT = "propose_card_edit"
TOOL_NAMES = frozenset({READ_ITEM, FIND_CARDS, PROPOSE_SUMMARY_EDIT, PROPOSE_TEXT_EDIT, PROPOSE_CARD_EDIT})

MAX_FOUND_CARDS = 10
MAX_GIST_CHARACTERS = 2000
MAX_SUMMARY_ITEMS = 30
MAX_MARKDOWN_CHARACTERS = 60_000
MAX_DESCRIPTION_CHARACTERS = 300
MAX_REPLACEMENTS = 20
MAX_QUESTION_CHARACTERS = 500
MAX_ANSWER_CHARACTERS = 2000
PROPOSED = "shown to the owner with Apply and Discard; nothing has changed yet"
_CLIP_CHARACTERS = 80

# A tuple, not a set: the tool schema's enum lists them, and a stable order keeps the request stable.
_TEXT_KINDS = (models.EditTarget.PRIMER, models.EditTarget.TOPIC_PRIMER, models.EditTarget.TAKE)
_NULLABLE_STRING: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_DESCRIPTION: dict[str, Any] = {"type": "string", "description": "One short line telling the owner what changes."}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """A strict-mode object schema: every property required, nothing else allowed."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


READ_ITEM_TOOL: dict[str, Any] = {
    "name": READ_ITEM,
    "description": (
        "Read the exact current content of something the owner can edit: a source's summary or primer (id: the "
        "source id), a topic primer (id: a topic primer id or the topic id), one of the owner's takes (id: the take "
        "id) or a review card (id: the card id). Call it before proposing an edit and copy text from it exactly. "
        "`pending` is an edit you already proposed in this chat, against this version, that the owner hasn't applied: "
        "build on it."
    ),
    "input_schema": _object(
        {"kind": {"type": "string", "enum": [kind.value for kind in models.EditTarget]}, "id": {"type": "string"}}
    ),
    "strict": True,
}
FIND_CARDS_TOOL: dict[str, Any] = {
    "name": FIND_CARDS,
    "description": (
        "Find the owner's review cards by words in their question or answer, by the item they came from, or both. "
        "Returns up to 10 cards with their ids."
    ),
    "input_schema": _object(
        {
            "query": {"type": "string", "description": "Words to look for; empty to list an item's cards."},
            "item": {
                "anyOf": [
                    _object(
                        {
                            "kind": {"type": "string", "enum": [kind.value for kind in models.SearchItemKind]},
                            "id": {"type": "string"},
                        }
                    ),
                    {"type": "null"},
                ]
            },
        }
    ),
    "strict": True,
}
PROPOSE_SUMMARY_EDIT_TOOL: dict[str, Any] = {
    "name": PROPOSE_SUMMARY_EDIT,
    "description": (
        "Propose a new version of a source's summary: the whole summary as it should read, with everything the owner "
        "didn't ask to change copied exactly, timestamps included. The owner sees a diff and taps Apply; nothing "
        "changes before that."
    ),
    "input_schema": _object(
        {
            "source_id": {"type": "string"},
            "description": _DESCRIPTION,
            "gist": {"type": "string"},
            "key_ideas": {
                "type": "array",
                "items": _object({"timestamp": _NULLABLE_STRING, "idea": {"type": "string"}}),
            },
            "numbers": {"type": "array", "items": _object({"timestamp": _NULLABLE_STRING, "fact": {"type": "string"}})},
        }
    ),
    "strict": True,
}
PROPOSE_TEXT_EDIT_TOOL: dict[str, Any] = {
    "name": PROPOSE_TEXT_EDIT,
    "description": (
        "Propose an edit to a source's primer (id: the source id), a topic primer or one of the owner's takes, as "
        "find-and-replace pairs over its current markdown from read_item. Each find must be copied exactly and "
        "appear exactly once; an empty replace deletes it. The owner sees a diff and taps Apply; nothing changes "
        "before that."
    ),
    "input_schema": _object(
        {
            "kind": {"type": "string", "enum": [kind.value for kind in _TEXT_KINDS]},
            "id": {"type": "string"},
            "description": _DESCRIPTION,
            "replacements": {
                "type": "array",
                "items": _object({"find": {"type": "string"}, "replace": {"type": "string"}}),
            },
        }
    ),
    "strict": True,
}
PROPOSE_CARD_EDIT_TOOL: dict[str, Any] = {
    "name": PROPOSE_CARD_EDIT,
    "description": (
        "Propose a new question and answer for one of the owner's review cards (find it with find_cards). The card "
        "keeps its review schedule. The owner sees a diff and taps Apply; nothing changes before that."
    ),
    "input_schema": _object(
        {
            "card_id": {"type": "string"},
            "description": _DESCRIPTION,
            "question": {"type": "string"},
            "answer": {"type": "string"},
        }
    ),
    "strict": True,
}
TOOLS: list[dict[str, Any]] = [
    READ_ITEM_TOOL,
    FIND_CARDS_TOOL,
    PROPOSE_SUMMARY_EDIT_TOOL,
    PROPOSE_TEXT_EDIT_TOOL,
    PROPOSE_CARD_EDIT_TOOL,
]


class ToolInputError(Exception):
    """A tool input the model can fix; the message goes back to it as the tool's error result."""


@dataclass(frozen=True)
class Proposal:
    """A validated edit, kept until the answer is stored and shown to the owner at once as an `edit` event."""

    id: uuid.UUID
    target: versions.Target
    title: str
    description: str
    base_version: int
    before: dict[str, Any]
    after: dict[str, Any]

    def to_event(self) -> dict[str, Any]:
        """The `edit` event's data."""
        return {
            "id": str(self.id),
            "target_kind": self.target.kind.value,
            "target_id": str(self.target.id),
            "title": self.title,
            "description": self.description,
            "base_version": self.base_version,
            "before": self.before,
            "after": self.after,
            "status": models.EditStatus.PROPOSED.value,
        }


@dataclass(frozen=True)
class ToolContext:
    """Who is asking, in which chat, and the proposals this answer already made (newest last)."""

    user_id: int
    conversation_id: uuid.UUID
    pending: tuple[Proposal, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolOutcome:
    """A tool's result block for the model, and the proposal it made, if any."""

    result: dict[str, Any]
    proposal: Proposal | None = None


class _ItemIn(pydantic.BaseModel):
    kind: models.EditTarget
    id: uuid.UUID


class _CardOriginIn(pydantic.BaseModel):
    kind: models.SearchItemKind
    id: uuid.UUID


class _FindCardsIn(pydantic.BaseModel):
    query: str
    item: _CardOriginIn | None


class _KeyIdeaIn(pydantic.BaseModel):
    timestamp: str | None
    idea: str = pydantic.Field(min_length=1)


class _NumberIn(pydantic.BaseModel):
    timestamp: str | None
    fact: str = pydantic.Field(min_length=1)


class _SummaryEditIn(pydantic.BaseModel):
    source_id: uuid.UUID
    description: str = pydantic.Field(min_length=1, max_length=MAX_DESCRIPTION_CHARACTERS)
    gist: str = pydantic.Field(min_length=1, max_length=MAX_GIST_CHARACTERS)
    key_ideas: list[_KeyIdeaIn] = pydantic.Field(max_length=MAX_SUMMARY_ITEMS)
    numbers: list[_NumberIn] = pydantic.Field(max_length=MAX_SUMMARY_ITEMS)


class _ReplacementIn(pydantic.BaseModel):
    find: str = pydantic.Field(min_length=1)
    replace: str


class _TextEditIn(pydantic.BaseModel):
    kind: models.EditTarget
    id: uuid.UUID
    description: str = pydantic.Field(min_length=1, max_length=MAX_DESCRIPTION_CHARACTERS)
    replacements: list[_ReplacementIn] = pydantic.Field(min_length=1, max_length=MAX_REPLACEMENTS)


class _CardEditIn(pydantic.BaseModel):
    card_id: uuid.UUID
    description: str = pydantic.Field(min_length=1, max_length=MAX_DESCRIPTION_CHARACTERS)
    question: str = pydantic.Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    answer: str = pydantic.Field(min_length=1, max_length=MAX_ANSWER_CHARACTERS)


_Handled = tuple[dict[str, Any], Proposal | None]
_Handler = Callable[[sqlalchemy.orm.Session, ToolContext, object], _Handled]


def run(
    engine: sqlalchemy.Engine, *, context: ToolContext, tool_use_id: str, name: str, tool_input: object
) -> ToolOutcome:
    """Run one editing tool in its own read-only session; a bad input is an error result the model can act on."""
    handler = _HANDLERS[name]
    with sqlalchemy.orm.Session(engine) as db:
        try:
            payload, proposal = handler(db, context, tool_input)
        except (ToolInputError, pydantic.ValidationError) as error:
            return ToolOutcome(
                result={
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": _error_text(error),
                }
            )
    return ToolOutcome(
        result={"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(payload)}, proposal=proposal
    )


def save_proposals(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    proposals: Sequence[Proposal],
) -> None:
    """Store the answer's proposals; each supersedes the chat's older still-proposed edits of the same target.

    The model was handed the pending edit to build on (`read_item`), so the newest proposal holds every change. The
    caller holds the user's write lock and has added the answer row.
    """
    for proposal in proposals:
        db.execute(
            sqlalchemy.update(models.EditProposal)
            .where(
                models.EditProposal.conversation_id == conversation_id,
                models.EditProposal.target_kind == proposal.target.kind.value,
                models.EditProposal.target_id == proposal.target.id,
                models.EditProposal.status == models.EditStatus.PROPOSED.value,
            )
            .values(
                status=models.EditStatus.SUPERSEDED.value,
                updated_at=sqlalchemy.func.now(),
                change_seq=changes.next_change_seq(),
            )
        )
        db.add(
            models.EditProposal(
                id=proposal.id,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                target_kind=proposal.target.kind.value,
                target_id=proposal.target.id,
                title=proposal.title,
                description=proposal.description,
                base_version=proposal.base_version,
                before=proposal.before,
                after=proposal.after,
                status=models.EditStatus.PROPOSED.value,
                # now() is the transaction's start, so rows saved together would tie; they must keep their order.
                created_at=sqlalchemy.func.clock_timestamp(),
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()


def apply_replacements(text: str, *, replacements: Sequence[tuple[str, str]]) -> str:
    """Apply each (find, replace) in order; each find must occur exactly once in the text as it stands by then."""
    edited = text
    for find, replace in replacements:
        count = edited.count(find)
        if count == 0:
            raise ToolInputError(f'"{_clip(find)}" isn\'t in the current text; call read_item and copy it exactly.')
        if count > 1:
            raise ToolInputError(f'"{_clip(find)}" appears {count} times; include more of the text around it.')
        edited = edited.replace(find, replace, 1)
    return edited


def _read_item(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _ItemIn.model_validate(tool_input)
    target = _resolve(db, context=context, kind=parsed.kind, item_id=parsed.id)
    snapshot = versions.current(db, target=target)
    payload = {
        "kind": target.kind.value,
        "id": str(target.id),
        "title": versions.title(db, target=target),
        "version": snapshot.version,
        "content": snapshot.content,
        "pending": _pending_after(db, context=context, target=target),
    }
    return payload, None


def _find_cards(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _FindCardsIn.model_validate(tool_input)
    words = search.any_terms(parsed.query)
    if not words and parsed.item is None:
        raise ToolInputError("Give some words to look for, an item, or both.")

    criteria = [models.Card.user_id == context.user_id, models.Card.deleted_at.is_(None)]
    if parsed.item is not None:
        criteria.append(_card_origin(db, item=parsed.item))
    statement = sqlalchemy.select(models.Card).where(*criteria)
    if words:
        # A user has hundreds of cards, not millions: ranking them on the fly needs no index.
        document = sqlalchemy.func.to_tsvector("english", models.Card.question + " " + models.Card.answer)
        query = sqlalchemy.func.websearch_to_tsquery("english", words)
        statement = statement.where(document.op("@@")(query)).order_by(
            sqlalchemy.func.ts_rank_cd(document, query).desc(), models.Card.created_at
        )
    else:
        statement = statement.order_by(models.Card.created_at)

    cards = db.scalars(statement.limit(MAX_FOUND_CARDS)).all()
    return {"cards": [{"id": str(card.id), "question": card.question, "answer": card.answer} for card in cards]}, None


def _propose_summary_edit(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _SummaryEditIn.model_validate(tool_input)
    target = _resolve(db, context=context, kind=models.EditTarget.SUMMARY, item_id=parsed.source_id)
    after = {
        "gist": parsed.gist.strip(),
        "key_ideas": [{"timestamp": item.timestamp, "idea": item.idea.strip()} for item in parsed.key_ideas],
        "numbers": [{"timestamp": item.timestamp, "fact": item.fact.strip()} for item in parsed.numbers],
    }
    return _proposal(db, target=target, description=parsed.description, after=after)


def _propose_text_edit(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _TextEditIn.model_validate(tool_input)
    if parsed.kind not in _TEXT_KINDS:
        raise ToolInputError("propose_text_edit edits a primer, a topic primer or a take.")
    target = _resolve(db, context=context, kind=parsed.kind, item_id=parsed.id)

    # A follow-up edit builds on the chat's pending proposal for the same target, which it then supersedes.
    base = _pending_after(db, context=context, target=target) or versions.current(db, target=target).content
    pairs = [(replacement.find, replacement.replace) for replacement in parsed.replacements]
    markdown = apply_replacements(base[versions.MARKDOWN_KEY], replacements=pairs).strip()
    limit = take_actions.MAX_TAKE_BODY_LENGTH if target.kind == models.EditTarget.TAKE else MAX_MARKDOWN_CHARACTERS
    if not markdown:
        raise ToolInputError("The edit would leave it empty.")
    if len(markdown) > limit:
        raise ToolInputError(f"The edited text is longer than {limit} characters.")
    return _proposal(db, target=target, description=parsed.description, after={versions.MARKDOWN_KEY: markdown})


def _propose_card_edit(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _CardEditIn.model_validate(tool_input)
    target = _resolve(db, context=context, kind=models.EditTarget.CARD, item_id=parsed.card_id)
    after = {versions.QUESTION_KEY: parsed.question.strip(), versions.ANSWER_KEY: parsed.answer.strip()}
    return _proposal(db, target=target, description=parsed.description, after=after)


_HANDLERS: dict[str, _Handler] = {
    READ_ITEM: _read_item,
    FIND_CARDS: _find_cards,
    PROPOSE_SUMMARY_EDIT: _propose_summary_edit,
    PROPOSE_TEXT_EDIT: _propose_text_edit,
    PROPOSE_CARD_EDIT: _propose_card_edit,
}


def _resolve(
    db: sqlalchemy.orm.Session, *, context: ToolContext, kind: models.EditTarget, item_id: uuid.UUID
) -> versions.Target:
    target = versions.resolve(db, user_id=context.user_id, kind=kind, item_id=item_id)
    if target is None:
        raise ToolInputError(f"There is no {kind.value} with id {item_id} that the owner can edit.")
    return target


def _proposal(
    db: sqlalchemy.orm.Session, *, target: versions.Target, description: str, after: dict[str, Any]
) -> _Handled:
    snapshot = versions.current(db, target=target)
    if after == snapshot.content:
        raise ToolInputError("That is exactly what it says now; change only what the owner asked for.")

    proposal = Proposal(
        id=uuid.uuid4(),
        target=target,
        title=versions.title(db, target=target),
        description=description.strip(),
        base_version=snapshot.version,
        before=snapshot.content,
        after=after,
    )
    return {"proposal_id": str(proposal.id), "status": PROPOSED}, proposal


def _pending_after(
    db: sqlalchemy.orm.Session, *, context: ToolContext, target: versions.Target
) -> dict[str, Any] | None:
    """The newest still-proposed edit of `target` in this chat, from this answer first, else from earlier ones.

    It counts only while it was made against the target's current version: once the target moved on (the owner edited
    it, Review rewrote the card, Archie regenerated it), building on it would drop the newer version's content.
    """
    current_version = versions.current(db, target=target).version
    for proposal in reversed(context.pending):
        if proposal.target == target:
            return proposal.after if proposal.base_version == current_version else None
    stored = db.scalars(
        sqlalchemy.select(models.EditProposal)
        .where(
            models.EditProposal.conversation_id == context.conversation_id,
            models.EditProposal.target_kind == target.kind.value,
            models.EditProposal.target_id == target.id,
            models.EditProposal.status == models.EditStatus.PROPOSED.value,
        )
        .order_by(models.EditProposal.created_at.desc())
        .limit(1)
    ).first()
    if stored is None or stored.base_version != current_version:
        return None
    return stored.after


def _card_origin(db: sqlalchemy.orm.Session, *, item: _CardOriginIn) -> sqlalchemy.ColumnElement[bool]:
    if item.kind == models.SearchItemKind.SOURCE:
        return models.Card.source_id == item.id
    if item.kind == models.SearchItemKind.TAKE:
        return models.Card.take_id == item.id

    # Foundation cards belong to one primer version; any version (or the topic itself) names them all.
    primer = db.get(models.TopicPrimer, item.id)
    topic_id = primer.topic_id if primer is not None else item.id
    versions_of_topic = sqlalchemy.select(models.TopicPrimer.id).where(models.TopicPrimer.topic_id == topic_id)
    return models.Card.topic_primer_id.in_(versions_of_topic)


def _error_text(error: ToolInputError | pydantic.ValidationError) -> str:
    if isinstance(error, ToolInputError):
        return str(error)
    problems = [f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}" for problem in error.errors()]
    return "Invalid input: " + "; ".join(problems[:3])


def _clip(text: str) -> str:
    return text if len(text) <= _CLIP_CHARACTERS else f"{text[:_CLIP_CHARACTERS]}…"
