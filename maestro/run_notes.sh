#!/usr/bin/env bash
# The notes flow: log in, import two invented Bear notes, seed their write-ups without a model, then refresh one and press Done.
# Run from the repo root with the backend and worker up (`make start-local`). Spends a few cents (one Sonnet answer that proposes the cards in a chat).
# scripts/import_bear.py is not used here: the flow posts the fixture to the endpoint directly.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH"

API=http://localhost:8000

maestro test maestro/newsletter_1_login.yaml

# The key stays in a variable and is never printed.
KEY=$(curl -fsS -X POST "$API/test/session" -H 'content-type: application/json' -d '{"apple_sub":"test-user"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_key"])')

IDS=$(curl -fsS -X POST "$API/notes/import" \
  -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' \
  --data-binary @maestro/fixtures/notes.json \
  | python3 -c 'import json,sys; print(" ".join(row["id"] for row in json.load(sys.stdin)["results"]))')

# A write-up without a model call: the domain, a gist with two key ideas, and one source link.
WRITE_UP='{"domain": "Crypto", "summary": {"gist": "Liquid staking lets you stake and still hold a tradable receipt token.", "key_ideas": [{"timestamp": null, "idea": "You stake with a provider and get an LST back."}, {"timestamp": null, "idea": "The LST can be used elsewhere while it earns staking rewards."}], "numbers": []}, "sources": [{"url": "https://example.com/lido", "title": "Lido docs"}]}'
for ID in $IDS; do
  curl -fsS -X POST "$API/test/notes/$ID/write-up" -H 'content-type: application/json' -d "$WRITE_UP" >/dev/null
done

maestro test maestro/notes.yaml
