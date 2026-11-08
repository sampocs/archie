# Newsletter sender allowlist

**Status:** designed 2026-11-08, approved by the owner in chat. It builds on the signup-confirmation feature
(`2026-11-08-confirm-emails-design.md`) and reuses its card, item-page prompt and Maestro shape. Where they differ,
this spec wins.

## Problem

The owner's newsletter address is public, and every ingested newsletter triggers paid LLM processing (fetch_content,
analyze, embeddings, the brief). Spam sent to it would cost money. A first email from a sender Archie hasn't seen
must wait, unprocessed, until the owner allows that sender.

## Decisions

- **Sender identity is the registrable domain of the From address**, lower-cased: `crew@morningbrew.com` →
  `morningbrew.com`, `dan@tldrnewsletter.com` → `tldrnewsletter.com`, `news@mail.example.co.uk` → `example.co.uk`.
  Domain-level, so newsletters that rotate addresses or subdomains keep working. `email_message.parse` gains
  `ParsedEmail.sender_domain: str | None`, computed by `email_message.registrable_domain(address)` with the
  `publicsuffixlist` package (`PublicSuffixList(only_icann=True).privatesuffix(host)`; the list ships inside the
  package, so nothing is fetched). When the PSL gives nothing (a bare TLD, an IP, a host without a dot) the domain is
  None. Shared senders such as `substack.com` therefore allow every Substack newsletter at once; that is accepted.
- **Storage** (server migration `0015_newsletter_senders`, revision `"0015"`, down `"0014"`):
  - New synced table `newsletter_senders`: `id bigint identity pk`, `user_id` (FK users, cascade), `domain
    varchar(253)`, `status varchar(16)` (`SenderStatus` StrEnum: `allowed` | `blocked`), `created_at`, `updated_at`,
    `change_seq bigint`; unique `(user_id, domain)`, index `(user_id, change_seq)`. Nothing is ever deleted from it:
    Unblock sets `allowed`.
  - `sources.sender_domain varchar(253)` (nullable) — set on every newsletter ingested from now on.
  - `sources.sender_pending boolean not null default false` — true while the source waits for its sender's approval.
- **Ingest** (`ingest/routes.py::ingest_email`, after the dedupe check), by `sender_domain` and the user's
  `newsletter_senders` row:
  - **No domain** (unparseable From): accept and drop, logged. Every newsletter source from now on therefore has a
    `sender_domain`, which is what makes the legacy rule below exact.
  - **Blocked:** accept and drop silently (logged at info, domain only).
  - **Allowed:** today's behaviour, with `sender_domain` stored.
  - **Unknown, but a legacy sender** — the user has a live (`deleted_at IS NULL`), non-confirmation
    (`confirm_url IS NULL`) newsletter source with `sender_domain IS NULL` (so stored before 0015) whose `sender`
    equals this email's parsed `sender` (the display name): insert an `allowed` row for the domain, then today's
    behaviour. This is the backfill (see "Backfill" below).
  - **Unknown confirmation** (`parsed.confirm_url` set): stored exactly as today (confirm card, ready, no jobs),
    `sender_pending = false`, `sender_domain` set. No sender row is written.
  - **Unknown otherwise:** store the source and its capture as today but with `sender_pending = true`,
    `processing = ready`, `processing_error = null` (even when unreadable), and **no jobs queued**. Nothing about it
    shows "Processing", and it costs nothing.
- **Backfill.** Existing sources never stored the From address (only its display name, `sources.sender`), so the
  migration cannot compute their domains; it adds the schema and changes no rows. Instead the legacy rule above
  allows a domain on its first email after deploy when its display name matches a newsletter the owner already has
  (Morning Brew, TLDR, Milk Road…), so they keep flowing with no prompt. A sender whose display name changed gets an
  ordinary new-sender card. Risk accepted: spam that copies an existing newsletter's exact display name would be
  allowed; that needs knowing which newsletters the owner reads.
