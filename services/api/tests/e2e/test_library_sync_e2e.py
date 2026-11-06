"""Library sync through the real API: five pulled tables, queue positions, `/me` topics and newsletter text."""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session, user_topics
from archie_shared import domains, topics
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

PAGE_SIZE = 500
OWNER_EMAIL = "owner@example.com"

SOURCE_KEYS_BEFORE_M4 = {
    "id",
    "url",
    "title",
    "kind",
    "state",
    "intent",
    "processing",
    "processing_error",
    "reaction",
    "note",
    "merged_into_id",
    "sender",
    "created_at",
    "updated_at",
    "deleted_at",
    "change_seq",
}
SOURCE_KEYS_ADDED_BY_M4 = {
    "domain",
    "topic_id",
    "image_url",
    "queue_position",
    "read_at",
    "snoozed_until",
    "primer_opened_at",
    "newsletter_kind",
}
SOURCE_KEYS_ADDED_BY_M4_POLISH = {"primer_queue_position", "primer_snoozed_until"}
SOURCE_KEYS_ADDED_BY_M6 = {"cards_off"}
SOURCE_KEYS_ADDED_BY_FAVORITES = {"favorited_at"}


def _add_source(url: str, *, intent: str = "queue") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": "add_source",
        "payload": {"id": str(uuid.uuid4()), "url": url, "intent": intent},
    }


def _pull_rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _pull_all_pages(authed: httpx.Client) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    position, more = 0, True
    while more:
        page = authed.get("/sync/pull", params={"since": position}).json()
        pages.append(page)
        position, more = page["position"], page["more"]
    return pages


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _insert_source(
    db: sqlalchemy.orm.Session, *, user_id: int, url: str, kind: models.SourceKind = models.SourceKind.ARTICLE
) -> models.Source:
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user_id,
        url=url,
        normalized_url=url,
        kind=kind.value,
        state="queued",
        intent="queue",
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source


def test_a_later_queued_source_sits_above_an_earlier_one(live_stack: LiveStack) -> None:
    """Queued sources get one less than the lowest position; a finished source has none."""
    authed = live_stack.authed(live_stack.sign_in())
    first = _add_source("https://example.com/first")
    second = _add_source("https://example.com/second")
    finished = _add_source("https://example.com/done", intent="finished")

    authed.post("/sync/push", json={"actions": [first]}).raise_for_status()
    authed.post("/sync/push", json={"actions": [second, finished]}).raise_for_status()

    by_url = {row["url"]: row for row in _pull_rows(authed)["sources"]}
    assert by_url["https://example.com/first"]["queue_position"] == 0
    assert by_url["https://example.com/second"]["queue_position"] == -1
    assert by_url["https://example.com/done"]["queue_position"] is None


def test_a_pulled_source_carries_the_library_columns_and_hides_the_episode_guid(live_stack: LiveStack) -> None:
    """The pulled source keeps its old keys (less `prep_me`), gains the library and queued-primer ones.

    It never shows `episode_guid`.
    """
    authed = live_stack.authed(live_stack.sign_in())
    authed.post("/sync/push", json={"actions": [_add_source("https://example.com/a")]}).raise_for_status()

    row = _pull_rows(authed)["sources"][0]

    assert set(row) == (
        SOURCE_KEYS_BEFORE_M4
        | SOURCE_KEYS_ADDED_BY_M4
        | SOURCE_KEYS_ADDED_BY_M4_POLISH
        | SOURCE_KEYS_ADDED_BY_M6
        | SOURCE_KEYS_ADDED_BY_FAVORITES
    )


