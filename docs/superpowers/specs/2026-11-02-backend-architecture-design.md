# Archie backend architecture (2026-11-02)

This is the reference document for decisions that span the whole backend. The building happens in milestones (see the Roadmap at the end), and each milestone gets its own spec, plan and build. If this doc and a milestone spec disagree, the milestone spec wins for that milestone and this doc gets updated.

It builds on:
- `2026-10-26-product-scope.md` (what Archie does; the single source of truth for product behavior. This doc only covers how it is built)
- `2026-10-26-derisk-findings.md` (spike results)
- `2026-10-29-ux-and-brand-design.md` (screens and brand)

## Decisions at a glance

| Area | Decision |
|---|---|
| Source of truth | Postgres. No Obsidian or markdown vault, and no desktop app. A one-way markdown export is a possible add-on later. |
| Hosting | Railway: one Python service running two processes (API and worker), plus Railway Postgres. |
| Cost | About $3.50–5/mo on Railway, inside the $5 Hobby credit if other projects leave room. AI spend is separate (see findings). |
| Content edits | Generated content is versioned. Edits and re-runs add a new version, and the original is never overwritten. |
| Search | Keyword search (Postgres full-text) plus meaning search (pgvector), merged into one ranking. |
| Embeddings | OpenAI `text-embedding-3-small`. |
| Jobs | A job queue table in Postgres, run by the worker. No Redis and no hosted workflow service. |
| Processing speed | Every job runs right away. The Batch API is not used; it would save about $1.50/mo. |
| Login | Sign in with Apple only (decided 2026-11-02; Google can be added later without design changes). After the first sign-in, a long-lived session key is kept in the Keychain. |
| Users | Built for many users from the start. Only whitelisted emails use the owner's API keys; everyone else brings their own. |
| Phone data | The phone keeps a full copy of the library in a local database, with an outbox for offline changes. |
| Chat | Answers from the library first, then from Claude's own knowledge, then from web search when needed. Every claim is labeled with where it came from. |
| Distribution | The App Store, because TestFlight builds expire. |
| Testing | Real-stack end-to-end tests that replay recorded outside calls, plus unit tests only for real logic. See Testing. |

## Hosting

- **The Railway service** runs one Python app, deployed as one service with two processes:
  - **api:** FastAPI. Serves the phone app, the share extension, and the newsletter webhook.
  - **worker:** pulls jobs from the Postgres queue and runs the pipeline.
- **Railway Postgres** with the `pgvector` extension.
- **Cloudflare** stays in use for:
  - email routing and the newsletter Worker;
  - R2, which holds the nightly backups.
- **Rough idle usage:** about 150 MB of RAM for Postgres and 200–300 MB for the app, with near-zero CPU. Railway's Hobby plan includes $5/mo of usage, and that credit is shared with the owner's other Railway projects.

## Data model

Every user-owned table has a `user_id`. The names below describe each table's job; the milestone specs pin down the exact columns.

- **users:**
  - email
  - whitelist flag: whether the owner's API keys pay for this user
  - created_at
- **sessions:** a hash of the session key, plus user, created_at, last_used_at and revoked_at.
- **user_api_keys:** keys a user brought themselves, one row per provider (Anthropic, Groq, OpenAI, Supadata). Encrypted at rest with an app secret.
- **sources:** one row per captured item.
  - kind: podcast, YouTube, X, article, newsletter or note
  - URL and title
  - state: Queued / Inbox / Briefed / Consumed
  - processing status, separate from state: pending / processing / ready / failed / unsupported (M2)
  - capture intent: Finished / Queue it (optionally with the primer queued too)
  - the raw capture: shared text, Safari page text, raw newsletter email
  - whether the source gets cards: educational content does; pure entertainment gets a summary only
- **briefs:** the Pulse brief (M5).
  - status: open or done; at most one open brief per user
  - content (jsonb): domains with their stories (headline, body, why, detail, importance, source ids), the "Also happening" lines, and the essays with their one-line pitch
  - source_ids: every newsletter the current content covers; since: the oldest one's created_at
  - version, bumped on every rewrite; done_at; synced to the phone like other tables