- **Sync action `set_sender_status`** (`schemas.ActionType.SET_SENDER_STATUS`, payload `{domain: str (1..253),
  status: "allowed" | "blocked"}`, handler in a new `services/api/archie_api/sync/sender_actions.py`). The domain is
  normalised with `.strip().lower()`. Upserts the user's row (touching `updated_at`/`change_seq` only when the status
  changes) and then, every time (idempotent):
  - `allowed`: every live source of the user with that `sender_domain` and `sender_pending = true` gets
    `sender_pending = false` and, if it has a capture, `processing = pending` plus `pipeline.enqueue_steps(...,
    [FETCH_CONTENT])`; without a capture, `processing = failed` with `UNREADABLE_EMAIL_ERROR` (move that constant
    somewhere both modules can import without a cycle, e.g. `archie_db.pipeline` or a small shared module). Each
    changed source is `changes.touch`ed.
  - `blocked`: every live source with that `sender_domain` and `sender_pending = true` is soft-deleted as
    `delete_source` does (share a helper; its cards would be none, but reuse the same code).
  - Confirmations and already-allowed sources from that domain are never touched.
- **Pull:** `newsletter_senders` becomes the 15th pulled table (`PulledTable.NEWSLETTER_SENDERS`,
  `schemas.NewsletterSenderOut {domain, status, created_at, updated_at, change_seq}`, `rows.newsletter_senders`).
  `SourceOut` gains `sender_domain: str | None` and `sender_pending: bool`.
- **The brief and other server readers:** `briefs.covered_newsletters` adds `sender_pending IS false`. The newsletter
  text route (`sources/routes.py`) serves the capture for a pending source as it does for a confirmation, so "Open
  the full email" works.
- **Phone storage:** drizzle migration `0015_newsletter_senders` adds `sources.sender_domain text`,
  `sources.sender_pending integer (boolean) not null default false`, the table `newsletter_senders` (`domain text
  primary key`, `status text not null`, `created_at`, `updated_at`, `change_seq`), then `UPDATE sync_state SET
  position = 0;` (re-pull, as 0014 did). Transport/engine map the new fields and table (absent → null / false / []).
- **Phone action** `setSenderStatus(db, domain, status)` in `app/src/db/actions.ts`, applied locally first like the
  others: upserts the local `newsletter_senders` row; `allowed` sets the domain's pending sources to
  `senderPending = false, processing = "pending"` (they show as processing until the pull says otherwise);
  `blocked` sets `deletedAt` on them. Then the queued `set_sender_status` action.
- **Library:** `joinLibrary` splits live sources with `senderPending` true into `LibraryData.pendingSenders` (newest
  first), exactly as it splits `confirmations` (a source with `confirmUrl` set is a confirmation, never pending). So
  they are in no list, section, search, Domains, Saved or filter count. `brief.ts::todayBrief` skips
  `senderPending` sources as it skips confirmations.
- **Sender card**, rendered at the top of Library with the confirm cards (same place, every chip; sender cards below
  confirm cards), reusing ConfirmCard's layout — extract the shared shell/pills so there is one card component with
  different words and buttons, not a parallel copy:
  - headline `New sender: {sender}` (missing sender → the domain), secondary line `{domain} · {time}`, and a third
    line with the subject (`title`, one line, ink3; omitted when null);
  - pills **Allow** (primary) and **Block** (secondary). Allow → `setSenderStatus(domain, "allowed")`, request sync,
    toast `{sender} allowed`. Block → `setSenderStatus(domain, "blocked")`, request sync, toast `{sender} blocked`.
  - Tapping the text opens the item page.
- **Item page** for a pending source: kicker `Newsletter · New sender`; in place of badges, actions, summary, note
  and cards: prompt `This email is from a new sender: {sender} ({domain}).`, explanation `Allow lets Archie read and
  summarise it, and future issues from {domain} arrive as normal newsletters. Block deletes it, and Archie drops
  anything else from {domain}.`, and the same Allow / Block pills (`item-allow`, `item-block`). "Open the full
  email" stays. After Allow the page stays and shows the normal (processing) page; after Block it goes back.
