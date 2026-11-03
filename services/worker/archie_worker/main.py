"""`archie-worker` (or `python -m archie_worker.main`): the background process that runs queued jobs."""

import signal
import threading
from types import FrameType

from archie_db import session
from archie_shared import config, logging

from archie_worker import loop

_logger = logging.get_logger(logging.LoggerName.WORKER)


def main() -> None:
    """Run the job loop until SIGTERM or Ctrl-C, finishing the job in hand first."""
    logging.configure()
    engine = session.engine_for(config.get_settings().require_database_url())

    stop = threading.Event()

    def request_stop(signal_number: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    _logger.info("Worker started")
    loop.run_forever(engine, stop=stop)
    _logger.info("Worker stopped")


if __name__ == "__main__":
    main()
