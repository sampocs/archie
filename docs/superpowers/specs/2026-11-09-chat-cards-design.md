# Cards from a chat: design

Approved mocks: `docs/superpowers/specs/2026-11-09-chat-cards-mocks.html` (screens 01–07, 03a, 03b; 03 is the compact
block: cheat-sheet line, card pager, one footer row).

## Why

The owner wants Ask to support "realise I should know X → ask about it → keep it": chat about something
(JWT vs session tokens), then turn the chat into review cards **and** a clean cheat sheet to re-read later. Today
"Make a card" drafts one card from one answer with a separate model call that the chat never sees, so there is no
way to make several cards, discuss them, or keep a tidy reference; and the chat looks frozen until the first token.

## What the owner sees

- **Working indicator (01).** From send until the first streamed text, the answer area shows three typing dots
  (bobbing in turn, `--ai` colour), a shimmering "Thinking" and an elapsed-seconds counter ("4s"). The label becomes
  "Searching your library…" / "Drafting an edit…" / "Drafting cards…" while those tools run (same row, same dots),
  and the row disappears when text streams. Reduced motion: dots static, no shimmer.
- **"Make cards" (02)** replaces "Make a card" on every complete answer. Tapping it sends the user message
  `Make cards` in that chat; typing "make me cards on this" does the same thing. The old single-card sheet goes.
- **A card-set proposal (03).** Claude answers with one compact proposal block, no kicker header:
  - one **cheat-sheet line** (`▤ Cheat sheet · {title} ›`, ellipsised); tapping it opens a sheet rendering the full
    markdown exactly as Library will (03a; Done / swipe down closes). No inline preview;
  - the **cards one at a time**, each card showing `CARD n` and its own **Keep** tick in the card's top-right
    corner, question, then answer under a dashed rule. Unticked cards dim and strike through;
  - **one footer row**: `‹ n / N ›` and **See all** on the left, **Save K** (K = kept count; disabled at 0) and
    **×** (Discard) on the right. See all switches the card area to a numbered list of every card with its tick
    (03b), whose footer reads **One at a time** instead. The chosen view is remembered on the phone;
  - the composer stays available below, so changes are asked for in the chat.
  - When this chat already saved an item, the Save button reads **Update K** instead.
- **Back and forth (04).** Asking for changes produces a fresh proposal; every earlier still-open proposal in that
  chat collapses to a one-line `Earlier proposal · Replaced`. Ticks reset to all-kept on each new proposal.
- **Saved (05).** The block keeps the cheat-sheet line and shows `✓ Saved · K cards in review` and **Open** (→ the Library item); toast
  `Saved to Library`. Later proposals in the same chat update that same item (one chat ↔ at most one item).
  Discarded shows `Discarded`.