- **source_artifacts:** generated content for a source, and who made it (`origin`); Archie's rewrites never replace an owner-chosen current version (see the chat-edits spec).
  - One row per (source, kind, version). Kind is transcript, summary, primer, etc.
  - Each row records how it was made: the model, prompt version, the user's instruction for a chat edit, and the version it was derived from.
  - The *current* version is a pointer on the source/kind. Edits and re-runs insert a new row, so the original is never lost and the user can revert.
- **Organization:**
  - domains → topics
  - tags
  - concepts
  - source↔topic links, allowing more than one domain per source
  - source↔source links
- **cards:**
  - question, a short graded answer and detail lines (shown after answering, never graded), and its version, with `card_versions` once a card has changed (an Ask edit, a care rewrite, a restore)
  - its origin: a source, a topic primer or a brief (quiz cards), and the source position (timestamp or section)
  - FSRS state: stability, difficulty, due date, reps, lapses, written by the phone
  - `expires_at` (quiz cards); there is no suspended flag, Drop soft-deletes the card
- **reviews:** an append-only log of every review: card, grade, reviewed_at, and the scheduler state before and after. The latest `reviewed_at` wins the card's state; reviews are never pulled to the phone.
- **card_preferences:** the "what I care about" and "not this" notes that steer card generation (the last 20 are used).
- `sources.cards_off`: the owner turned cards off for this source.
- `sources.published_at`: when an article or podcast episode came out (the page's date or the feed item's day, as
  noon UTC); null when unknown, and always null for newsletters, which are sent and saved the same day (`created_at`).
  Ask's `search_library` bounds by saved day (`created_at`) or published day (`coalesce(published_at, created_at)`),
  both in the phone's time zone, and its result titles show the saved day plus the published date when it differs.
- **chunks:** passages of the transcript or text, with an embedding (`vector(1536)`) and a full-text `tsvector`. These are what search and chat search over.
- **jobs:**
  - the step and the source it belongs to
  - status, attempts, next_run_at, last_error
  - claimed with `SELECT … FOR UPDATE SKIP LOCKED`
- **llm_calls:** one row per outside model or API call: provider, model, input and output tokens, cost in USD as a `Decimal`, the job, and the user. Monthly spend is computed from this table.
- **sync log:** a per-user change sequence that phones pull from (see Phone sync).

### Files

- **Audio** is downloaded only to be transcribed and is deleted after, so no object storage is needed.
- **Page captures and newsletter bodies** are stored as text in Postgres.
- **The newsletter Worker** also keeps each raw email in Cloudflare KV as a backup.

## Pipeline

- **Each step is a job:** fetch/transcribe → name corrections → analyze → primer → cards → embed → links. When a job finishes, it queues the next step.
- **Steps run immediately.** Models and prices are taken from the findings doc:
  - Groq Whisper for transcription
  - Haiku 5.5 for corrections and analyze
  - Sonnet 5.5 for primers
- **Failure handling:**
  - A failed step retries with backoff.
  - A model refusal (`stop_reason: refusal`) or a cut-off answer counts as a failure, and the retry uses the fallback model (e.g. Sonnet ↔ Opus).
  - Once retries run out, the source is marked Failed, and the app shows a Retry button.
- **Content-specific steps:**
  - The cards step is skipped for entertainment-only content. Within long episodes, cards come only from the educational sections.
- **Sources:** each source kind has its own fetcher.
  - fxtwitter, falling back to vxtwitter, for X
  - the Safari page capture for articles
  - Supadata, falling back to a residential proxy or audio + Groq, for YouTube
  - the podcast feed or audio + Groq for podcasts
  - the email body for newsletters
- **Keys:** each call uses either the owner's keys (for whitelisted users) or the user's own keys.

## Login

- **Sign-in:** Sign in with Apple only. Archie is iPhone-only, so this meets the App Store rules on its own and needs no Google Cloud setup. Google sign-in can be added later as another `/auth/<provider>` route. Apple can hide a user's email behind a relay address, so the owner picks "Share My Email" on first sign-in, so that the whitelist matches.
- **First sign-in:**
  - The app sends the provider's ID token to `/auth`.
  - The backend checks the token's signature against Apple's public keys, which are cached.
  - It then creates the user if they're new, and returns a random session key.
- **Storing the session key:**
  - The key lives in the iOS Keychain, in an access group shared with the share extension.
  - Each use extends its expiry, so the user stays signed in until they reinstall or sign out.
