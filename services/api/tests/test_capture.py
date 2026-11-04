"""The pull page merge: synced tables become one page ordered by change position."""

from dataclasses import dataclass

from archie_api.sync import pull


@dataclass(frozen=True)
class _Row:
    change_seq: int


def _rows(*change_seqs: int) -> list[_Row]:
    return [_Row(change_seq=change_seq) for change_seq in change_seqs]


def _seqs(rows: list[_Row]) -> list[int]:
    return [row.change_seq for row in rows]


def _tables(**rows: list[_Row]) -> dict[str, list[_Row]]:
    return dict(rows)


def _kept(page: pull.MergedPage[_Row]) -> dict[str, list[int]]:
    return {name: _seqs(rows) for name, rows in page.rows.items()}


def test_rows_from_all_tables_fit_one_page() -> None:
    """Under the limit every row is kept, the position is the highest one, and nothing is left."""
    page = pull.merge_page(tables=_tables(sources=_rows(1, 4), artifacts=_rows(2), cards=_rows(3)), since=0, limit=10)

    assert _kept(page) == {"sources": [1, 4], "artifacts": [2], "cards": [3]}
    assert (page.position, page.more) == (4, False)


def test_rows_past_the_limit_are_cut_from_every_table_by_position() -> None:
    """The lowest `limit` positions across tables stay; the position is the last kept one, and more is set."""
    tables = _tables(sources=_rows(1, 5), artifacts=_rows(2, 6), cards=_rows(3, 4))

    page = pull.merge_page(tables=tables, since=0, limit=4)

    assert _kept(page) == {"sources": [1], "artifacts": [2], "cards": [3, 4]}
    assert (page.position, page.more) == (4, True)


def test_a_full_table_means_more_even_when_nothing_is_cut() -> None:
    """A table that returned `limit` rows may have more behind it, so `more` is set when only it filled the page."""
    page = pull.merge_page(tables=_tables(sources=_rows(1, 2), artifacts=_rows(), cards=_rows()), since=0, limit=2)

    assert (_kept(page)["sources"], page.position, page.more) == ([1, 2], 2, True)


def test_two_of_five_tables_filling_their_own_limit_means_more() -> None:
    """With five tables, two that each hold `limit` rows are cut together and the page is not the last."""
    tables = _tables(
        sources=_rows(1, 4),
        artifacts=_rows(),
        cards=_rows(),
        topics=_rows(2, 5),
        topic_primers=_rows(3),
    )

    page = pull.merge_page(tables=tables, since=0, limit=2)

    assert _kept(page) == {"sources": [1], "artifacts": [], "cards": [], "topics": [2], "topic_primers": []}
    assert (page.position, page.more) == (2, True)


def test_an_empty_pull_keeps_the_position() -> None:
    """With no rows the phone stays where it was."""
    page = pull.merge_page(tables=_tables(sources=_rows(), artifacts=_rows(), cards=_rows()), since=7, limit=3)

    assert _kept(page) == {"sources": [], "artifacts": [], "cards": []}
    assert (page.position, page.more) == (7, False)
