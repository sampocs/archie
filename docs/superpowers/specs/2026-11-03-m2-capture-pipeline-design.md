# Milestone 2: Capture → pipeline (2026-11-03)

**Status:** Built 2026-11-03; live check pending (the share extension, a Safari capture and a real X share on a device, and the `source_page` Maestro flow against real keys).

The second milestone of the roadmap in `2026-11-02-backend-architecture-design.md`. Product behavior is defined in `2026-10-26-product-scope.md`, the screens in `2026-10-29-ux-and-brand-design.md`, and the models and prompts were measured in `spikes/llm_processing/`.

**How this spec was made:** the owner asked for M2 to be built as far as possible without them, so the decisions below were made without a brainstorming round. Each one the owner might reasonably want differently is listed under **Decisions to confirm** at the end.

## Goal

On the phone, the user can:

1. Share an article from Safari (including a paywalled one they're logged in to) or a post from X to Archie through the iOS share sheet, choosing Finished or Queue it.
2. Within a few minutes, open that source in Library and read its summary (gist, key ideas, rough numbers), its primer, and the cards it produced.
3. See when processing failed and tap Retry.

Behind that: every model call is recorded in `llm_calls` with its cost, and generated content is versioned.

## Out of scope

- Podcasts, YouTube and newsletters (M3). A Spotify or YouTube link still saves and gets its title, as in M1, and is marked as not yet supported for processing.
- Domains/topics as tables, filters, the Today screen and the polished item page (M4). M2 stores domain, topic, tags and concepts inside the summary, and shows a plain item page.
- Reviewing cards, FSRS fields and the grading flow (M5). M2 only creates and shows cards.
- Embeddings, related links and chat edits (M6). Revert-to-version UI waits for chat edits.
- Voice notes in the share sheet. The note is typed.
- Bring-your-own keys (M9). Sources of non-whitelisted users fail with "needs your own API key".
- The reading-voice style guide. Prompts use the spike's neutral voice; the style guide replaces it later.

## Pipeline

### Kinds

`SourceKind` grows from `link` to: `article`, `x`, `youtube`, `podcast`, `link`. The server sets the kind from the URL when it applies `add_source`:

| URL | Kind | Processed in M2 |
|---|---|---|
| `x.com` / `twitter.com` (and `mobile.`, `www.`), path with `/status/<id>` or `/article/<id>` | `x` | yes |
| `youtube.com`, `youtu.be`, `m.youtube.com` | `youtube` | no, title only |
| `open.spotify.com`, `podcasts.apple.com` | `podcast` | no, title only |
| anything else http(s) | `article` | yes |

`link` stays only for M1 rows; a migration leaves them alone.

### Steps

Each step is a job (`JobKind`). A step that succeeds enqueues the next ones in the same transaction as its writes.

1. **`fetch_content`** (replaces `fetch_title` for new sources; `fetch_title` stays for youtube/podcast and for old jobs):
   - **article with a Safari capture:** use the captured text and title. Clean it: normalize whitespace, drop lines repeated more than twice (captions `innerText` repeats), cap at 200,000 characters.
   - **article without a capture:** GET the page (15 s total, 5 MB limit), extract the main text and title with `trafilatura`. Title falls back to the M1 `og:title`/`<title>` extractor.
   - **x:** parse the post id; `GET https://api.fxtwitter.com/2/thread/{id}`. Retry inside the step: up to 3 tries, 2 s apart, on 404, 5xx or timeout. Build the text from the thread's posts by the shared post's author in order, plus quoted-post text, plus an X Article's blocks joined with its title. Title: `@handle: ` + the first 80 characters of the first post, or the Article title. If fxtwitter still fails, fall back to `https://api.vxtwitter.com/i/status/{id}` (single post).
   - **Too little text:** under 50 words for an article (X posts can be short; they need 1 word) fails the step with `text_missing`, which is not retried: the reason shown is "Couldn't read this page. Share it from Safari to capture it."
   - Writes a `text` artifact and the title (unless the source already has one), then enqueues `analyze` and `primer`.
2. **`analyze`** (Haiku 5.5, fallback Sonnet 5.5): one structured call returning the spike's schema plus `is_educational: bool`. Writes a `summary` artifact (gist, key ideas, numbers, domain, topic, tags, concepts, is_educational) and, when `is_educational`, the 3–5 cards. For text sources key ideas and numbers have no timestamp (the field is nullable).
3. **`primer`** (Sonnet 5.5, fallback Opus 5.5): markdown, the spike's prompt. Writes a `primer` artifact.

`analyze` and `primer` run independently after `fetch_content`. The source is **ready** when both are done.

### Processing status

Separate from the reading `state` (Queued/Consumed…), because a queued item is still queued while it's processing. The architecture doc put Processing and Failed inside `state`; this spec moves them out and the architecture doc is updated.

- `sources.processing`: `pending` → `processing` → `ready` | `failed` | `unsupported`.
- `sources.processing_error`: short user-facing reason when failed.
- Set by the steps under the user's lock: `fetch_content` start → `processing`; the last of analyze/primer to finish → `ready`; any step's final failure → `failed`.
- The job loop calls a per-kind `on_final_failure(db, job)` hook when a job runs out of attempts, so the source can be marked failed with the reason. A `text_missing` or `needs_api_key` error is raised as `PermanentJobError` and fails the job on its first attempt.
- **Retry:** a new phone action `retry_source {id}` re-enqueues the failed steps (from `fetch_content` if no current `text` artifact exists, otherwise whichever of analyze/primer has no current artifact) and sets `processing` back to `processing`.

### Model calls

- One small module, `archie_worker.llm`, wraps the Anthropic SDK: `messages.create(...)` with a 300 s timeout (outputs are at most 8,000 tokens, so streaming isn't needed, and plain responses record and replay cleanly), SDK retries off (the job loop retries), structured output through `output_config.format` (json_schema) for analyze, and a `(primary, fallback)` model pair per step.
- **Fallback:** a response with `stop_reason` `refusal` or `max_tokens` is a failure of that model; the call is repeated once on the fallback model in the same attempt. If the fallback also fails that way, the step raises (and the job retries per the loop). API errors (429, 5xx, connection) raise and use the loop's backoff.
- **Every call** — including a refused one — inserts an `llm_calls` row: user, source, job, step, provider `anthropic`, model, input and output tokens, `cost_usd` (`Decimal`, computed from a price table in code: Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10, Opus 5.5 $4/$20 per M tokens), stop reason, created_at.
- **Keys:** whitelisted users use `ANTHROPIC_API_KEY` from the environment. Anyone else: `PermanentJobError("needs_api_key")` → "Add your own API key in Settings (coming soon)".
- **Max output:** analyze 8,000 tokens, primer 6,000 (the spike's values). Input text is capped at 200,000 characters before the call.

### Connections during outside calls

M1's handlers run inside one open transaction, so a slow fetch holds a Postgres connection. LLM calls take up to a minute, so M2 changes the handler contract: a handler reads what it needs, **ends the read transaction** (`db.commit()`) before any outside call, then takes the user's lock and writes. The loop still marks the job done in the handler's session after it returns. `fetch_title` gets the same change.

## Versions

`source_artifacts`:

| Column | Notes |
|---|---|
| id (UUID, server-made), user_id, source_id | |
| kind | `text`, `summary`, `primer` (`ArtifactKind`) |
| version | 1, 2, … per (source, kind) |
| content (jsonb) | `{"text": ...}` for text; the analysis object for summary; `{"markdown": ...}` for primer |
| is_current | partial unique index on (source_id, kind) where is_current |
| model, prompt_version | e.g. `claude-haiku-5-5`, `analyze-v1` |
| derived_from_id, instruction | null in M2; for chat edits later |
| created_at, change_seq | |

- A step that runs again (Retry, or a re-run later) inserts version N+1, flips the old row's `is_current` to false and the new one to true, both under the lock with new change positions. The original is never changed.
- **What syncs to the phone:** `summary` and `primer` artifacts, current and old. `text` doesn't sync: it can be large, and only server-side steps and chat need it.

## Cards

`cards`: id (UUID), user_id, source_id, artifact_id (the summary version that produced it), kind (`concept`/`mechanism`/`number`), question, answer, created_at, updated_at, deleted_at, change_seq. Synced. A re-run of analyze soft-deletes the cards of the previous summary version and inserts the new ones. FSRS columns come in M5.

## Capture

### `add_source` grows

Payload: `{id, url, intent, reaction?, note?, prep_me?, capture?: {title, text}}`.

- `reaction`: `easy` | `mostly` | `lost` (Finished only). `note`: up to 2,000 characters. `prep_me`: bool (Queue only). All stored on `sources` and synced.
- `capture.text` up to 400,000 characters (`capture.title` up to 500). Stored in a `source_captures` table (source_id, title, text, created_at) that `fetch_content` reads, so `add_source` stays a quick insert. Not synced.
- The lengths are checked when the action is validated; an over-long capture is rejected like any bad payload.

### Duplicates

M1 deferred this. Decision: sharing a URL the user already has (same normalized URL, not deleted) **merges into the existing source** instead of creating a second one.

- **Normalizing:** lowercase scheme and host, drop `www.`/`mobile.`/`m.`, drop the fragment, drop `utm_*`, `si`, `s`, `t` (X), `ref`, `fbclid`, `gclid`; drop a trailing `/`. X URLs normalize to `x.com/i/status/<id>`.
- **Merging:** the new row is still inserted (the phone made it, and it must sync back), with `deleted_at` set and `merged_into_id` pointing at the existing source. The existing source takes the new intent/state if it moves forward (Queued → Consumed, never back), the new reaction/note/prep_me when given, and a capture if it had none (which re-runs the pipeline from `fetch_content` when the previous attempt failed with `text_missing`). The phone pulls both rows: the new one disappears, the old one updates.
- `sources.normalized_url` is stored with an index on (user_id, normalized_url).

### Share extension

- `expo-share-extension` in the main app's config, activation rules url + text, with the spike's `preprocessing.js` for Safari pages (url, title, `innerText` of `<article>` or body).
- **The extension's UI** (its own small RN entry, `index.share.tsx`, no Drizzle): the title (capture title, else the URL's host) and URL; **Finished** / **Queue it**; Finished reveals "How'd it go?" (Easy / Mostly followed / Parts lost me) and "Anything confusing?" (text); Queue reveals the Prep me toggle; **Save**. Styled with the app's theme tokens.
- **Saving:** the extension reads the session key from the shared Keychain access group and POSTs one `add_source` action to `/sync/push` itself, so the source is processing before the user opens the app. On success it shows a check and closes after ~1 s.
- **Offline or not signed in:** it shows "Couldn't reach Archie" with **Open Archie**, which calls `openHostApp("share?…")` with the url, intent, reaction, note and prep_me (no capture: deep-link URLs can't carry an article). The app's `share` route calls the existing `addSource`, so the outbox delivers it later. Not signed in → the same button, and the app shows sign-in first.
- **URL from text:** Spotify and YouTube share text holding a URL; the first http(s) URL is taken (unit-tested).
- **Session key in a shared Keychain group:** `keychain-access-groups` = `$(AppIdentifierPrefix)com.sampocs.archie.shared` on both targets, and `expo-secure-store` with `keychainAccessGroup`. On launch the app moves an M1 key (no group) into the group, so the owner doesn't sign in again.
- **App Group:** not used. The spike showed `expo-share-extension` adds an App Group entitlement that the Apple portal didn't have; a small config plugin removes it so automatic signing works without portal changes.
- **＋ tab:** gets the same Finished/Queue + reaction/note/Prep me controls (shared component), writing through `addSource`.

## API and sync

- `POST /sync/push`: action types `add_source` (extended) and `retry_source`.
- `GET /sync/pull`: `rows` becomes `{sources, artifacts, cards}`. The page is the 500 lowest `change_seq` values across the three tables (each table queried with `change_seq > since ORDER BY change_seq LIMIT 500`, merged, cut to 500), so `position` stays a single number.
- `SourceOut` adds kind's new values, `processing`, `processing_error`, `reaction`, `note`, `prep_me`, `merged_into_id`.

## App

- **Local tables:** `sources` gains the new columns; new `artifacts` (id, source_id, kind, version, content JSON text, is_current, created_at) and `cards` (id, source_id, kind, question, answer, deleted_at). Drizzle migration.
- **Library row:** title, kind, state, and a processing line: "Processing…", "Failed · Retry" (tapping Retry pushes `retry_source`), "Not processed yet" for unsupported.
- **Item page** `library/[id]`: title, kind/host, gist, key ideas (numbered), rough numbers (mono), "Background you might need" (the primer, collapsed, rendered as markdown), your reaction/note, "Cards from this". Plain styling from the existing theme; M4 does the full UX.
- **Markdown:** a small renderer for the primer's headings, paragraphs, bold/italic and lists (no dependency if it stays under ~100 lines; otherwise `react-native-markdown-display`).

## Testing

**Backend e2e** (pytest, real API + worker + Postgres, outside calls replayed):
- **Article main path:** push `add_source` for a recorded article URL with no capture → worker runs fetch_content (recorded page), analyze and primer (recorded Anthropic responses) → pull returns the source `ready` with a summary artifact, a primer artifact, 3–5 cards, and `llm_calls` holds two rows with costs.
- **Safari capture:** an `add_source` with `capture` makes no page fetch (the cassette has none) and produces a summary.
- **X thread:** a recorded fxtwitter thread → a text artifact containing every post by the author in order.
- **Refusal fallback:** a recorded refusal from the primary model, then the fallback's real answer → primer written, two `llm_calls` rows, the first with `stop_reason=refusal`. (A real refusal is hard to provoke; the cassette for this one case may be produced by editing a recorded response's `stop_reason`, and says so in a comment.)
- **Permanent failure:** a page with too little text → source `failed` with the reason, job failed after one attempt; `retry_source` with a capture-less retry fails again; a duplicate share with a capture re-runs and becomes ready.
- **Retry after a transient failure:** a recorded 529 from Anthropic, then success → ready.
- **Duplicates:** the second share of the same URL (with `utm_` noise) yields a deleted merged row and an updated original.
- **Versions:** `retry_source` on a ready-but-forced-failed primer makes version 2 current, version 1 kept, both synced.
- **Non-whitelisted user:** source fails with `needs_api_key`, and no Anthropic call is made.
- **Pull across tables:** with more than 500 changed rows spread over sources, artifacts and cards, paging returns every row exactly once.

**Recording:** cassettes are recorded with `--record-mode=once`. In record mode only, a fixture reads `ANTHROPIC_API_KEY` from `.env` (the root conftest still strips it for every normal run), and the VCR config filters `x-api-key` and `authorization` out of recordings. Recording the suite costs a few cents.

**Backend unit:** URL normalizing and kind detection; capture text cleaning; the X thread → text builder (on a recorded fxtwitter JSON); choosing the steps for `retry_source`; the cost calculation; the fallback decision.

**App unit (jest):** URL extraction from shared text; the extended pull applying artifacts and cards; `retry_source` outbox entry.

**Maestro:** add a link through ＋ against the local backend in replay mode, open it, see the gist and the primer section. The share sheet itself is a manual check (it can't be automated).

**Live check (the owner):** share a Safari article, a paywalled one, and an X thread from the phone; each shows a summary, a primer and cards within ~3 minutes; `llm_calls` shows the cost.

## Deploy

- `ANTHROPIC_API_KEY` is added to the `archie` service as `preserve()` in `.railway/railway.ts` and set once in Railway from the owner's `.env`.
- `install_ios.sh` builds both targets (the extension is part of the app's scheme).

## Decisions to confirm

Made without the owner; each is easy to change before or after the build.

1. **Duplicates merge** into the existing source (rather than allowing two rows).
2. **Every source is processed, queued ones included** (summary, primer and cards). M5 decides that only consumed sources' cards enter review.
3. **Offline share falls back to opening the app**, losing the Safari capture for that share.
4. **Processing status is a separate column** from the reading state.
5. **Domain list** is the spike's: AI, Macro, Crypto, Startups, Finance, Tech, History, Security, Sports, Other. Real domains/topics come in M4.
6. **Educational vs entertainment** is decided per source by analyze (`is_educational`); per-section cards for long episodes come with podcasts in M3.
