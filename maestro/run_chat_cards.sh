#!/usr/bin/env bash
# The chat-cards flow: log in, seed a chat holding a card-set proposal without a model, then save it with one card
# unticked and open the Library item it made; then browse and practice those cards on the Review tab. Run from the repo root with the backend up (`make start-local`).
# Spends nothing on models (the save queues one embedding of the item).
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH"

API=http://localhost:8000

maestro test maestro/newsletter_1_login.yaml

# The key stays in a variable and is never printed.
KEY=$(curl -fsS -X POST "$API/test/session" -H 'content-type: application/json' -d '{"apple_sub":"test-user"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_key"])')

# A new chat whose answer proposes the fixture's cheat sheet and three cards; the phone pulls it on its next sync.
curl -fsS -X POST "$API/test/card-sets" \
  -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' \
  --data-binary @maestro/fixtures/chat_cards.json >/dev/null

maestro test maestro/chat_cards.yaml maestro/review_browse.yaml
