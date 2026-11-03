"""`python -m archie_worker.main`: the background worker process that runs queued jobs."""

from archie_shared import logging

_logger = logging.get_logger(logging.LoggerName.WORKER)


def main() -> None:
    """Run the worker until the process is stopped."""
    logging.configure()
    # SCAFFOLD: stub entry point; the real job loop (claim, run, retry, requeue stale) lands in plan Task 7.
    _logger.info("Worker has no job loop yet; exiting")


if __name__ == "__main__":
    main()
