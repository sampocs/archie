"""`archie-launch`: the container's one command. Migrates the database, then runs the API and the worker.

If either child exits, the other is stopped and the launcher exits with the first one's code, so the
platform restarts the whole container instead of leaving half a service running.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from types import FrameType

import sqlalchemy.exc
import sqlalchemy.orm
from archie_db import backfill_embed, migrate, session
from archie_shared import config, logging

_DEFAULT_PORT = "8000"
_POLL_SECONDS = 0.5
_STOP_TIMEOUT_SECONDS = 30

_logger = logging.get_logger(logging.LoggerName.API, "launch")


def main() -> None:
    """Apply migrations, index what search hasn't seen, start both processes, and exit when either one does."""
    logging.configure()
    database_url = config.get_settings().require_database_url()
    migrate.upgrade(database_url)
    _queue_unindexed_items(database_url)

    port = os.environ.get("PORT", _DEFAULT_PORT)
    api = subprocess.Popen(["uvicorn", "archie_api.main:app", "--host", "0.0.0.0", "--port", port])
    worker = subprocess.Popen(["archie-worker"])
    children = [api, worker]
    stopping = False

    def forward_stop(signal_number: int, frame: FrameType | None) -> None:
        # A plain flag, not a threading.Event: a repeated signal (uv forwards ours again) re-enters this handler,
        # and Event.set() would deadlock on its own lock. Idempotent, so a repeat does nothing.
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for child in children:
            child.terminate()

    signal.signal(signal.SIGTERM, forward_stop)
    signal.signal(signal.SIGINT, forward_stop)

    exit_code = _wait_for_first_exit(children)

    # A SIGTERM or SIGINT we were asked to forward is a clean stop (uvicorn re-raises it, so its code is -15).
    if stopping:
        sys.exit(0)
    # A child that quits on its own is a failure even with code 0, or the restart policy would not restart us.
    sys.exit(exit_code or 1)


def _queue_unindexed_items(database_url: str) -> None:
    """Queue `embed` for items that predate search, so a deploy indexes them; a failure is logged, never raised."""
    engine = session.engine_for(database_url)
    try:
        with sqlalchemy.orm.Session(engine) as db:
            queued = backfill_embed.backfill_all(db)
    except sqlalchemy.exc.SQLAlchemyError:
        # A best-effort indexing step must never block the API and worker from starting.
        _logger.exception("Could not queue embed for unindexed items; starting anyway")
        return
    finally:
        engine.dispose()

    _logger.info("Queued embed for %d unindexed items", queued)


def _wait_for_first_exit(children: list[subprocess.Popen[bytes]]) -> int:
    """Block until a child exits, stop the rest, and return the exiting child's code."""
    while True:
        exited = next((child for child in children if child.poll() is not None), None)
        if exited is not None:
            break
        time.sleep(_POLL_SECONDS)

    _logger.warning("A child process exited with code %s; stopping the others", exited.returncode)
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            child.kill()
    return exited.returncode


if __name__ == "__main__":
    main()
