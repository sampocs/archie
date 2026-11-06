"""Centralized logging setup shared by every Archie service.

One place owns log format, level, and noisy-logger suppression, instead of each module
re-deriving them with a bare `logging.getLogger("some.string")`. A service calls `configure()`
once at startup; every module asks for a logger with `get_logger`, naming the high-level
process via `LoggerName` and an optional submodule. Loggers are hierarchical, so
`get_logger(LoggerName.WORKER, "fetch_title")` is named `worker.fetch_title` and inherits the
root configuration.

Money is formatted explicitly at the call site (USD `:.2f`); see `archie_shared.money`.
"""

import logging
import sys
from enum import StrEnum, auto

# Human-readable console format, compact enough to scan in Railway's log view.
_CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"
_CONSOLE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that are noisy at INFO and add nothing to our logs. `httpx` logs a line for
# every request, including every page the worker fetches.
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3")

_console_handler = logging.StreamHandler(sys.stdout)
_configured = False


class LoggerName(StrEnum):
    """Identifies the high-level process emitting a log line."""

    API = auto()
    WORKER = auto()
    DB = auto()
    LLM = auto()


def configure(*, level: int = logging.INFO) -> None:
    """Install the shared console handler on the root logger, exactly once.

    Idempotent: safe to call from a service entrypoint and again indirectly via `get_logger`,
    so a module that builds its logger at import time still gets a configured root.
    """
    global _configured
    if _configured:
        return

    _console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_CONSOLE_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(_console_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True


def get_logger(process: LoggerName, module: str | None = None) -> logging.Logger:
    """Return the namespaced logger for a process (and optional submodule).

    Ensures the root is configured first, so callers never see an unconfigured logger.
    """
    configure()
    name = str(process) if module is None else f"{process}.{module}"
    return logging.getLogger(name)
