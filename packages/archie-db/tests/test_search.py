"""Search ranking on fixed chunks with fixed embeddings: keyword, meaning, merged, liveness and the about boost.

Embeddings are unit vectors along one axis each, so cosine distance picks exactly one chunk per query vector.
"""

from __future__ import annotations

import uuid
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
    _chunk(db, owner=far, text="Football results.", embedding=_axis(2))

    hits = search.search_chunks(db, user_id=user_id, query="zzqx", query_embedding=_axis(1), limit=10)

    assert [hit.title for hit in hits] == ["Near", "Far"]
    assert not hits[0].keyword_match


def test_a_chunk_found_both_ways_outranks_one_found_once(db: sqlalchemy.orm.Session) -> None:
    """Rank fusion sums 1/(60+rank) over both lists."""
    user_id = _user(db)
    both = _source(db, user_id=user_id, title="Both")
    words_only = _source(db, user_id=user_id, title="Words")
    meaning_only = _source(db, user_id=user_id, title="Meaning")
    _chunk(db, owner=words_only, text="Money printing and money printing again.")
    _chunk(db, owner=both, text="Money printing is a loose phrase.", embedding=_axis(3))
    _chunk(db, owner=meaning_only, text="Reserves are created by asset purchases.", embedding=_axis(4))

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


@pytest.mark.parametrize(
    ("text", "query", "keyword_match", "expected_start", "contains"),
    [
        ("Short text.", "short", True, "Short", "Short text."),
        ("x " * 200 + "the Fed doesn't print money in that sense " + "y " * 200, "printing", True, "…", "print money"),
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
