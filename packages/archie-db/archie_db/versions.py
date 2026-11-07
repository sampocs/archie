"""What Ask can edit, as versions: read a target's current content, write its next version, restore an earlier one.

A target is a source's summary or primer, a topic's primer, a take or a card (`Target`). Every change adds a version
and makes it current; nothing is overwritten. Content travels in one edit shape per kind:
- summary: the artifact's `summary` object (`gist`, `key_ideas`, `numbers`); writing copies the rest of the
  artifact's content (domain, tags, the cards it came with) from the current version;
- primer, topic primer and take: `{"markdown": ...}` (a take's body);
- card: `{"question": ..., "answer": ...}`.
Writing a topic primer version also moves the topic's live foundation cards onto it, since Review only knows the
current primer version.
Cards are versioned lazily: a card has no `card_versions` rows until its first change, which writes version 1 (the
card as it was) and version 2 together. Every function that writes expects the caller to hold
`changes.lock_user_writes` for the target's user.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm

from archie_db import card_rows, changes, jobs, models, pipeline, takes, topic_primers

MARKDOWN_KEY = "markdown"
SUMMARY_KEY = "summary"
QUESTION_KEY = "question"
ANSWER_KEY = "answer"

_ARTIFACT_KINDS: dict[models.EditTarget, models.ArtifactKind] = {
    models.EditTarget.SUMMARY: models.ArtifactKind.SUMMARY,
    models.EditTarget.PRIMER: models.ArtifactKind.PRIMER,
}


@dataclass(frozen=True)
class Target:
    """One editable thing; `id` is the source (summary, primer), the topic (topic primer), the take or the card."""

    kind: models.EditTarget
    id: uuid.UUID


@dataclass(frozen=True)
class Snapshot:
    """A target's version number and its content in the edit shape."""

    version: int
    content: dict[str, Any]


def resolve(db: sqlalchemy.orm.Session, *, user_id: int, kind: models.EditTarget, item_id: uuid.UUID) -> Target | None:
    """The user's live target, or None. A topic primer may be named by its topic or by any of its version ids."""
    if kind in _ARTIFACT_KINDS:
        return _source_target(db, user_id=user_id, kind=kind, source_id=item_id)
    if kind == models.EditTarget.TOPIC_PRIMER:
        return _topic_target(db, user_id=user_id, item_id=item_id)
    if kind == models.EditTarget.TAKE:
        take = db.get(models.Take, item_id)
        is_live = take is not None and take.user_id == user_id and take.deleted_at is None
        return Target(kind=kind, id=item_id) if is_live else None
    card = card_rows.owned_live_card(db, user_id=user_id, card_id=item_id)
    return Target(kind=kind, id=item_id) if card is not None else None


def title(db: sqlalchemy.orm.Session, *, target: Target) -> str:
    """What the chat calls the target: the source's title, the topic's name, the take's title or the card's question."""
    if target.kind in _ARTIFACT_KINDS:
        source = db.get_one(models.Source, target.id)
        return source.title or source.url
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        return db.get_one(models.Topic, target.id).name
    if target.kind == models.EditTarget.TAKE:
        return db.get_one(models.Take, target.id).title
    return db.get_one(models.Card, target.id).question


def current(db: sqlalchemy.orm.Session, *, target: Target) -> Snapshot:
    """The target's current version and content; `target` came from `resolve`, so it has one."""
    if target.kind in _ARTIFACT_KINDS:
        artifact = pipeline.current_artifact(db, source_id=target.id, kind=_ARTIFACT_KINDS[target.kind])
        assert artifact is not None
        return Snapshot(version=artifact.version, content=_artifact_shape(target.kind, artifact.content))
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        primer = topic_primers.current(db, topic_id=target.id)
        assert primer is not None
        return Snapshot(version=primer.version, content={MARKDOWN_KEY: primer.content[MARKDOWN_KEY]})
    if target.kind == models.EditTarget.TAKE:
        take = db.get_one(models.Take, target.id)
        version = takes.current_version(db, take=take)
        assert version is not None
        return Snapshot(version=take.current_version, content={MARKDOWN_KEY: takes.shown_body(version)})
    card = db.get_one(models.Card, target.id)
    return Snapshot(version=card.version, content={QUESTION_KEY: card.question, ANSWER_KEY: card.answer})


