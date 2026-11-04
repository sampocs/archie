"""Topic actions through the real API: every rule in the table, what phones pull afterwards, and the picker."""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_shared import domains
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

FINANCE = domains.Domain.FINANCE.value
AI = domains.Domain.AI.value


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, action: dict[str, Any]) -> dict[str, Any]:
    response = authed.post("/sync/push", json={"actions": [action]})
    response.raise_for_status()
    return response.json()["results"][0]


def _add(authed: httpx.Client, name: str, *, domain: str = FINANCE) -> str:
    topic_id = str(uuid.uuid4())
    result = _push(authed, _action("add_topic", {"id": topic_id, "domain": domain, "name": name}))
    assert result["result"] == "applied", result
    return topic_id


def _rejected(authed: httpx.Client, action_type: str, payload: dict[str, Any], reason: str) -> None:
    result = _push(authed, _action(action_type, payload))
    assert result["result"] == "rejected" and result["reason"] == reason, result


def _topics_by_id(authed: httpx.Client) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in authed.get("/sync/pull", params={"since": 0}).json()["rows"]["topics"]}


def _sources_by_id(authed: httpx.Client) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in authed.get("/sync/pull", params={"since": 0}).json()["rows"]["sources"]}


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _db(live_stack: LiveStack) -> sqlalchemy.orm.Session:
    return sqlalchemy.orm.Session(session.engine_for(live_stack.database_url))


