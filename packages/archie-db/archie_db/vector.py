"""A pgvector `vector(n)` column without the `pgvector` package: lists of floats in, lists of floats out.

psycopg sends the literal as an untyped string, which Postgres casts to `vector` on insert; raw SQL that compares
against a parameter casts it explicitly (`CAST(:embedding AS vector)`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy.types


def to_literal(values: Sequence[float]) -> str:
    """pgvector's text form, e.g. `[0.1,0.2]`."""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def from_literal(text: str) -> list[float]:
    """The floats of pgvector's text form."""
    inner = text.strip().removeprefix("[").removesuffix("]")
    return [float(part) for part in inner.split(",")] if inner else []


class Vector(sqlalchemy.types.UserDefinedType[list[float]]):
    """`vector(dimensions)`; Alembic reflects it as an unknown type and so never reports it as changed."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        """The DDL type."""
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: sqlalchemy.Dialect) -> Callable[[Sequence[float] | None], str | None]:
        """Lists go to the database as pgvector literals."""

        def process(value: Sequence[float] | None) -> str | None:
            return None if value is None else to_literal(value)

        return process

    def result_processor(
        self, dialect: sqlalchemy.Dialect, coltype: object
    ) -> Callable[[str | None], list[float] | None]:
        """pgvector's text comes back as a list of floats."""

        def process(value: str | None) -> list[float] | None:
            return None if value is None else from_literal(value)

        return process
