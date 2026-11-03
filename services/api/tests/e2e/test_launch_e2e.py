"""The real `archie-launch` process: a burst of stop signals stops it cleanly instead of deadlocking."""

import os
import pathlib
import signal
import subprocess
import sys
import time

import httpx
import pytest
from archie_shared import config
from archie_testing import harness

pytestmark = pytest.mark.postgres

STARTUP_TIMEOUT_SECONDS = 30.0
EXIT_TIMEOUT_SECONDS = 15.0
SIGNAL_BURST = [signal.SIGTERM, signal.SIGINT] * 500
POLL_INTERVAL_SECONDS = 0.1


def test_a_burst_of_stop_signals_exits_cleanly_and_leaves_no_children(migrated_database_url: str) -> None:
    """A repeated stop (uv forwards it again) re-enters the handler; the launcher must still exit 0 and reap both."""
    bin_dir = pathlib.Path(sys.executable).parent
    port = harness.free_port()
    env = {
        **os.environ,
        config.DATABASE_URL_ENV: migrated_database_url,
        config.ARCHIE_ENV_ENV: "test",
        "PORT": str(port),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    launcher = subprocess.Popen([str(bin_dir / "archie-launch")], env=env, start_new_session=True)

    try:
        _wait_for_health(port=port, launcher=launcher)
        child_pids = _child_pids(launcher.pid)
        assert len(child_pids) == 2, f"expected the API and the worker as children, found {child_pids}"

        for stop_signal in SIGNAL_BURST:
            _send(launcher.pid, stop_signal)

        try:
            exit_code = launcher.wait(timeout=EXIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pytest.fail(f"the launcher did not exit within {EXIT_TIMEOUT_SECONDS}s of a signal burst (deadlocked)")

        assert exit_code == 0
        assert [pid for pid in child_pids if _is_alive(pid)] == []
    finally:
        _kill_group(launcher.pid)
        launcher.wait()


def _wait_for_health(*, port: int, launcher: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        assert launcher.poll() is None, f"the launcher exited early with code {launcher.returncode}"
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health").status_code == httpx.codes.OK:
                return
        except httpx.TransportError:
            pass
        time.sleep(POLL_INTERVAL_SECONDS)
    pytest.fail(f"/health did not answer within {STARTUP_TIMEOUT_SECONDS}s")


def _child_pids(parent_pid: int) -> list[int]:
    listing = subprocess.run(["pgrep", "-P", str(parent_pid)], capture_output=True, text=True, check=False)
    return [int(pid) for pid in listing.stdout.split()]


def _send(pid: int, stop_signal: signal.Signals) -> None:
    # Raw os.kill (no Popen bookkeeping between signals) so they land back to back; a dead launcher is fine.
    try:
        os.kill(pid, stop_signal)
    except ProcessLookupError:
        pass


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill_group(group_id: int) -> None:
    try:
        os.killpg(group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