- **Each request** costs one indexed lookup of the key's hash in Postgres. There are no calls to Apple after sign-in, and a lost phone's session can be revoked.
- **Whitelist:** the owner's emails are kept in config. Any other user must add their own keys in Settings before their sources are processed. That friction is fine, since Archie is mainly for its owner.

## Phone sync

- **The phone keeps a full copy of the library** in a local database (`expo-sqlite`). It's only text, so it's small, and every screen reads from it.
- **Local writes:**
  - Every user action (grade a card, change state, capture a share, edit a note) is applied to the local database right away and added to an **outbox**.
  - When the phone is online, the outbox is sent in order.
  - Each outbox entry has an id, so a retry can't apply the same change twice.
- **Pulling changes:** the phone asks for everything that changed since its last sync position (the per-user change sequence) and applies it.
- **Conflicts:** the latest write wins, field by field. Conflicts are rare in practice: the server only adds generated content, and only one person edits.
- **Offline:** reading, reviewing any card (due, ahead or by topic) and capturing all work. Chat, Pulse and chat edits need a connection.

## Notes

> M8: imported Bear notes are `note` sources (no fetch, own write-up and refresh flow); `2026-11-08-notes-import-design.md` is the source of truth.

## Search and chat

> Shipped in M7; `2026-11-06-m7-search-ask-design.md` is the source of truth where it differs: saved, synced conversations; labels computed per paragraph from citations; card drafts (Make a card, since replaced by a `propose_cards` tool and Save/Discard routes; see `2026-11-09-chat-cards-design.md`); Sonnet 5.5 with `between_tools` thinking; `text-embedding-3-small` (1536 dims); chunks indexed when a source's text is fetched, not only after analyze.

- **Search** runs keyword search and meaning search over `chunks` and merges the two result lists with reciprocal rank fusion.
- **Chat** is Claude with tools: `search_library` and Anthropic's web search tool.
  - **When it searches the web:** when the library and Claude's own knowledge can't answer, or when the question is about something recent or a fact that changes often (prices, deals, who runs what).
  - **Forcing it:** a "search the web" toggle in chat, or saying "look it up," makes it search every time.
  - **Labels:** every answer labels its sources as **your library** (with source and timestamp), **background**, or **web** (with links).
- **Edits through chat** ("remove this bullet") create a new version of the source's content (see Data model); built as proposals the owner applies, see `2026-11-08-chat-edits-design.md`.
- **Cost:** web search is about $0.01 per search plus tokens, well under $5/mo even with heavy use.

## Newsletters

- **The Cloudflare Worker** forwards each email to `POST /ingest/email`, authenticated with a shared secret. It also writes the raw email to KV as a backup.
- **Mapping emails to users:** the address the email was sent to decides which user it belongs to. `news@` belongs to the owner, and other users get their own addresses through the catch-all rule.

## Pulse (the brief)

- **`update_brief`** is a worker job (payload: the user). It is enqueued when a newsletter source becomes ready and when Done leaves unbriefed newsletters behind; at most one is queued per user, and a running one doesn't block a new one.
- It covers every ready newsletter still in the inbox, with no window. Essays go in unchanged, with their summary's gist as the pitch. News newsletters go into **one Sonnet call** (Opus as fallback) that splits them into stories, groups them by domain, ranks them and writes them. A pydantic model validates the output.
- Post-processing drops source ids the model invented, orders domains by their top story and stories by importance, and keeps at most 10 stories (the rest become "Also happening" lines). A failed update leaves the previous content in place.
- **`finish_brief`** (an outbox action) marks the newsletters the phone showed as briefed, closes the brief, and enqueues a new `update_brief` if others remain.
- The weekly news quiz is the `news_quiz` job; see "Review" below.

## Review

- **The phone schedules.** It runs FSRS (`ts-fsrs`) and pushes `review_card`, `drop_card` and `set_cards_off` actions; the server logs reviews and stores the card state.
- **API routes** grade a typed answer (Haiku), transcribe a voice answer (Groq Whisper, OpenAI as fallback) and rewrite a card from a "what I care about" note.
- **`news_quiz`** is a worker job the phone requests on Sundays (`request_news_quiz`); it writes 5 expiring quiz cards from recent briefs.
- **`packages/archie-llm`** holds the model calls shared by the worker and the API.

