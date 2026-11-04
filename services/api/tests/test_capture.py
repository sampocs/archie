"""The pull page merge: three tables become one page ordered by change position."""

from dataclasses import dataclass

from archie_api.sync import pull


@dataclass(frozen=True)
class _Row:
    change_seq: int


def _rows(*change_seqs: int) -> list[_Row]:
    return [_Row(change_seq=change_seq) for change_seq in change_seqs]


def _seqs(rows: list[_Row]) -> list[int]:
    return [row.change_seq for row in rows]


def test_rows_from_all_tables_fit_one_page() -> None:
    """Under the limit every row is kept, the position is the highest one, and nothing is left."""
    page = pull.merge_page(sources=_rows(1, 4), artifacts=_rows(2), cards=_rows(3), since=0, limit=10)

    assert (_seqs(page.sources), _seqs(page.artifacts), _seqs(page.cards)) == ([1, 4], [2], [3])
    assert (page.position, page.more) == (4, False)


def test_rows_past_the_limit_are_cut_from_every_table_by_position() -> None:
    """The lowest `limit` positions across tables stay; the position is the last kept one, and more is set."""
    page = pull.merge_page(sources=_rows(1, 5), artifacts=_rows(2, 6), cards=_rows(3, 4), since=0, limit=4)

    assert (_seqs(page.sources), _seqs(page.artifacts), _seqs(page.cards)) == ([1], [2], [3, 4])
    assert (page.position, page.more) == (4, True)


def test_a_full_table_means_more_even_when_nothing_is_cut() -> None:
    """A table that returned `limit` rows may have more behind it, so `more` is set when only it filled the page."""
    page = pull.merge_page(sources=_rows(1, 2), artifacts=_rows(), cards=_rows(), since=0, limit=2)

    assert (_seqs(page.sources), page.position, page.more) == ([1, 2], 2, True)


def test_an_empty_pull_keeps_the_position() -> None:
    """With no rows the phone stays where it was."""
    page = pull.merge_page(sources=_rows(), artifacts=_rows(), cards=_rows(), since=7, limit=3)

    assert (page.sources, page.artifacts, page.cards) == ([], [], [])
    assert (page.position, page.more) == (7, False)
