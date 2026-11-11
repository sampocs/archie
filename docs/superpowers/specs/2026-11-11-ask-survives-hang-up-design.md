# Ask answers survive a hang-up, and card sets stay in view

## Why

A "Make cards" answer in a chat about a source failed: the owner backgrounded the app while it was drafting, iOS
dropped the connection, and the server stopped and saved the answer as failed. Three things then went wrong:

1. **The server stops when the phone hangs up.** `answer.stream` catches `GeneratorExit`, saves what arrived as
   failed and stops the model. The app's own comment says "leaving the chat lets the stream run on", but backgrounding
   the app kills the connection, so in practice the answer dies.
2. **A failed answer vanishes from the model's history.** `context.history_messages` drops a failed answer with its
   question. The failed answer had already proposed a card set, so the next question ("add a card on…") was answered
   as if no set existed, and its new set replaced the first one.
3. **A replaced set is only named.** `context.card_set_note` gives a replaced set's title but not its cards, so "bring
   back the first set" can't be done. The model rebuilt paraphrases instead.

## Behavior

### Server: an answer finishes even if the phone hangs up

- When the phone hangs up mid-answer, the server keeps running the tool loop to the end and sends nothing more. It
  then saves the answer as it ended: complete if the model finished its turn, failed otherwise (refusal, cut-off, out
  of rounds, API or database error), with the same rules as a connected answer.
- The save gives the question, the answer and the chat new positions as now, so the next pull brings the answer.
- The work stays on the worker thread that closes the stream (`stream_async` already closes `stream` with
  `anyio.to_thread.run_sync`), so the event loop is never blocked. `MAX_ROUNDS` × `REQUEST_TIMEOUT_SECONDS` bounds it.
- A deploy or crash mid-answer still loses it. The question then stands alone, which the app handles (below).
- Errors after a hang-up log the existing "Answer failed for conversation …" warning. A hang-up itself logs one info
  line ("Phone hung up; finishing answer for conversation …").

### Server: the model sees what was proposed

- `history_messages` keeps a failed answer, with its question, when it proposed something (an edit or a card set).
  The answer turn is its stored text, or "(This answer was cut off.)" when empty, followed by its notes as now. A
  failed answer that proposed nothing is still dropped with its question.
- `card_set_note` lists the cards of a replaced set too (numbered, with detail lines, as for the other statuses). Its
  cheat sheet stays left out. So the model can bring back cards from an earlier set word for word.
- `CARD_SET_RULES` gains two rules:
  - "More cards" or "add a card on X" adds to the open proposal: re-propose it whole, with the new cards after the
    old ones. It is not a fresh set. Up to 10 cards in all (`MAX_CARDS`).
  - To bring back cards from an earlier (replaced) proposal, copy them word for word from its listing.

### App: a dropped connection isn't a failed answer

- A stream that opened (the server answered 200, so it holds the question) and then closed or broke without `done`
  or `error` marks the live answer **waiting**, not failed. A request that never opened (offline, 401, 4xx, 5xx)
  fails at once, as now. Waiting shows the
  thinking row as "Still answering…". Sending stays disabled, as while streaming.
- While a live answer is waiting, the chat asks for a sync every 5 seconds. The pulled answer takes over the overlay
  as it does today (`handedOver` treats waiting like failed: any assistant row after the question).
- A waiting answer turns failed ("Didn't finish. Try again") once 3 minutes have passed since the question was sent
  with nothing pulled.
- **A question with no answer and no overlay** (the app was relaunched, or the chat was left and reopened): if the
  chat's last row is the owner's question and it is under 3 minutes old, the chat shows the "Still answering…" row
  under it and polls the same way. Older than that, it shows the failed answer view ("Didn't finish. Try again") under
  the question, whose retry sends the question again.
- An `error` event still means failed at once, as now.

## Design

Server (`services/api/archie_api/ask/`):
- `answer.stream`: catch `GeneratorExit` at the `yield`, then drain `_run` without yielding (still inside the same
  error handling) and save with `failed` set by how the loop ended. Never yield after `GeneratorExit` (Python raises
  `RuntimeError`). The module docstring's hang-up sentence changes to match.
- `context.HistoryMessage` gains `proposed: bool` (set when the message has edit or card-set notes). `history_messages`
  keeps a failed answer when `proposed`.
- `context.card_set_note`: drop the replaced early-return for the cards (keep the cheat sheet out for replaced).
- `prompts.CARD_SET_RULES`: the two rules above. The prompt's first 60 characters (cassette key) stay unchanged.

App (`app/src/ask/`):
- `stream.ts`: a body read that breaks after a 200 throws a new `StreamCutError` (distinct from the `NetworkError` of a
  request that never opened).
- `sections.ts`: `LiveAnswer` gains `waiting: boolean`. `endOfStream` and the stream's network-error path set waiting
  instead of failed. `thinkingLabel` returns "Still answering…" while waiting. `handedOver` treats waiting like failed.
  A pure `unansweredState(messages, now)` returns `"waiting" | "failed" | null` for a trailing question with no
  answer, using a 3-minute `ANSWER_WAIT_MS`.
- `useChatSession.ts`: while the overlay is waiting, `requestSync()` every 5 s; flip to failed after `ANSWER_WAIT_MS`
  from `sentAt`.
- `app/ask/[id].tsx`: render the trailing-question state (thinking row or failed `AnswerView` with retry), polling
  while waiting.

## Testing

- `tests/e2e/test_ask_e2e.py`: the two hang-up tests change to expect the answer stored **complete** with its full
  text from the cassette, the question moved and the round(s) recorded. A third test: a hang-up where the model then
  fails (the broken-search monkeypatch) stores it failed.
- Unit tests (`tests/test_ask_units.py` or the existing context tests): `history_messages` keeps a failed answer that
  proposed something and drops one that didn't; `card_set_note` lists a replaced set's cards.
- Jest: `sections.test.ts` covers waiting (end of stream, label, hand-over) and `unansweredState` (recent → waiting,
  old → failed, answered → null).
- `make test-db`, `make lint`, `npm test`, `npm run typecheck`, then `make maestro-ask` as a regression smoke test.

## Data repair (done)

The affected chat's open proposal was rewritten in prod to the 10 cards the owner asked for (the first set's 7 plus
the 3 kept, "easy shorting" already on the benefits card), and its answer text updated to match.

## Build plan

Two chunks, independent.

**Chunk 1 — server** · Depends on: none
- Files: `ask/answer.py`, `ask/context.py`, `ask/prompts.py`, `tests/e2e/test_ask_e2e.py`, context unit tests.
- Interfaces: none new for the app; the wire is unchanged.
- Key decisions: drain on the closing thread; never yield after `GeneratorExit`; `proposed` flag on `HistoryMessage`.
- Tests: as above.

**Chunk 2 — app** · Depends on: none
- Files: `app/src/ask/stream.ts`, `app/src/ask/sections.ts` (+ test), `app/src/ask/useChatSession.ts`, `app/src/app/ask/[id].tsx`.
- Key decisions: copy exactly "Still answering…", 3-minute `ANSWER_WAIT_MS`, 5-second poll; HTTP error responses and
  `error` events stay failed at once.
- Tests: as above.
