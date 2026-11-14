# Maestro flows

UI flows that drive the debug app on the iOS simulator against the local backend.

| Flow | What it proves |
| --- | --- |
| `add_link.yaml` | Dev login, add a link from the Library ＋, the worker's title appears in Library |
| `source_page.yaml` | Dev login as the owner's user, add a finished article with a reaction, open it from Library, wait for the primer, open it from the primer button, see "✓ Primed" |
| `add_podcast.yaml` | Dev login as the owner's user, add a Spotify episode, open it from Library, wait for the primer, see the gist, a timestamp chip and the primer button (real keys, a few cents) |
| `library_queue.yaml` | Library queue: reorder by drag, snooze from a swipe; Snoozed · 1 |
| `library_search.yaml` | Library search finds the item on the server and shows its matching quote, then the empty state for a query nothing matches (free) |
| `edit.yaml` | Finish an article, Ask about it from its ••• menu, ask to drop a key idea, Apply, Undo, and find three Summary versions (real keys, a few cents; `make maestro-edit`) |
| `ask.yaml` | Finish an article, ask about it on the Ask tab, see the Your library section, Make cards and wait for the proposed set, and find the chat in the list (real keys, a few cents; `make maestro-ask`) |
| `chat_cards.yaml` + `run_chat_cards.sh` | Seed a chat holding a three-card proposal through `/test/card-sets`, open the cheat sheet, untick card 2, See all, Save 2, Open the Chat item, See original, then Review search opens a saved card's page (question, answer, detail), Practice starts and closes back to it, and the card's chat box shows (no model; `make maestro-chat-cards`) |
| `review_browse.yaml` (after `chat_cards.yaml`, same runner) | Review tab: Items → the Chat item's card list → Practice all, miss both cards (self-graded), the caught-up card shows Review ahead, Missed lists both and Practice these 2 starts, Shuffle 10 starts, the browse mode is remembered and still chosen after a relaunch, and Back to Today shows the done row or day card (no model; `make maestro-chat-cards`) |
| `problems.yaml` + `run_problems.sh` | Seed a failed summary job through `/test/failed-job`, see Today's "problems-banner", tap it, and the sheet lists "Summaries failing" (no model; `make maestro-problems`) |
| `favorites.yaml` | Star an item from its page, find it under Library → Saved → Other, unstar it with a swipe; Saved shows its empty state |
| `collections.yaml` | Save a link from the Library ＋ into a new collection, see it on the collection page and not in All, delete the collection from its tile |
| `topics.yaml` | Topics: add, remove and restore a topic |
| `finish_item.yaml` | Finish an item with "Make review cards" unticked: it leaves the queue, lands in the finished state, and its menu no longer offers "No cards for this" |
| `topic_picker.yaml` | Signs in as `picker-user` (no topics chosen yet), the topic picker appears, pick topics and continue |
| `today_primer.yaml` | finish an article with "Parts lost me", its queued primer appears in Up next, open it, Mark as done (real keys, a few cents) |
| `takes.yaml` | Write a take from the Library ＋, open it from Takes, edit it into version 2, see Earlier versions and version 1, delete it |
| `takes_clean.yaml` | Write a take with Clean it up on (whitelisted, a few cents), see the cleaned take, See what you said, and its cards |
| `newsletter_*.yaml` + `run_newsletter.sh` | Log in, deliver a newsletter through `/ingest/email`, Add to queue then Undo (toast), Make review cards from the ••• menu |
| `brief.yaml` + `run_brief.sh` | Log in, deliver a news newsletter and an essay through `/ingest/email`, wait for the Today brief preview, open the brief, open a story's sources ("Covered by"), back, queue the essay, Done, the preview disappears (real keys, a few cents) |
| `review.yaml` | Finish an article, its cards reach Today, review a typed answer (graded by Haiku, accepted answer shown), Next, Drop the rest to the Done screen with the Dropped tally (real keys, a few cents) |
| `books.yaml` | Type a book's title in the Library ＋, Find book (live Open Library lookup), keep Reading, Add book; the book is under Library ▸ Reading, its page waits for the primer, and the primer is in Up next (spends a few cents: one book primer; `make maestro-books`) |
| `sign_out.yaml` | Dev login, Settings tab, Sign out, back on the Apple sign-in screen |
| `offline_*.yaml` + `run_offline.sh` | Add a link with the backend down ("1 change waiting"), restart it, the change syncs and the title arrives |
| `share_sheet.yaml` | Safari → Share → Archie opens the share sheet, and a screenshot of it matches `screenshots/share_sheet.png` (text drawn, Cancel on screen) |
| `login.yaml` | Shared preamble (fresh install + dev login, lands on Library); other flows `runFlow` it, it is not run on its own |

## One-time setup

- Java 17+: `brew install openjdk@17`
- Maestro: `curl -fsSL "https://get.maestro.mobile.dev" | bash`
- The Makefile and `run_offline.sh` put both on `PATH` themselves (`/opt/homebrew/opt/openjdk@17/bin` and `~/.maestro/bin`). To run `maestro` by hand, export that `PATH` in your shell; nothing edits your shell rc files.

## Running

1. Boot an iOS simulator (e.g. iPhone 17 Pro) and install the debug build: `cd app && npx expo run:ios`. Leave Metro running.
2. `make maestro` with the backend up in another terminal (`make start-local`). Runs `add_link`, `sign_out`, `source_page`, `library_queue`, `library_search`, `favorites`, `collections`, `takes`, `topics`, `finish_item`, `topic_picker` and `today_primer`.
   `source_page` and `today_primer` call Anthropic for real, so a run spends a few cents.
   `make maestro-podcast` runs `add_podcast` separately because it spends real API credits.
