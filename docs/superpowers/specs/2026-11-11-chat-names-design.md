# Chat names, rename and the Ask list's long-press menu

## Why

A chat is named after its first message, cut to 60 characters. Chats started from a note's Make cards button are all
called "Make cards", so the Ask list can't tell them apart. There's also no way to rename a chat, and deleting one
from the list is swipe-only.

## Behavior

### Automatic names

- **When:** once, after a chat's first answer is saved **complete**. Naming never runs again for that chat, and it
  never runs for a failed first answer (the next complete answer, if it's the chat's first complete one, names it).
- **How:** a worker job (`name_chat`) asks Haiku for a short name from the first question, the first answer's text,
  the titles of any card set it proposed, and the about item's title (if any). The name is 2 to 6 words, at most 60
  characters (`CONVERSATION_TITLE_LENGTH`), sentence case, no quotes or trailing period. It names the
  subject, not the action: "Perps vs options", "Convex vault mechanics", never "Make cards" or "Chat about…".
- **Fallback** when the job fails for good (the worker's usual retries, a refusal, or an empty or over-long reply):
  - a chat about an item: the item's title, plus " · cards" when the first answer proposed a card set
    ("Derivatives · cards");
  - a general chat: its title stays the first question.
- **The owner's name wins.** The job (and the fallback) writes the name only if the chat's title is still the one it
  was created with. A chat the owner renamed first keeps the owner's name.
- The new title gets a new position (`touch_conversation`), so phones pull it. The list shows the first question as
  the title for the few seconds until then.
- **Existing chats:** a one-off script names every live chat that has a complete answer, by the same job, skipping
  none (no chat has an owner-given name yet).

### Rename and delete

- **Ask list:** long-press a chat row → a menu sheet with **Rename** and **Delete** (the same `MenuSheet` the
  collection tiles use). Swipe-to-delete stays.
- **Rename** opens the system text prompt (as `promptCollectionName` does): title "Rename chat", the current title
  filled in, buttons Cancel / Rename. A blank answer does nothing. The name is trimmed and cut to 60 characters.
- **Delete** from the long-press menu asks first, with the same confirm the chat's ••• menu uses (`confirmDeleteChat`).
- **Inside a chat:** the ••• menu gets **Rename** above Delete chat; it opens the same prompt.
- A rename shows at once (local write) and syncs as a new push action `rename_conversation {id, title}`. The server
  trims, refuses a blank title (malformed), cuts to 60, stores it and gives the chat a new change position (its `updated_at`, the last activity, is unchanged). Renaming another user's or a
  deleted chat is refused like `delete_conversation`.

## Design

Server:
- `sync/schemas.py` `ActionType.RENAME_CONVERSATION`; `sync/conversation_actions.rename_conversation` registered in
  `sync/actions.py` next to `delete_conversation`.
- `models.JobKind.NAME_CHAT = "name_chat"`; the job's payload names the conversation and the title it expects to
  replace (the creation title). `ask/answer._save` enqueues it when it saves the chat's first complete answer.
- Worker handler `handlers/name_chat.py` (follow the existing handlers' shape, `llm` recording with a new step name):
  the Haiku call, the guarded write, and the fallback on final failure. The prompt lives with the worker's prompts.
- `scripts/` or a worker module for the one-off backfill that enqueues `name_chat` for existing chats (run once in
  prod via `railway ssh`, as other one-offs are).

App:
- `db/actions.ts` `renameConversation(db, id, title)`: local update + enqueue `rename_conversation`;
  `sync/transport.ts` `CONVERSATION_ACTIONS` gains it.
- `app/(tabs)/ask.tsx`: `onLongPress` on the chat row (ChatRow / SwipeRow need a long-press prop) opens a
  `MenuSheet` with Rename / Delete.
- `app/ask/[id].tsx`: Rename in the ••• `MenuSheet`.
- A shared `promptChatName` next to `confirmDeleteChat`.

## Testing

- API e2e: `rename_conversation` renames, trims, cuts to 60, refuses blank / another user's / deleted; the first
  complete answer enqueues one `name_chat` job and later answers don't; a failed first answer doesn't.
- Worker: the handler with a recorded Haiku cassette writes the name; it leaves an owner-renamed chat alone; the
  fallback writes "Item · cards" / leaves a general chat's question; a reply that is empty or too long falls back.
- Jest: `renameConversation` local write + queued action.
- Maestro: extend `chat_cards.yaml` (no model): long-press the chat in the Ask list → Rename → type a name → the row
  shows it; open the chat → ••• → Rename.
- `make test`, `make lint`, `npm test`, `npm run typecheck`, `make maestro-chat-cards`.

## Build plan

**Chunk 1 — server: rename action, naming job, backfill** · Depends on: none
- Files: `sync/schemas.py`, `sync/actions.py`, `sync/conversation_actions.py`, `archie_db/models.py` (JobKind),
  `ask/answer.py` (enqueue), worker handler + prompt + registration, backfill script, tests.
- Interfaces produced: push action `rename_conversation {id: uuid, title: string}`.
- Key decisions: the guarded write (title unchanged since creation); fallback only on final failure.

**Chunk 2 — app: rename and long-press menu** · Depends on: none (uses the action name above)
- Files: `db/actions.ts` (+ test), `sync/transport.ts`, `app/(tabs)/ask.tsx`, `ask/ChatRow.tsx` / `ui/SwipeRow`,
  `app/ask/[id].tsx`, the prompt helper, `maestro/chat_cards.yaml`.
- Key decisions: copy "Rename chat", "Rename", "Delete"; 60-character cut; blank does nothing.
