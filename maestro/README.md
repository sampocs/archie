# Maestro flows

UI flows that drive the debug app on the iOS simulator against the local backend.

| Flow | What it proves |
| --- | --- |
| `add_link.yaml` | Dev login, add a link, the worker's title appears in Library |
| `source_page.yaml` | Dev login as the owner's user, add a finished article with a reaction, open it from Library, wait for the primer, open it from the primer button, see "✓ Primed" |
| `add_podcast.yaml` | Dev login as the owner's user, add a Spotify episode, open it from Library, wait for the primer, see the gist, a timestamp chip and the primer button (real keys, a few cents) |
| `library_queue.yaml` | Library queue: reorder by drag, snooze from a swipe; Snoozed · 1 |
| `library_search.yaml` | Library search finds items by title and filters the list |
| `topics.yaml` | Topics: add, remove and restore a topic |
| `finish_item.yaml` | Finish an item: it leaves the queue and lands in the finished state |
| `topic_picker.yaml` | Signs in as `picker-user` (no topics chosen yet), the topic picker appears, pick topics and continue |
| `today_primer.yaml` | finish an article with "Parts lost me", its queued primer appears in Up next, open it, Mark as done (real keys, a few cents) |
| `newsletter_*.yaml` + `run_newsletter.sh` | Log in, deliver a newsletter through `/ingest/email`, Add to queue then Undo (toast), Make review cards from the ••• menu |
| `brief.yaml` + `run_brief.sh` | Log in, deliver a news newsletter and an essay through `/ingest/email`, wait for the Today brief preview, open the brief, open a story's sources ("Covered by"), back, queue the essay, Done, the preview disappears (real keys, a few cents) |
| `review.yaml` | Finish an article, its cards reach Today, review a typed answer (graded by Haiku, accepted answer shown), Next, Drop the rest to the Done screen with the Dropped tally (real keys, a few cents) |
| `sign_out.yaml` | Dev login, Today tab, account button, Sign out, back on the Apple sign-in screen |
| `offline_*.yaml` + `run_offline.sh` | Add a link with the backend down ("1 change waiting"), restart it, the change syncs and the title arrives |
| `share_sheet.yaml` | Safari → Share → Archie opens the share sheet, and a screenshot of it matches `screenshots/share_sheet.png` (text drawn, Cancel on screen) |
| `login.yaml` | Shared preamble (fresh install + dev login, lands on Library); other flows `runFlow` it, it is not run on its own |

## One-time setup

- Java 17+: `brew install openjdk@17`
- Maestro: `curl -fsSL "https://get.maestro.mobile.dev" | bash`
- The Makefile and `run_offline.sh` put both on `PATH` themselves (`/opt/homebrew/opt/openjdk@17/bin` and `~/.maestro/bin`). To run `maestro` by hand, export that `PATH` in your shell; nothing edits your shell rc files.

## Running

1. Boot an iOS simulator (e.g. iPhone 17 Pro) and install the debug build: `cd app && npx expo run:ios`. Leave Metro running.
2. `make maestro` with the backend up in another terminal (`make start-local`). Runs `add_link`, `sign_out`, `source_page`, `library_queue`, `library_search`, `topics`, `finish_item`, `topic_picker` and `today_primer`.
   `source_page` and `today_primer` call Anthropic for real, so a run spends a few cents.
   `make maestro-podcast` runs `add_podcast` separately because it spends real API credits.
3. `make maestro-newsletter` with the backend up (`make start-local`): runs `run_newsletter.sh`, which needs `INGEST_SECRET` and the owner's keys in `.env` and spends a few cents.
4. `make maestro-brief` with the backend up (`make start-local`): runs `run_brief.sh`, which delivers two newsletters and waits up to 5 minutes for the brief (the worker cleans, analyzes and files them, then writes the brief with Sonnet). Same `.env` needs as above; spends a few cents (Haiku + Sonnet).
5. `make maestro-review` with the backend up (`make start-local`): runs `review.yaml`, which waits up to 4 minutes for the finished article's cards to reach Today. Needs the owner's keys in `.env`; spends a few cents (analyze, primer, one Haiku grade).
6. `make maestro-offline` with the backend **stopped**: the script starts and stops `make start-local` itself.

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
