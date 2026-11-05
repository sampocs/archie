#!/usr/bin/env bash
# The newsletter flow: log in, deliver a newsletter through the ingest endpoint, then queue it, undo, and make review cards from it.
# Run from the repo root with the backend already up (`make start-local`); needs the owner's keys and INGEST_SECRET in .env.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH"

if ! grep -q '^INGEST_SECRET=' .env; then
  echo "INGEST_SECRET is not set in .env; the ingest endpoint needs it to accept the email"
  exit 1
fi

maestro test maestro/newsletter_1_login.yaml

TOKEN=$(docker compose exec -T postgres psql -q -U archie archie -tAc "SELECT ingest_token FROM users WHERE apple_sub = 'test-user'" | tr -d '[:space:]')
SECRET=$(grep '^INGEST_SECRET=' .env | cut -d= -f2-)

curl -fsS -X POST http://localhost:8000/ingest/email \
  -H "content-type: message/rfc822" \
  -H "x-ingest-secret: $SECRET" \
  -H "x-ingest-to: $TOKEN@local.test" \
  -H "x-ingest-from: crew@morningbrew.com" \
  --data-binary @services/api/tests/fixtures/newsletters/morning_brew.eml >/dev/null

maestro test maestro/newsletter_2_go_deeper.yaml
