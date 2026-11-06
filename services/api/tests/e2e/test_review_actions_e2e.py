"""Review actions through the real API: graded answers, dropping a card, cards off for a source, the weekly quiz."""

import datetime
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api.sync import review_actions, rows
from archie_db import briefs, card_rows, changes, models, pipeline, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

_NOW = datetime.datetime(2026, 11, 5, 12, 0, tzinfo=datetime.UTC)
_NEW_STATE: dict[str, Any] = {
    "fsrs_state": "new",
    "stability": None,
    "difficulty": None,
    "due_at": None,
    "last_review_at": None,
    "reps": 0,
    "lapses": 0,
}


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a fresh user."""
    return live_stack.authed(live_stack.sign_in())


def test_review_card_stores_the_review_and_the_cards_new_state(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The review keeps grade, grader, answer, missing, was_due and both states; a pull shows the card's new state."""
    user_id = _user_id(authed)
    card_id = _add_card(live_stack, user_id=user_id)
    review_id = uuid.uuid4()

    [result] = _push(authed, _review(card_id, review_id=review_id, grade="partly", answer="mine", missing="the rest"))

    assert result["result"] == models.ActionResult.APPLIED.value
    [review] = _reviews(live_stack, card_id)
    assert (review.id, review.grade, review.graded_by, review.answer, review.missing, review.was_due) == (
        review_id,
        "partly",
        "model",
        "mine",
        "the rest",
        True,
    )
    assert review.reviewed_at == _NOW
    assert review.state_before == _NEW_STATE
    # The state is stored as the server serializes it ("Z" for UTC), so the expected instants are spelled the same way.
    assert review.state_after == _state(stability=2.5, days=3, reps=1) | {
        "due_at": "2026-11-08T12:00:00Z",
        "last_review_at": "2026-11-05T12:00:00Z",
    }
    pulled = _pulled_card(authed, card_id)
    assert (pulled["fsrs_state"], pulled["stability"], pulled["difficulty"], pulled["reps"], pulled["lapses"]) == (
        "review",
        2.5,
        5.0,
        1,
        0,
    )
    assert pulled["due_at"].startswith("2026-11-08T12:00:00")
    assert pulled["last_review_at"].startswith("2026-11-05T12:00:00")