## Running it

- **Backups:** a nightly `pg_dump` to Cloudflare R2, keeping the last 30 days.
- **Cost:** monthly spend for each user comes from `llm_calls`.
- **App Store requirements:**
  - deleting your account in the app, which removes all of that user's data
  - a privacy policy page on example.com
  - a test login for Apple's reviewers, through a whitelisted reviewer account

## Testing

**Unit tests are for logic, not wiring.** A unit test belongs only where a plausible mistake in the code would fail it.

- **Worth testing:**
  - FSRS scheduling and review-ahead
  - replaying the outbox and resolving sync conflicts
  - merging keyword and meaning search into one ranking
  - pulling URLs out of share payloads
  - choosing the current version
  - deciding retries and model fallback
  - routing calls to the owner's keys or the user's own keys
  - checking the Apple sign-in token, using test signing keys
- **Not tests:**
  - restating a constant
  - a function that only calls other functions
  - checking that a mock returns what it was told to
- **The rule of thumb:** if changing a value means changing the test to match, delete the test.

**Backend end-to-end tests are the main check.**

- **Setup:** pytest runs the real FastAPI app, the real worker and a real Postgres locally.
- **How a test works:** it goes through HTTP the way the phone does, e.g. post a share, let the worker run the whole pipeline, then read back the summary, cards, versions and `llm_calls`.
- **Recorded outside calls:** every call to an outside service (Anthropic, Groq, OpenAI, fxtwitter, Supadata) is recorded once from a real call and replayed after that, with a VCR-style library such as `pytest-recording`.
  - Because replays are real responses, the parsing and storage code runs on real data, and replays cost nothing.
  - Recordings match on the endpoint, so a prompt change doesn't break them. One command re-records when prompts or providers change, which costs cents.
- **Failure cases:** replays of real 429s, server errors and the refusal stop reason check that retries and model fallback work.
- **Login in tests:** a test-only route issues a session directly. That route exists only when running tests.
- **What these tests don't judge:** the quality of what the models write. That is checked by small evaluation scripts like the spikes, run when prompts change.

**Live check against the real services.**

- **What it runs:** the cheapest real inputs, which are a 1-minute audio clip, a short article, one X post, and one chat question that uses web search.
- **Cost:** about $0.05 a run.
- **When it runs:** when each milestone finishes and before each App Store build. It never runs automatically.

**Phone end-to-end tests use Maestro.**

- **What they cover:** flows that tap through tabs and screens on the iOS simulator, against the local backend in replay mode. That tests everything from the screen down to the database.
- **The share sheet:** iOS's share sheet can't be automated reliably. The extension's handling of what it receives gets a unit test, and the share sheet itself gets a manual check whenever the extension changes.

## Roadmap

Each milestone gets its own spec → plan → build, and each one ends with something usable on the phone.

| # | Milestone | Done when the user can… |
|---|---|---|
| 1 | **Foundation:** Railway + Postgres, the job queue, Sign in with Apple and sessions, an Expo app shell with the local database, the outbox and the sync layer, and the test setup (replay recording, Maestro) | log in on the phone, and a change made offline syncs |
| 2 | **Capture → pipeline:** share extension → API; analyze, primer and cards; versions; `llm_calls`; articles/Safari and X first | share an article and read its summary minutes later |
| 3 | **All sources:** podcasts (Spotify), YouTube, newsletters from the Worker | see everything they consume arrive |
| 4 | **Library + Today screens:** states, domains/topics, source pages, following the UX spec | actually live in the app |
| 5 | **Pulse:** the newsletter brief, grouped by story | read the news brief |
| 6 | **Cards + review:** starts with the deferred card-grading spike; then FSRS, review ahead and by topic, the daily notification | do daily reviews, including offline |
| 7 | **Search + chat:** embeddings, merged search, web search, edits through chat | ask Archie questions |
| 8 | **Notes import:** Bear, Google Docs | bring in old notes |
| 9 | **App Store:** bring-your-own-keys in Settings, delete account, privacy policy, reviewer account, submission | install it from the App Store |

Sync is in milestone 1 so that every screen is built to read the phone's local copy from the start. Adding sync later would mean rewriting every screen.
