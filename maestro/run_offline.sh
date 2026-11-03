#!/usr/bin/env bash
# The offline-sync flow: log in with the backend up, add a link with it down, bring it back, watch the link sync.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH"

LOG_FILE="${TMPDIR:-/tmp}/archie-offline-backend.log"
BACKEND_PID=""

start_backend() {
  # Job control gives the backend its own process group so `stop_backend` can take down make, uv and uvicorn together.
  set -m
  make start-local >>"$LOG_FILE" 2>&1 &
  BACKEND_PID=$!
  set +m

  until curl -fs http://localhost:8000/health >/dev/null 2>&1; do
    kill -0 "$BACKEND_PID" 2>/dev/null || { echo "backend exited early; see $LOG_FILE"; exit 1; }
    sleep 1
  done
}

stop_backend() {
  [ -n "$BACKEND_PID" ] || return 0
  kill -TERM -- "-$BACKEND_PID" 2>/dev/null || true
  while curl -fs http://localhost:8000/health >/dev/null 2>&1; do sleep 0.5; done
  BACKEND_PID=""
}

trap stop_backend EXIT

start_backend
maestro test maestro/offline_1_login.yaml

stop_backend
maestro test maestro/offline_2_add.yaml

start_backend
maestro test maestro/offline_3_synced.yaml
