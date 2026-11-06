"""Review rows through the real API: a pull sends every card origin with its FSRS state, and sources' cards-off flag."""

import datetime
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session
from archie_shared import domains
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

_DUE_AT = datetime.datetime(2026, 11, 9, 20, 30, tzinfo=datetime.UTC)
_LAST_REVIEW_AT = datetime.datetime(2026, 11, 4, 20, 30, tzinfo=datetime.UTC)
_EXPIRES_AT = datetime.datetime(2026, 11, 12, 9, 0, tzinfo=datetime.UTC)


@dataclass(frozen=True)
class _Seeded:
    source_id: uuid.UUID
    summary_card_id: uuid.UUID
    topic_primer_id: uuid.UUID
    foundation_card_id: uuid.UUID
    brief_id: uuid.UUID
    quiz_card_id: uuid.UUID


def test_a_pull_sends_cards_of_every_origin_with_their_schedule(live_stack: LiveStack) -> None:
    """A summary card, a topic-primer foundation card and a brief quiz card each carry their one origin."""
    authed = live_stack.authed(live_stack.sign_in())
    seeded = _seed(live_stack, user_id=authed.get("/me").json()["user_id"])

    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]

    cards = {row["id"]: row for row in rows["cards"]}
    assert set(cards) == {str(seeded.summary_card_id), str(seeded.foundation_card_id), str(seeded.quiz_card_id)}
    assert _without_positions(cards[str(seeded.summary_card_id)]) == {
        "id": str(seeded.summary_card_id),
        "source_id": str(seeded.source_id),
        "topic_primer_id": None,
        "brief_id": None,
        "kind": models.CardKind.CONCEPT.value,
        "question": "Why?",
        "answer": "Because.",
        "fsrs_state": models.FsrsState.REVIEW.value,
        "stability": 4.5,
        "difficulty": 6.25,
        "due_at": "2026-11-09T20:30:00Z",
        "last_review_at": "2026-11-04T20:30:00Z",
        "reps": 3,
        "lapses": 1,
        "expires_at": None,
        "deleted_at": None,
    }

    foundation = cards[str(seeded.foundation_card_id)]
    assert (foundation["source_id"], foundation["topic_primer_id"], foundation["brief_id"]) == (
        None,
        str(seeded.topic_primer_id),
        None,
    )
    assert (foundation["kind"], foundation["fsrs_state"], foundation["reps"], foundation["due_at"]) == (
        models.CardKind.FOUNDATION.value,
        models.FsrsState.NEW.value,
        0,
        None,
    )

    quiz = cards[str(seeded.quiz_card_id)]
    assert (quiz["source_id"], quiz["topic_primer_id"], quiz["brief_id"]) == (None, None, str(seeded.brief_id))
    assert (quiz["kind"], quiz["expires_at"]) == (models.CardKind.QUIZ.value, "2026-11-12T09:00:00Z")

    [source] = rows["sources"]
    assert source["cards_off"] is True


def _without_positions(row: dict[str, Any]) -> dict[str, Any]:
    """The row minus the server-assigned `created_at` and `change_seq`, which the test can't predict."""
    assert row["created_at"] is not None
    assert isinstance(row["change_seq"], int)
    return {key: value for key, value in row.items() if key not in {"created_at", "change_seq"}}


def _seed(live_stack: LiveStack, *, user_id: int) -> _Seeded:
    """One card per origin: a cards-off source's summary, a topic's primer, and a done brief."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)

        # A source the user turned cards off for, still holding a scheduled summary card.
        url = f"https://example.com/{uuid.uuid4()}"
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=url,
            normalized_url=url,
            kind=models.SourceKind.ARTICLE.value,
            state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value,
            processing=models.ProcessingStatus.READY.value,
            cards_off=True,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        summary = pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY, content={}, model=None, prompt_version=None
        )
        summary_card = _card(
            user_id=user_id,
            kind=models.CardKind.CONCEPT,
            source_id=source.id,
            artifact_id=summary.id,
            fsrs_state=models.FsrsState.REVIEW.value,
            stability=4.5,
            difficulty=6.25,
            due_at=_DUE_AT,
            last_review_at=_LAST_REVIEW_AT,
            reps=3,
            lapses=1,
        )

        # A topic primer's foundation card and a done brief's quiz card have no source.
        topic = models.Topic(
            id=uuid.uuid4(),
            user_id=user_id,
            domain=domains.Domain.MACRO.value,
            name=f"Rates {uuid.uuid4()}",
            origin=models.TopicOrigin.USER.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(topic)
        db.flush()
        topic_primer = models.TopicPrimer(
            id=uuid.uuid4(),
            user_id=user_id,
            topic_id=topic.id,
            version=1,
            is_current=True,
            content={"markdown": "# Rates"},
            change_seq=changes.next_change_seq(),
        )
        brief = models.Brief(
            id=uuid.uuid4(),
            user_id=user_id,
            status=models.BriefStatus.DONE.value,
            done_at=sqlalchemy.func.now(),
            change_seq=changes.next_change_seq(),
        )
        db.add_all([topic_primer, brief])
        db.flush()
        foundation_card = _card(user_id=user_id, kind=models.CardKind.FOUNDATION, topic_primer_id=topic_primer.id)
        quiz_card = _card(user_id=user_id, kind=models.CardKind.QUIZ, brief_id=brief.id, expires_at=_EXPIRES_AT)

        db.add_all([summary_card, foundation_card, quiz_card])
        db.commit()
        return _Seeded(
            source_id=source.id,
            summary_card_id=summary_card.id,
            topic_primer_id=topic_primer.id,
            foundation_card_id=foundation_card.id,
            brief_id=brief.id,
            quiz_card_id=quiz_card.id,
        )


def _card(*, user_id: int, kind: models.CardKind, **fields: Any) -> models.Card:
    return models.Card(
        id=uuid.uuid4(),
        user_id=user_id,
        kind=kind.value,
        question="Why?",
        answer="Because.",
        change_seq=changes.next_change_seq(),
        **fields,
    )