def test_topics_topic_primers_and_sources_page_in_position_order(live_stack: LiveStack) -> None:
    """260 topics interleaved with 260 sources (and a primer) fill pages of 500 and 21; every row appears once."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    engine = session.engine_for(live_stack.database_url)
    expected: set[str] = set()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        for index in range(260):
            topic = user_topics.create_topic(
                db,
                user_id=user_id,
                domain=domains.Domain.AI,
                name=f"Topic {index}",
                origin=models.TopicOrigin.USER,
            )
            source = _insert_source(db, user_id=user_id, url=f"https://example.com/{index}")
            expected |= {str(topic.id), str(source.id)}
            if index == 0:
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
                db.flush()
                expected.add(str(primer.id))
        db.commit()

    pages = _pull_all_pages(authed)

    row_ids = [row["id"] for page in pages for rows in page["rows"].values() for row in rows]
    page_sizes = [sum(len(rows) for rows in page["rows"].values()) for page in pages]
    positions = [page["position"] for page in pages]
    assert page_sizes == [PAGE_SIZE, 21]
    assert len(row_ids) == 521 and set(row_ids) == expected
    assert positions == sorted(positions)
    assert set(pages[0]["rows"]) == {
        "sources",
        "artifacts",
        "cards",
        "topics",
        "topic_primers",
        "briefs",
        "collections",
        "collection_items",
        "takes",
        "take_versions",
    }


def test_a_new_user_has_not_chosen_topics(live_stack: LiveStack) -> None:
    """`/me` says topics_chosen is false until the picker is done, and a pull holds no topics."""
    authed = live_stack.authed(live_stack.sign_in())

    assert authed.get("/me").json()["topics_chosen"] is False
    assert _pull_rows(authed)["topics"] == []


def test_a_test_session_can_seed_the_owner_topics(live_stack: LiveStack) -> None:
    """`seed_topics` gives the owner's live topics plus the starter extras as removed ones, and marks them chosen."""
    authed = live_stack.authed(live_stack.sign_in(seed_topics=True))

    me = authed.get("/me").json()
    pulled = _pull_rows(authed)["topics"]

    live_count = sum(len(names) for names in topics.OWNER_TOPICS.values())
    assert me["topics_chosen"] is True
    assert sum(row["removed_at"] is None for row in pulled) == live_count
    assert sum(row["removed_at"] is not None for row in pulled) == 3
    assert set(pulled[0]) == {
        "id",
        "domain",
        "name",
        "origin",
        "removed_at",
        "merged_into_id",
        "created_at",
        "updated_at",
        "change_seq",
    }


def test_the_owners_first_me_seeds_their_topics_once(live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch) -> None:
    """An owner who never signs in again still gets topics from `/me`; a second call adds nothing."""
    monkeypatch.setenv("OWNER_EMAILS", OWNER_EMAIL)
    authed = live_stack.authed(live_stack.sign_in(apple_sub="owner", email=OWNER_EMAIL))

    first = authed.get("/me").json()
    seeded = _pull_rows(authed)["topics"]
    authed.get("/me").raise_for_status()
    after_second = _pull_rows(authed)["topics"]

    assert first["topics_chosen"] is True
    assert seeded
    assert after_second == seeded


def _insert_text_source(live_stack: LiveStack, *, user_id: int, kind: models.SourceKind, text: str | None) -> str:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        source = _insert_source(db, user_id=user_id, url=f"https://example.com/{uuid.uuid4()}", kind=kind)
        if text is not None:
            db.add(
                models.SourceArtifact(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    source_id=source.id,
                    kind=models.ArtifactKind.TEXT.value,
                    version=1,
                    content={"text": text},
                    is_current=True,
                    change_seq=changes.next_change_seq(),
                )
            )
        db.commit()
        return str(source.id)


def test_a_newsletters_text_is_served_to_its_owner_only(live_stack: LiveStack) -> None:
    """The owner gets the text; another user, an article and a newsletter without text all get 404."""
    authed = live_stack.authed(live_stack.sign_in(apple_sub="alice"))
    other = live_stack.authed(live_stack.sign_in(apple_sub="bob"))
    user_id = _user_id(authed)
    newsletter = _insert_text_source(live_stack, user_id=user_id, kind=models.SourceKind.NEWSLETTER, text="Hello")
    article = _insert_text_source(live_stack, user_id=user_id, kind=models.SourceKind.ARTICLE, text="Body")
    empty = _insert_text_source(live_stack, user_id=user_id, kind=models.SourceKind.NEWSLETTER, text=None)

    assert authed.get(f"/sources/{newsletter}/text").json() == {"text": "Hello"}
    assert other.get(f"/sources/{newsletter}/text").status_code == 404
    assert authed.get(f"/sources/{article}/text").status_code == 404
    assert authed.get(f"/sources/{empty}/text").status_code == 404
    assert authed.get(f"/sources/{uuid.uuid4()}/text").status_code == 404
