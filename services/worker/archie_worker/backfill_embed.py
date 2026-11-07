"""`archie-worker backfill-embed`: queue `embed` for unindexed items by hand (the launcher also does it on deploy)."""

from __future__ import annotations

import sqlalchemy.orm
from archie_db import backfill_embed, session
from archie_shared import config, logging

_logger = logging.get_logger(logging.LoggerName.WORKER, "backfill_embed")


def main() -> None:
    """Queue the jobs against `DATABASE_URL` and report how many."""
    logging.configure()
    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        count = backfill_embed.backfill_all(db)
        db.commit()
    _logger.info("Queued embed for %d items", count)