def at_version(db: sqlalchemy.orm.Session, *, target: Target, version: int) -> dict[str, Any] | None:
    """The content of the target's version numbered `version`, or None when there is no such version."""
    if target.kind in _ARTIFACT_KINDS:
        artifact = _artifact_at(db, source_id=target.id, kind=_ARTIFACT_KINDS[target.kind], version=version)
        return _artifact_shape(target.kind, artifact.content) if artifact is not None else None
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        primer = topic_primers.at_version(db, topic_id=target.id, version=version)
        return {MARKDOWN_KEY: primer.content[MARKDOWN_KEY]} if primer is not None else None
    if target.kind == models.EditTarget.TAKE:
        take_version = takes.version_at(db, take_id=target.id, version=version)
        return {MARKDOWN_KEY: takes.shown_body(take_version)} if take_version is not None else None

    card = db.get_one(models.Card, target.id)
    if version == card.version:
        return {QUESTION_KEY: card.question, ANSWER_KEY: card.answer}
    row = _card_version(db, card_id=card.id, version=version)
    return {QUESTION_KEY: row.question, ANSWER_KEY: row.answer} if row is not None else None


def write(
    db: sqlalchemy.orm.Session,
    *,
    target: Target,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
    derived_from: int | None,
) -> int:
    """Save `content` as the target's next, current version and return its number.

    Side effects match a normal save of that kind: a source or topic primer is re-indexed for search, a take version
    queues its cards and indexing, a card keeps its schedule.
    """
    if target.kind in _ARTIFACT_KINDS:
        return _write_artifact(
            db, target=target, content=content, origin=origin, instruction=instruction, derived_from=derived_from
        )
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        return _write_topic_primer(
            db, target=target, content=content, origin=origin, instruction=instruction, derived_from=derived_from
        )
    if target.kind == models.EditTarget.TAKE:
        markdown = content[MARKDOWN_KEY]
        return _write_take(db, take_id=target.id, body=markdown, raw_body=markdown, cleaned=False, origin=origin)
    return _write_card(db, card_id=target.id, content=content, origin=origin, instruction=instruction)


def restore(db: sqlalchemy.orm.Session, *, target: Target, version: int) -> int | None:
    """Save version `version` again as the newest, current one (origin `restore`); None when there is no such version.

    A take keeps the restored version's raw text and Clean it up flag, as the take page's own Restore does.
    """
    if target.kind == models.EditTarget.TAKE:
        earlier = takes.version_at(db, take_id=target.id, version=version)
        if earlier is None:
            return None
        return _write_take(
            db,
            take_id=target.id,
            body=takes.shown_body(earlier),
            raw_body=earlier.raw_body,
            cleaned=earlier.cleaned,
            origin=models.VersionOrigin.RESTORE,
        )

    content = at_version(db, target=target, version=version)
    if content is None:
        return None
    return write(
        db, target=target, content=content, origin=models.VersionOrigin.RESTORE, instruction=None, derived_from=version
    )


def _source_target(
    db: sqlalchemy.orm.Session, *, user_id: int, kind: models.EditTarget, source_id: uuid.UUID
) -> Target | None:
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user_id or source.deleted_at is not None:
        return None
    if source.merged_into_id is not None:
        return None
    if pipeline.current_artifact(db, source_id=source_id, kind=_ARTIFACT_KINDS[kind]) is None:
        return None
    return Target(kind=kind, id=source_id)


def _topic_target(db: sqlalchemy.orm.Session, *, user_id: int, item_id: uuid.UUID) -> Target | None:
    """Search results and the about block name a primer version; the target is always its topic."""
    primer = db.get(models.TopicPrimer, item_id)
    topic = db.get(models.Topic, primer.topic_id if primer is not None else item_id)
    if topic is None or topic.user_id != user_id or topic.removed_at is not None or topic.merged_into_id is not None:
        return None
    if topic_primers.current(db, topic_id=topic.id) is None:
        return None
    return Target(kind=models.EditTarget.TOPIC_PRIMER, id=topic.id)


def _artifact_shape(kind: models.EditTarget, content: dict[str, Any]) -> dict[str, Any]:
    if kind == models.EditTarget.SUMMARY:
        return dict(content[SUMMARY_KEY])
    return {MARKDOWN_KEY: content[MARKDOWN_KEY]}


def _artifact_at(
    db: sqlalchemy.orm.Session, *, source_id: uuid.UUID, kind: models.ArtifactKind, version: int
) -> models.SourceArtifact | None:
    return db.scalar(
        sqlalchemy.select(models.SourceArtifact).where(
            models.SourceArtifact.source_id == source_id,
            models.SourceArtifact.kind == kind.value,
            models.SourceArtifact.version == version,
        )
    )


