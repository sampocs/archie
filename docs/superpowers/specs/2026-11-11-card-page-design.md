# A card's own page, with editing by chat

Mocks: `2026-11-11-card-page-mocks.html` (published at https://claude.ai/artifact/2p4N3VYoeUeeSSm4PQmo4n).

## Why

A card found in Review (search, Items, Missed) can only be practiced or removed: tapping it starts a one-card
session, so there's no way to just read it with its answer, and changing it means finding its source and asking in a
chat on the Ask tab. The owner wants a card to open as a record, and to change it by chat without leaving Review.

## Behavior

### Opening a card

- Tapping a card row anywhere it is listed with `CardListRow` (Review search results, Review → Items → an item's
  cards, Missed, an item page's "Cards from this") opens the card's page, `/card/[id]`, pushed on the current stack
  (so from Review it stays in the Review tab). A card that can't be reviewed yet ("After you finish") opens too.
- Swipe actions on the rows (Remove, Versions) are unchanged.

### The card's page (mock 2)

- Nav: back label as usual, title "Card", ••• menu.
- The card, as a record: a kicker line (the kind label, e.g. "Mechanism", and the due label), the question, a dashed
  rule, the answer, then the detail lines (all of them, up to 5).
- Meta pills: the due label ("Due Thu" / "Due today" / "Starts Nov 24" / "After you finish"), "Reviewed N×" when
  reviewed at least once, "Last: Got it|Partly|Missed" from its latest review, and "Edited" when `version > 1`.
- A source row: "From <item title> ›" opening the item it came from (source, take, topic primer or chat item; hidden
  when the card has no openable origin).
- Buttons: **Practice** (`/review/session?mode=card&id=…`, disabled with the existing "After you finish" rule when it
  isn't reviewable) and **Remove** (`dropCard`, then back).
- ••• menu: **Versions** (the existing card `VersionsSheet`) when edited, and **Remove**.

### Changing it by chat (mocks 3 and 4)

- A composer pinned at the bottom: placeholder "Ask to change this card…". Sending starts a chat **about this card**
  (a new conversation the first time; the same one afterwards, see below). The exchange renders under the card with
  the existing chat pieces: user bubbles, answers, thinking row, and `EditProposalCard` with Apply / Discard.
- While a chat is under it, the card collapses to its kicker and question (mock 3); tapping the collapsed card expands
  it again.
- After Apply the card shows its new content in place (it reads the live card row), with "Edited" and a toast "Card
  updated" (the edit card's existing toast).
- **Reopening the card** shows its latest live chat about it under the card, and new messages continue that chat.
- The chat is an ordinary chat: it appears in the Ask list (named by `name_chat` like any other) and can be opened,
  renamed or deleted there. Opened from the Ask list it is the normal chat screen, with "About: <card question>".
- Hang-up, waiting and failed behavior is the same as any chat (it reuses `useChatSession`).

### Ask, about a card

- A chat can be about a card: `conversations.about_card_id` (nullable FK to cards), `about_kind = "card"`.
- The system prompt's about text for a card: "A review card (card id <id>): Q / A / detail lines", plus the title of
  the item it came from, and a line that the owner is here to change or understand this card. The model edits it with
  `read_item` + `propose_card_edit` (it already has the id; no `find_cards` needed).
- Search boost: the card's origin item when it is a source, take or topic primer; none otherwise.
- `name_chat`'s fallback for a card chat: the card's question, cut to fit.

## Design

Server (`services/api`, `packages/archie-db`):
- Migration: `conversations.about_card_id` (UUID, FK `cards.id` `ON DELETE SET NULL`), and the about check becomes
  `num_nonnulls(about_source_id, about_topic_primer_id, about_take_id, about_card_id) <= 1`. `about_kind` gains
  `"card"` (a `ConversationAboutKind` StrEnum if `SearchItemKind` shouldn't grow a non-search kind).
- `ask/routes.py`: `AboutIn.kind` accepts `card`; `_set_about` checks the card is the owner's and live.
- `ask/context.py`: `about_text`, `boost`, `note_title` (None) handle a card.
- `name_chat`: fallback title for a card chat.
- Sync: the conversation row carries `about_card_id`.

App:
- Drizzle migration 0021: `conversations.about_card_id`; sync maps it.
- `app/src/app/card/[id].tsx` (new route) with the record view, pills, source row, buttons, ••• menu, and the
  embedded chat: reuse `useChatSession`, `AnswerView`, `UserBubble`, `EditProposalCard`, `Composer`, the waiting and
  failed handling; find the card's latest live chat with a small query hook (`useCardChat(cardId)`).
- `review/ui/CardListRow.tsx`: tap → `router.push(\`/card/${card.id}\`)`.
- The chat screen (`app/ask/[id].tsx`) shows "About: <card question>" for a card chat; its item sheet isn't offered
  for a card.
- Shared pieces that live inside `app/ask/[id].tsx` today (the thread of turns + pending overlay) move to a component
  both screens use, so the card page doesn't copy the chat screen.

## Testing

- API e2e: a chat about a card is created, refused for another user's or a dropped card; its about text names the card
  id; a `propose_card_edit` in it applies (replay an existing edit cassette pattern or record a new one, a few cents).
- Worker: `name_chat` fallback for a card chat.
- Jest: the meta pills (due label, reviewed count, last grade, edited); `useCardChat` picks the latest live chat.
- Maestro: extend `chat_cards.yaml` (no model): Review → search a seeded card → the card page shows question, answer
  and detail → Practice starts a one-card session → back → the composer is visible. (The chat itself spends money;
  covered by API e2e.)
- `make test`, `make lint`, `npm test`, `npm run typecheck`, `make maestro-chat-cards`.

## Build plan

**Chunk 1 — server: chats about a card** · Depends on: none
- Files: migration, `models.py`, `ask/routes.py`, `ask/context.py`, sync conversation rows, `name_chat` fallback,
  tests.
- Interfaces produced: ask body `about: {kind: "card", id}`; pulled conversation rows gain `about_card_id`.

**Chunk 2 — app: the card page** · Depends on: none (uses the interfaces above)
- Files: drizzle 0021 + schema + sync mapping, `app/card/[id].tsx`, the shared chat thread component, `useCardChat`,
  `CardListRow`, `app/ask/[id].tsx` about line, jest tests, `maestro/chat_cards.yaml`.
- Key decisions: copy "Card", "Practice", "Remove", "Ask to change this card…", "Reviewed N×", "Last: Got it",
  "Edited", "From <title> ›"; American spelling throughout.
