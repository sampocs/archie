# M8: Notes import (Bear)

**Status:** designed 2026-11-08 from the owner's approved design and mocks (`2026-11-08-notes-import-mocks.html`).
Product background is `2026-10-26-product-scope.md` ("Notes import: years of existing notes become library items and go
through the same processing") and the M8 row of `2026-11-02-backend-architecture-design.md`. Where they differ, this
spec wins. Google Docs import is out of scope (later).

## Problem

The owner has years of Bear notes and has triaged them: each is marked `skip`, `import` or `cards` in a marks file on
their Mac. The marked ones should become library items (searchable and in Ask), each with a fresh write-up by Archie,
and the `cards` ones should come back to the owner a couple a day so that refreshing a note, not importing it, is what
adds its review cards.

## Decisions

- **A new source kind, `note`**, shown as **Notes** (kicker `Notes · {Domain}`, monogram tile `✎`). A note keeps its
  original markdown, its Bear id (re-imports dedupe on it), its Bear tags and its created and last-edited dates.
  - Its `url` is `bear:{bear id}` (like a newsletter's `newsletter:` placeholder); `normalized_url` the same.
  - `created_at` is the note's Bear creation date, so Library sorts and sections old notes by when they were written.
  - Mark `import` → `cards_off = true`, state `consumed` (a Done item): searchable and in Ask, never any cards.
  - Mark `cards` → `cards_off = false`, state `inbox`: it waits in the **refresher queue** (below). It is never in the
    regular queue (state is never `queued`), never briefed (briefs only read newsletters) and never in Library's
    Inbox filter (the filter skips notes).
  - The existing "Make review cards" / "No cards for this" menu entries keep working: they flip `cards_off`, which
    moves an unrefreshed note into or out of the refresher queue.
- **Import is a script on the Mac plus an authenticated endpoint.** `scripts/import_bear.py` reads Bear's database
  read-only and the marks file, and uploads only the notes marked `import` or `cards` to `POST /notes/import` with the
  owner's session key. Nothing else from Bear leaves the Mac. Re-running it is safe (idempotent on Bear id).
- **Getting a session key for the script:** a new CLI, `archie-issue-session --email <email>`, run in the deployed
  container (`railway ssh`), creates an ordinary session for that user and prints its key once. The script reads it
  from `ARCHIE_SESSION_KEY`. It is a normal, revocable session row; nothing new is stored.
- **The write-up is the note's summary artifact**, in the existing summary shape (`gist`, `key_ideas`, `numbers`,
  plus `domain`, `topic`, `tags`, `concepts`, `is_educational`, `cards: []`) and one new key, `sources` (the links
  the note cites). Reusing the shape means the source page's summary rendering, chat edits and versions, filing,
  embeddings and Ask all work for notes unchanged. The mocks' write-up (a gist, then Key ideas) is exactly this shape.
- **Cost gate: nothing is generated on import.** Import stores the note's text and queues only `embed` (search
  passages of the original text, a fraction of a cent for all notes). Write-ups are queued only by an explicit
  `POST /notes/write-ups`, which the owner triggers with `scripts/import_bear.py --write` once the reading voice is
  picked. Every model call records `llm_calls` through `llm.complete`, as every step does.
- **The reading voice stays one constant.** The write-up prompt ends with the shared `prompts.READING_VOICE`, like
  every other step, so choosing the voice later is a one-place change (then re-run write-ups if wanted).
- **Cards are written at Done.** Tapping **Done, add review cards** pushes a `refresh_note` action (works offline);
  the server marks the note refreshed and Done and queues a `note_cards` job (Haiku) that writes the cards from the
  write-up and the note. The toast "N review cards added from {title}" shows when those cards reach the phone.
- **The refresher's picks are computed on the phone**, from synced rows, like the rest of Today: 2 notes a day,
  ordered by topic runs starting from the most recently edited, with Skip. Reorder is a follow-up.
- **Sharing a Bear note to Archie is a follow-up** (see Not in scope).

## Data (server migration 0015, phone drizzle 0015)

> Numbered after `0014_confirm_url`. If `sender-allowlist` merges first with its own 0015, this becomes 0016 (server
> revision `"0016"`, down `"0015"`; phone `0016`) on rebase.

