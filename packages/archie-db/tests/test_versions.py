"""Versions of what Ask can edit: writing, restoring and resolving each kind, and Archie's regeneration rule."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session, takes, topic_primers, versions

pytestmark = pytest.mark.postgres

SUMMARY: dict[str, Any] = {
    "gist": "Index funds beat most stock pickers.",
    "key_ideas": [
        {"timestamp": None, "idea": "They track an index."},
        {"timestamp": None, "idea": "Low fees compound."},
    ],
    "numbers": [{"timestamp": None, "fact": "~90% of managers trail the index."}],
}


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session on the migrated test database."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as database:
        yield database
    engine.dispose()


def _user(db: sqlalchemy.orm.Session, sub: str = "editor") -> int:
    user = models.User(apple_sub=sub)
    db.add(user)
    db.flush()
    changes.lock_user_writes(db, user.id)
    return user.id


def _source_with_summary(db: sqlalchemy.orm.Session, *, user_id: int) -> models.Source:
    url = f"https://example.com/{uuid.uuid4()}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user_id,
        url=url,
        normalized_url=url,
        title="Index funds",
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.CONSUMED.value,
        intent=models.SourceIntent.FINISHED.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.TEXT, content={"text": "..."}, model=None, prompt_version=None
    )
    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.SUMMARY,
        content={"summary": SUMMARY, "domain": "Finance", "tags": ["funds"], "cards": []},
        model="claude-haiku-5-5",
        prompt_version="analyze-v2",
    )
    return source


def _summaries(db: sqlalchemy.orm.Session, source_id: uuid.UUID) -> list[models.SourceArtifact]:
    return list(
        db.scalars(
            sqlalchemy.select(models.SourceArtifact)
            .where(
                models.SourceArtifact.source_id == source_id,
                models.SourceArtifact.kind == models.ArtifactKind.SUMMARY.value,
            )
            .order_by(models.SourceArtifact.version)
        )
    )


def _queued(db: sqlalchemy.orm.Session) -> list[str]:
    return list(db.scalars(sqlalchemy.select(models.Job.kind).order_by(models.Job.id)))


def test_a_summary_edit_is_the_next_current_version_and_keeps_the_rest_of_the_analysis(
    db: sqlalchemy.orm.Session,
) -> None:
    """Version 2 is current with the new summary, origin chat_edit and its description; domain and tags carry over."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    target = versions.resolve(db, user_id=user_id, kind=models.EditTarget.SUMMARY, item_id=source.id)
    assert target is not None
    edited = {**SUMMARY, "key_ideas": SUMMARY["key_ideas"][:1]}

    new_version = versions.write(
        db,
        target=target,
        content=edited,
        origin=models.VersionOrigin.CHAT_EDIT,
        instruction="Drop the fees idea",
        derived_from=1,
    )

    first, second = _summaries(db, source.id)
    assert new_version == 2
    assert (first.is_current, second.is_current) == (False, True)
    assert second.content == {"summary": edited, "domain": "Finance", "tags": ["funds"], "cards": []}
    assert (second.origin, second.instruction, second.derived_from_id) == ("chat_edit", "Drop the fees idea", first.id)
    assert versions.current(db, target=target) == versions.Snapshot(version=2, content=edited)
    assert versions.at_version(db, target=target, version=1) == SUMMARY
    assert models.JobKind.EMBED.value in _queued(db)


def test_restoring_copies_an_earlier_version_as_the_newest(db: sqlalchemy.orm.Session) -> None:
    """Restore makes version 3 a copy of version 1 (origin restore); an unknown version restores nothing."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    target = versions.Target(kind=models.EditTarget.SUMMARY, id=source.id)
    versions.write(
        db, target=target, content={**SUMMARY, "gist": "Edited."}, origin=models.VersionOrigin.CHAT_EDIT,
        instruction=None, derived_from=1,
    )  # fmt: skip

    assert versions.restore(db, target=target, version=1) == 3
    assert versions.restore(db, target=target, version=9) is None

    third = _summaries(db, source.id)[-1]
    assert (third.version, third.is_current, third.origin) == (3, True, "restore")
    assert third.content["summary"] == SUMMARY


def test_archie_rewrites_never_replace_an_owner_chosen_version_unless_the_text_changed(
    db: sqlalchemy.orm.Session,
) -> None:
    """Archie's version 3 lands not current over an edit; after a new text artifact, Archie's version 4 is current."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    target = versions.Target(kind=models.EditTarget.SUMMARY, id=source.id)
    versions.write(
        db, target=target, content={**SUMMARY, "gist": "Mine."}, origin=models.VersionOrigin.CHAT_EDIT,
        instruction=None, derived_from=1,
    )  # fmt: skip
    archie_content = {"summary": SUMMARY, "domain": "Finance", "tags": [], "cards": []}

    rewrite = pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.SUMMARY, content=archie_content, model="m", prompt_version="p"
    )
    assert (rewrite.version, rewrite.is_current) == (3, False)
    assert versions.current(db, target=target).content["gist"] == "Mine."

    # A newer text (a re-fetch, "Wrong episode?") means the owner's edit described other text.
    db.execute(sqlalchemy.text("SELECT pg_sleep(0.01)"))
    db.commit()
    changes.lock_user_writes(db, user_id)
    pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.TEXT, content={"text": "new"}, model=None, prompt_version=None
    )
    db.commit()
    changes.lock_user_writes(db, user_id)
    after_refetch = pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.SUMMARY, content=archie_content, model="m", prompt_version="p"
    )
    assert (after_refetch.version, after_refetch.is_current) == (4, True)
    assert [summary.is_current for summary in _summaries(db, source.id)] == [False, False, False, True]