- **Confirm also allows:** tapping Confirm on a confirmation card or item page (after the sheet closes) also calls
  `setSenderStatus(senderDomain, "allowed")` when the source has a `senderDomain` and is not Gmail forwarding
  (allowing `google.com` would let all Google mail through; forwarded mail keeps its original From). Dismiss does
  not.
- **Settings → Newsletters** (`app/src/app/settings/newsletters.tsx`, linked from Settings as "Blocked senders", with
  testID `blocked-senders-link`, modelled on `settings/removed-topics.tsx`): the blocked domains, A–Z, each with an
  **Unblock** button (`unblock-<domain>`) that calls `setSenderStatus(domain, "allowed")`; empty state `No blocked
  senders.` (`blocked-senders-empty`).
- **Words** the phone derives live in one pure module, `app/src/library/senders.ts` (+ jest test): headline, from
  line, toasts, prompt, explanation, with the missing-sender fallbacks.
- The server never follows any link. Every handler validates before its first write.

## Wire shape

- `rows.sources[*].sender_domain: str | null`, `rows.sources[*].sender_pending: bool` (always present from the
  server; optional on the phone, read as null / false).
- `rows.newsletter_senders: [{domain, status, created_at, updated_at, change_seq}]` (optional on the phone → []).
- Push action `{type: "set_sender_status", payload: {domain, status}}`.

## Testing

- **Parser (no db)** `services/api/tests/test_email_message.py`: the fixtures' `sender_domain` (Morning Brew →
  `morningbrew.com`, Substack → `substack.com`, TLDR → `tldrnewsletter.com`); `registrable_domain` edge cases only:
  `news@mail.example.co.uk` → `example.co.uk`, upper case lowered, no `@` / IP / bare `localhost` → None.
- **Ingest e2e (Postgres)** `services/api/tests/e2e/test_ingest_e2e.py`: existing tests allow their sender first (a
  small helper). New: unknown sender → source with `sender_pending`, ready, capture present, no jobs, not in
  `covered_newsletters`, in the pull with `sender_pending: true` and `sender_domain`; allowed → jobs as today;
  blocked → no source; legacy display-name match → allowed row written and jobs queued, while a different display
  name on the same fresh domain stays pending; unknown confirmation → confirm card as today, not pending, no sender
  row; no-domain From → dropped.
- **Sender actions e2e (Postgres)** (new `services/api/tests/e2e/test_sender_actions_e2e.py`, or alongside the
  source-action tests): Allow → every pending source from that domain un-pended with FETCH_CONTENT queued, a pending
  source from another domain untouched, the sender row `allowed` in the pull; pushing it again is a no-op (no extra
  jobs); Block → pending sources deleted, a later email from that domain dropped; Unblock (allowed after blocked) →
  later email processed; malformed payload rejected.
- **Migration** `packages/archie-db/tests/test_db_migrations.py`: an existing source keeps its row with
  `sender_domain` null and `sender_pending` false; the table exists and its unique key holds.
- **App jest:** `senders.test.ts`; `join.test.ts` (pending split out, a confirmation is not pending); `brief.test.ts`
  (a pending source alone makes no "writing" brief); `actions.test.ts` (setSenderStatus allowed / blocked local
  effects and the queued action); the sync engine test covers the new source fields and table.
- **Maestro (free):** `maestro/sender_allowlist.yaml`, run by `maestro/run_sender_allowlist.sh` (modelled on
  `run_confirm_email.sh`): log in, deliver `morning_brew.eml` (fresh DB, so `morningbrew.com` is unknown), run the
  flow: Library shows `New sender: Morning Brew`, tap Block, toast `Morning Brew blocked`, card gone; Settings →
  Blocked senders lists `morningbrew.com`. The script then delivers the same fixture again with a new Message-ID
  (sed the header) and runs a second short flow asserting no card appears after a sync (pull-to-refresh or a wait).
  `make maestro-allowlist` (after `reset-local-data`), README row. Allow is covered in pytest only (it spends).