def _insert_source(
    live_stack: LiveStack,
    *,
    user_id: int,
    topic_id: str | None = None,
    domain: str | None = None,
    deleted: bool = False,
    summary: bool = False,
) -> str:
    with _db(live_stack) as db:
        changes.lock_user_writes(db, user_id)
        source = models.Source(
            id=uuid.uuid4(),
            user_id=user_id,
            url=f"https://example.com/{uuid.uuid4()}",
            normalized_url=f"https://example.com/{uuid.uuid4()}",
            kind=models.SourceKind.ARTICLE.value,
            state="queued",
            intent="queue",
            topic_id=uuid.UUID(topic_id) if topic_id else None,
            domain=domain,
            deleted_at=sqlalchemy.func.now() if deleted else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        if summary:
            db.add(
                models.SourceArtifact(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    source_id=source.id,
                    kind=models.ArtifactKind.SUMMARY.value,
                    version=1,
                    content={"gist": "x"},
                    is_current=True,
                    change_seq=changes.next_change_seq(),
                )
            )
        db.commit()
        return str(source.id)


def _queued_jobs(live_stack: LiveStack, kind: models.JobKind) -> list[dict[str, Any]]:
    with _db(live_stack) as db:
        jobs = db.scalars(
            sqlalchemy.select(models.Job).where(models.Job.kind == kind.value).order_by(models.Job.id)
        ).all()
        return [dict(job.payload) for job in jobs]


def _insert_primer(live_stack: LiveStack, *, user_id: int, topic_id: str) -> None:
    with _db(live_stack) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.TopicPrimer(
                id=uuid.uuid4(),
                user_id=user_id,
                topic_id=uuid.UUID(topic_id),
                version=1,
                is_current=True,
                content={"markdown": "# x"},
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client for the default test user."""
    return live_stack.authed(live_stack.sign_in())


def test_add_topic_creates_a_user_topic_and_queues_one_primer(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A new topic is stored cleaned, as a user topic, and gets one primer job."""
    topic_id = _add(authed, "  Fed &   monetary policy ")

    row = _topics_by_id(authed)[topic_id]
    assert (row["name"], row["domain"], row["origin"]) == ("Fed & monetary policy", FINANCE, "user")
    assert _queued_jobs(live_stack, models.JobKind.TOPIC_PRIMER) == [{"topic_id": topic_id}]


def test_a_repeated_action_id_is_a_duplicate_with_one_row(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Pushing the same action twice adds one topic and one job."""
    action = _action("add_topic", {"id": str(uuid.uuid4()), "domain": FINANCE, "name": "Bonds"})

    first = _push(authed, action)
    second = _push(authed, action)

    assert (first["result"], second["result"]) == ("applied", "duplicate")
    assert len(_topics_by_id(authed)) == 1
    assert len(_queued_jobs(live_stack, models.JobKind.TOPIC_PRIMER)) == 1


def test_add_topic_rejections(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Each add_topic rule rejects with its reason and queues nothing."""
    live_id = _add(authed, "Fed & monetary policy")
    removed_id = _add(authed, "Bonds")
    _push(authed, _action("remove_topic", {"id": removed_id}))

    def add(domain: str, name: str, topic_id: str | None = None) -> dict[str, Any]:
        return {"id": topic_id or str(uuid.uuid4()), "domain": domain, "name": name}

    _rejected(authed, "add_topic", add("Nonsense", "X"), "domain is not one of Archie's domains")
    _rejected(authed, "add_topic", add(FINANCE, "   "), "topic name is empty")
    _rejected(authed, "add_topic", add(FINANCE, "x" * 81), "topic name is longer than 80 characters")
    _rejected(authed, "add_topic", add(AI, "FED and monetary-policy"), "a topic with this name already exists")
    _rejected(authed, "add_topic", add(AI, "bonds"), "a removed topic has this name; restore it instead")
    _rejected(authed, "add_topic", add(AI, "Fresh", live_id), "id already exists")
    _rejected(authed, "add_topic", {"id": "not-a-uuid"}, "payload is malformed")
    assert len(_queued_jobs(live_stack, models.JobKind.TOPIC_PRIMER)) == 2


def test_rename_topic(authed: httpx.Client) -> None:
    """Rename touches the name, ignores the topic itself, and refuses clashes and removed topics."""
    topic_id = _add(authed, "Bonds")
    other_id = _add(authed, "Equities")
    removed_id = _add(authed, "Gold")
    _push(authed, _action("remove_topic", {"id": removed_id}))
    missing_id = str(uuid.uuid4())

    padded_rename = _action("rename_topic", {"id": topic_id, "name": "BONDS "})
    assert _push(authed, padded_rename)["result"] == "applied"
    assert _push(authed, _action("rename_topic", {"id": topic_id, "name": "Fixed income"}))["result"] == "applied"

    assert _topics_by_id(authed)[topic_id]["name"] == "Fixed income"
    _rejected(authed, "rename_topic", {"id": topic_id, "name": "equities"}, "a topic with this name already exists")
    _rejected(
        authed, "rename_topic", {"id": topic_id, "name": "gold"}, "a removed topic has this name; restore it instead"
    )
    _rejected(authed, "rename_topic", {"id": topic_id, "name": ""}, "topic name is empty")
    _rejected(authed, "rename_topic", {"id": removed_id, "name": "Silver"}, "topic not found")
    _rejected(authed, "rename_topic", {"id": missing_id, "name": "Silver"}, "topic not found")
    assert other_id in _topics_by_id(authed)


def test_merge_topic_moves_sources_and_frees_the_name(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Merging moves sources (domain follows) and lets the merged name be added again."""
    user_id = _user_id(authed)
    loser = _add(authed, "Rates", domain=FINANCE)
    winner = _add(authed, "Inflation", domain=AI)
    first = _insert_source(live_stack, user_id=user_id, topic_id=loser, domain=FINANCE)
    second = _insert_source(live_stack, user_id=user_id, topic_id=loser, domain=FINANCE)

    result = _push(authed, _action("merge_topic", {"id": loser, "into_id": winner}))

    assert result["result"] == "applied"
    sources = _sources_by_id(authed)
    for source_id in (first, second):
        assert (sources[source_id]["topic_id"], sources[source_id]["domain"]) == (winner, AI)
    assert _topics_by_id(authed)[loser]["merged_into_id"] == winner
    _add(authed, "Rates")


def test_merge_topic_rejections(authed: httpx.Client) -> None:
    """Merging into itself, or with a missing, removed or merged topic, is rejected."""
    topic_id = _add(authed, "Rates")
    removed_id = _add(authed, "Gold")
    _push(authed, _action("remove_topic", {"id": removed_id}))
    merged_id = _add(authed, "Bonds")
    _push(authed, _action("merge_topic", {"id": merged_id, "into_id": topic_id}))

    _rejected(authed, "merge_topic", {"id": topic_id, "into_id": topic_id}, "can't merge a topic into itself")
    _rejected(authed, "merge_topic", {"id": topic_id, "into_id": removed_id}, "topic not found")
    _rejected(authed, "merge_topic", {"id": removed_id, "into_id": topic_id}, "topic not found")
    _rejected(authed, "merge_topic", {"id": merged_id, "into_id": topic_id}, "topic not found")
    _rejected(authed, "merge_topic", {"id": topic_id, "into_id": str(uuid.uuid4())}, "topic not found")


def test_remove_topic_unfiles_its_live_sources_and_queues_filing(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Removing clears live sources' topic (keeping domain) and queues one filing job each."""
    user_id = _user_id(authed)
    topic_id = _add(authed, "Rates")
    kept = _insert_source(live_stack, user_id=user_id, topic_id=topic_id, domain=FINANCE)
    gone = _insert_source(live_stack, user_id=user_id, topic_id=topic_id, domain=FINANCE, deleted=True)

    result = _push(authed, _action("remove_topic", {"id": topic_id}))

    assert result["result"] == "applied"
    sources = _sources_by_id(authed)
    assert (sources[kept]["topic_id"], sources[kept]["domain"]) == (None, FINANCE)
    assert sources[gone]["topic_id"] == topic_id
    assert _topics_by_id(authed)[topic_id]["removed_at"] is not None
    assert _queued_jobs(live_stack, models.JobKind.FILE_TOPIC) == [{"source_id": kept}]
    _rejected(authed, "remove_topic", {"id": topic_id}, "topic not found")


def test_restore_topic_brings_it_back_without_refiling(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Restoring only clears removed_at; it queues no filing."""
    topic_id = _add(authed, "Rates")
    source_id = _insert_source(live_stack, user_id=_user_id(authed), topic_id=topic_id, domain=FINANCE)
    _rejected(authed, "restore_topic", {"id": topic_id}, "topic is not removed")
    _push(authed, _action("remove_topic", {"id": topic_id}))

    result = _push(authed, _action("restore_topic", {"id": topic_id}))

    assert result["result"] == "applied"
    assert _topics_by_id(authed)[topic_id]["removed_at"] is None
    assert _queued_jobs(live_stack, models.JobKind.FILE_TOPIC) == [{"source_id": source_id}]
    _rejected(authed, "restore_topic", {"id": str(uuid.uuid4())}, "topic not found")


def test_set_source_topic(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Filing by hand sets the topic and the topic's domain; missing or removed topics are refused."""
    user_id = _user_id(authed)
    topic_id = _add(authed, "Rates", domain=AI)
    removed_id = _add(authed, "Gold")
    _push(authed, _action("remove_topic", {"id": removed_id}))
    source_id = _insert_source(live_stack, user_id=user_id, domain=FINANCE)

    result = _push(authed, _action("set_source_topic", {"id": source_id, "topic_id": topic_id}))

    assert result["result"] == "applied"
    row = _sources_by_id(authed)[source_id]
    assert (row["topic_id"], row["domain"]) == (topic_id, AI)
    _rejected(authed, "set_source_topic", {"id": str(uuid.uuid4()), "topic_id": topic_id}, "source not found")
    _rejected(authed, "set_source_topic", {"id": source_id, "topic_id": removed_id}, "topic not found")
    _rejected(authed, "set_source_topic", {"id": source_id, "topic_id": str(uuid.uuid4())}, "topic not found")


def test_another_users_topic_is_not_found(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Another user's topic behaves as missing for every action."""
    bob = live_stack.authed(live_stack.sign_in(apple_sub="bob"))
    topic_id = _add(authed, "Rates")

    _rejected(bob, "rename_topic", {"id": topic_id, "name": "X"}, "topic not found")
    _rejected(bob, "remove_topic", {"id": topic_id}, "topic not found")
    _rejected(bob, "restore_topic", {"id": topic_id}, "topic not found")
    _rejected(bob, "request_topic_primer", {"id": topic_id}, "topic not found")
    _rejected(bob, "merge_topic", {"id": topic_id, "into_id": topic_id}, "can't merge a topic into itself")


def test_request_topic_primer(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A primer is queued once; an existing or in-flight one rejects the request."""
    user_id = _user_id(authed)
    topic_id = _add(authed, "Rates")
    other_id = _add(authed, "Equities")
    with _db(live_stack) as db:
        db.execute(sqlalchemy.delete(models.Job))
        db.commit()

    first = _push(authed, _action("request_topic_primer", {"id": topic_id}))

    assert first["result"] == "applied"
    assert _queued_jobs(live_stack, models.JobKind.TOPIC_PRIMER) == [{"topic_id": topic_id}]
    _rejected(authed, "request_topic_primer", {"id": topic_id}, "a primer is already being written")
    _insert_primer(live_stack, user_id=user_id, topic_id=other_id)
    _rejected(authed, "request_topic_primer", {"id": other_id}, "topic already has a primer")
    _push(authed, _action("remove_topic", {"id": topic_id}))
    _rejected(authed, "request_topic_primer", {"id": topic_id}, "topic not found")


def test_choose_topics_creates_topics_marks_chosen_and_files_analyzed_sources(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """The picker creates starter and own topics, marks chosen, and files analyzed sources only."""
    user_id = _user_id(authed)
    analyzed = [_insert_source(live_stack, user_id=user_id, summary=True) for _ in range(2)]
    _insert_source(live_stack, user_id=user_id)
    starter_id, own_id = str(uuid.uuid4()), str(uuid.uuid4())
    chosen = [
        {"id": starter_id, "domain": domains.Domain.MACRO.value, "name": "Inflation"},
        {"id": own_id, "domain": AI, "name": "Robotics"},
    ]

    result = _push(authed, _action("choose_topics", {"topics": chosen}))

    assert result["result"] == "applied"
    pulled = _topics_by_id(authed)
    assert (pulled[starter_id]["origin"], pulled[own_id]["origin"]) == ("starter", "user")
    assert _queued_jobs(live_stack, models.JobKind.TOPIC_PRIMER) == [{"topic_id": own_id}]
    filed = {job["source_id"] for job in _queued_jobs(live_stack, models.JobKind.FILE_TOPIC)}
    assert filed == set(analyzed)
    assert authed.get("/me").json()["topics_chosen"] is True
    _rejected(authed, "choose_topics", {"topics": chosen}, "topics already chosen")


def test_a_second_choose_topics_is_rejected_across_requests_and_within_a_batch(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Only the first picker submit counts: later ones are refused without new topics or filing jobs."""
    user_id = _user_id(authed)
    _insert_source(live_stack, user_id=user_id, summary=True)
    first = [{"id": str(uuid.uuid4()), "domain": FINANCE, "name": "Rates"}]
    second = [{"id": str(uuid.uuid4()), "domain": FINANCE, "name": "Bonds"}]
    assert _push(authed, _action("choose_topics", {"topics": first}))["result"] == "applied"

    _rejected(authed, "choose_topics", {"topics": second}, "topics already chosen")

    assert len(_queued_jobs(live_stack, models.JobKind.FILE_TOPIC)) == 1


def test_two_choose_topics_in_one_batch_reject_the_second(authed: httpx.Client) -> None:
    """The in-batch pending timestamp still blocks a second submit."""
    actions = [
        _action("choose_topics", {"topics": [{"id": str(uuid.uuid4()), "domain": FINANCE, "name": "Rates"}]}),
        _action("choose_topics", {"topics": [{"id": str(uuid.uuid4()), "domain": FINANCE, "name": "Bonds"}]}),
    ]

    response = authed.post("/sync/push", json={"actions": actions})
    response.raise_for_status()

    results = response.json()["results"]
    assert [result["result"] for result in results] == ["applied", "rejected"]
    assert results[1]["reason"] == "topics already chosen"


def test_choose_topics_rejections_create_nothing(authed: httpx.Client) -> None:
    """A duplicate, empty or bad-domain pick is rejected with nothing created."""
    twice = [
        {"id": str(uuid.uuid4()), "domain": FINANCE, "name": "Inflation"},
        {"id": str(uuid.uuid4()), "domain": FINANCE, "name": "inflation "},
    ]

    _rejected(authed, "choose_topics", {"topics": twice}, "a topic with this name already exists")
    _rejected(authed, "choose_topics", {"topics": []}, "choose at least one topic")
    _rejected(
        authed,
        "choose_topics",
        {"topics": [{"id": str(uuid.uuid4()), "domain": "X", "name": "A"}]},
        "domain is not one of Archie's domains",
    )

    assert _topics_by_id(authed) == {}
    assert authed.get("/me").json()["topics_chosen"] is False


def test_starter_topics_lists_domains_in_order(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The starter list has 12 domains in order, and needs a session."""
    body = authed.get("/topics/starter").json()

    names = [entry["domain"] for entry in body["domains"]]
    finance = next(entry for entry in body["domains"] if entry["domain"] == FINANCE)
    assert len(names) == 12
    assert names == [domain.value for domain in domains.Domain if domain.value in names]
    assert finance["topics"][-2:] == ["Personal finance & taxes", "Insurance"]
    assert httpx.get(f"{live_stack.base_url}/topics/starter").status_code == 401
