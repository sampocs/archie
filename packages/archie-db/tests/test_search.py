"""Search ranking on fixed chunks with fixed embeddings: keyword, meaning, merged, liveness and the about boost.

Embeddings are unit vectors along one axis each, so cosine distance picks exactly one chunk per query vector.
"""

from __future__ import annotations

import datetime
import uuid
import zoneinfo
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, search, session

pytestmark = pytest.mark.postgres


def _axis(index: int) -> list[float]:
    vector = [0.0] * models.EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


def _leaning(index: int, *, toward: int, weight: float) -> list[float]:
    """`_axis(index)` tilted toward another axis: still close to it, but not identical."""
    vector = _axis(index)
    vector[toward] = weight
    return vector


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session on the migrated test database."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as database:
        yield database
    engine.dispose()


def _user(db: sqlalchemy.orm.Session, sub: str = "searcher") -> int:
    user = models.User(apple_sub=sub)
    db.add(user)
    db.flush()
    return user.id


def _source(db: sqlalchemy.orm.Session, *, user_id: int, title: str, deleted: bool = False) -> models.Source:
    changes.lock_user_writes(db, user_id)
    url = f"https://example.com/{uuid.uuid4()}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user_id,
        url=url,
        normalized_url=url,
        title=title,
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.QUEUE.value,
        deleted_at=sqlalchemy.func.now() if deleted else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source