- `run_newsletter.sh` and `run_brief.sh` deliver real newsletters on a fresh DB, so they allow their senders first
  (psql `INSERT INTO newsletter_senders ... nextval('change_seq')` for the test user, like they read the token).

## Not in scope

- Per-address (rather than per-domain) identities, SPF/DKIM checks, or a list of shared-sender domains.
- Allowing a sender from Settings before its first email; a list of allowed senders.

## Build plan

Two chunks, built in parallel. The interface is the wire shape above: `rows.sources[*].sender_domain` /
`sender_pending`, `rows.newsletter_senders`, and the push action `set_sender_status {domain, status}`.

### Chunk 1: server (parser, migration, ingest, action, pull, brief)

- Files: `services/api/pyproject.toml` (+ `uv.lock`, `publicsuffixlist`), `services/api/archie_api/ingest/
  email_message.py`, `ingest/routes.py`, `packages/archie-db/archie_db/models.py` (`NewsletterSender`,
  `SenderStatus`, the two `Source` columns), new `packages/archie-db/archie_db/migrations/versions/
  0015_newsletter_senders.py`, `archie_db/briefs.py`, `services/api/archie_api/sync/{schemas,pull,actions}.py`, new
  `sync/sender_actions.py`, `sources/routes.py`, `source_actions.py` (shared soft-delete helper), tests listed above,
  and `maestro/run_newsletter.sh` + `maestro/run_brief.sh` (pre-allow inserts). Mirror commit `b013980`
  (`confirm_url`) and `7c50daf` (`published_at`) for column plumbing; mirror an existing synced table (e.g.
  collections) for the new table's model/migration/pull wiring. The models-vs-migrations comparison test must pass.
- Tests: `uv run pytest services/api/tests/test_email_message.py`, and with Postgres the ingest, sender-action,
  library-sync and migration tests (`TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test`
  or as the Makefile's `test-db` sets it; never run docker make targets from a worktree). `make lint`.
- Depends on: none.

### Chunk 2: app (storage, sync, action, Library card, item page, settings, Maestro)

- Files: new `app/drizzle/0015_newsletter_senders.sql` + `meta/0015_snapshot.json` + `_journal.json` +
  `migrations.js` (generated as 0014 was: `npx drizzle-kit generate --name newsletter_senders`, then append the
  re-pull), `app/src/db/schema.ts`, `app/src/sync/{transport,engine}.ts` (+ test), `app/src/db/actions.ts` (+ test),
  `app/src/library/join.ts`, new `app/src/library/senders.ts` (+ test), `app/src/library/ConfirmCard.tsx` (extract
  the shared card shell and pills; add the sender card), `app/src/library/confirmActions.ts` (Confirm also allows),
  `app/src/library/LibraryList.tsx`, `app/src/brief/brief.ts`, `app/src/app/source/[id].tsx`, `app/src/app/(tabs)/
  settings.tsx`, new `app/src/app/settings/newsletters.tsx` (+ `_layout.tsx` screen), `app/src/library/testRows.ts`,
  Maestro files (`maestro/sender_allowlist.yaml`, a second flow file if needed, `maestro/run_sender_allowlist.sh`),
  `Makefile` target `maestro-allowlist` (+ `.PHONY`), `maestro/README.md` row, `AGENTS.md` Commands line.
- testIDs: `sender-card-<sourceId>`, `sender-card-allow`, `sender-card-block` (inside each card), `item-allow`,
  `item-block`, `item-sender-prompt`, `blocked-senders-link`, `blocked-senders-empty`, `unblock-<domain>`.
- The Maestro flow can't run in the implementer's worktree (Docker + simulator); write it, the main agent runs it.
- Tests: `cd app && npx jest src/library src/brief src/sync src/db && npm run typecheck`.
- Depends on: none.
