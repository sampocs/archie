"""`archie-worker backfill-chat-names`: queue `name_chat` for every live chat with a complete answer, run once.

Chats from before automatic names are titled after their first question. Each job writes only while the chat still
has that title, so a chat the owner renamed keeps its name; running it twice is harmless: a chat already named
is skipped before any model call.
"""

from __future__ import annotations

import sqlalchemy.orm
from archie_db import chat_names, session
from archie_shared import config, logging

_logger = logging.get_logger(logging.LoggerName.WORKER, "backfill_chat_names")


def main() -> None:
    """Queue the jobs against `DATABASE_URL` and report how many."""
    logging.configure()
    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        count = chat_names.backfill_all(db)
    _logger.info("Queued name_chat for %d chats", count)
