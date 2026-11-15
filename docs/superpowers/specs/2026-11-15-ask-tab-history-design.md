# Ask tab: a question box, with History on its own page

## Why

The Ask tab puts the box for a new chat under the list of past chats. That reads as if the box belongs to the chats
above it. The user picked option 2 from the mocks (ChatGPT/Claude style, without suggestions): the Ask tab only starts
chats, and past chats move to a History page.

## Ask tab (`app/src/app/(tabs)/ask.tsx`)

- It always opens on a blank box. It never reopens the last chat. Sending pushes `ask/[id]` as it does today and
  clears the box, so going back returns to a blank box.
- Layout, top to bottom:
  - **History button** at the top left. It's a pill with a `time-outline` icon and "History" (testID `ask-history`)
    and pushes `/ask/history`.
  - **Heading** "What do you want to understand?" in the display face, left-aligned, set roughly a third of the way
    down.
  - **Question box**:
    - a large rounded field, about 4 lines tall, with the placeholder "Ask about anything";
    - the web globe and send sit inside it at the bottom right;
    - no suggestions and no recent chats.
- **Offline:** the box shows the existing "Ask needs a connection" line in place of the field.
- **Unavailable account:** this state is unchanged.
- **Keyboard:** tapping outside the box closes it.
- The tab bar stays as it is.
- **Component:** `Composer` gains `variant?: "bar" | "hero"`. The default `"bar"` keeps chats as they are. `"hero"` is
  the large box. Both keep the testIDs `ask-composer-input`, `ask-web-toggle` and `ask-send`.

## History page (`app/src/app/ask/history.tsx`, new route)

- `Screen` with `nav={{ title: "History", backLabel: "Ask" }}`. Register `ask/history` in the root Stack's signed-in
  block. A static route wins over `ask/[id]`.
- **Search field** at the top (testID `history-search`, placeholder "Search chats"). It filters locally on the title
  and the preview text, ignoring case.
- **Groups:**
  - **TODAY:** the same calendar day as now.
  - **THIS WEEK:** the 6 days before today.
  - **EARLIER:** everything older.
  - Group headers are small caps-style labels. A group with no chats is left out.
  - Order within a group is newest activity first, as `useChats` already returns.
- **Rows:**
  - full width, with no card around them and a hairline between rows;
  - the title (one line) with the relative time on the right, and the preview below it (two lines);
  - the existing `ChatRow`, with its preview raised to two lines and the testID `ask-row-<id>` kept;
  - long-press Rename/Delete and swipe-to-delete behave as they do today, moved over from the Ask tab.
- **Empty states:**
  - no chats: "No chats yet." (testID `history-empty`);
  - search with no match: "No chats match." (testID `history-no-match`).

## Logic

`historyGroups(items, now)` in `app/src/ask/sections.ts` returns `{ key: "today" | "week" | "earlier"; label; items }[]`
with empty groups left out. It has unit tests at the day boundaries (midnight, 6 versus 7 days back).
`matchesChatQuery(item, query)` is the search predicate and is tested too.

## Testing

Maestro flows that open a chat from the Ask list now tap `ask-history` first:
- `ask.yaml`, after going back from the chat;
- `chat_cards.yaml`;
- `notes.yaml`.

`chat_cards.yaml` also covers search: type part of the title, the row stays, type nonsense, "No chats match." shows.

## Build plan

One chunk.

**Chunk 1: Ask tab, History page, flows.** Depends on: none.
- **Files:**
  - `(tabs)/ask.tsx`: rewritten to the hero layout;
  - `ask/history.tsx`: new, with the list, search, menus and swipe moved from the tab;
  - `_layout.tsx`: the route;
  - `Composer.tsx`: the hero variant;
  - `ChatRow.tsx`: two-line preview, full-width styling;
  - `sections.ts` and its test: `historyGroups` and `matchesChatQuery`;
  - the three Maestro flows.
- **Interfaces:** `historyGroups` and `matchesChatQuery` are consumed only by the History page. `Composer`'s
  `variant` defaults to `"bar"`, so `ask/[id]` and `card/[id]` are untouched.
- **Key decisions:**
  - follow the picked mock in the scratchpad `ask-mocks.html` (option 2);
  - use theme tokens only, no new colors;
  - the hero box's field grows with its text up to a max height and then scrolls.
- **Tests:** the sections unit tests; `npm test` and `npm run typecheck`; the Maestro chat_cards and notes flows on
  the simulator.
