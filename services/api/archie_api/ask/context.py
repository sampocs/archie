"""What a chat's model call is given besides the question: earlier messages, and the about item's details and boost."""

from __future__ import annotations

import datetime
import uuid
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy
from archie_db import models, pipeline, search, takes
from sqlalchemy import orm

from archie_api.ask import card_set_tools

HISTORY_MESSAGES = 20
ABOUT_PRIMER_CHARACTERS = 2000
_EDIT_STATUS_NOTES: dict[models.EditStatus, str] = {
    models.EditStatus.PROPOSED: "waiting for the owner to apply it",
    models.EditStatus.APPLIED: "the owner applied it",
    models.EditStatus.UNDONE: "the owner applied it, then undid it",
    models.EditStatus.DISCARDED: "the owner discarded it",
    models.EditStatus.STALE: "it went stale: the item changed before it was applied",
    models.EditStatus.SUPERSEDED: "replaced by a later proposal",
}
_CARD_SET_STATUS_NOTES: dict[models.CardSetStatus, str] = {
    models.CardSetStatus.PROPOSED: "waiting for the owner to save it",
    models.CardSetStatus.SAVED: "the owner saved it",
    models.CardSetStatus.REPLACED: "replaced by a later proposal",
    models.CardSetStatus.DISCARDED: "the owner discarded it",
}
_CITED_ITEM_KEYS = (("source", "source_id"), ("topic_primer", "topic_primer_id"), ("take", "take_id"))
# A question's `segments` hold at most one segment, under this key: the Keep ticks it was sent with.
CARD_SET_CHOICE_KEY = "card_set_choice"
# The answer turn of a failed answer that proposed something but wrote no text: the API rejects an empty turn.
CUT_OFF_ANSWER = "(This answer was cut off.)"


@dataclass(frozen=True)
class HistoryMessage:
    """The parts of a stored message that history needs."""

    role: models.MessageRole
    text: str
    status: models.MessageStatus
    notes: tuple[str, ...] = ()
    # It proposed an edit or a card set: kept in history even if it failed, so a follow-up can build on the proposal.
    proposed: bool = False


@dataclass(frozen=True)
class CardSetChoice:
    """The Keep ticks a question was sent with: the open set's kept card indices (sorted) out of its `card_count`."""

    proposal_id: uuid.UUID
    kept: tuple[int, ...]
    card_count: int

    def to_segments(self) -> list[dict[str, Any]]:
        """The question's stored `segments`; the phone reads `kept` and `card_count` for its "Kept 3 of 5" line."""
        choice = {"proposal_id": str(self.proposal_id), "kept": list(self.kept), "card_count": self.card_count}
        return [{CARD_SET_CHOICE_KEY: choice}]


def owner_zone(name: str | None) -> datetime.tzinfo:
    """The phone's IANA time zone, or UTC when it sent none or one this server doesn't know."""
    if not name:
        return datetime.UTC
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        # Outside input: an unknown or malformed name (ValueError, e.g. a path; OSError, e.g. a bare directory
        # like "America") only costs the owner's days.
        return datetime.UTC


def history(db: orm.Session, *, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    """The conversation's earlier finished exchanges as Messages API turns, oldest first.

    A question sent with Keep ticks opens with the line saying which cards the owner kept and dropped, as its turn did.
    Each answer is followed by lines naming the items it cited, the edits it proposed and the card sets it proposed
    (with what became of each), so a follow-up like "and fix that card too" or "change card 2" can find its target.
    """
    stored = db.scalars(
        sqlalchemy.select(models.Message)
        .where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at, models.Message.id)
    ).all()
    proposals = db.scalars(
        sqlalchemy.select(models.EditProposal)
        .where(models.EditProposal.conversation_id == conversation_id)
        .order_by(models.EditProposal.created_at)
    ).all()
    card_sets = db.scalars(
        sqlalchemy.select(models.CardSetProposal)
        .where(models.CardSetProposal.conversation_id == conversation_id)
        .order_by(models.CardSetProposal.created_at)
    ).all()
    card_sets_by_id = {card_set.id: card_set for card_set in card_sets}
    proposal_notes: dict[uuid.UUID, list[str]] = {}
    for proposal in proposals:
        proposal_notes.setdefault(proposal.message_id, []).append(proposal_note(proposal))
    for card_set in card_sets:
        proposal_notes.setdefault(card_set.message_id, []).append(card_set_note(card_set))

    return history_messages(
        [
            HistoryMessage(
                role=models.MessageRole(row.role),
                text=_stored_question(row, card_sets_by_id=card_sets_by_id),
                status=models.MessageStatus(row.status),
                notes=(*citation_notes(row.segments), *proposal_notes.get(row.id, [])),
                proposed=row.id in proposal_notes,
            )
            for row in stored
        ]
    )


