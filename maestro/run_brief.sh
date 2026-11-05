#!/usr/bin/env bash
# The brief flow: log in, deliver a news newsletter and an essay through the ingest endpoint, then read the brief.
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

# Both go to the same address (one inbox); the fixtures carry distinct Message-IDs, so neither is deduped away.
deliver() {
  curl -fsS -X POST http://localhost:8000/ingest/email \
    -H "content-type: message/rfc822" \
    -H "x-ingest-secret: $SECRET" \
    -H "x-ingest-to: $TOKEN@local.test" \
    -H "x-ingest-from: $1" \
    --data-binary @"$2" >/dev/null
}

deliver crew@morningbrew.com services/api/tests/fixtures/newsletters/morning_brew.eml
deliver bytebytego@substack.com services/api/tests/fixtures/newsletters/substack_bytebytego.eml

maestro test maestro/brief.yaml