def _write_artifact(
    db: sqlalchemy.orm.Session,
    *,
    target: Target,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
    derived_from: int | None,
) -> int:
    kind = _ARTIFACT_KINDS[target.kind]
    source = db.get_one(models.Source, target.id)
    base = pipeline.current_artifact(db, source_id=source.id, kind=kind)
    assert base is not None
    derived = _artifact_at(db, source_id=source.id, kind=kind, version=derived_from) if derived_from else None

    # A summary edit changes only the summary; the analysis around it (domain, tags, the cards it came with) stays.
    full_content = (
        {**base.content, SUMMARY_KEY: content}
        if target.kind == models.EditTarget.SUMMARY
        else {MARKDOWN_KEY: content[MARKDOWN_KEY]}
    )
    artifact = pipeline.write_artifact(
        db,
        source=source,
        kind=kind,
        content=full_content,
        model=None,
        prompt_version=None,
        origin=origin,
        derived_from_id=derived.id if derived is not None else None,
        instruction=instruction,
    )
    jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)
    return artifact.version


def _write_topic_primer(
    db: sqlalchemy.orm.Session,
    *,
    target: Target,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
    derived_from: int | None,
) -> int:
    topic = db.get_one(models.Topic, target.id)
    derived = topic_primers.at_version(db, topic_id=topic.id, version=derived_from) if derived_from else None
    primer = topic_primers.write(
        db,
        topic=topic,
        markdown=content[MARKDOWN_KEY],
        model=None,
        prompt_version=None,
        origin=origin,
        derived_from_id=derived.id if derived is not None else None,
        instruction=instruction,
    )

    # Review loads only the current primer version and drops cards pointing at any other, so the topic's live
    # foundation cards follow every new version.
    earlier_ids = sqlalchemy.select(models.TopicPrimer.id).where(
        models.TopicPrimer.topic_id == topic.id, models.TopicPrimer.id != primer.id
    )
    db.execute(
        sqlalchemy.update(models.Card)
        .where(models.Card.topic_primer_id.in_(earlier_ids), models.Card.deleted_at.is_(None))
        .values(
            topic_primer_id=primer.id,
            updated_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
    )
    jobs.enqueue_embed(db, user_id=topic.user_id, item_kind=models.SearchItemKind.TOPIC_PRIMER, item_id=primer.id)
    return primer.version


def _write_take(
    db: sqlalchemy.orm.Session,
    *,
    take_id: uuid.UUID,
    body: str,
    raw_body: str,
    cleaned: bool,
    origin: models.VersionOrigin,
) -> int:
    take = db.get_one(models.Take, take_id)
    takes.add_version(
        db, take=take, version_id=uuid.uuid4(), body=body, raw_body=raw_body, cleaned=cleaned, origin=origin
    )
    changes.touch(take)
    return take.current_version


def _write_card(
    db: sqlalchemy.orm.Session,
    *,
    card_id: uuid.UUID,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
) -> int:
    card = db.get_one(models.Card, card_id)

    # A card's history starts at its first change: the card as it was becomes the version it is at.
    if _card_version(db, card_id=card.id, version=card.version) is None:
        _add_card_version(
            db,
            card=card,
            question=card.question,
            answer=card.answer,
            origin=models.VersionOrigin.ARCHIE,
            instruction=None,
        )

    # Only the words change: the card keeps its schedule and its review history.
    card.version += 1
    card.question = content[QUESTION_KEY]
    card.answer = content[ANSWER_KEY]
    card.updated_at = sqlalchemy.func.now()
    card.change_seq = changes.next_change_seq()
    _add_card_version(db, card=card, question=card.question, answer=card.answer, origin=origin, instruction=instruction)
    db.flush()
    return card.version


def _card_version(db: sqlalchemy.orm.Session, *, card_id: uuid.UUID, version: int) -> models.CardVersion | None:
    return db.scalar(
        sqlalchemy.select(models.CardVersion).where(
            models.CardVersion.card_id == card_id, models.CardVersion.version == version
        )
    )


def _add_card_version(
    db: sqlalchemy.orm.Session,
    *,
    card: models.Card,
    question: str,
    answer: str,
    origin: models.VersionOrigin,
    instruction: str | None,
) -> None:
    db.add(
        models.CardVersion(
            id=uuid.uuid4(),
            user_id=card.user_id,
            card_id=card.id,
            version=card.version,
            question=question,
            answer=answer,
            origin=origin.value,
            instruction=instruction,
            change_seq=changes.next_change_seq(),
        )
    )
    db.flush()