def _take(db: sqlalchemy.orm.Session, *, user_id: int, title: str, deleted: bool = False) -> models.Take:
    take = models.Take(
        id=uuid.uuid4(),
        user_id=user_id,
        kind=models.TakeKind.OPINION.value,
        title=title,
        current_version=1,
        deleted_at=sqlalchemy.func.now() if deleted else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(take)
    db.flush()
    return take


def _topic_primer(db: sqlalchemy.orm.Session, *, user_id: int, name: str, current: bool) -> models.TopicPrimer:
    topic = models.Topic(
        id=uuid.uuid4(),
        user_id=user_id,
        domain="Macro",
        name=name,
        origin=models.TopicOrigin.USER.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(topic)
    db.flush()
    primer = models.TopicPrimer(
        id=uuid.uuid4(),
        user_id=user_id,
        topic_id=topic.id,
        version=1,
        is_current=current,
        content={"markdown": ""},
        change_seq=changes.next_change_seq(),
    )
    db.add(primer)
    db.flush()
    return primer


def _chunk(
    db: sqlalchemy.orm.Session,
    *,
    owner: models.Source | models.Take | models.TopicPrimer,
    text: str,
    index: int = 0,
    embedding: list[float] | None = None,
    owner_kind: models.ChunkOwner | None = None,
) -> models.Chunk:
    columns = {
        models.Source: ("source_id", models.ChunkOwner.SOURCE_TEXT),
        models.Take: ("take_id", models.ChunkOwner.TAKE),
        models.TopicPrimer: ("topic_primer_id", models.ChunkOwner.TOPIC_PRIMER),
    }
    column, default_kind = columns[type(owner)]
    chunk = models.Chunk(
        user_id=owner.user_id,
        owner_kind=(owner_kind or default_kind).value,
        chunk_index=index,
        text=text,
        embedding=embedding,
        **{column: owner.id},
    )
    db.add(chunk)
    db.flush()
    return chunk


def test_keyword_search_finds_stemmed_words_and_skips_deleted_items(db: sqlalchemy.orm.Session) -> None:
    """'stablecoin' finds 'Stablecoins'; a deleted source and a deleted take never come back."""
    user_id = _user(db)
    live = _source(db, user_id=user_id, title="Payments")
    gone = _source(db, user_id=user_id, title="Gone", deleted=True)
    dead_take = _take(db, user_id=user_id, title="Old take", deleted=True)
    _chunk(db, owner=live, text="Stablecoins settle payments without a bank in the middle.")
    _chunk(db, owner=gone, text="Stablecoins were in this deleted article.")
    _chunk(db, owner=dead_take, text="Stablecoins are my deleted opinion.")

    hits = search.search_chunks(db, user_id=user_id, query="stablecoin", query_embedding=None, limit=10)

    assert [(hit.item.id, hit.title, hit.keyword_match) for hit in hits] == [(live.id, "Payments", True)]


def test_meaning_search_ranks_by_cosine_distance(db: sqlalchemy.orm.Session) -> None:
    """With no shared words, the chunk whose embedding points the query's way comes first."""
    user_id = _user(db)
    near = _source(db, user_id=user_id, title="Near")
    far = _source(db, user_id=user_id, title="Far")
    _chunk(db, owner=near, text="Reserves at the central bank.", embedding=_axis(1))
    _chunk(db, owner=far, text="Football results.", embedding=_leaning(1, toward=2, weight=0.5))

    hits = search.search_chunks(db, user_id=user_id, query="zzqx", query_embedding=_axis(1), limit=10)

    assert [hit.title for hit in hits] == ["Near", "Far"]
    assert not hits[0].keyword_match


def test_meaning_search_drops_chunks_beyond_the_distance_cutoff(db: sqlalchemy.orm.Session) -> None:
    """A chunk nearly the query's way is returned; an unrelated one (orthogonal, distance 1.0) is not."""
    user_id = _user(db)
    within = _source(db, user_id=user_id, title="Within")
    beyond = _source(db, user_id=user_id, title="Beyond")
    _chunk(db, owner=within, text="Reserves at the central bank.", embedding=_leaning(1, toward=2, weight=0.5))
    _chunk(db, owner=beyond, text="Football results.", embedding=_axis(5))

    hits = search.search_chunks(db, user_id=user_id, query="zzqx", query_embedding=_axis(1), limit=10)

    assert [hit.title for hit in hits] == ["Within"]


def test_a_chunk_found_both_ways_outranks_one_found_once(db: sqlalchemy.orm.Session) -> None:
    """Rank fusion sums 1/(60+rank) over both lists."""
    user_id = _user(db)
    both = _source(db, user_id=user_id, title="Both")
    words_only = _source(db, user_id=user_id, title="Words")
    meaning_only = _source(db, user_id=user_id, title="Meaning")
    _chunk(db, owner=words_only, text="Money printing and money printing again.")
    _chunk(db, owner=both, text="Money printing is a loose phrase.", embedding=_axis(3))
    _chunk(
        db,
        owner=meaning_only,
        text="Reserves are created by asset purchases.",
        embedding=_leaning(3, toward=4, weight=0.5),
    )

    hits = search.search_chunks(db, user_id=user_id, query="money printing", query_embedding=_axis(3), limit=10)

    assert hits[0].title == "Both"
    assert {hit.title for hit in hits} == {"Both", "Words", "Meaning"}


def test_best_per_item_keeps_each_items_best_chunk(db: sqlalchemy.orm.Session) -> None:
    """Two matching chunks of one source make one result, the better-ranked one."""
    user_id = _user(db)
    source = _source(db, user_id=user_id, title="Fed")
    best = _chunk(db, owner=source, index=0, text="Quantitative easing. Quantitative easing. Quantitative easing.")
    _chunk(db, owner=source, index=1, text="A passing mention of quantitative easing.")

    hits = search.search_chunks(db, user_id=user_id, query="quantitative easing", query_embedding=None, limit=80)
    grouped = search.best_per_item(hits, limit=20)

    assert [hit.chunk_id for hit in grouped] == [best.id]


def test_only_current_topic_primers_and_the_users_own_items_are_searched(db: sqlalchemy.orm.Session) -> None:
    """An old primer version and another user's chunk never match."""
    user_id = _user(db)
    other_id = _user(db, sub="other")
    current = _topic_primer(db, user_id=user_id, name="Monetary plumbing", current=True)
    stale = _topic_primer(db, user_id=user_id, name="Old plumbing", current=False)
    theirs = _source(db, user_id=other_id, title="Theirs")
    _chunk(db, owner=current, text="Central banks set the price of reserves.")
    _chunk(db, owner=stale, text="Central banks in the old version.")
    _chunk(db, owner=theirs, text="Central banks belong to someone else.")

    hits = search.search_chunks(db, user_id=user_id, query="central banks", query_embedding=None, limit=10)

    assert [(hit.item.kind, hit.title) for hit in hits] == [(models.SearchItemKind.TOPIC_PRIMER, "Monetary plumbing")]


def test_match_any_finds_a_passage_with_only_some_of_the_words(db: sqlalchemy.orm.Session) -> None:
    """The chat tool's queries match on any word; Library search needs them all."""
    user_id = _user(db)
    source = _source(db, user_id=user_id, title="Fed")
    _chunk(db, owner=source, text="The Fed buys bonds and pays with reserves.")

    strict = search.search_chunks(db, user_id=user_id, query="fed printing", query_embedding=None, limit=10)
    loose = search.search_chunks(
        db, user_id=user_id, query="fed printing", query_embedding=None, limit=10, match_any=True
    )

    assert (strict, [hit.title for hit in loose]) == ([], ["Fed"])


def test_the_about_boost_lifts_the_items_own_passages(db: sqlalchemy.orm.Session) -> None:
    """Equal matches: the boosted item's chunk comes first."""
    user_id = _user(db)
    first = _source(db, user_id=user_id, title="First")
    about = _take(db, user_id=user_id, title="My take")
    _chunk(db, owner=first, text="Tariffs raise prices.")
    _chunk(db, owner=about, text="Tariffs raise prices.")
    boost = search.ItemRef(kind=models.SearchItemKind.TAKE, id=about.id)

    hits = search.search_chunks(db, user_id=user_id, query="tariffs", query_embedding=None, limit=10, boost=boost)

    assert hits[0].item == boost


def _at(day: int, hour: int = 12) -> datetime.datetime:
    return datetime.datetime(2026, 11, day, hour, tzinfo=datetime.UTC)


def _dated_titles(db: sqlalchemy.orm.Session, *, user_id: int, dates: search.DateFilter) -> dict[str, set[str]]:
    """The titles found for one filter, by keyword and by meaning (every test chunk lies on axis 5)."""
    return {
        way: {
            hit.title
            for hit in search.search_chunks(
                db, user_id=user_id, query=query, query_embedding=embedding, limit=10, dates=dates
            )
        }
        for way, query, embedding in (("keyword", "rates", None), ("meaning", "zzqx", _axis(5)))
    }


def test_saved_and_published_bounds_pick_items_by_each_date(db: sqlalchemy.orm.Session) -> None:
    """Saved bounds read created_at; published bounds read published_at, else created_at. Both ends are inclusive.

    The filter applies to keyword and meaning search alike, and each hit carries its url, sender and both dates.
    """
    user_id = _user(db)
    tuesday_brew = _source(db, user_id=user_id, title="Tuesday brew")
    tuesday_brew.kind, tuesday_brew.sender, tuesday_brew.created_at = (
        models.SourceKind.NEWSLETTER.value,
        "Morning Brew",
        _at(3),
    )
    old_essay = _source(db, user_id=user_id, title="Old essay")
    old_essay.published_at, old_essay.created_at = datetime.datetime(2023, 1, 1, 12, tzinfo=datetime.UTC), _at(5, 23)
    friday_article = _source(db, user_id=user_id, title="Friday article")
    friday_article.created_at = _at(6)
    monday_take = _take(db, user_id=user_id, title="Monday take")
    monday_take.created_at = _at(2)
    for owner in (tuesday_brew, old_essay, friday_article, monday_take):
        _chunk(db, owner=owner, text="Rates and the Fed.", embedding=_axis(5))
    db.flush()

    tuesday, thursday = datetime.date(2026, 11, 3), datetime.date(2026, 11, 5)
    saved = _dated_titles(db, user_id=user_id, dates=search.DateFilter(saved_after=tuesday, saved_before=thursday))
    published = _dated_titles(
        db, user_id=user_id, dates=search.DateFilter(published_after=tuesday, published_before=thursday)
    )
    published_long_ago = _dated_titles(
        db, user_id=user_id, dates=search.DateFilter(published_before=datetime.date(2023, 12, 31))
    )

    assert saved == {"keyword": {"Tuesday brew", "Old essay"}, "meaning": {"Tuesday brew", "Old essay"}}
    assert published == {"keyword": {"Tuesday brew"}, "meaning": {"Tuesday brew"}}
    assert published_long_ago == {"keyword": {"Old essay"}, "meaning": {"Old essay"}}
    [essay_hit] = search.search_chunks(
        db,
        user_id=user_id,
        query="rates",
        query_embedding=None,
        limit=10,
        dates=search.DateFilter(published_before=datetime.date(2023, 12, 31)),
    )
    assert (essay_hit.saved_at, essay_hit.published_at, essay_hit.sender) == (
        _at(5, 23),
        datetime.datetime(2023, 1, 1, 12, tzinfo=datetime.UTC),
        None,
    )
    assert essay_hit.url is not None and essay_hit.url.startswith("https://example.com/")


def test_the_date_bounds_are_the_owners_days(db: sqlalchemy.orm.Session) -> None:
    """Thursday 23:00 UTC is Thursday evening in New York but already Friday in Tokyo."""
    user_id = _user(db)
    late_thursday = _source(db, user_id=user_id, title="Thursday night")
    late_thursday.created_at = _at(5, hour=23)
    _chunk(db, owner=late_thursday, text="Rates and the Fed.", embedding=_axis(5))
    db.flush()

    thursday = datetime.date(2026, 11, 5)
    found = {
        zone: _dated_titles(
            db,
            user_id=user_id,
            dates=search.DateFilter(saved_after=thursday, saved_before=thursday, day_zone=zoneinfo.ZoneInfo(zone)),
        )["keyword"]
        for zone in ("America/New_York", "Asia/Tokyo")
    }

    assert found == {"America/New_York": {"Thursday night"}, "Asia/Tokyo": set()}


@pytest.mark.parametrize(
    ("text", "query", "keyword_match", "expected_start", "contains"),
    [
        ("Short text.", "short", True, "Short", "Short text."),
        ("x " * 200 + "the Fed doesn't print money in that sense " + "y " * 200, "printing", True, "…", "print money"),
        ("unfed " + "x " * 100 + "the Fed buys bonds " + "y " * 100, "fed", True, "…", "Fed buys bonds"),
        ("Opening words " + "z " * 300, "unrelated", False, "Opening words", "Opening words"),
    ],
)
def test_passage_is_about_220_characters_around_the_first_matched_term(
    text: str, query: str, keyword_match: bool, expected_start: str, contains: str
) -> None:
    """A stemmed term is found mid-text; a meaning-only hit shows the start."""
    snippet = search.passage(text, query=query, keyword_match=keyword_match)

    assert snippet.startswith(expected_start)
    assert contains in snippet
    assert len(snippet) <= search.PASSAGE_CHARACTERS + 2