3. `make maestro-newsletter` with the backend up (`make start-local`): runs `run_newsletter.sh`, which needs `INGEST_SECRET` and the owner's keys in `.env` and spends a few cents.
4. `make maestro-confirm` with the backend up (`make start-local`): runs `run_confirm_email.sh`, which needs `INGEST_SECRET` in `.env`; it delivers TLDR's signup confirmation email, taps Confirm on its Library card, closes the browser sheet with Done and checks the card is gone and the toast showed. Spends nothing.
5. `make maestro-notes` with the backend and worker up (`make start-local`): runs `run_notes.sh`, which imports two invented Bear notes (`fixtures/notes.json`), seeds their write-ups and a chat about the first note with a card set, all without a model, then `notes.yaml` opens the Today refresher, the note page and the original-note sheet, then saves the set from the chat and opens the note. Spends nothing on models.
6. `make maestro-allowlist` with the backend up (`make start-local`): runs `run_sender_allowlist.sh`, which needs `INGEST_SECRET` in `.env`; it delivers Morning Brew's newsletter as an unknown sender, blocks it from its Library card, checks the toast and Settings → Blocked senders, then re-delivers it under a new Message-ID and checks no card comes back. Spends nothing.
7. `make maestro-brief` with the backend up (`make start-local`): runs `run_brief.sh`, which delivers two newsletters and waits up to 5 minutes for the brief (the worker cleans, analyzes and files them, then writes the brief with Sonnet). Same `.env` needs as above; spends a few cents (Haiku + Sonnet).
8. `make maestro-review` with the backend up (`make start-local`): runs `review.yaml`, which waits up to 4 minutes for the finished article's cards to reach Today. Needs the owner's keys in `.env`; spends a few cents (analyze, primer, one Haiku grade).
9. `make maestro-takes-clean` with the backend up (`make start-local`): runs `takes_clean.yaml`, which waits up to 2.5 minutes each for the Sonnet cleanup and the Haiku cards. Needs the owner's keys in `.env`; spends a few cents.
10. `make maestro-ask` with the backend up (`make start-local`): runs `ask.yaml`, which waits for analyze and embeddings, then a Sonnet 5.5 answer, then taps Make cards and waits for the proposed card set. Needs the owner's keys in `.env` (`OPENAI_API_KEY` too, for embeddings); spends a few cents.
11. `make maestro-edit` with the backend up (`make start-local`): runs `edit.yaml`, which waits for analyze and the primer, then a Sonnet 5.5 answer that proposes an edit; it taps Apply and Undo and opens Summary versions. Same `.env` needs as `maestro-ask`; spends a few cents.
12. `make maestro-chat-cards` with the backend up (`make start-local`): runs `run_chat_cards.sh`, which seeds a chat holding a card-set proposal (`fixtures/chat_cards.json`) through `POST /test/card-sets` without a model, then `chat_cards.yaml` opens the chat, previews the cheat sheet, unticks a card, switches to See all, saves, opens the new Chat item and its original, and `review_browse.yaml` browses and practices those cards on the Review tab. Spends nothing on models (the save queues one embedding).
13. `make maestro-books` with the backend up (`make start-local`): runs `books.yaml`, which looks a title up on Open Library for real and waits up to 4 minutes for the book primer. Needs the owner's keys in `.env`; spends a few cents (one book primer).
14. `make maestro-problems` with the backend up (`make start-local`): runs `run_problems.sh`, which seeds a failed summary job through `POST /test/failed-job`, then `problems.yaml` relaunches, waits for Today's problems banner, opens its sheet and sees "Summaries failing". Spends nothing.
15. `make maestro-offline` with the backend **stopped**: the script starts and stops `make start-local` itself.

These targets first empty the local dev database's synced data (`make reset-local-data`), and each flow starts with a clean app install (state and keychain cleared).

## Notes

- `share_sheet.yaml` needs a **Release** build on the simulator (the debug extension loads its bundle from Metro):
  `cd app && EXPO_PUBLIC_API_URL=https://archie-production-4856.up.railway.app npx expo run:ios --configuration Release`.
  Run it from the repo root (`maestro test maestro/share_sheet.yaml`): Maestro only finds the reference screenshot
  relative to a flow path that has a directory. It checks pixels, not just the accessibility tree, because text that
  measures zero high still shows up in the tree. When the sheet's look changes on purpose, retake the reference with
  a `takeScreenshot` cropped on `id: share-sheet` and replace the PNG. It taps Archie's share cell by position, so a
  different simulator model or share-sheet layout needs the point updated.

- `source_page.yaml` calls Anthropic for real (a few cents per run): it signs in with `archie://dev/login?whitelisted=1`, so the worker uses the owner's `ANTHROPIC_API_KEY` from `.env`, and it waits up to 3 minutes for the primer. The local backend has no replay mode yet, so it only works when the owner runs it with real keys. It uses a single `extendedWaitUntil` because Maestro shares one timeout budget across consecutive waits.

- `add_podcast.yaml` also costs a few cents (Groq transcription plus Anthropic) and needs `GROQ_API_KEY` in `.env` for the worker; it waits up to 5 minutes. Same single-`extendedWaitUntil` rule as above.
- `archie://dev/login` needs `ARCHIE_ENV=dev`, which `make start-local` sets. iOS asks "Open in Archie?" for the link; the flows tap Open.
- Flows need a network connection: the worker fetches `paulgraham.com` and `example.com` for real.
- The offline flow adds `https://example.com/` (not a made-up path): example.com now returns 404 for other paths, so the worker could not read a title.