New nullable columns on `sources` (none on other tables):

| Column | Type | Synced | Meaning |
|---|---|---|---|
| `bear_id` | `varchar(64)` | no | Bear's `ZUNIQUEIDENTIFIER`. Unique index `uq_sources_user_id_bear_id (user_id, bear_id)` (nulls never collide). |
| `note_markdown` | `text` | yes | The note's original markdown, as imported (rendered by "See original note"). |
| `note_tags` | `text[]` | no | Bear's tags for the note (write-up and filing hints). |
| `note_edited_at` | `timestamptz` | yes | Bear's last-modified date ("last edited", refresher order). |
| `refreshed_at` | `timestamptz` | yes | When the owner tapped Done on the note. |
| `refreshed_from_queue` | `boolean not null default false` | yes | Done counted toward that day's two (it was the refresher's current pick). |
| `refresh_skipped_at` | `timestamptz` | yes | Set by Skip; skipped notes go to the end of the refresher queue. |

Phone migration: `ALTER TABLE sources ADD` the five synced columns (`note_markdown text`, `note_edited_at text`,
`refreshed_at text`, `refreshed_from_queue integer NOT NULL DEFAULT 0`, `refresh_skipped_at text`), then
`UPDATE sync_state SET position = 0;` (a full re-pull, so a note imported before the phone update gets its markdown).
Generated as 0012–0014 were (`npx drizzle-kit generate` with a custom name, then append the re-pull).

New enum values: `SourceKind.NOTE = "note"`, `JobKind.WRITE_NOTE = "write_note"`, `JobKind.NOTE_CARDS =
"note_cards"`, `NoteMark` (`import`, `cards`) as a `StrEnum` in the API's notes module. `pipeline.required_artifacts`
for a note is `(SUMMARY,)`; `pipeline.steps_after_text(NOTE)` is `[WRITE_NOTE]`, with `_STEP_OUTPUTS[WRITE_NOTE] =
SUMMARY`, so Retry on a failed note re-runs its write-up (an explicit tap, like any retry).

## Import (`POST /notes/import`, API `archie_api/notes/routes.py`)

- **Auth:** `deps.current_user` (Bearer session key); 401 otherwise. Any signed-in user may import (import spends
  nothing beyond embeddings, which only whitelisted users get).
- **Request:** `{"notes": [NoteIn, …]}`, at most 50 per request (the script batches). `NoteIn`: `bear_id`
  (1–64 chars), `title` (1–500), `markdown` (≤ 200,000 chars), `tags` (≤ 50 strings of ≤ 200), `created_at` and
  `edited_at` (aware datetimes), `mark` (`import` | `cards`). A repeated `bear_id` within one request is a 422.
- **Response:** `{"results": [{"bear_id", "id", "status"}]}` in request order; `status` is `created`, `updated`,
  `unchanged` or `deleted`.
- Under `changes.lock_user_writes`, in one transaction, for each note matched by `(user_id, bear_id)`:
  - **New:** insert the source (fields as in Decisions, `intent = finished`, `processing = ready`), a current `text`
    artifact `{"text": markdown}` (`pipeline.write_artifact`, model and prompt version null), and
    `jobs.enqueue_embed`. No other job.
  - **Existing and live:** if any of title, markdown, tags, edited date or mark differs, update them and answer
    `updated`; a changed markdown writes a new `text` version and queues `embed`. The mark is applied only while the
    note is unrefreshed (`refreshed_at` null): `cards` ↔ `import` sets `cards_off` and state (`inbox` / `consumed`).
    Otherwise `unchanged`, with no writes.
  - **Existing and deleted** (the owner deleted it in Archie): untouched, `deleted`. A deletion is the owner's choice.
  - Every written source row gets `changes.next_change_seq()`.

## Write-ups

- **`POST /notes/write-ups`** (same router, `deps.current_user`): 403 `deps.NEEDS_OWN_KEY` for a user who is not
  whitelisted. Queues one `write_note` job per live note whose current `text` artifact is newer than its current
  summary (or has no summary), skipping notes with a `write_note` job queued or running. Jobs are queued most
  recently edited first, the n-th with `delay = n × 60 s` (`WRITE_UP_SPACING`), so a burst of ~90 Sonnet calls never
  starves the queue: a share made meanwhile waits for at most one write-up. Answers `{"queued": n}`.