def test_review_card_logs_an_older_review_but_ignores_its_state(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A late upload from another phone can't roll the schedule back."""
    card_id = _add_card(live_stack, user_id=_user_id(authed))
    later = _review(card_id, reviewed_at=_NOW, state_after=_state(stability=9.0, days=20, reps=2))
    earlier = _review(card_id, reviewed_at=_NOW - datetime.timedelta(days=1), state_after=_state(stability=1.0, days=1))

    results = _push(authed, later, earlier)

    assert [result["result"] for result in results] == ["applied", "applied"]
    assert len(_reviews(live_stack, card_id)) == 2
    pulled = _pulled_card(authed, card_id)
    assert (pulled["stability"], pulled["reps"]) == (9.0, 2)


def test_review_card_is_idempotent_by_review_id_and_by_action_id(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The same review under a new action id is applied once; the same action id again is a duplicate."""
    card_id = _add_card(live_stack, user_id=_user_id(authed))
    review_id = uuid.uuid4()
    first = _review(card_id, review_id=review_id)

    [applied] = _push(authed, first)
    [resent_action] = _push(authed, first)
    [resent_review] = _push(authed, _review(card_id, review_id=review_id))

    assert applied["result"] == "applied"
    assert resent_action["result"] == "duplicate"
    assert resent_review["result"] == "applied"
    assert len(_reviews(live_stack, card_id)) == 1


def test_review_card_refuses_a_review_id_that_belongs_to_another_card(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A review id already used on a different card is not a re-send, and writes nothing."""
    user_id = _user_id(authed)
    card_id = _add_card(live_stack, user_id=user_id)
    other_card_id = _add_card(live_stack, user_id=user_id)
    review_id = uuid.uuid4()
    _push(authed, _review(card_id, review_id=review_id))

    [result] = _push(authed, _review(other_card_id, review_id=review_id))

    assert (result["result"], result["reason"]) == ("rejected", "review id already used")
    assert _reviews(live_stack, other_card_id) == []


def test_review_card_refuses_a_review_id_that_belongs_to_another_user(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Another user's review id is not a re-send of this user's."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    other_card_id = _add_card(live_stack, user_id=_user_id(other))
    card_id = _add_card(live_stack, user_id=_user_id(authed))
    review_id = uuid.uuid4()
    _push(other, _review(other_card_id, review_id=review_id))

    [result] = _push(authed, _review(card_id, review_id=review_id))

    assert (result["result"], result["reason"]) == ("rejected", "review id already used")
    assert _reviews(live_stack, card_id) == []


def test_i_actually_knew_it_replaces_the_state_of_the_review_it_overrides(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A later review naming the first overwrites the state; one naming another card's review is rejected."""
    user_id = _user_id(authed)
    card_id = _add_card(live_stack, user_id=user_id)
    other_card_id = _add_card(live_stack, user_id=user_id)
    first_id, other_review_id = uuid.uuid4(), uuid.uuid4()
    _push(
        authed,
        _review(card_id, review_id=first_id, grade="missed", state_after=_state(stability=0.5, days=1)),
        _review(other_card_id, review_id=other_review_id),
    )

    results = _push(
        authed,
        _review(
            card_id,
            grade="got_it",
            graded_by="self",
            reviewed_at=_NOW + datetime.timedelta(seconds=30),
            state_after=_state(stability=4.0, days=6),
            replaces_review_id=first_id,
        ),
        _review(card_id, replaces_review_id=other_review_id),
        _review(card_id, replaces_review_id=uuid.uuid4()),
    )

    assert [result["result"] for result in results] == ["applied", "rejected", "rejected"]
    assert results[1]["reason"] == results[2]["reason"] == "replaced review not found"
    assert _pulled_card(authed, card_id)["stability"] == 4.0
    assert len(_reviews(live_stack, card_id)) == 2


def test_review_card_refuses_other_users_deleted_and_malformed_cards(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Only a live card of the user can be reviewed, with a well-formed state."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    others = _add_card(live_stack, user_id=_user_id(other))
    deleted = _add_card(live_stack, user_id=_user_id(authed), deleted=True)
    live = _add_card(live_stack, user_id=_user_id(authed))
    bad_state = _state(stability=1.0, days=1) | {"reps": -1}

    results = _push(
        authed,
        _review(others),
        _review(deleted),
        _review(live, state_after=bad_state),
        _action("review_card", {"id": str(live)}),
    )

    assert [(result["result"], result["reason"]) for result in results] == [
        ("rejected", review_actions.NO_CARD),
        ("rejected", review_actions.NO_CARD),
        ("rejected", rows.MALFORMED),
        ("rejected", rows.MALFORMED),
    ]
    assert _reviews(live_stack, live) == []


def test_drop_card_retires_the_card_and_remembers_its_question(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A pull shows the card deleted, and a `drop` preference holds the question as its note."""
    user_id = _user_id(authed)
    card_id = _add_card(live_stack, user_id=user_id)
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    others = _add_card(live_stack, user_id=_user_id(other))

    results = _push(authed, _action("drop_card", {"id": str(card_id)}), _action("drop_card", {"id": str(others)}))

    assert [result["result"] for result in results] == ["applied", "rejected"]
    assert results[1]["reason"] == review_actions.NO_CARD
    assert _pulled_card(authed, card_id)["deleted_at"] is not None
    assert _preferences(live_stack, user_id) == [(models.CardPreferenceKind.DROP.value, "Why?", card_id)]
    # Dropping a card that is already gone is refused, so it leaves no second preference.
    [again] = _push(authed, _action("drop_card", {"id": str(card_id)}))
    assert again["reason"] == review_actions.NO_CARD
    assert len(_preferences(live_stack, user_id)) == 1


def test_cards_off_retires_the_sources_cards_and_leaves_other_sources(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Summary and foundation cards of the source go; another source's cards stay."""
    user_id = _user_id(authed)
    source_id = _add_source(live_stack, user_id=user_id)
    other_source_id = _add_source(live_stack, user_id=user_id)
    summary = _add_card(live_stack, user_id=user_id, source_id=source_id, kind=models.CardKind.CONCEPT)
    foundation = _add_card(live_stack, user_id=user_id, source_id=source_id, kind=models.CardKind.FOUNDATION)
    kept = _add_card(live_stack, user_id=user_id, source_id=other_source_id)

    [result] = _push(authed, _action("set_cards_off", {"id": str(source_id), "off": True}))

    assert result["result"] == "applied"
    pulled = {row["id"]: row for row in _rows(authed)["cards"]}
    assert pulled[str(summary)]["deleted_at"] is not None
    assert pulled[str(foundation)]["deleted_at"] is not None
    assert pulled[str(kept)]["deleted_at"] is None
    assert _source(authed, source_id)["cards_off"] is True
    assert _analyze_jobs(live_stack, source_id) == 0


def test_cards_on_requeues_analysis_once_and_only_for_a_source_with_text(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Cards on clears the flag and queues one analyze; a queued analyze or a missing text artifact queues none."""
    user_id = _user_id(authed)
    with_text = _add_source(live_stack, user_id=user_id, cards_off=True, with_text=True)
    pending = _add_source(live_stack, user_id=user_id, cards_off=True, with_text=True, pending_analyze=True)
    without_text = _add_source(live_stack, user_id=user_id, cards_off=True)

    results = _push(
        authed,
        *[_action("set_cards_off", {"id": str(sid), "off": False}) for sid in (with_text, pending, without_text)],
    )

    assert [result["result"] for result in results] == ["applied"] * 3
    assert _analyze_jobs(live_stack, with_text) == 1
    assert _analyze_jobs(live_stack, pending) == 1
    assert _analyze_jobs(live_stack, without_text) == 0
    assert _source(authed, with_text)["cards_off"] is False
    assert _source(authed, with_text)["processing"] == models.ProcessingStatus.PROCESSING.value
    assert _source(authed, without_text)["cards_off"] is False
    assert _source(authed, without_text)["processing"] == models.ProcessingStatus.READY.value
    [missing] = _push(authed, _action("set_cards_off", {"id": str(uuid.uuid4()), "off": True}))
    assert missing["reason"] == rows.NO_SOURCE
    [malformed] = _push(authed, _action("set_cards_off", {"id": str(with_text)}))
    assert malformed["reason"] == rows.MALFORMED


def test_go_deeper_clears_cards_off(live_stack: LiveStack, authed: httpx.Client) -> None:
    """ "Make review cards" on an inbox newsletter goes through go_deeper, which undoes "No cards for this"."""
    source_id = _add_source(live_stack, user_id=_user_id(authed), cards_off=True)

    [result] = _push(authed, _action("go_deeper", {"id": str(source_id)}))

    assert result["result"] == "applied"
    assert _source(authed, source_id)["cards_off"] is False


def test_request_news_quiz_queues_one_job_per_week_when_a_brief_was_done_recently(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Asked again for the same week it is applied without a second job; another week queues another."""
    user_id = _user_id(authed)
    _add_done_brief(live_stack, user_id=user_id, days_ago=2)

    results = _push(authed, _quiz("2026-11-01"), _quiz("2026-11-01"), _quiz("2026-11-08"))

    assert [result["result"] for result in results] == ["applied"] * 3
    assert _quiz_payloads(live_stack, user_id) == [
        {briefs.USER_ID_KEY: user_id, card_rows.WEEK_START_KEY: "2026-11-01"},
        {briefs.USER_ID_KEY: user_id, card_rows.WEEK_START_KEY: "2026-11-08"},
    ]
    [malformed] = _push(authed, _action("request_news_quiz", {"week_start": "soon"}))
    assert malformed["reason"] == rows.MALFORMED


def test_request_news_quiz_needs_a_brief_done_in_the_last_seven_days(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """No brief, or one done eight days ago, is applied but queues nothing."""
    user_id = _user_id(authed)
    [without_brief] = _push(authed, _quiz("2026-11-01"))
    _add_done_brief(live_stack, user_id=user_id, days_ago=8)
    [with_old_brief] = _push(authed, _quiz("2026-11-01"))

    assert (without_brief["result"], with_old_brief["result"]) == ("applied", "applied")
    assert _quiz_payloads(live_stack, user_id) == []


def test_request_news_quiz_may_be_asked_again_after_the_weeks_job_failed(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A failed quiz job doesn't count as made, so asking again queues a new one."""
    user_id = _user_id(authed)
    _add_done_brief(live_stack, user_id=user_id, days_ago=1)
    _push(authed, _quiz("2026-11-01"))
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        db.execute(
            sqlalchemy.update(models.Job)
            .where(models.Job.kind == models.JobKind.NEWS_QUIZ.value)
            .values(status=models.JobStatus.FAILED.value)
        )
        db.commit()

    _push(authed, _quiz("2026-11-01"))

    assert len(_quiz_payloads(live_stack, user_id)) == 2


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _state(*, stability: float, days: int, reps: int = 1) -> dict[str, Any]:
    return {
        "fsrs_state": "review",
        "stability": stability,
        "difficulty": 5.0,
        "due_at": (_NOW + datetime.timedelta(days=days)).isoformat(),
        "last_review_at": _NOW.isoformat(),
        "reps": reps,
        "lapses": 0,
    }


def _review(
    card_id: uuid.UUID,
    *,
    review_id: uuid.UUID | None = None,
    grade: str = "got_it",
    graded_by: str = "model",
    answer: str | None = None,
    missing: str | None = None,
    reviewed_at: datetime.datetime = _NOW,
    state_after: dict[str, Any] | None = None,
    replaces_review_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return _action(
        "review_card",
        {
            "id": str(card_id),
            "review_id": str(review_id or uuid.uuid4()),
            "grade": grade,
            "graded_by": graded_by,
            "answer": answer,
            "missing": missing,
            "was_due": True,
            "reviewed_at": reviewed_at.isoformat(),
            "state_before": _NEW_STATE,
            "state_after": state_after or _state(stability=2.5, days=3),
            "replaces_review_id": str(replaces_review_id) if replaces_review_id else None,
        },
    )


def _quiz(week_start: str) -> dict[str, Any]:
    return _action("request_news_quiz", {"week_start": week_start})


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _pulled_card(authed: httpx.Client, card_id: uuid.UUID) -> dict[str, Any]:
    return next(row for row in _rows(authed)["cards"] if row["id"] == str(card_id))


def _source(authed: httpx.Client, source_id: uuid.UUID) -> dict[str, Any]:
    return next(row for row in _rows(authed)["sources"] if row["id"] == str(source_id))


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _add_source(
    live_stack: LiveStack,
    *,
    user_id: int,
    cards_off: bool = False,
    with_text: bool = False,
    pending_analyze: bool = False,
) -> uuid.UUID:
    """A ready inbox newsletter, optionally with cards off, a text artifact, or an analyze job already queued."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=f"https://example.com/{uuid.uuid4()}",
            normalized_url=f"https://example.com/{uuid.uuid4()}",
            kind=models.SourceKind.NEWSLETTER.value,
            state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value,
            processing=models.ProcessingStatus.READY.value,
            cards_off=cards_off,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        if with_text:
            db.add(
                models.SourceArtifact(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    source_id=source.id,
                    kind=models.ArtifactKind.TEXT.value,
                    version=1,
                    content={"text": "Some text."},
                    is_current=True,
                    change_seq=changes.next_change_seq(),
                )
            )
        if pending_analyze:
            pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.ANALYZE])
        db.commit()
        return source.id


def _add_card(
    live_stack: LiveStack,
    *,
    user_id: int,
    source_id: uuid.UUID | None = None,
    kind: models.CardKind = models.CardKind.CONCEPT,
    deleted: bool = False,
) -> uuid.UUID:
    """A new card; without a source it belongs to a fresh one."""
    source_id = source_id or _add_source(live_stack, user_id=user_id)
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        card = models.Card(
            id=uuid.uuid4(),
            user_id=user_id,
            source_id=source_id,
            kind=kind.value,
            question="Why?",
            answer="Because.",
            deleted_at=_NOW if deleted else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(card)
        db.commit()
        return card.id


def _add_done_brief(live_stack: LiveStack, *, user_id: int, days_ago: int) -> None:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Brief(
                id=uuid.uuid4(),
                user_id=user_id,
                status=models.BriefStatus.DONE.value,
                content={"domains": [], "also": [], "essays": []},
                source_ids=[],
                since=_NOW,
                version=3,
                done_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago),
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()


def _reviews(live_stack: LiveStack, card_id: uuid.UUID) -> list[models.Review]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine, expire_on_commit=False) as db:
        return list(
            db.scalars(
                sqlalchemy.select(models.Review)
                .where(models.Review.card_id == card_id)
                .order_by(models.Review.created_at)
            )
        )


def _preferences(live_stack: LiveStack, user_id: int) -> list[tuple[str, str, uuid.UUID | None]]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return [
            (preference.kind, preference.note, preference.card_id)
            for preference in db.scalars(
                sqlalchemy.select(models.CardPreference).where(models.CardPreference.user_id == user_id)
            )
        ]


def _analyze_jobs(live_stack: LiveStack, source_id: uuid.UUID) -> int:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return len(
            db.scalars(
                sqlalchemy.select(models.Job).where(
                    models.Job.kind == models.JobKind.ANALYZE.value,
                    models.Job.payload["source_id"].astext == str(source_id),
                )
            ).all()
        )


def _quiz_payloads(live_stack: LiveStack, user_id: int) -> list[dict[str, Any]]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return [
            job.payload
            for job in db.scalars(
                sqlalchemy.select(models.Job)
                .where(models.Job.kind == models.JobKind.NEWS_QUIZ.value, models.Job.user_id == user_id)
                .order_by(models.Job.id)
            )
        ]