def citation_notes(segments: list[dict[str, Any]] | None) -> list[str]:
    """One `[cited: title — kind id]` line per library item an answer cited, in order, each once."""
    cited = [
        citation
        for segment in segments or []
        for citation in segment.get("citations", [])
        if citation.get("kind") == "library"
    ]
    tagged = (f"[cited: {citation['title']} — {tag}]" for citation in cited if (tag := _item_tag(citation)))
    return list(dict.fromkeys(tagged))


def proposal_note(proposal: models.EditProposal) -> str:
    """A `[edit proposed: …]` line: what the edit does, its target, and what the owner did with it."""
    status = _EDIT_STATUS_NOTES[models.EditStatus(proposal.status)]
    return f"[edit proposed: {proposal.description} — {proposal.target_kind} {proposal.target_id} — {status}]"


def card_set_note(card_set: models.CardSetProposal) -> str:
    """A `[cards proposed: …]` line with what the owner did with it, then its numbered cards with their detail lines, so
    the model can re-propose it with one change or bring back a replaced set's cards word for word. An open, saved or
    discarded set also carries its cheat sheet (a note's set has none); a replaced one's is left out, as no longer
    in play.
    """
    status = models.CardSetStatus(card_set.status)
    note = f"[cards proposed: {card_set.title} — {_CARD_SET_STATUS_NOTES[status]}]"
    cards = [
        "\n".join(
            [
                f"{number}. ({card.kind.value}) Q: {card.question}",
                f"   A: {card.answer}",
                *(f"   - {line}" for line in card.detail),
            ]
        )
        for number, card in enumerate(card_set_tools.stored_cards(card_set), start=1)
    ]
    has_cheat_sheet = card_set.cheat_sheet and status != models.CardSetStatus.REPLACED
    cheat_sheet = ["<cheat_sheet>", card_set.cheat_sheet, "</cheat_sheet>"] if has_cheat_sheet else []
    return "\n".join([note, *cheat_sheet, *cards])


def question_content(text: str, *, choice_line: str | None) -> str:
    """A question as the model reads it: the line about the owner's Keep ticks, if any, then the owner's words."""
    return f"{choice_line}\n\n{text}" if choice_line else text


def choice_line(*, kept: Sequence[int], card_set: models.CardSetProposal) -> str:
    """The sentence the model reads before a question sent with Keep ticks, from the 0-based kept indices.

    For example: The owner kept cards 1 and 3 of the proposed set and dropped 2 (“…”).
    """
    kept_numbers = [index + 1 for index in sorted(kept)]
    dropped = [
        f"{number} (“{card['question']}”)"
        for number, card in enumerate(card_set.cards, start=1)
        if number not in kept_numbers
    ]
    if not kept_numbers:
        kept_part = "none of the cards"
    else:
        cards_word = "card" if len(kept_numbers) == 1 else "cards"
        kept_part = f"{cards_word} {_spoken_list([str(number) for number in kept_numbers])}"
    return f"The owner kept {kept_part} of the proposed set and dropped {_spoken_list(dropped)}."


def stored_choice(segments: list[dict[str, Any]] | None) -> CardSetChoice | None:
    """The Keep ticks stored on a question, or None (an answer's segments, or a question sent without ticks)."""
    choice = next((segment[CARD_SET_CHOICE_KEY] for segment in segments or [] if CARD_SET_CHOICE_KEY in segment), None)
    if choice is None:
        return None
    return CardSetChoice(
        proposal_id=uuid.UUID(choice["proposal_id"]), kept=tuple(choice["kept"]), card_count=choice["card_count"]
    )


def history_messages(rows: Sequence[HistoryMessage]) -> list[dict[str, Any]]:
    """Question-answer pairs as plain text (no citations) with each answer's notes, the last `HISTORY_MESSAGES` of them.

    A pair is kept when its answer finished, or when it failed after proposing an edit or a card set: the proposal is
    still open in the chat, so the next question may build on it. A failed answer that proposed nothing is dropped
    with its question, so the history always alternates and starts with a question.
    """
    turns: list[dict[str, Any]] = []
    for question, answer in zip(rows, rows[1:], strict=False):
        is_pair = question.role == models.MessageRole.USER and answer.role == models.MessageRole.ASSISTANT
        finished = answer.status == models.MessageStatus.COMPLETE and bool(answer.text.strip())
        if not is_pair or not (finished or answer.proposed):
            continue

        text = answer.text if answer.text.strip() else CUT_OFF_ANSWER
        turns += [
            {"role": "user", "content": question.text},
            {"role": "assistant", "content": "\n\n".join([text, *answer.notes])},
        ]
    return turns[-HISTORY_MESSAGES:]