- **`write_note` handler** (`services/worker/archie_worker/handlers/write_note.py`), following the loop's handler
  contract (read and commit, outside calls with no transaction, then lock and write):
  1. Read the source (live, kind note), its current text, title, tags, edited date; mark it `processing` and
     commit. Raise `PermanentJobError` (via `keys.anthropic_key_for`) for a user without a key.
  2. **Links** (`archie_worker/note_links.py`, pure, unit-tested): markdown links `[text](url)` and bare `http(s)`
     URLs from the note, in order of first appearance, de-duplicated by `urls.normalize_url`, at most 8. Each is an
     **episode** (Spotify, Apple Podcasts, YouTube, any URL `urls` recognises as a podcast or video) or a **page**.
  3. **Fetch reference material** for each link, best effort (any error or a 4xx/5xx skips that link's material but
     keeps the link): a page uses `fetch_title.fetch_page` + `article.extract` (the article fetch path), text cut to
     20,000 characters and 60,000 in total; an episode uses only its page's title and description
     (`og:title` / `og:description`, else `<title>` / `<meta name="description">`; a new
     `fetch_title.extract_description`), never a transcript. The link's title is the fetched title, else the markdown
     link text, else the host.
  4. **One Sonnet call** (`llm.NOTE_WRITE_UP_MODELS = ModelPair(SONNET, OPUS)`, step `write_note`, JSON schema
     `prompts.NOTE_WRITE_UP_SCHEMA` = the analysis schema without `cards`), system `prompts.NOTE_WRITE_UP_SYSTEM`,
     message `prompts.note_write_up_message(...)`: today's date, title, tags, last-edited date, the note in `<note>`
     tags, then each fetched link in `<reference url=… title=… kind=page|episode>` tags.
  5. Lock, re-check the source is live, and write the summary artifact: the model's output plus `cards: []` and
     `sources: [{"url", "title"}]` (every link, fetched or not), `prompt_version = "note-write-up-v1"`. Then
     `jobs.enqueue_embed`, `user_topics.enqueue_file_topic` when the note has no domain yet and the user chose topics
     (as analyze does), and `pipeline.finish_step` (→ READY). Failure hook: `mark_source_failed` (Retry appears).
- **The prompt contract** (`NOTE_WRITE_UP_SYSTEM`): write a fresh explanation of the subject, as of today, with the
  note setting the direction: cover what the note covers, keep its emphasis, fill the gaps, spell out its shorthand,
  correct anything wrong and state current facts. **Never mention, quote or compare against the note or its author**
  (no "your note", "the note says", "as of 2024 … now"); write as if explaining the subject from scratch. Events
  keep their own dates as facts ("In August 2024, the yen carry trade unwound…"). Use the references as material;
  never mention them either (the page lists them as Sources). `gist`: 2–4 sentences; `key_ideas`: one per idea the
  note covers (usually 3–10), each a short bolded lead phrase then 1–3 sentences; `numbers`: figures worth
  remembering; timestamps always null; `domain`/`topic`/`tags`/`concepts`/`is_educational` as analyze writes them.
  Ends with `READING_VOICE`.

## Refresh and cards

- **`refresh_note` sync action** (`archie_api/sync/note_actions.py`), payload `{"id", "counted": bool, "at": aware
  datetime}`: rejected unless the source is the user's live note, unrefreshed, `cards_off` false and has a current
  summary. Sets `refreshed_at = min(at, now)` (the phone's tap time, so "today" means the same day on both sides),
  `refreshed_from_queue = counted`, `state = consumed`, touches the row, and queues `note_cards`.
- **`skip_note` sync action**, payload `{"id", "at"}`: rejected unless it is an unrefreshed live note; sets
  `refresh_skipped_at = min(at, now)`.
- **`note_cards` handler** (`handlers/note_cards.py`): reads the note's current summary, its markdown and the user's
  card preferences (`prompts.preferences_block`); nothing to do when the note is gone, unrefreshed or `cards_off`.
  One Haiku call (`llm.NOTE_CARDS_MODELS = ModelPair(HAIKU, SONNET)`, step `note_cards`, schema
  `prompts.NOTE_CARDS_SCHEMA` = `{"cards": [{kind, question, answer}]}`), system `prompts.NOTE_CARDS_SYSTEM`: 3–5
  open-recall cards of kind concept, mechanism or number on what the note chose to cover, worded from the write-up,
  the same one-focused-question and no-trivia rules as analyze, and an empty list when nothing is worth remembering.
  Writes them under the lock with `artifact_id` = the summary's id (retiring any earlier live cards of that note
  first, so a retried job never doubles them). No failure hook: a note without cards still reads fine.
