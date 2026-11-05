"""Reading-state actions through the real API: finish, primers, read, opened, snooze, queue, deeper, later, delete."""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session, user_topics
from archie_shared import domains
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

SNOOZE_UNTIL = "2030-01-02T09:00:00+00:00"


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _source(authed: httpx.Client, source_id: str) -> dict[str, Any]:
    return next(row for row in _rows(authed)["sources"] if row["id"] == source_id)


def _add(authed: httpx.Client, *, intent: str = "queue") -> str:
    source_id = str(uuid.uuid4())
    url = f"https://example.com/{source_id}"
    _push(authed, _action("add_source", {"id": source_id, "url": url, "intent": intent}))
    return source_id


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _insert_source(
    live_stack: LiveStack,
    *,
    user_id: int,
    kind: models.SourceKind,
    state: models.SourceState,
    processing: models.ProcessingStatus,
    with_card: bool = False,
    with_primer: bool = False,
) -> str:
    """A source the API can't create itself (a ready inbox newsletter), optionally with a live card or a primer."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=f"https://example.com/{uuid.uuid4()}",
            normalized_url=f"https://example.com/{uuid.uuid4()}",
            kind=kind.value,
            state=state.value,
            intent="queue",
            processing=processing.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        if with_primer:
            db.add(
                models.SourceArtifact(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    source_id=source.id,
                    kind=models.ArtifactKind.PRIMER.value,
                    version=1,
                    content={"markdown": "# Primer"},
                    is_current=True,
                    change_seq=changes.next_change_seq(),
                )
            )
        if with_card:
            artifact = models.SourceArtifact(
                id=uuid.uuid4(),
                user_id=user_id,
                source_id=source.id,
                kind=models.ArtifactKind.SUMMARY.value,
                version=1,
                content={},
                is_current=True,
                change_seq=changes.next_change_seq(),
            )
            db.add(artifact)
            db.flush()
            db.add(
                models.Card(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    source_id=source.id,
                    artifact_id=artifact.id,
                    kind="concept",
                    question="q",
                    answer="a",
                    change_seq=changes.next_change_seq(),
                )
            )
        db.commit()
        return str(source.id)


def _insert_topic_primer(live_stack: LiveStack, *, user_id: int) -> str:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        topic = user_topics.create_topic(
            db, user_id=user_id, domain=domains.Domain.AI, name="Topic", origin=models.TopicOrigin.USER
        )
        primer = models.TopicPrimer(
            id=uuid.uuid4(),
            user_id=user_id,
            topic_id=topic.id,
            version=1,
            is_current=True,
            content={"markdown": "# x"},
            change_seq=changes.next_change_seq(),
        )
        db.add(primer)
        db.commit()
        return str(primer.id)


def _jobs(live_stack: LiveStack, source_id: str) -> list[str]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        jobs = db.scalars(
            sqlalchemy.select(models.Job)
            .where(models.Job.payload["source_id"].astext == source_id)
            .order_by(models.Job.id)
        )
        return [job.kind for job in jobs]


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a fresh user."""
    return live_stack.authed(live_stack.sign_in())


