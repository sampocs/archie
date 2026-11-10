#!/usr/bin/env bash
# The notes flow: log in, import two invented Bear notes, seed their write-ups and a chat about the first without a model, then open the note page and the seeded chat.
# Run from the repo root with the backend and worker up (`make start-local`). Spends nothing on models.
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

# A chat about the first note with a three-card proposal (no cheat sheet), as Done would leave it, without a model.
FIRST_ID=${IDS%% *}
CARD_SET=$(python3 - "$FIRST_ID" <<'PY'
import json, sys
cards = [
    {"kind": "concept", "question": "What is liquid staking?", "answer": "Staking while holding a tradable receipt token."},
    {"kind": "mechanism", "question": "What do you get back for staking?", "answer": "An LST that earns the staking rewards."},
    {"kind": "concept", "question": "Why use an LST elsewhere?", "answer": "It stays usable while it earns."},
]
print(json.dumps({"title": "Liquid Staking", "cheat_sheet": "", "cards": cards, "about_note_id": sys.argv[1]}))
PY
)
curl -fsS -X POST "$API/test/card-sets" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d "$CARD_SET" >/dev/null

maestro test maestro/notes.yaml