- **The `import` mark never gets cards:** `refresh_note` is rejected for `cards_off`, the handler re-checks it, and
  the write-up writes `cards: []`.

## Test-only route

`POST /test/notes/{source_id}/write-up` (in `test_routes.py`, so it exists only with `ARCHIE_ENV` dev or test): body
`{"domain", "summary": {gist, key_ideas, numbers}, "sources": [{url, title}]}`; writes the summary artifact
(`prompt_version = "test-seed"`), sets the domain, marks it READY. Maestro uses it to get a write-up without a model.

## The phone

- **Labels** (`app/src/ui/sourceLabels.ts`): `kindLabel("note") = "Notes"`; `sourceByline` of a note is `Bear`; the
  item page's dated by-line is `From Bear · edited {Mon D, YYYY}` (`noteEditedAt`, else `createdAt`). `monogramFor` a
  note is `✎`.
- **Refresher** (`app/src/notes/refresher.ts`, pure, jest): `DAILY_NOTES = 2`.
  - `refresherQueue(sources)`: live notes with `cardsOff` false, `refreshedAt` null and a write-up (current
    summary). Unskipped first, grouped into **topic runs** by `topicId` (else `domain:{domain}`, else one ungrouped
    run); runs ordered by their most recently edited note, newest first; within a run, most recently edited first
    (`noteEditedAt ?? createdAt`), ties by id. Then skipped notes, by `refreshSkippedAt` oldest first.
  - `todayRefresher(sources, now)`: `counted` = notes with `refreshedFromQueue` and `refreshedAt` on the phone's
    local today. If `counted ≥ 2`, or the queue is empty and `counted > 0`: `{ kind: "done", nextUp }`. If the queue
    is empty and `counted = 0`: `null` (no card). Otherwise `{ kind: "pick", position: counted + 1, note: queue[0],
    minutes, nextUp: queue[1..2] titles }`. `minutes` = `readingMinutes(write-up words)`.
  - `noteMeta(source, queue, now)` (Library row): refreshed → `Notes · refreshed {today | weekday | Mon D} · N cards`
    (`· N cards` only when N > 0); first in the queue → `Notes · up next`; in the queue → `Notes · to refresh`; no
    write-up yet → `Notes · from Bear`; otherwise `Notes`.
- **Today** (`RefresherCard`, under the review card; `testID="today-refresher"`): kicker `Refresh a note · 1 of 2
  today`, a row with the `✎` tile, title and `Notes · {Domain} · N min read` that opens the note page, `Next up: A,
  B` when there are more, and a quiet **Skip** text button (`refresher-skip`) that pushes `skip_note`. The done
  state reads `Refresh a note · Done for today` with `Next up tomorrow: A` when any are left. Today's empty check
  counts the card.
- **The note page** (`app/src/app/source/[id].tsx`, a `note` branch):
  - Kicker `Notes · {Domain}`, title, by-line, then **Archie's write-up** (the existing summary sections), then a
    **Sources** list when the write-up has any (host above title, like the mocks; tap → `WebBrowser.openBrowserAsync`),
    then **See original note ›** (`item-original-note`), then "Cards from this" once there are cards.
  - Before the write-up exists: the original note rendered with `Markdown`, under a quiet line "Archie's write-up is
    on its way" (`note-write-up-pending`); no Done button.
  - **See original note** opens `OriginalNoteSheet` (`BottomSheet`, `testID="original-note-sheet"`): header "Your
    original note", sub-line "From Bear · last edited {Mon D, YYYY}", then `note_markdown` rendered with the app's
    `Markdown` component in a `ScrollView`. Read-only, and offline (the markdown is synced).
  - **Done, add review cards** (`note-done`), pinned to the bottom, shows only while the note is in the refresher
    queue: a note with `cardsOff` false, unrefreshed, with a write-up (so it also shows on such a note opened from
    Library, which refreshes it early and the queue skips it). Tapping it calls `refreshNote(db, id, counted)` where
    `counted` = this note is today's pick (`todayRefresher` says `pick` with this note), registers the pending toast,
    requests a sync and goes back.
  - Hidden for notes: the badge line, `ItemActions`, "Your note", the email links; in the ••• menu, "Remind me
    later…", "Queue the primer" and "Wrong episode?". Favorite, Ask about this, card toggles, Change topic, Summary
    versions and Delete stay.
