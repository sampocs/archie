"""Podcast `fetch_content` end to end: real jobs in a real Postgres, real handlers, HTTP replayed from cassettes.

Re-record with `uv run pytest services/worker/tests/test_podcast_e2e.py --record-mode=once -m postgres` after deleting
a cassette (needs `TEST_DATABASE_URL`, as `make test-db` sets it); nothing here spends an API key.
"""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, jobs, models, pipeline, session
from archie_testing import media, recording
from archie_worker import errors, handlers, loop
from archie_worker.content import episode as episode_content
from archie_worker.content import podcast

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[vcr_module.cassette.Cassette]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
AUDIO_SUFFIXES = (".mp3", ".m4a")
MIN_TRANSCRIPT_WORDS = 200
SPOTIFY_SHOW_ITUNES_ID = 1680976721
GONE_FEED_URL = "https://feeds.libsyn.com/464601/archie-no-such-feed"
# The feed item right after "182: Blackshades" ("181: Ricky"), read from the `podcast_apple_transcript` cassette's feed.
NEXT_EPISODE_GUID = "prx_7057_88c4d72a-2377-4fef-9dac-3cd23529b881"
NEXT_EPISODE_TITLE = "Ricky"


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> Replay:
    """Returns `use_cassette(name)`: replay-only unless pytest is given `--record-mode`."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def test_an_apple_episode_with_a_published_transcript_becomes_timed_text(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """The lookup's guid differs from the feed's, so the item is matched by title and date; no audio is fetched."""
    source_id = _add_source(engine, url=media.APPLE_TRANSCRIPT_EPISODE_URL)

    with replay("podcast_apple_transcript") as cassette:
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    assert not [request for request in cassette.requests if request.path.endswith(AUDIO_SUFFIXES)]
    source = _source(engine, source_id)
    artifact = _only_artifact(engine, source_id)
    assert (artifact.kind, artifact.version, artifact.is_current) == (models.ArtifactKind.TEXT, 1, True)
    segments = artifact.content["segments"]
    assert len(artifact.content["text"].split()) >= MIN_TRANSCRIPT_WORDS
    starts = [segment["start"] for segment in segments]
    assert starts == sorted(starts)
    assert artifact.content["episode"]["feed_url"]
    assert artifact.content["episode"]["audio_url"]
    assert source.title == artifact.content["episode"]["title"]
    assert (source.image_url or "").startswith("https://")
    assert media.APPLE_TRANSCRIPT_EPISODE_TITLE in source.title
    # The feed item's day, which Apple's lookup matched on.
    assert source.published_at == datetime.datetime(2026, 11, 3, tzinfo=datetime.UTC)
    assert source.processing == models.ProcessingStatus.PROCESSING
    assert _queued_kinds(engine) == [models.JobKind.EMBED, models.JobKind.ANALYZE, models.JobKind.PRIMER]


def test_a_spotify_episode_without_a_transcript_queues_transcription_and_remembers_the_show(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """Page, iTunes Search and the feed resolve the episode; no audio is downloaded, the show is registered."""
    source_id = _add_source(engine, url=media.SPOTIFY_EPISODE_URL)

    with replay("podcast_spotify_resolve") as cassette:
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    assert not [request for request in cassette.requests if request.path.endswith(AUDIO_SUFFIXES)]
    _assert_transcription_queued(engine, source_id)
    (show,) = _shows(engine)
    assert show.name_key == podcast.name_key(media.SPOTIFY_SHOW_NAME)
    assert show.feed_url == media.EPISODE_FEED_URL


def test_a_registered_show_skips_itunes_search(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """With the show in the registry only the page and the feed are requested."""
    with sqlalchemy.orm.Session(engine) as db:
        db.add(
            models.PodcastShow(
                name_key=podcast.name_key(media.SPOTIFY_SHOW_NAME),
                name=media.SPOTIFY_SHOW_NAME,
                feed_url=media.EPISODE_FEED_URL,
                itunes_id=SPOTIFY_SHOW_ITUNES_ID,
            )
        )
        db.commit()
    source_id = _add_source(engine, url=media.SPOTIFY_EPISODE_URL)

    with replay("podcast_spotify_registry_hit") as cassette:
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    assert "itunes.apple.com" not in {request.host for request in cassette.requests}
    _assert_transcription_queued(engine, source_id)
    assert len(_shows(engine)) == 1


def test_a_registered_feed_that_is_gone_is_replaced_by_the_searched_feed(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """The remembered feed 404s, so iTunes Search is asked and its feed resolves the episode and replaces the row."""
    with sqlalchemy.orm.Session(engine) as db:
        db.add(
            models.PodcastShow(
                name_key=podcast.name_key(media.SPOTIFY_SHOW_NAME),
                name=media.SPOTIFY_SHOW_NAME,
                feed_url=GONE_FEED_URL,
                itunes_id=SPOTIFY_SHOW_ITUNES_ID,
            )
        )
        db.commit()
    source_id = _add_source(engine, url=media.SPOTIFY_EPISODE_URL)

    with replay("podcast_spotify_gone_feed") as cassette:
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    assert "itunes.apple.com" in {request.host for request in cassette.requests}
    _assert_transcription_queued(engine, source_id)
    (show,) = _shows(engine)
    assert show.feed_url == media.EPISODE_FEED_URL


def test_a_spotify_exclusive_episode_fails_without_a_retry_or_a_registered_show(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """A show with no public feed ends the source `failed` after one attempt, and nothing is remembered."""
    if media.SPOTIFY_EXCLUSIVE_EPISODE_URL is None:
        pytest.skip("No Spotify-exclusive episode was found for the test media.")
    source_id = _add_source(engine, url=media.SPOTIFY_EXCLUSIVE_EPISODE_URL)

    with replay("podcast_spotify_exclusive"):
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    job = _fetch_content_job(engine)
    assert (job.status, job.attempts) == (models.JobStatus.FAILED.value, 1)
    source = _source(engine, source_id)
    assert source.processing == models.ProcessingStatus.FAILED
    # The show's exact-name hit has no feedUrl, so there is no RSS to search.
    assert source.processing_error == errors.FailureReason.SPOTIFY_ONLY
    assert _shows(engine) == []


def test_a_chosen_guid_replaces_the_episode_apple_matched(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """With the source's `episode_guid` set, the feed item with that guid is used instead of Lookup's episode."""
    source_id = _add_source(engine, url=media.APPLE_TRANSCRIPT_EPISODE_URL, episode_guid=NEXT_EPISODE_GUID)

    with replay("podcast_apple_chosen_episode"):
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    source = _source(engine, source_id)
    assert NEXT_EPISODE_TITLE in (source.title or "")
    assert (source.image_url or "").startswith("https://")
    assert _chosen_episode(engine, source_id).guid == NEXT_EPISODE_GUID


def test_a_chosen_guid_missing_from_the_feed_fails_as_episode_not_found(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """No item has the guid, so the job fails at once and nothing beyond Lookup and the feed is requested."""
    source_id = _add_source(engine, url=media.APPLE_TRANSCRIPT_EPISODE_URL, episode_guid="no-such-guid")

    with replay("podcast_apple_chosen_episode") as cassette:
        assert loop.run_one(engine, handlers=handlers.HANDLERS) is True

    # Lookup and the feed; the cassette also holds the chosen episode's transcript request, which must stay unplayed.
    assert cassette.play_count == 2
    source = _source(engine, source_id)
    assert source.processing == models.ProcessingStatus.FAILED
    assert source.processing_error == errors.FailureReason.EPISODE_NOT_FOUND
    assert _artifacts(engine, source_id) == []


def _chosen_episode(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> episode_content.PodcastEpisode:
    """The episode stored on the text artifact, else the one carried by the queued `transcribe` job."""
    artifacts = _artifacts(engine, source_id)
    if artifacts:
        return episode_content.PodcastEpisode.from_payload(artifacts[0].content[episode_content.EPISODE_KEY])
    return episode_content.PodcastEpisode.from_payload(_transcribe_payload(engine)[episode_content.EPISODE_KEY])


def _assert_transcription_queued(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> None:
    source = _source(engine, source_id)
    assert _artifacts(engine, source_id) == []
    assert source.processing == models.ProcessingStatus.PROCESSING
    assert source.title == media.SPOTIFY_EPISODE_TITLE
    assert _queued_kinds(engine) == [models.JobKind.TRANSCRIBE]

    payload = _transcribe_payload(engine)
    episode = episode_content.PodcastEpisode.from_payload(payload[episode_content.EPISODE_KEY])
    assert episode.audio_url == media.EPISODE_AUDIO_URL
    assert episode.title == media.SPOTIFY_EPISODE_TITLE
    assert episode.show_name == media.SPOTIFY_SHOW_NAME
    assert payload[pipeline.SOURCE_ID_KEY] == str(source_id)
    assert (episode.image_url or "").startswith("https://")
    assert (_source(engine, source_id).image_url or "").startswith("https://")


def _add_source(engine: sqlalchemy.Engine, *, url: str, episode_guid: str | None = None) -> uuid.UUID:
    """A user's podcast source and its queued `fetch_content` job, as the sync push creates them."""
    source_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        db.add(
            models.Source(
                id=source_id,
                user_id=user.id,
                url=url,
                normalized_url=url,
                kind=models.SourceKind.PODCAST.value,
                state=models.SourceState.INBOX.value,
                intent=models.SourceIntent.QUEUE.value,
                episode_guid=episode_guid,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        jobs.enqueue(
            db,
            kind=models.JobKind.FETCH_CONTENT,
            user_id=user.id,
            payload={pipeline.SOURCE_ID_KEY: str(source_id)},
        )
        db.commit()
    return source_id


def _source(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.Source:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.Source, source_id)


def _artifacts(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> list[models.SourceArtifact]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(
            db.scalars(sqlalchemy.select(models.SourceArtifact).where(models.SourceArtifact.source_id == source_id))
        )


def _only_artifact(engine: sqlalchemy.Engine, source_id: uuid.UUID) -> models.SourceArtifact:
    (artifact,) = _artifacts(engine, source_id)
    return artifact


def _shows(engine: sqlalchemy.Engine) -> list[models.PodcastShow]:
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.PodcastShow)))


def _fetch_content_job(engine: sqlalchemy.Engine) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        return db.execute(
            sqlalchemy.select(models.Job).where(models.Job.kind == models.JobKind.FETCH_CONTENT.value)
        ).scalar_one()


def _transcribe_payload(engine: sqlalchemy.Engine) -> dict[str, Any]:
    with sqlalchemy.orm.Session(engine) as db:
        job = db.execute(
            sqlalchemy.select(models.Job).where(models.Job.kind == models.JobKind.TRANSCRIBE.value)
        ).scalar_one()
        return dict(job.payload)


def _queued_kinds(engine: sqlalchemy.Engine) -> list[models.JobKind]:
    with sqlalchemy.orm.Session(engine) as db:
        kinds = db.scalars(
            sqlalchemy.select(models.Job.kind)
            .where(models.Job.status == models.JobStatus.QUEUED.value)
            .order_by(models.Job.id)
        )
        return [models.JobKind(kind) for kind in kinds]
