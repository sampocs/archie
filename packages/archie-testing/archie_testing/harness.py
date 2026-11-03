"""A live Archie stack for e2e tests: the real API served by uvicorn on a free local port.

Tests talk to it over real HTTP with `httpx`, exactly as the phone app does. The worker loop runs
in a background thread only when a test asks for it, so API-only tests never import worker code.
"""

from __future__ import annotations

import contextlib
import importlib
import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import archie_api.deps
import archie_api.main
import httpx
import uvicorn
from archie_db import session

_STARTUP_TIMEOUT_SECONDS = 10.0
_SHUTDOWN_TIMEOUT_SECONDS = 10.0
_POLL_INTERVAL_SECONDS = 0.02


@dataclass
class LiveStack:
    """A running API (and maybe worker) plus the HTTP clients tests use to drive it."""

    base_url: str
    database_url: str
    client: httpx.Client
    _authed_clients: list[httpx.Client] = field(default_factory=list)

    def sign_in(self, *, apple_sub: str = "test-user") -> str:
        """Create (or reuse) a user and return a fresh session key, via the test-only route."""
        response = self.client.post("/test/session", json={"apple_sub": apple_sub})
        response.raise_for_status()
        return response.json()["session_key"]

    def authed(self, session_key: str) -> httpx.Client:
        """A client that sends `session_key` as a bearer token on every request."""
        authed_client = httpx.Client(base_url=self.base_url, headers={"Authorization": f"Bearer {session_key}"})
        self._authed_clients.append(authed_client)
        return authed_client

    def close_authed_clients(self) -> None:
        """Close every client `authed` handed out."""
        for authed_client in self._authed_clients:
            authed_client.close()


@contextlib.contextmanager
def running_stack(*, database_url: str, start_worker: bool) -> Iterator[LiveStack]:
    """Serve the real app (and optionally the worker) until the block exits.

    The caller must already have set `DATABASE_URL` and `ARCHIE_ENV=test`: the app reads them when built.
    """
    archie_api.deps.reset_engine()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(archie_api.main.create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    _wait_until(condition=lambda: server.started, description="the API server to start")

    stop_worker = threading.Event()
    worker_thread = _start_worker(database_url=database_url, stop=stop_worker) if start_worker else None

    base_url = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=base_url) as client:
        stack = LiveStack(base_url=base_url, database_url=database_url, client=client)
        try:
            yield stack
        finally:
            stack.close_authed_clients()
            stop_worker.set()
            if worker_thread is not None:
                worker_thread.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS)

            server.should_exit = True
            server_thread.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
            archie_api.deps.reset_engine()


def _start_worker(*, database_url: str, stop: threading.Event) -> threading.Thread:
    # Imported here so tests without the worker marker never depend on worker code.
    loop = importlib.import_module("archie_worker.loop")
    engine = session.engine_for(database_url)
    thread = threading.Thread(target=loop.run_forever, args=(engine,), kwargs={"stop": stop}, daemon=True)
    thread.start()
    return thread


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_until(*, condition: Callable[[], bool], description: str) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {description}")
        time.sleep(_POLL_INTERVAL_SECONDS)