def about_text(db: orm.Session, *, conversation: models.Conversation) -> str | None:
    """The about item's title, summary and the owner's note, for the system prompt; None for a general chat."""
    if conversation.about_source_id is not None:
        return _source_text(db, source_id=conversation.about_source_id)
    if conversation.about_topic_primer_id is not None:
        primer = _current_primer(db, primer_id=conversation.about_topic_primer_id)
        if primer is None:
            return None
        topic = db.get_one(models.Topic, primer.topic_id)
        markdown = primer.content["markdown"][:ABOUT_PRIMER_CHARACTERS]
        return f"Topic primer: {topic.name} (topic primer id {primer.id})\n\n{markdown}"
    if conversation.about_take_id is not None:
        take = db.get_one(models.Take, conversation.about_take_id)
        version = takes.current_version(db, take=take)
        body = (version.body or version.raw_body) if version is not None else ""
        kind_name = takes.KIND_NAMES[models.TakeKind(take.kind)]
        return f"The owner's own {kind_name}: {take.title} (take id {take.id})\n\n{body}"
    return None


def boost(db: orm.Session, *, conversation: models.Conversation) -> search.ItemRef | None:
    """The item whose passages rank first; a topic primer is boosted as its topic's current version."""
    if conversation.about_source_id is not None:
        return search.ItemRef(kind=models.SearchItemKind.SOURCE, id=conversation.about_source_id)
    if conversation.about_take_id is not None:
        return search.ItemRef(kind=models.SearchItemKind.TAKE, id=conversation.about_take_id)
    if conversation.about_topic_primer_id is not None:
        primer = _current_primer(db, primer_id=conversation.about_topic_primer_id)
        return search.ItemRef(kind=models.SearchItemKind.TOPIC_PRIMER, id=primer.id) if primer else None
    return None


def note_title(db: orm.Session, *, conversation: models.Conversation) -> str | None:
    """The title of the note the chat is about, whose cards a card set in it makes; None when it isn't about a note."""
    if conversation.about_source_id is None:
        return None
    source = db.get_one(models.Source, conversation.about_source_id)
    return (source.title or source.url) if source.kind == models.SourceKind.NOTE else None


def _current_primer(db: orm.Session, *, primer_id: uuid.UUID) -> models.TopicPrimer | None:
    """The current version of the topic primer `primer_id` is a version of (the chat may predate a rewrite)."""
    started_with = db.get(models.TopicPrimer, primer_id)
    if started_with is None:
        return None
    return db.scalars(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == started_with.topic_id, models.TopicPrimer.is_current
        )
    ).one_or_none()


def _source_text(db: orm.Session, *, source_id: uuid.UUID) -> str:
    source = db.get_one(models.Source, source_id)
    lines = [
        f"{source.kind.capitalize()}: {source.title or source.url}",
        f"Source id: {source.id} (its summary and primer are editable)",
    ]
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    if summary is not None:
        content = summary.content["summary"]
        lines.append(f"Gist: {content['gist']}")
        lines += [f"- {item['idea']}" for item in content.get("key_ideas", [])]
    if source.note:
        lines.append(f"The owner's note: {source.note}")
    return "\n".join(lines)


def _stored_question(row: models.Message, *, card_sets_by_id: dict[uuid.UUID, models.CardSetProposal]) -> str:
    """A question's text as its turn read it (with its Keep-ticks line); any other message's text as stored."""
    choice = stored_choice(row.segments) if row.role == models.MessageRole.USER else None
    card_set = card_sets_by_id.get(choice.proposal_id) if choice is not None else None
    if choice is None or card_set is None:
        return row.text
    return question_content(row.text, choice_line=choice_line(kept=choice.kept, card_set=card_set))


def _spoken_list(items: Sequence[str]) -> str:
    """Items joined as spoken: `1`, `1 and 3`, `1, 3 and 5`."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _item_tag(citation: dict[str, Any]) -> str | None:
    return next((f"{kind} {citation[key]}" for kind, key in _CITED_ITEM_KEYS if citation.get(key)), None)
