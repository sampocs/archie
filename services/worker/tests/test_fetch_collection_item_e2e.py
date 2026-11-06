"""`fetch_collection_item` end to end: real jobs in Postgres, the preview lookups replayed from recorded cassettes.

The X post, YouTube watch page, og page and failure cassettes are the pipeline's own; only the X video was recorded
for this test. Re-record it: delete `collection_x_video.yaml`, then
`uv run pytest services/worker/tests/test_fetch_collection_item_e2e.py --record-mode=once -m postgres -k x_video`
with `TEST_DATABASE_URL` set (fxtwitter needs no key).
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, jobs, models, session
from archie_testing import media, recording
from archie_worker import handlers, loop

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[vcr_module.cassette.Cassette]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

# The shared post has no media of its own; its quoted post has this photo.
X_QUOTE_URL = "https://x.com/hwchase17/status/2116230499140251964"
X_QUOTE_PHOTO = "https://pbs.twimg.com/media/HV4_v0saYAAwybe.jpg?name=orig"
X_TEXT_ONLY_URL = "https://x.com/sama/status/2107691261776052633"
YOUTUBE_TITLE = "Jay Powell and the Fed Pause in 60 Seconds"
YOUTUBE_CHANNEL = "Bloomberg Television"
YOUTUBE_LENGTH_SECONDS = 57
YOUTUBE_THUMBNAIL = "https://i.ytimg.com/vi/e0gVE3YxZs8/hqdefault.jpg"
OG_PAGE_URL = "https://ogp.me/"


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> Replay:
    """Returns `use_cassette(name)`; replay-only unless pytest is given `--record-mode`."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    # A recorded failure may replay on every retry of a job.
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def test_an_x_video_gets_its_thumbnail_author_caption_and_length(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """fxtwitter's video gives the post its thumbnail and length; the author is the @handle."""
    item_id = _add_item(engine, url=media.X_VIDEO_POST_URL, kind=models.CollectionItemKind.X)

    with replay("collection_x_video"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert item.metadata_status == models.MetadataStatus.READY
    assert item.image_url is not None and item.image_url.startswith("https://")
    assert item.duration_seconds is not None and item.duration_seconds > 0
    assert item.author is not None and item.author.startswith("@")
    assert item.title


def test_an_x_post_without_media_uses_its_quoted_posts_photo(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A quote post with no media of its own shows the quoted post's photo; it is not a video."""
    item_id = _add_item(engine, url=X_QUOTE_URL, kind=models.CollectionItemKind.X)

    with replay("x_quote"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.image_url, item.duration_seconds, item.author) == (X_QUOTE_PHOTO, None, "@hwchase17")
    assert item.metadata_status == models.MetadataStatus.READY


def test_a_text_only_x_post_has_a_caption_and_no_image(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """No media anywhere: the post shows its caption over a neutral tile."""
    item_id = _add_item(engine, url=X_TEXT_ONLY_URL, kind=models.CollectionItemKind.X)

    with replay("x_thread_sama"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert item.image_url is None
    assert item.title is not None and item.title.startswith("looking up at the stars")
    assert item.author == "@sama"


def test_a_youtube_video_gets_title_channel_length_and_thumbnail(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The existing watch-page fetch gives the title, channel and length; the thumbnail is the standard one."""
    item_id = _add_item(engine, url=media.YOUTUBE_VIDEO_URL, kind=models.CollectionItemKind.YOUTUBE)

    with replay("youtube_powell"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.title, item.author, item.duration_seconds, item.image_url) == (
        YOUTUBE_TITLE,
        YOUTUBE_CHANNEL,
        YOUTUBE_LENGTH_SECONDS,
        YOUTUBE_THUMBNAIL,
    )


def test_any_other_link_gets_its_og_title_and_image(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A plain page: og:title and og:image, no author, no length; phones see a newer change position."""
    item_id = _add_item(engine, url=OG_PAGE_URL, kind=models.CollectionItemKind.LINK)
    seq_before = _item(engine, item_id).change_seq

    with replay("og_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.title, item.image_url, item.author) == ("Open Graph protocol", "https://ogp.me/logo.png", None)
    assert item.change_seq > seq_before
    assert _job(engine).status == models.JobStatus.DONE


def test_the_preview_never_makes_a_source_or_queues_other_work(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The boundary: a saved post's job writes only the post."""
    _add_item(engine, url=OG_PAGE_URL, kind=models.CollectionItemKind.LINK)

    with replay("og_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    with sqlalchemy.orm.Session(engine) as db:
        assert db.scalar(sqlalchemy.select(sqlalchemy.func.count()).select_from(models.Source)) == 0
        assert [job.kind for job in db.scalars(sqlalchemy.select(models.Job))] == [
            models.JobKind.FETCH_COLLECTION_ITEM.value
        ]


def test_a_missing_page_fails_at_once_and_keeps_the_url(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A 4xx can't be fixed by retrying: one attempt, the post is marked failed and keeps only its URL."""
    url = "https://httpbin.org/status/404"
    item_id = _add_item(engine, url=url, kind=models.CollectionItemKind.LINK)

    with replay("page_status_404"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.metadata_status, item.url, item.title, item.image_url) == (
        models.MetadataStatus.FAILED,
        url,
        None,
        None,
    )
    assert (_job(engine).attempts, _job(engine).status) == (1, models.JobStatus.FAILED)


def test_a_server_error_is_retried_and_the_post_stays_pending(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A 5xx is transient: the job is re-queued with backoff."""
    item_id = _add_item(engine, url="https://httpbin.org/status/500", kind=models.CollectionItemKind.LINK)

    with replay("server_error"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _item(engine, item_id).metadata_status == models.MetadataStatus.PENDING
    assert (_job(engine).attempts, _job(engine).status) == (1, models.JobStatus.QUEUED)


def test_a_post_removed_before_the_job_runs_is_left_alone(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """No request is made (the missing cassette raises on any) and nothing is written."""
    item_id = _add_item(engine, url=OG_PAGE_URL, kind=models.CollectionItemKind.LINK)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.CollectionItem, item_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    seq_before = _item(engine, item_id).change_seq

    with replay("no_requests") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 0
    assert _item(engine, item_id).change_seq == seq_before
    assert _job(engine).status == models.JobStatus.DONE


def _add_item(engine: sqlalchemy.Engine, *, url: str, kind: models.CollectionItemKind) -> uuid.UUID:
    """A user's collection, one post in it and its queued job, as the sync push makes them."""
    item_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        collection = models.Collection(
            id=uuid.uuid4(), user_id=user.id, name="Bears hype", position=0.0, change_seq=changes.next_change_seq()
        )
        db.add(collection)
        db.flush()
        db.add(
            models.CollectionItem(
                id=item_id,
                user_id=user.id,
                collection_id=collection.id,
                url=url,
                kind=kind.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        jobs.enqueue(
            db,
            kind=models.JobKind.FETCH_COLLECTION_ITEM,
            user_id=user.id,
            payload={jobs.COLLECTION_ITEM_ID_KEY: str(item_id)},
        )
        db.commit()
    return item_id


def _item(engine: sqlalchemy.Engine, item_id: uuid.UUID) -> models.CollectionItem:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.CollectionItem, item_id)


def _job(engine: sqlalchemy.Engine) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        return db.scalars(sqlalchemy.select(models.Job)).one()
