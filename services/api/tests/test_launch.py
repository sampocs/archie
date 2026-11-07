"""`archie-launch` starts the API and worker even when the deploy-time embed backfill fails."""

import pytest
import sqlalchemy.exc
from archie_api import launch
from archie_db import backfill_embed
from sqlalchemy.orm import Session


def test_a_failing_backfill_does_not_stop_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The backfill is best-effort: a database error is logged and swallowed."""

    def fail(db: Session) -> int:
        raise sqlalchemy.exc.OperationalError(statement="select 1", params=None, orig=Exception("down"))

    monkeypatch.setattr(backfill_embed, "backfill_all", fail)

    launch._queue_unindexed_items("postgresql+psycopg://archie:archie@127.0.0.1:1/none")