- **The toast** (`app/src/notes/RefreshToastRoot.tsx`, mounted at the root beside `ReminderRoot`): holds the pending
  `{sourceId, title}`; a live count of that source's live cards; when it becomes > 0 it shows `Toast` "N review cards
  added from {title}" (`N review card added` when 1) and clears. It shows wherever the owner is (Today in the mocks).
- **Library:** notes are filed under their domain and topic like any source; rows use `noteMeta`; the Inbox filter
  and its count skip notes; `statusTag` of an unrefreshed note is `Read` (no unread dot). `useLibraryData` adds a
  live per-source count of live cards (`LibrarySource.cardCount`).
- **`Markdown`** (`app/src/ui/Markdown.tsx`) learns what Bear notes use: `[text](url)` links (underlined spans that
  open in `WebBrowser`), headings `#`–`######` (4–6 render as level 3), `+` bullets, `- [ ]` / `- [x]` items as
  bullets (`☐` / `☑`), and Bear's `==highlight==` and `~strike~` shown as plain text. `parseMarkdown` stays pure.
- **Sync:** `transport.ts` / `engine.ts` map the five new fields; `db/actions.ts` gains `refreshNote` and `skipNote`
  (local write + outbox, like `setFavorite`).

## The import script (`scripts/import_bear.py`)

Standard library only, so `uv run python -I scripts/import_bear.py …` runs it from the repo root.