def test_a_topic_primer_is_resolved_from_any_version_and_edits_carry_its_read_state(
    db: sqlalchemy.orm.Session,
) -> None:
    """A primer version id resolves to its topic; the edit becomes current and keeps the primer's opened_at."""
    user_id = _user(db)
    topic = models.Topic(
        id=uuid.uuid4(), user_id=user_id, domain="Macro", name="The Fed", origin=models.TopicOrigin.USER.value,
        change_seq=changes.next_change_seq(),
    )  # fmt: skip
    db.add(topic)
    db.flush()
    first = topic_primers.write(db, topic=topic, markdown="## The Fed\nIt sets rates.", model="m", prompt_version="p")
    first.opened_at = sqlalchemy.func.now()
    db.flush()

    target = versions.resolve(db, user_id=user_id, kind=models.EditTarget.TOPIC_PRIMER, item_id=first.id)
    assert target == versions.Target(kind=models.EditTarget.TOPIC_PRIMER, id=topic.id)
    assert versions.write(
        db, target=target, content={"markdown": "## The Fed\nIt sets short-term rates."},
        origin=models.VersionOrigin.CHAT_EDIT, instruction="Be precise", derived_from=1,
    ) == 2  # fmt: skip

    current = topic_primers.current(db, topic_id=topic.id)
    assert current is not None
    db.refresh(current)
    assert (current.version, current.origin, current.derived_from_id) == (2, "chat_edit", first.id)
    assert current.opened_at is not None
    assert versions.resolve(db, user_id=user_id + 1, kind=models.EditTarget.TOPIC_PRIMER, item_id=topic.id) is None


def test_a_take_edit_makes_a_take_version_and_rewrites_its_cards(db: sqlalchemy.orm.Session) -> None:
    """A chat edit of a take is version 2 (origin chat_edit, not cleaned) and queues take_cards and embed."""
    user_id = _user(db)
    take = models.Take(
        id=uuid.uuid4(), user_id=user_id, kind=models.TakeKind.OPINION.value, title="Rates", current_version=0,
        change_seq=changes.next_change_seq(),
    )  # fmt: skip
    db.add(take)
    db.flush()
    takes.add_version(
        db, take=take, version_id=uuid.uuid4(), body="Rates stay high.", raw_body="Rates stay high.", cleaned=False,
        origin=models.VersionOrigin.OWNER,
    )  # fmt: skip
    db.execute(sqlalchemy.delete(models.Job))
    target = versions.Target(kind=models.EditTarget.TAKE, id=take.id)

    assert versions.write(
        db, target=target, content={"markdown": "Rates stay high into 2027."}, origin=models.VersionOrigin.CHAT_EDIT,
        instruction="Add the year", derived_from=1,
    ) == 2  # fmt: skip

    version = takes.version_at(db, take_id=take.id, version=2)
    assert version is not None
    assert (version.body, version.raw_body, version.cleaned, version.origin) == (
        "Rates stay high into 2027.",
        "Rates stay high into 2027.",
        False,
        "chat_edit",
    )
    assert _queued(db) == [models.JobKind.TAKE_CARDS.value, models.JobKind.EMBED.value]
    assert versions.restore(db, target=target, version=1) == 3


def test_a_card_gets_versions_one_and_two_on_its_first_change(db: sqlalchemy.orm.Session) -> None:
    """The card as it was becomes version 1 (archie); the edit is version 2; the card keeps its schedule."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    card = models.Card(
        id=uuid.uuid4(), user_id=user_id, source_id=source.id, kind=models.CardKind.CONCEPT.value,
        question="What do fees do?", answer="They compound.", fsrs_state=models.FsrsState.REVIEW.value, reps=3,
        change_seq=changes.next_change_seq(),
    )  # fmt: skip
    db.add(card)
    db.flush()
    target = versions.Target(kind=models.EditTarget.CARD, id=card.id)

    versions.write(
        db, target=target, content={"question": "What do fees do?", "answer": "They compound over decades."},
        origin=models.VersionOrigin.CHAT_EDIT, instruction="Say over decades", derived_from=1,
    )  # fmt: skip
    versions.restore(db, target=target, version=1)

    rows = db.scalars(
        sqlalchemy.select(models.CardVersion)
        .where(models.CardVersion.card_id == card.id)
        .order_by(models.CardVersion.version)
    ).all()
    assert [(row.version, row.answer, row.origin) for row in rows] == [
        (1, "They compound.", "archie"),
        (2, "They compound over decades.", "chat_edit"),
        (3, "They compound.", "restore"),
    ]
    db.refresh(card)
    assert (card.version, card.answer, card.fsrs_state, card.reps) == (3, "They compound.", "review", 3)


def test_resolve_refuses_other_users_deleted_items_and_missing_content(db: sqlalchemy.orm.Session) -> None:
    """Another user's source, a deleted source, and a source with no primer are not targets."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)

    assert versions.resolve(db, user_id=user_id, kind=models.EditTarget.PRIMER, item_id=source.id) is None
    assert versions.resolve(db, user_id=user_id + 1, kind=models.EditTarget.SUMMARY, item_id=source.id) is None
    source.deleted_at = sqlalchemy.func.now()
    db.flush()
    assert versions.resolve(db, user_id=user_id, kind=models.EditTarget.SUMMARY, item_id=source.id) is None
    assert versions.resolve(db, user_id=user_id, kind=models.EditTarget.CARD, item_id=uuid.uuid4()) is None