- **In Library (06).** A new source kind **Chat** (kicker `Chat`, label "Chat", `--ai` tile). The item page shows
  Archie's version (the cheat-sheet markdown) first, a segmented `Archie's version | See original`; the original is
  the chat transcript, read-only, with **Continue in Ask** when the chat still exists. The item's Cards list works as
  on any item. Chat items never enter the queue, the analyze/primer pipeline, or the notes refresher.
- **In review (07).** A card from a chat item shows `From {title} · Chat`; tapping it opens the item.

## Decisions

- **A tool, not a `<cards>` tag.** The model calls a strict client tool `propose_cards`, like the chat-edit
  `propose_*` tools: the input is schema-validated (lengths, counts), streams as an event, persists as a synced row,
  and renders natively. Free text stays free text.
- **The cheat sheet is markdown, stored as the item's primer artifact.** Primers are already markdown, rendered in
  the app and editable through chat (`propose_text_edit`), so a chat item's cheat sheet gets rendering and edits for
  free. The item's `summary` artifact holds only `{"gist": <first paragraph, ≤ 300 chars>, "key_ideas": [],
  "numbers": []}` (Library row, search snippets); its `text` artifact is the transcript (embedding, Ask, See
  original).
- **Cards belong to the item** (`source_id` = the chat item, `message_id` = the proposal's message), so the item's
  card list, deletes and the review source line all work as for other items. Existing chat-origin cards
  (`conversation_id` set) are untouched.
- **Online-only Save/Discard**, as REST calls like edit Apply (Ask is already online-only and whitelisted).
- **No new model call on save.** Save copies what the proposal holds; the transcript is built from stored messages.

## Data

Migration `0017_chat_cards` (+ the phone drizzle migration):

- `SourceKind.CHAT = "chat"`.
- `sources.chat_conversation_id uuid NULL REFERENCES conversations(id) ON DELETE SET NULL`, synced, with a partial
  unique index on it where not null (one item per chat). A deleted conversation leaves the item; See original still
  renders from the text artifact, Continue in Ask hides.
- Table `card_set_proposals` (synced like `edit_proposals`): `id uuid pk`, `user_id`, `conversation_id` (fk, cascade),
  `message_id` (fk, cascade), `title text`, `cheat_sheet text` (markdown), `cards jsonb` (`[{kind, question,
  answer}]`), `status varchar(16)` (`proposed | saved | replaced | discarded`), `saved_source_id uuid NULL`,
  `kept jsonb NULL` (indices saved), `created_at`, `updated_at`, `change_seq`; index `(user_id, change_seq)`.

## Server

- **Tool `propose_cards`** (`archie_api/ask/card_set_tools.py`, registered beside `edit_tools`): input `{title (1–120),
  cheat_sheet (markdown, 1–20,000), cards: 1–10 × {kind ∈ concept|mechanism|number|foundation, question (≤ 500),
  answer (≤ 2,000)}}`. Valid → a `card_set_proposals` row (`proposed`), every earlier `proposed` row in the chat →
  `replaced` (touched), and a stream event `cards` carrying the row; the `editing`-style start event is
  `drafting_cards`. Invalid → a tool error the model can correct (existing `_error_text` pattern). Saved with the
  answer like edit proposals.
- **Prompt** (`prompts.CARD_SET_RULES`, appended to `ASK_SYSTEM`): when the owner asks for cards (the `Make cards`
  message or any wording), call `propose_cards` once with the whole conversation in view: a cheat sheet that reads
  as a fresh, self-contained reference (headings, a comparison table when comparing, gotchas; never "as discussed
  above"), in `prompts.READING_VOICE`; 3–7 open-recall cards on what the chat established, each answerable alone.
  On "change card 2" etc., re-propose the full set with the change. Keep the surrounding prose to one or two
  sentences.
- **`POST /ask/card-sets/{id}/save`** `{"kept": [int, …]}` (unique, in range, ≥ 1) under the user write lock:
  `409` unless `proposed`. Find or create the chat item (kind chat, title = proposal title, `chat_conversation_id`,
  state `inbox`, intent none, processing ready, never queued); write primer = cheat sheet, summary = gist, text =
  transcript (`**You:** … / **Archie:** …` from the chat's complete messages), each a new version when the item
  exists (title updated too); queue `embed`; create one card per kept index (`source_id` = item, `message_id`,
  `kind`, `question`, `answer`, FSRS new); proposal → `saved`, `saved_source_id`, `kept`. Returns the row.
- **`POST /ask/card-sets/{id}/discard`** → `discarded` (`409` unless `proposed`).
- **Removed:** `POST /ask/messages/{id}/card-draft`, `POST /ask/cards`, `card_prompts.py`, `llm.CARD_DRAFT_MODELS`,
  their tests and cassettes.
- **Test seed** `POST /test/card-sets` (dev/test env only, like the notes seed): makes a proposal in a chat without a
  model, for Maestro.

## App

- Sync: `card_set_proposals` table and `sources.chat_conversation_id` in drizzle schema and pull.
- `app/src/ask/ThinkingRow.tsx` (dots + shimmer + seconds; label prop) used by `AnswerView` for the pending state and
  the `searching` / `editing` / new `drafting_cards` states.
- `app/src/ask/CardSetProposal.tsx` (block, pager/list, per-card Keep, Save/Discard, states) and
  `CheatSheetSheet.tsx` (full markdown). `sections.ts` gains `cards` events in `LiveAnswer` (like `proposals`).
- `MakeCardSheet.tsx` and its api calls removed; "Make cards" sends the message.
- Labels: `kindLabel("chat") = "Chat"`; item page for kind chat = primer markdown + `See original` (text artifact
  markdown) + Continue in Ask; review card source line `From {title} · Chat`.

## Testing

- Server e2e (Postgres): a recorded Sonnet cassette where `Make cards` yields one valid `propose_cards` call →
  `cards` event, row persisted; a re-proposal replaces the earlier one; save creates the item, three artifacts and
  only the kept cards, and a second save in the same chat updates the same item; discard; 409s; invalid tool input
  returns a correctable error. Unit: transcript building, gist extraction.
- App jest: pager/list keep state and Save count, replaced/saved/discarded rendering, ThinkingRow label switching.
- Maestro `chat_cards.yaml` (+ `make maestro-chat-cards`, spends nothing): seed a proposal, untick one, See all,
  Save, open the item, See original.

## Build plan

### Chunk 1: server
Files: migration 0017, `models.py`, `ask/card_set_tools.py`, `ask/answer.py` (register tool, events), `ask/prompts.py`,
`ask/card_routes.py` (replace contents with the save/discard routes) and removal of `card_prompts.py`, sync pull of
the new table/column, `test_routes.py` seed, tests + cassette.
Produces: the row shape above, events `drafting_cards` / `cards` (payload = the row as pulled), the two routes, the
seed route. Depends on: none.

### Chunk 2: app
Files: drizzle schema + migration, sync, `ThinkingRow`, `CardSetProposal`, `CheatSheetSheet`, `AnswerView`,
`sections.ts`, `[id].tsx`, `api.ts`, item page and labels for kind chat, review source line, removal of
`MakeCardSheet`, Maestro flow + Makefile target + README.
Consumes chunk 1's contract as written here. Depends on: none (built against this spec; merged after chunk 1).

## Follow-ups (2026-11-10)

- **Only the tick flips Keep.** In the pager (`CardFace`) and See all (`ListRow`) the Keep checkbox is the only
  pressable for Keep: a 44-point target around the 14-point tick (`hitSlop`), with a light selection haptic. The rest
  of the row or card isn't pressable, so tapping or scrolling over a card never changes what is kept.
- **The next message carries the ticks.** The chat screen holds every set's ticks by set id (a live set keeps them
  when its stored row lands). When the owner sends any message (typed, Make cards, Try again) while the chat's stored
  set is `proposed` with at least one card unticked, the body carries `card_set_choice: {proposal_id, kept}`
  (0-based indices); with every card ticked it carries nothing. The server applies it only if the set is this chat's
  and user's, is `proposed`, names each index once, in range, and drops at least one card; otherwise it is ignored and
  the turn goes ahead as typed.
  - Stored in the question's existing `segments` (null for a question until now) as one segment
    `{card_set_choice: {proposal_id, kept, card_count}}`; no migration. Every reader already tolerates it (the
    phone's `parseSegments` and the server's citation lines skip a segment without their keys), it syncs to the
    phone with the message unchanged, and `card_count` lets the phone draw its line without finding the set.
  - The model reads it as a line before the owner's words, in that turn and in every later turn's history:
    "The owner kept cards 1, 3 and 5 of the proposed set and dropped 2 (“…”) and 4 (“…”)." `CARD_SET_RULES` says
    the next proposal copies the kept cards word for word (so Save matches them) unless asked to change them, and
    doesn't bring back dropped ones.
  - The app shows a muted "Kept 3 of 5 cards" under that question's bubble, from the stored segment (or, while it
    is pending, from what it sent). A new set has a new id, so its ticks start all kept.