def test_finish_marks_consumed_with_reaction_and_note(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Finishing a queued source consumes it; "lost" alone queues nothing; a second finish is refused."""
    source_id = _add(authed)
    seq_before = _source(authed, source_id)["change_seq"]
    jobs_before = _jobs(live_stack, source_id)

    results = _push(authed, _action("finish_source", {"id": source_id, "reaction": "lost", "note": "hard"}))
    again = _push(authed, _action("finish_source", {"id": source_id}))

    row = _source(authed, source_id)
    assert results[0]["result"] == "applied"
    assert (row["state"], row["reaction"], row["note"]) == ("consumed", "lost", "hard")
    assert row["primer_queue_position"] is None
    assert row["change_seq"] > seq_before
    assert _jobs(live_stack, source_id) == jobs_before
    assert again[0] == {"id": again[0]["id"], "result": "rejected", "reason": "source is not queued"}


def test_finish_with_queue_primer_puts_the_primer_at_the_top_of_the_queue(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """An article's primer is queued above every other entry; an article is not analyzed again."""
    source_id = _add(authed)
    other = _add(authed)
    jobs_before = _jobs(live_stack, source_id)

    _push(authed, _action("finish_source", {"id": source_id, "reaction": "lost", "queue_primer": True}))

    row = _source(authed, source_id)
    assert row["state"] == "consumed"
    assert row["primer_queue_position"] < _source(authed, other)["queue_position"]
    assert _jobs(live_stack, source_id) == jobs_before


def test_finishing_a_queued_newsletter_analyzes_it_again_and_writes_a_requested_primer(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A finished newsletter is re-analyzed (so it gets cards); queueing its missing primer also writes one."""
    user_id = _user_id(authed)
    plain = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.QUEUED,
        processing=models.ProcessingStatus.READY,
    )
    with_primer = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.QUEUED,
        processing=models.ProcessingStatus.READY,
    )

    _push(
        authed,
        _action("finish_source", {"id": plain}),
        _action("finish_source", {"id": with_primer, "queue_primer": True}),
    )

    plain_row, primed_row = _source(authed, plain), _source(authed, with_primer)
    assert (plain_row["state"], plain_row["processing"], plain_row["primer_queue_position"]) == (
        "consumed",
        "processing",
        None,
    )
    assert _jobs(live_stack, plain) == ["analyze"]
    assert (primed_row["processing"], primed_row["primer_queue_position"]) == ("processing", 0)
    assert _jobs(live_stack, with_primer) == ["analyze", "primer"]


def test_a_repeated_action_is_a_duplicate_and_changes_nothing(authed: httpx.Client) -> None:
    """The same action id twice answers `duplicate` and the row's change_seq stays put."""
    source_id = _add(authed)
    action = _action("queue_primer", {"id": source_id, "queued": True})

    first = _push(authed, action)[0]
    row = _source(authed, source_id)
    second = _push(authed, action)[0]

    assert (first["result"], second["result"]) == ("applied", "duplicate")
    assert _source(authed, source_id)["change_seq"] == row["change_seq"]
    assert _source(authed, source_id)["primer_queue_position"] == row["primer_queue_position"] == -1


def test_another_users_source_is_not_found(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Every source action on someone else's id is rejected as `source not found`."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    source_id = _add(authed)
    payloads: list[tuple[str, dict[str, Any]]] = [
        ("finish_source", {"id": source_id}),
        ("queue_primer", {"id": source_id, "queued": True}),
        ("request_primer", {"id": source_id}),
        ("return_to_inbox", {"id": source_id}),
        ("set_read", {"id": source_id, "read": True}),
        ("set_primer_opened", {"target": "source", "id": source_id, "opened": True}),
        ("snooze", {"target": "source", "id": source_id, "until": SNOOZE_UNTIL}),
        ("snooze", {"target": "source_primer", "id": source_id, "until": SNOOZE_UNTIL}),
        ("set_queue_position", {"id": source_id, "position": 3}),
        ("set_queue_position", {"id": source_id, "target": "source_primer", "position": 3}),
        ("go_deeper", {"id": source_id}),
        ("read_later", {"id": source_id}),
        ("delete_source", {"id": source_id}),
    ]

    results = _push(other, *[_action(kind, payload) for kind, payload in payloads])

    assert {result["reason"] for result in results} == {"source not found"}
    assert _source(authed, source_id)["deleted_at"] is None


def test_a_source_queue_position_applies_to_queued_sources_only(authed: httpx.Client) -> None:
    """The default target writes a queued source's position and is refused once it is consumed."""
    source_id = _add(authed)

    applied = _push(authed, _action("set_queue_position", {"id": source_id, "position": 2.5}))
    _push(authed, _action("finish_source", {"id": source_id}))
    refused = _push(authed, _action("set_queue_position", {"id": source_id, "target": "source", "position": 9}))

    assert applied[0]["result"] == "applied"
    assert refused[0]["reason"] == "source is not queued"
    assert _source(authed, source_id)["queue_position"] == 2.5


def test_a_primer_queue_position_needs_a_queued_primer(authed: httpx.Client) -> None:
    """`source_primer` moves only the primer's entry, and only while the primer is queued."""
    source_id = _add(authed)
    move_primer = {"id": source_id, "target": "source_primer"}
    refused = _push(authed, _action("set_queue_position", {**move_primer, "position": 1}))

    _push(authed, _action("queue_primer", {"id": source_id, "queued": True}))
    applied = _push(authed, _action("set_queue_position", {**move_primer, "position": 7.5}))

    row = _source(authed, source_id)
    assert refused[0]["reason"] == "primer is not queued"
    assert applied[0]["result"] == "applied"
    assert (row["queue_position"], row["primer_queue_position"]) == (0, 7.5)


def test_queued_sources_and_queued_primers_share_one_top_of_the_queue(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Each new entry goes above the lowest position of either kind: source, primer, then an inbox item read later."""
    first = _add(authed)
    _push(authed, _action("queue_primer", {"id": first, "queued": True}))
    inbox = _insert_source(
        live_stack,
        user_id=_user_id(authed),
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
    )
    _push(authed, _action("read_later", {"id": inbox}))
    second = _add(authed)

    assert _source(authed, first)["queue_position"] == 0
    assert _source(authed, first)["primer_queue_position"] == -1
    assert _source(authed, inbox)["queue_position"] == -2
    assert _source(authed, second)["queue_position"] == -3


def test_queue_primer_queues_and_unqueues_and_clears_a_snooze(authed: httpx.Client) -> None:
    """Queueing puts the primer at the top unsnoozed; `queued: false` takes it out; a deleted source is refused."""
    source_id = _add(authed)
    _push(
        authed,
        _action("queue_primer", {"id": source_id, "queued": True}),
        _action("snooze", {"target": "source_primer", "id": source_id, "until": SNOOZE_UNTIL}),
        _action("queue_primer", {"id": source_id, "queued": True}),
    )
    requeued = _source(authed, source_id)

    _push(authed, _action("queue_primer", {"id": source_id, "queued": False}))
    unqueued = _source(authed, source_id)
    _push(authed, _action("delete_source", {"id": source_id}))
    refused = _push(authed, _action("queue_primer", {"id": source_id, "queued": True}))

    assert requeued["primer_snoozed_until"] is None
    assert requeued["primer_queue_position"] == -3
    assert unqueued["primer_queue_position"] is None
    assert unqueued["change_seq"] > requeued["change_seq"]
    assert refused[0]["reason"] == "source not found"


def test_queueing_a_newsletters_missing_primer_writes_it_once(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A newsletter without a primer gets one job and shows processing; one with a primer or a job on its way none."""
    user_id = _user_id(authed)
    without = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
    )
    primed = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
        with_primer=True,
    )

    _push(
        authed,
        _action("queue_primer", {"id": without, "queued": True}),
        _action("queue_primer", {"id": without, "queued": False}),
        _action("queue_primer", {"id": without, "queued": True}),
        _action("queue_primer", {"id": primed, "queued": True}),
    )

    assert (_source(authed, without)["processing"], _jobs(live_stack, without)) == ("processing", ["primer"])
    primed_row = _source(authed, primed)
    assert (primed_row["processing"], primed_row["primer_queue_position"]) == ("ready", -1)
    assert _jobs(live_stack, primed) == []


def test_request_primer_writes_a_ready_newsletters_missing_primer_only(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A ready newsletter without a primer gets a primer job; an article, a busy one and a primed one are refused."""
    user_id = _user_id(authed)

    def newsletter(processing: models.ProcessingStatus, *, with_primer: bool = False) -> str:
        return _insert_source(
            live_stack,
            user_id=user_id,
            kind=models.SourceKind.NEWSLETTER,
            state=models.SourceState.INBOX,
            processing=processing,
            with_primer=with_primer,
        )

    ready = newsletter(models.ProcessingStatus.READY)
    busy = newsletter(models.ProcessingStatus.PROCESSING)
    primed = newsletter(models.ProcessingStatus.READY, with_primer=True)
    article = _add(authed)

    results = _push(authed, *[_action("request_primer", {"id": source}) for source in (ready, busy, primed, article)])

    assert results[0]["result"] == "applied"
    assert [result["reason"] for result in results[1:]] == [
        "source is not ready",
        "source already has a primer",
        "source is not a newsletter",
    ]
    assert (_source(authed, ready)["processing"], _jobs(live_stack, ready)) == ("processing", ["primer"])
    assert _source(authed, ready)["primer_queue_position"] is None
    assert _jobs(live_stack, busy) == _jobs(live_stack, primed) == []


def test_return_to_inbox_undoes_adding_a_newsletter_to_the_queue(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A newsletter read later goes back to the inbox with no position; an article or an inbox item is refused."""
    inbox = _insert_source(
        live_stack,
        user_id=_user_id(authed),
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
    )
    article = _add(authed)

    _push(authed, _action("read_later", {"id": inbox}))
    results = _push(
        authed,
        _action("return_to_inbox", {"id": inbox}),
        _action("return_to_inbox", {"id": inbox}),
        _action("return_to_inbox", {"id": article}),
    )

    row = _source(authed, inbox)
    assert (row["state"], row["queue_position"]) == ("inbox", None)
    assert results[0]["result"] == "applied"
    assert [result["reason"] for result in results[1:]] == ["source is not queued", "source is not a newsletter"]
    assert _source(authed, article)["state"] == "queued"


def test_an_infinite_queue_position_is_malformed(authed: httpx.Client) -> None:
    """`Infinity` can't be a position."""
    source_id = _add(authed)

    result = _push(authed, _action("set_queue_position", {"id": source_id, "position": "Infinity"}))[0]

    assert result["reason"] == "payload is malformed"


def test_snoozing_a_queued_source_moves_it_to_the_top_and_null_clears_it(authed: httpx.Client) -> None:
    """A snoozed queued source sits below every other position number; `until: null` unsnoozes."""
    first = _add(authed)
    second = _add(authed)
    lowest_other = min(_source(authed, first)["queue_position"], _source(authed, second)["queue_position"])

    _push(authed, _action("snooze", {"target": "source", "id": first, "until": SNOOZE_UNTIL}))
    snoozed = _source(authed, first)
    _push(authed, _action("snooze", {"target": "source", "id": first, "until": None}))

    assert snoozed["snoozed_until"].startswith("2030-01-02T09:00:00")
    assert snoozed["queue_position"] < lowest_other
    assert _source(authed, first)["snoozed_until"] is None


def test_snoozing_a_queued_primer_moves_only_the_primer_to_the_top(authed: httpx.Client) -> None:
    """The primer's own snooze is set and its entry goes above everything; the source's snooze and place stay."""
    source_id = _add(authed)
    other = _add(authed)
    _push(authed, _action("queue_primer", {"id": source_id, "queued": True}))
    _push(authed, _action("set_queue_position", {"id": source_id, "target": "source_primer", "position": 5}))

    _push(authed, _action("snooze", {"target": "source_primer", "id": source_id, "until": SNOOZE_UNTIL}))
    snoozed = _source(authed, source_id)
    _push(authed, _action("snooze", {"target": "source_primer", "id": source_id, "until": None}))

    assert snoozed["primer_snoozed_until"].startswith("2030-01-02T09:00:00")
    assert snoozed["primer_queue_position"] < _source(authed, other)["queue_position"]
    assert (snoozed["snoozed_until"], snoozed["queue_position"]) == (None, 0)
    assert _source(authed, source_id)["primer_snoozed_until"] is None


def test_a_snooze_without_an_offset_is_malformed(authed: httpx.Client) -> None:
    """A naive datetime is ambiguous, so it is refused."""
    source_id = _add(authed)

    result = _push(authed, _action("snooze", {"target": "source", "id": source_id, "until": "2030-01-02T09:00:00"}))[0]

    assert result["reason"] == "payload is malformed"


def test_read_and_unread_apply_to_inbox_newsletters_only(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A newsletter in the inbox toggles read_at; an article and a queued newsletter are refused."""
    user_id = _user_id(authed)
    newsletter = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
    )
    queued_newsletter = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.QUEUED,
        processing=models.ProcessingStatus.READY,
    )
    article = _add(authed)

    _push(authed, _action("set_read", {"id": newsletter, "read": True}))
    read_at = _source(authed, newsletter)["read_at"]
    _push(authed, _action("set_read", {"id": newsletter, "read": False}))
    refused = _push(
        authed,
        _action("set_read", {"id": article, "read": True}),
        _action("set_read", {"id": queued_newsletter, "read": True}),
    )

    assert read_at is not None
    assert _source(authed, newsletter)["read_at"] is None
    assert [result["reason"] for result in refused] == ["source is not a newsletter", "source is not in the inbox"]


def test_primer_opened_and_snooze_apply_to_a_source_and_to_a_topic_primer(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Both targets write their own row and pull back; an unknown topic primer is refused."""
    source_id = _add(authed)
    primer_id = _insert_topic_primer(live_stack, user_id=_user_id(authed))

    results = _push(
        authed,
        _action("set_primer_opened", {"target": "source", "id": source_id, "opened": True}),
        _action("set_primer_opened", {"target": "topic_primer", "id": primer_id, "opened": True}),
        _action("snooze", {"target": "topic_primer", "id": primer_id, "until": SNOOZE_UNTIL}),
        _action("snooze", {"target": "topic_primer", "id": str(uuid.uuid4()), "until": SNOOZE_UNTIL}),
    )

    primer = next(row for row in _rows(authed)["topic_primers"] if row["id"] == primer_id)
    assert [result["result"] for result in results] == ["applied", "applied", "applied", "rejected"]
    assert results[3]["reason"] == "topic primer not found"
    assert _source(authed, source_id)["primer_opened_at"] is not None
    assert primer["opened_at"] is not None and primer["snoozed_until"].startswith("2030-01-02T09:00:00")

    _push(authed, _action("set_primer_opened", {"target": "topic_primer", "id": primer_id, "opened": False}))
    cleared = next(row for row in _rows(authed)["topic_primers"] if row["id"] == primer_id)
    assert cleared["opened_at"] is None and cleared["change_seq"] > primer["change_seq"]


def test_go_deeper_consumes_a_ready_inbox_item_and_queues_analysis_then_primer(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A ready inbox newsletter becomes consumed and processing with analyze then primer jobs; a busy one is refused."""
    user_id = _user_id(authed)
    ready = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
    )
    busy = _insert_source(
        live_stack,
        user_id=user_id,
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.PROCESSING,
    )

    results = _push(authed, _action("go_deeper", {"id": ready}), _action("go_deeper", {"id": busy}))

    row = _source(authed, ready)
    assert results[0]["result"] == "applied"
    assert (row["state"], row["processing"]) == ("consumed", "processing")
    assert row["read_at"] is not None
    assert _jobs(live_stack, ready) == ["analyze", "primer"]
    assert results[1]["reason"] == "source is not ready"
    assert _jobs(live_stack, busy) == []

    queued = _add(authed)
    jobs_before = _jobs(live_stack, queued)
    refused = _push(authed, _action("go_deeper", {"id": queued}))
    assert refused[0]["reason"] == "source is not in the inbox"
    assert _jobs(live_stack, queued) == jobs_before


def test_go_deeper_clears_a_snooze_so_the_consumed_item_is_not_hidden(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Going deeper on a snoozed inbox item consumes it and drops the snooze."""
    inbox = _insert_source(
        live_stack,
        user_id=_user_id(authed),
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
    )

    _push(authed, _action("snooze", {"target": "source", "id": inbox, "until": SNOOZE_UNTIL}))
    _push(authed, _action("go_deeper", {"id": inbox}))

    row = _source(authed, inbox)
    assert row["state"] == "consumed"
    assert row["snoozed_until"] is None


def test_read_later_puts_an_inbox_item_at_the_top_of_the_queue(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The item becomes queued below every other position number; a queued source is refused."""
    queued = _add(authed)
    inbox = _insert_source(
        live_stack,
        user_id=_user_id(authed),
        kind=models.SourceKind.NEWSLETTER,
        state=models.SourceState.INBOX,
        processing=models.ProcessingStatus.READY,
    )

    results = _push(authed, _action("read_later", {"id": inbox}), _action("read_later", {"id": queued}))

    row = _source(authed, inbox)
    assert row["state"] == "queued" and row["snoozed_until"] is None
    assert row["queue_position"] < _source(authed, queued)["queue_position"]
    assert results[1]["reason"] == "source is not in the inbox"


def test_delete_pulls_the_source_and_its_cards_as_deleted(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Both rows come back with deleted_at and a fresh change_seq."""
    source_id = _insert_source(
        live_stack,
        user_id=_user_id(authed),
        kind=models.SourceKind.ARTICLE,
        state=models.SourceState.CONSUMED,
        processing=models.ProcessingStatus.READY,
        with_card=True,
    )
    [card_before] = _rows(authed)["cards"]

    result = _push(authed, _action("delete_source", {"id": source_id}))[0]

    [card] = _rows(authed)["cards"]
    assert result["result"] == "applied"
    assert _source(authed, source_id)["deleted_at"] is not None
    assert card["deleted_at"] is not None and card["change_seq"] > card_before["change_seq"]
