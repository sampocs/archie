"""A podcast's nearby episodes and the `choose_episode` action, through the real API and Postgres.

The feed download is replayed from a recorded real response. Re-record with
`uv run pytest services/api/tests/e2e/test_episodes_e2e.py --record-mode=once -m postgres` after deleting the cassette
(needs `TEST_DATABASE_URL`); nothing here spends an API key.
"""

from __future__ import annotations

import datetime
import pathlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_api.sources import routes
from archie_db import changes, models, session
from archie_shared import podcast_feed
from archie_testing import recording
from archie_testing.harness import LiveStack

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
FEED_FIXTURE = (
    pathlib.Path(__file__).parents[3] / "worker" / "tests" / "fixtures" / "podcast" / "darknet_diaries_feed.xml"
)

FEED_URL = "https://podcast.darknetdiaries.com"
# "182: Blackshades", the newest item of the recorded feed.
CURRENT_GUID = "prx_7057_c0abbff3-ae98-4e23-a389-5ee0fd824f51"
CHOSEN_GUID = "prx_7057_88c4d72a-2377-4fef-9dac-3cd23529b881"
WINDOW = datetime.timedelta(days=routes.EPISODE_WINDOW_DAYS)


def test_episodes_near_are_within_the_window_newest_first_with_one_current() -> None:
    """Centred on a middle item's guid: every result is within 30 days, newest first, exactly one is current."""
    items = podcast_feed.parse_feed(FEED_FIXTURE.read_bytes())
    middle = items[1]
    assert middle.published is not None

    near = routes.episodes_near(items=items, current_guid=middle.guid, fallback_date=datetime.date(2000, 1, 1))

    published = [datetime.date.fromisoformat(episode.published or "") for episode in near]
    assert 1 < len(near) < len(items)
    assert all(abs(day - middle.published) <= WINDOW for day in published)
    assert published == sorted(published, reverse=True)
    assert [episode.guid for episode in near if episode.is_current] == [middle.guid]


def test_an_unknown_guid_centres_the_window_on_the_fallback_date() -> None:
    """Without the current item the window is centred on the day the source was saved; none is current."""
    items = podcast_feed.parse_feed(FEED_FIXTURE.read_bytes())
    oldest = items[-1]
    assert oldest.published is not None

    near = routes.episodes_near(items=items, current_guid="not-in-the-feed", fallback_date=oldest.published)

    assert near and near[-1].guid == oldest.guid
    assert not any(episode.is_current for episode in near)
    assert all(
        abs(datetime.date.fromisoformat(episode.published or "") - oldest.published) <= WINDOW for episode in near
    )


