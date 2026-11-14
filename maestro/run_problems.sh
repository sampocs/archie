#!/usr/bin/env bash
# The problems flow: log in, seed a failed summary job for the signed-in user through the dev route, then check that Today
# shows the banner and the sheet names the problem. Run from the repo root with the backend up (`make start-local`).
# Spends nothing on models.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH"

API=http://localhost:8000

maestro test maestro/login.yaml

# The key stays in a variable and is never printed.
KEY=$(curl -fsS -X POST "$API/test/session" -H 'content-type: application/json' -d '{"apple_sub":"test-user"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_key"])')

# A failed analyze job for the test user; the phone asks /problems when Today gains focus and after its next sync.
curl -fsS -X POST "$API/test/failed-job" -H "Authorization: Bearer $KEY" >/dev/null

maestro test maestro/problems.yaml
