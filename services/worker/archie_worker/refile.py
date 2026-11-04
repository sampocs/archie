"""`archie-refile-sources`: queue `file_topic` for every live, analyzed source of every user who has chosen topics.

Run once after deploying M4, after the owner opened the app (which seeds their topics); see docs/deploy.md.
Re-running only files sources again.
"""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session, user_topics
from archie_shared import config, logging

_logger = logging.get_logger(logging.LoggerName.WORKER, "refile")


def main() -> None:
    """Queue the filing jobs against `DATABASE_URL` and report how many."""
    logging.configure()
    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        count = refile_all(db)
        db.commit()
    _logger.info("Queued file_topic for %d sources", count)


def refile_all(db: sqlalchemy.orm.Session) -> int:
    """Queue one `file_topic` per analyzed live source of each user with topics, in the caller's transaction."""
    user_ids = db.scalars(sqlalchemy.select(models.User.id).where(models.User.topics_chosen_at.is_not(None))).all()
    queued = 0
    for user_id in user_ids:
        changes.lock_user_writes(db, user_id)
        for source in user_topics.analyzed_sources(db, user_id=user_id):
            user_topics.enqueue_file_topic(db, source=source)
            queued += 1
    return queued