@pytest.mark.postgres
def test_the_episode_list_has_the_matched_episode_current_within_30_days_newest_first(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """One feed download; the matched guid is present and current, the rest are within 30 days of it."""
    authed = live_stack.authed(live_stack.sign_in())
    source_id = _insert_podcast(live_stack, user_id=_user_id(authed), episode_guid=CURRENT_GUID).id

    with _replay(request, "episodes_darknet"):
        response = authed.get(f"/sources/{source_id}/episodes")

    assert response.status_code == 200
    episodes = response.json()["episodes"]
    published = [datetime.date.fromisoformat(episode["published"]) for episode in episodes]
    current = next(episode for episode in episodes if episode["guid"] == CURRENT_GUID)
    assert [episode["guid"] for episode in episodes if episode["is_current"]] == [CURRENT_GUID]
    assert set(current) == {"guid", "title", "published", "duration_s", "is_current"}
    assert published == sorted(published, reverse=True)
    assert all(abs(day - datetime.date.fromisoformat(current["published"])) <= WINDOW for day in published)
    assert len(episodes) > 1


@pytest.mark.postgres
def test_the_episode_list_is_not_found_for_other_users_articles_and_podcasts_without_text(
    live_stack: LiveStack,
) -> None:
    """Only the caller's own resolved podcast has an episode list."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner"))
    other = live_stack.authed(live_stack.sign_in(apple_sub="other"))
    owner_id = _user_id(owner)
    podcast = _insert_podcast(live_stack, user_id=owner_id, episode_guid=CURRENT_GUID)
    article = _insert_podcast(live_stack, user_id=owner_id, episode_guid=CURRENT_GUID, kind=models.SourceKind.ARTICLE)
    unresolved = _insert_podcast(live_stack, user_id=owner_id, episode_guid=None, with_text=False)

    assert other.get(f"/sources/{podcast.id}/episodes").status_code == 404
    assert owner.get(f"/sources/{article.id}/episodes").status_code == 404
    assert owner.get(f"/sources/{unresolved.id}/episodes").status_code == 404
    assert owner.get(f"/sources/{uuid.uuid4()}/episodes").status_code == 404


@pytest.mark.postgres
def test_choosing_an_episode_retires_the_outputs_and_fetches_again(live_stack: LiveStack) -> None:
    """Text, summary and primer stop being current, cards are deleted, chunks go, and one fetch_content job queues."""
    authed = live_stack.authed(live_stack.sign_in())
    source = _insert_podcast(live_stack, user_id=_user_id(authed), episode_guid=CURRENT_GUID, with_outputs=True)

    result = _choose(authed, source_id=source.id, guid=CHOSEN_GUID)

    assert result["result"] == "applied"
    pulled = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    row = next(row for row in pulled["sources"] if row["id"] == str(source.id))
    assert (row["processing"], row["title"], row["image_url"]) == ("processing", None, None)
    assert "episode_guid" not in row
    assert pulled["artifacts"] and not any(artifact["is_current"] for artifact in pulled["artifacts"])
    assert pulled["cards"] and all(card["deleted_at"] is not None for card in pulled["cards"])

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        stored = db.get_one(models.Source, source.id)
        text = db.scalars(
            sqlalchemy.select(models.SourceArtifact).where(models.SourceArtifact.kind == models.ArtifactKind.TEXT.value)
        ).one()
        chunk_count = db.scalar(sqlalchemy.select(sqlalchemy.func.count()).select_from(models.TranscriptChunk))
        jobs = list(db.scalars(sqlalchemy.select(models.Job)))
    engine.dispose()
    assert stored.episode_guid == CHOSEN_GUID
    assert text.is_current is False
    assert chunk_count == 0
    assert [(job.kind, job.payload["source_id"]) for job in jobs] == [("fetch_content", str(source.id))]


@pytest.mark.postgres
def test_choosing_an_episode_is_rejected_for_an_article_a_busy_source_and_another_users_source(
    live_stack: LiveStack,
) -> None:
    """Each refusal leaves the source untouched, and a repeated action id is a duplicate."""
    authed = live_stack.authed(live_stack.sign_in(apple_sub="owner"))
    other = live_stack.authed(live_stack.sign_in(apple_sub="other"))
    user_id = _user_id(authed)
    article = _insert_podcast(live_stack, user_id=user_id, episode_guid=None, kind=models.SourceKind.ARTICLE)
    busy = _insert_podcast(
        live_stack, user_id=user_id, episode_guid=CURRENT_GUID, processing=models.ProcessingStatus.PROCESSING
    )
    ready = _insert_podcast(live_stack, user_id=user_id, episode_guid=CURRENT_GUID, with_outputs=True)

    assert _choose(authed, source_id=article.id, guid=CHOSEN_GUID)["reason"] == "source is not a podcast"
    assert _choose(authed, source_id=busy.id, guid=CHOSEN_GUID)["reason"] == "source is still processing"
    assert _choose(other, source_id=ready.id, guid=CHOSEN_GUID)["reason"] == "source not found"
    assert _choose(authed, source_id=ready.id, guid="")["reason"] == "payload is malformed"

    action_id = str(uuid.uuid4())
    first = _choose(authed, source_id=ready.id, guid=CHOSEN_GUID, action_id=action_id)
    repeat = _choose(authed, source_id=ready.id, guid=CHOSEN_GUID, action_id=action_id)
    assert (first["result"], repeat["result"]) == ("applied", "duplicate")

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        guids = {row.id: row.episode_guid for row in db.scalars(sqlalchemy.select(models.Source))}
    engine.dispose()
    assert guids[article.id] is None and guids[busy.id] is None
    assert guids[ready.id] == CHOSEN_GUID


def _choose(authed: httpx.Client, *, source_id: uuid.UUID, guid: str, action_id: str | None = None) -> dict[str, Any]:
    action = {
        "id": action_id or str(uuid.uuid4()),
        "type": "choose_episode",
        "payload": {"id": str(source_id), "guid": guid},
    }
    response = authed.post("/sync/push", json={"actions": [action]})
    response.raise_for_status()
    return response.json()["results"][0]


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    # The test's own calls to the live API must reach it; only the feed download is replayed.
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=True)


def _insert_podcast(
    live_stack: LiveStack,
    *,
    user_id: int,
    episode_guid: str | None,
    kind: models.SourceKind = models.SourceKind.PODCAST,
    processing: models.ProcessingStatus = models.ProcessingStatus.READY,
    with_text: bool = True,
    with_outputs: bool = False,
) -> models.Source:
    """A source row, and optionally its resolved-episode `text` artifact, summary, primer, a card and a chunk."""
    engine = session.engine_for(live_stack.database_url)
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Source(
                id=source_id,
                user_id=user_id,
                url=f"https://podcasts.example/{source_id}",
                normalized_url=f"https://podcasts.example/{source_id}",
                kind=kind.value,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                processing=processing.value,
                title="Old title",
                image_url="https://img.example/old.jpg",
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        if with_text or with_outputs:
            episode = {"feed_url": FEED_URL, "guid": episode_guid}
            artifacts = {models.ArtifactKind.TEXT: {"text": "hello", podcast_feed.EPISODE_KEY: episode}}
            if with_outputs:
                artifacts[models.ArtifactKind.SUMMARY] = {"summary": {"gist": "g"}}
                artifacts[models.ArtifactKind.PRIMER] = {"markdown": "# p"}
            summary_id = _add_artifacts(db, user_id=user_id, source_id=source_id, artifacts=artifacts)
            if with_outputs:
                _add_card_and_chunk(db, user_id=user_id, source_id=source_id, artifact_id=summary_id)
        db.commit()
        source = db.get_one(models.Source, source_id)
        db.expunge(source)
    engine.dispose()
    return source


def _add_artifacts(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    source_id: uuid.UUID,
    artifacts: dict[models.ArtifactKind, dict[str, Any]],
) -> uuid.UUID | None:
    """Insert each kind as a current version 1 and return the summary's id, if there is one."""
    summary_id = None
    for kind, content in artifacts.items():
        artifact_id = uuid.uuid4()
        db.add(
            models.SourceArtifact(
                id=artifact_id,
                user_id=user_id,
                source_id=source_id,
                kind=kind.value,
                version=1,
                content=content,
                is_current=True,
                change_seq=changes.next_change_seq(),
            )
        )
        if kind == models.ArtifactKind.SUMMARY:
            summary_id = artifact_id
    db.flush()
    return summary_id


def _add_card_and_chunk(
    db: sqlalchemy.orm.Session, *, user_id: int, source_id: uuid.UUID, artifact_id: uuid.UUID | None
) -> None:
    assert artifact_id is not None
    db.add(
        models.Card(
            id=uuid.uuid4(),
            user_id=user_id,
            source_id=source_id,
            artifact_id=artifact_id,
            kind=models.CardKind.CONCEPT.value,
            question="q",
            answer="a",
            change_seq=changes.next_change_seq(),
        )
    )
    db.add(
        models.TranscriptChunk(
            source_id=source_id,
            chunk_index=0,
            provider="groq",
            model="whisper",
            segments=[{"start": 0.0, "text": "hi"}],
        )
    )
