# A note's cards, made in chat: design

Owner-approved direction (2026-11-10): reuse the chat-cards flow (`2026-11-09-chat-cards-design.md`) for notes, so
the owner can shape a note's cards instead of taking whatever `note_cards` writes.

## What the owner sees

- On a note's page the bottom button reads **Done, make cards** (was "Done, add review cards").
- Tapping it marks the note refreshed (as today: Done item, counts toward the 2-a-day refresher) and opens an Ask chat
  about the note, which immediately sends `Make cards`. The chat streams Claude's proposal in the same card-set block
  as chat cards (one card at a time, per-card Keep, See all, Save K / ×), **without the cheat-sheet line**: the note
  already has its write-up.
- The owner can push back in the chat ("skip the Rust internals; cover when to pick Convex over Postgres"); Claude
  re-proposes the full set and the earlier one collapses to Replaced, as in chat cards.
- **Save K** adds the kept cards to the note; the block shows `✓ Saved · K cards in review` and **Open** goes back to
  the note. Saving again from the same chat follows the chat-cards rule: identical kept cards keep their progress, new
  ones are added, unkept cards that were never reviewed are retired, reviewed cards are never retired.
- Offline, or for a user who can't use Ask: Done behaves as before (marks refreshed and queues `note_cards`), with the
  label "Done, add review cards".
- Discarding (×) leaves the note with no new cards; the owner can come back via ••• → Ask about this and say "make
  cards".

## Server

- `refresh_note` payload gains optional `make_cards: bool` (default `true`, so older phones keep working). `false`
  skips enqueuing `NOTE_CARDS`; everything else is unchanged.
- `propose_cards`: in a conversation about a source of kind `note` (`about_source_id`), `cheat_sheet` may be empty
  (and the prompt asks for it empty); elsewhere it stays required (1–20,000). `title` = the note's title.
- Card-set Save for such a proposal: no chat item is created and no artifacts are written; the kept cards are synced
  onto the note source with the existing `_keep_cards` rules; `saved_source_id` = the note's id. 409/404 rules as now
  (a deleted note → 404).
- Prompt (`prompts.CARD_SET_RULES`): when the chat is about a note, call `propose_cards` with an empty cheat sheet and
  3–5 open-recall cards (concept / mechanism / number) on what the note chose to cover, worded from its write-up and
  the owner's steer in the chat; same one-call, full-set-on-revision rules.
- `_requeue_note_cards` (cards-on) is unchanged.

## App

- Note page: when Ask is available and online, Done sends `refresh_note` with `make_cards: false` then opens the chat
  about the note (the existing `openChat` with about = the note) with `Make cards` as the first message; otherwise the
  old behaviour and label.
- `CardSetProposal`: hide the cheat-sheet line when `cheatSheet` is empty; `Open` goes to `saved_source_id` (the
  note) as before.

## Testing

Server e2e: `refresh_note` with `make_cards: false` queues no `NOTE_CARDS` (and default still does); a note-about
proposal with an empty cheat sheet validates while a free-standing chat's empty one is rejected; Save attaches kept
cards to the note, creates no chat item and writes no artifacts; re-save keeps reviewed cards. Record one small
cassette (Sonnet, "Make cards" in a chat about a seeded note → `propose_cards` with an empty cheat sheet). App jest:
the Done branch (online+Ask → chat with make_cards false; else old path), proposal without a cheat sheet renders no
cheat-sheet line. Maestro: extend `notes.yaml` only if a free path exists (seed via `/test/card-sets` with the note's
conversation); don't spend credits.

## Build plan

One chunk (server then app, same worktree): `sync/note_actions.py`, `ask/card_set_tools.py`, `ask/card_routes.py`,
`ask/prompts.py`, tests + cassette; `app/src/app/source/[id].tsx`, `app/src/ask/CardSetProposal.tsx`, the refresh
action in the app's db/actions, tests. Depends on: none.