- Arguments: `--marks <path>` (required), `--bear-db <path>` (default: Bear's group container database),
  `--api-url` (default the Railway URL `scripts/install_ios.sh` uses), `--dry-run`, `--write`.
- Opens the database with `sqlite3.connect("file:…?mode=ro", uri=True)`. Reads `ZSFNOTE` rows not trashed, archived,
  permanently deleted or encrypted, and their tags through `Z_5TAGS` / `ZSFNOTETAG`. Dates are seconds since
  2001-01-01 UTC (Core Data). Keeps the notes the marks file marks `import` or `cards`, matched on `id` =
  `ZUNIQUEIDENTIFIER`.
- The markdown sent is `ZTEXT` without lines that are only Bear tags (`#tag`, `#tag/sub`, `#multi word tag#`);
  the title is `ZTITLE` (else the first line, else "Untitled").
- `--dry-run` prints counts only (marked notes found, by mark; marked ids missing from Bear; skipped as encrypted)
  and makes no request. Never prints note titles or text.
- Otherwise it needs `ARCHIE_SESSION_KEY`, uploads in batches of 25, and prints the totals per status. With
  `--write` it then calls `POST /notes/write-ups` and prints how many write-ups were queued.

## Wire shape

`rows.sources[*]` gains `note_markdown: str | null`, `note_edited_at: datetime | null`, `refreshed_at: datetime |
null`, `refreshed_from_queue: bool`, `refresh_skipped_at: datetime | null`. New actions: `refresh_note {id, counted,
at}`, `skip_note {id, at}`.

## Testing

Real note content never appears in the repo: every fixture note is invented.

- **Import e2e (Postgres)** `services/api/tests/e2e/test_notes_e2e.py`: 401 without a session; importing an
  `import` note and a `cards` note creates sources with kind `note`, the right state, `cards_off`, `created_at`, a
  text artifact, an embed job and **no `write_note` job and no `llm_calls`**; the pull carries `note_markdown`,
  `note_edited_at`, `refreshed_*`; importing the same payload again answers `unchanged` with no new change_seq; an
  edited note answers `updated` with a new text version; a deleted note answers `deleted`; another user's note with
  the same Bear id is a separate source. `POST /notes/write-ups`: 403 for a non-whitelisted user; queues one job per
  note without a write-up, then 0 on a second call. `refresh_note`: consumed, `refreshed_from_queue`, a `note_cards`
  job; rejected for an `import` note and for one without a write-up. `skip_note` sets `refresh_skipped_at`. The test
  route is gated like `/test/session` (`test_test_route_gate.py`).
- **Write-up e2e (worker, recorded)** `services/worker/tests/test_write_note_e2e.py`: an invented note (e.g. on
  proof-of-stake staking, with one Wikipedia link and one Spotify episode link) → a current summary with `cards: []`
  and both links in `sources`, an `llm_calls` row with step `write_note`, `file_topic` and `embed` queued, READY;
  the recorded gist and key ideas never contain "note" / "notes" (the prompt contract). Cassette records the page
  fetches and the Anthropic call.
- **Note cards e2e (worker, recorded)** `services/worker/tests/test_note_cards_e2e.py`: a refreshed note with a
  write-up → 3–5 cards with the summary's `artifact_id` and an `llm_calls` row; a `cards_off` note → no cards and no
  call.
- **Units (no database):** `note_links` (markdown and bare links, de-duplication, the cap, episode vs page);
  `fetch_title.extract_description`; the import script against a Bear-shaped SQLite file the test builds (Core Data
  dates, tags, trashed/archived/encrypted skipped, tag-only lines stripped, marks filtering, dry-run counts).
- **Migration** in `packages/archie-db/tests/test_db_migrations.py`: an existing source keeps its row with the new
  columns null / false.
- **App (jest):** `notes/refresher.test.ts` (topic runs, edited order, skipped last, day picks and counts across a
  local midnight, done state, early refresh from Library not counted, `noteMeta`); `Markdown.test.ts` (links,
  deep headings, checkboxes); `sourceLabels.test.ts` (note labels); the sync engine test maps the new fields;
  `sections` test (Inbox skips notes).
- **Maestro** `maestro/notes.yaml`, run by `maestro/run_notes.sh` (log in, get a session for `test-user` from
  `/test/session`, import `maestro/fixtures/notes.json` (two invented `cards` notes in one topic) through
  `/notes/import`, seed both write-ups through the test route) and `make maestro-notes` (after `reset-local-data`),
  with a README row. The flow: Today shows "Refresh a note · 1 of 2 today" and the first note; open it; "See
  original note" shows the rendered markdown (a heading's text, no `#`); close; tap "Done, add review cards"; Today
  shows "2 of 2 today" with the second note and the toast "… review cards added from …". The `note_cards` job is one
  Haiku call, so the flow spends a fraction of a cent.

## Not in scope

- **Sharing a Bear note to Archie (follow-up).** Bear shares a note as plain text whose links the share extension
  already treats as the thing shared (`extractFirstUrl`), and the sheet's offline fallback is a deep link that can't
  carry a whole note. It needs a "Save as a note" choice in the sheet, an `add_note` action, and a decision on whether
  a shared note writes itself up at once (it should, once the voice is picked). Until then, re-running the import
  script brings in new notes.
- Reordering the refresher queue (Skip only), Google Docs, ongoing Bear sync, and generating write-ups for the
  owner's real notes (the owner runs `--write` after choosing the reading voice).

## Build plan

Five chunks, run one after another in this worktree (each depends only on the wire shapes above).

1. **Server data + API:** models, migration, `SourceKind.NOTE` and job kinds, pipeline rules, `notes/routes.py`
   (import, write-ups), sync fields and the two actions, the test route, `archie-issue-session`, import/action e2e
   tests, migration test.
2. **Worker:** `note_links.py`, `extract_description`, prompts, `write_note` and `note_cards` handlers registered in
   `HANDLERS`, model pairs and step names, recorded e2e tests, unit tests.
3. **Import script** and its unit test.
4. **App:** drizzle migration, schema, transport/engine, actions, `notes/refresher.ts`, `RefresherCard`, the note
   page, `OriginalNoteSheet`, `RefreshToastRoot`, Library labels and counts, `Markdown`, jest tests.
5. **Maestro and docs:** `maestro/notes.yaml`, `run_notes.sh`, fixture, `make maestro-notes`, README row, a `## M8`
   section in `docs/deploy.md` with the owner's commands.
