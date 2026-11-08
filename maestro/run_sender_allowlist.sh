#!/usr/bin/env bash
# The sender allowlist flow: log in, deliver Morning Brew's newsletter (an unknown sender on a fresh database) and block
# it from its Library card, then re-deliver it under a new Message-ID and check it is dropped.
# Run from the repo root with the backend already up (`make start-local`); needs INGEST_SECRET in .env. Spends nothing.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH"

if ! grep -q '^INGEST_SECRET=' .env; then
  echo "INGEST_SECRET is not set in .env; the ingest endpoint needs it to accept the email"
  exit 1
fi

FIXTURE=services/api/tests/fixtures/newsletters/morning_brew.eml
SECRET=$(grep '^INGEST_SECRET=' .env | cut -d= -f2-)

deliver() {
  curl -fsS -X POST http://localhost:8000/ingest/email \
    -H "content-type: message/rfc822" \
    -H "x-ingest-secret: $SECRET" \
    -H "x-ingest-to: $TOKEN@local.test" \
    -H "x-ingest-from: crew@morningbrew.com" \
    --data-binary @"$1" >/dev/null
}

maestro test maestro/newsletter_1_login.yaml
TOKEN=$(docker compose exec -T postgres psql -q -U archie archie -tAc "SELECT ingest_token FROM users WHERE apple_sub = 'test-user'" | tr -d '[:space:]')

deliver "$FIXTURE"
maestro test maestro/sender_allowlist.yaml

# The same newsletter again with a new Message-ID, so the dedupe check doesn't hide the sender check.
REDELIVERY_DIR=$(mktemp -d)
trap 'rm -rf "$REDELIVERY_DIR"' EXIT
sed "s/^Message-ID: .*/Message-ID: <redelivery-$(date +%s)@example.invalid>/" "$FIXTURE" >"$REDELIVERY_DIR/morning_brew_again.eml"
deliver "$REDELIVERY_DIR/morning_brew_again.eml"

# A blocked sender's email is dropped, not stored: only the first, deleted one exists.
STORED=$(docker compose exec -T postgres psql -q -U archie archie -tAc "SELECT count(*) FROM sources WHERE kind = 'newsletter'" | tr -d '[:space:]')
if [ "$STORED" != "1" ]; then
  echo "expected the re-delivered email to be dropped (1 newsletter source), found $STORED"
  exit 1
fi

maestro test maestro/sender_blocked_stays_gone.yaml
