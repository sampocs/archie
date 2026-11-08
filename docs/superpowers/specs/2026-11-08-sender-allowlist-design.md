# Newsletter sender allowlist

**Status:** designed 2026-11-08, approved by the owner in chat (with their follow-up: lenient multi-identifier matching, shared platforms by address, display-name backfill, a CLI). It builds on the signup-confirmation feature
(`2026-11-08-confirm-emails-design.md`) and reuses its card, item-page prompt and Maestro shape. Where they differ,
this spec wins.

## Problem

The owner's newsletter address is public, and every ingested newsletter triggers paid LLM processing (fetch_content,
analyze, embeddings, the brief). Spam sent to it would cost money. A first email from a sender Archie hasn't seen
must wait, unprocessed, until the owner allows that sender.

## Decisions

### Identity: who a sender is

- **A sender is a set of identifiers, and matching is lenient.** Some newsletters send from several domains, so an
  email's sender counts as allowed when **any** of its identifiers matches an allowed entry. `IdentifierKind`
  (StrEnum): `domain`, `address`, `list_id`, `name`. An email's identifiers
  (`archie_api.ingest.senders.identifiers_for(address=..., list_id=..., name=...)` → list of
  `SenderIdentifier(kind, value)`, all values normalised):
  - **domain** — the registrable domain of the From address, lower-cased: `crew@morningbrew.com` → `morningbrew.com`,
    `news@mail.example.co.uk` → `example.co.uk`. Computed with the `publicsuffixlist` package
    (`PublicSuffixList(only_icann=True).privatesuffix(host)`, built once; the list ships in the package, so nothing is
    fetched). None for no `@`, an IP, a host without a dot, or no PSL answer.
  - **address** — the full From address, lower-cased — used **instead of** the domain when the domain is a shared
    sending platform or mailbox provider (constant `SHARED_SENDER_DOMAINS`: `substack.com`, `beehiiv.com`,
    `ghost.io`, `convertkit.com`, `kit.com`, `mcsv.net`, `mcdlv.net`, `mailchimpapp.com`, `buttondown.email`,
    `buttondown.com`, `mailerlite.com`, `sendgrid.net`, `amazonses.com`, `gmail.com`, `googlemail.com`, `google.com`,
    `outlook.com`, `hotmail.com`, `yahoo.com`, `icloud.com`). The bare platform domain is never recorded or matched,
    so allowing ByteByteGo (`bytebytego@substack.com`) never allows another Substack sender.
  - **list_id** — the `List-Id` header's `<...>` part (or the whole trimmed value when it has no brackets),
    lower-cased; absent when there's no header. (ByteByteGo: `bytebytego.substack.com`.)
  - **name** — the From display name, trimmed, whitespace collapsed, lower-cased; absent when empty.
- **Status of an email** (`senders.status_for(db, user_id=..., identifiers=...)` → `SenderStatus | None`): `allowed`
  if any identifier belongs to an allowed sender; else `blocked` if any belongs to a blocked sender; else None
  (unknown). Allowed wins: when in doubt, process.
- `email_message.parse` gains `ParsedEmail.sender_address: str | None` (lower-cased From address) and
  `ParsedEmail.list_id: str | None` (normalised). `sender` (display name, original case) is unchanged.

### Storage (server migration `0015_newsletter_senders`, revision `"0015"`, down `"0014"`)

- `newsletter_senders` (synced): `id uuid pk` (server-generated), `user_id` (FK users, cascade), `label text` (what
  the phone shows: the display name, else the address/domain), `status varchar(16)` (`SenderStatus`: `allowed` |
  `blocked`), `created_at`, `updated_at`, `change_seq bigint`; index `(user_id, change_seq)`. Never deleted; Unblock
  sets `allowed`.
- `newsletter_sender_identifiers` (server only): `id bigint identity pk`, `sender_id uuid` (FK newsletter_senders,
  cascade), `user_id` (FK users, cascade), `kind varchar(16)`, `value varchar(998)`, `created_at`; **unique
  `(user_id, kind, value)`** (an identifier belongs to one sender).
- `sources.sender_address varchar(320)` and `sources.list_id varchar(998)` (nullable; set on every newsletter from
  now on), `sources.sender_pending boolean not null default false`.
- **Backfill in the migration:** existing sources only stored the display name (`sources.sender`), so for every
  user, each distinct normalised display name of their live (`deleted_at IS NULL`), non-confirmation
  (`confirm_url IS NULL`) newsletter sources becomes an `allowed` sender (label = one original `sender` value,
  `gen_random_uuid()`, `nextval('change_seq')`) with one `name` identifier. Nothing else changes. Morning Brew, TLDR,
  Milk Road… keep flowing by display name, and their first new email adds nothing (identifiers are only recorded by
  Allow/Block/CLI). Normalisation in SQL must equal the Python one (`lower(regexp_replace(trim(sender), '\s+', ' ',
  'g'))`); a test pins that.

### Ingest (`ingest/routes.py::ingest_email`, after the dedupe check)

- **No identifiers at all:** accept and drop, logged.
- **Blocked:** accept and drop silently (log the sender id only).
- **Allowed:** today's behaviour, with `sender_address`/`list_id` stored.
- **Unknown confirmation** (`parsed.confirm_url` set): stored exactly as today (confirm card, ready, no jobs), not
  pending. No sender is written.
- **Unknown otherwise:** store the source and its capture as today but with `sender_pending = true`,
  `processing = ready`, `processing_error = null` (even when unreadable), and **no jobs queued**. Nothing shows
  "Processing", and it costs nothing.

### Recording a decision (`senders.record(db, user_id, identifiers, status, label)`)

Shared by the sync action and the CLI. Finds the senders that already own any of the identifiers. None → create one
sender (`label`, `status`). Otherwise the oldest of them is kept; every owning sender gets `status` (touched only if
it changed), and the identifiers not yet owned are attached to the kept sender. Then `senders.resolve_pending(db,
user_id)`: every live `sender_pending` source of the user is re-checked with `status_for` (using its stored
`sender_address`, `list_id`, `sender`): allowed → `sender_pending = false` and, with a capture, `processing =
pending` + `pipeline.enqueue_steps(..., [FETCH_CONTENT])`; without one, `processing = failed` with
`UNREADABLE_EMAIL_ERROR` (move that constant where both can import it without a cycle). Blocked → soft-deleted with
the helper shared with `source_actions.delete_source`. Unknown → untouched. Each changed source is `changes.touch`ed.
Idempotent: a repeat finds nothing to change and queues nothing.

### Sync action `set_sender_status`

`schemas.ActionType.SET_SENDER_STATUS`, handler in new `services/api/archie_api/sync/sender_actions.py`. Payload
`{status: "allowed" | "blocked", source_id?: uuid, sender_id?: uuid}`, exactly one of the ids (else malformed).
- `source_id` (Allow/Block on a card or item page, and Confirm): the user's source (live or not, so an action queued
  just before a delete still works) must be a newsletter; its identifiers come from its stored
  `sender_address`/`list_id`/`sender`; `record(...)` with label = `sender` or the address. No identifiers → rejected.
- `sender_id` (Unblock in Settings): the user's sender gets `status`, then `resolve_pending`. Unknown id → rejected.

### Pull

`newsletter_senders` is the 15th pulled table (`PulledTable.NEWSLETTER_SENDERS`, `schemas.NewsletterSenderOut {id,
label, status, created_at, updated_at, change_seq}`, `rows.newsletter_senders`). `SourceOut` gains `sender_address:
str | None` and `sender_pending: bool` (`list_id` stays server-only).

### Other server readers

`briefs.covered_newsletters` adds `sender_pending IS false`. The newsletter text route (`sources/routes.py`) serves
the capture for a pending source as it does for a confirmation, so "Open the full email" works.

### CLI `archie-allow-sender`

In `packages/archie-db` (modelled on `archie-set-ingest-address`: runs in the container, the email on the command
line so it never lands in the repo): `archie-allow-sender --email <user email> --sender <value> [--kind
domain|address|list_id|name]`. Without `--kind`: a value with `@` → `address`, unless its domain isn't shared, then
the same identifiers an email from it would have (its `domain`); a value with a dot and no spaces → `domain`
(refused when it's a shared platform domain); else `name`. Normalised like ingest, recorded as `allowed` with label =
the value. Because `record` lives with ingest in the API package and the CLI in archie-db, put the identifier and
record logic in `archie_db` (e.g. `archie_db/senders.py`, with `publicsuffixlist` an archie-db dependency) and have
the API import it.

### Phone

- **Storage:** drizzle migration `0015_newsletter_senders`: `sources.sender_address text`, `sources.sender_pending
  integer (boolean) not null default false`, table `newsletter_senders` (`id text primary key`, `label text not
  null`, `status text not null`, `created_at`, `updated_at`, `change_seq`), then `UPDATE sync_state SET position =
  0;` (re-pull, as 0014). Transport/engine map them (absent → null / false / []).
- **Actions** in `app/src/db/actions.ts`, local-first like the others:
  - `judgeSender(db, sourceId, status)` — queues `set_sender_status {source_id, status}`. Locally: the tapped
    source, and any other pending source whose `sender` matches it (trimmed, case-insensitive) or whose
    `senderAddress` equals it, get `senderPending = false, processing = "pending"` (allowed) or `deletedAt` (blocked).
    The pull corrects the rest.
  - `setSenderStatus(db, senderId, status)` — queues `set_sender_status {sender_id, status}`; locally sets the row's
    status.
- **Library:** `joinLibrary` splits live sources with `senderPending` into `LibraryData.pendingSenders` (newest
  first), exactly as it splits `confirmations` (a confirmation is never pending). So they are in no list, section,
  search, Domains, Saved or filter count. `brief.ts::todayBrief` skips `senderPending` sources.
- **Sender card**, at the top of Library below the confirm cards (every chip), reusing ConfirmCard's layout — extract
  the shared shell/pills so there's one card component with different words and buttons, not a parallel copy:
  headline `New sender: {sender}` (no sender → the address), secondary `{address} · {time}` (no address → just the
  time), a third line with the subject (`title`, one line, ink3; omitted when null). Pills **Allow** (primary) and
  **Block** (secondary) → `judgeSender`, request sync, toast `{sender} allowed` / `{sender} blocked`. Tapping the text
  opens the item page.
- **Item page** for a pending source: kicker `Newsletter · New sender`; instead of badges, actions, summary, note and
  cards: prompt `This email is from a new sender: {sender}.`, explanation `Allow lets Archie read and summarise it,
  and their future issues arrive as normal newsletters. Block deletes it, and Archie drops anything else they send.`,
  the same Allow / Block pills (`item-allow`, `item-block`). "Open the full email" stays. After Allow the page stays
  (now the normal processing page); after Block it goes back.
- **Confirm also allows:** after the browser sheet closes, `confirmSignup` calls `judgeSender(source.id, "allowed")`
  before deleting, unless the source is Gmail forwarding (`isGmailForwarding`). Dismiss doesn't.
- **Settings → Blocked senders** (`app/src/app/settings/newsletters.tsx`, linked from Settings with testID
  `blocked-senders-link`, modelled on `settings/removed-topics.tsx`): blocked senders by label A–Z, each with
  **Unblock** (`unblock-<senderId>`) → `setSenderStatus(id, "allowed")`; empty state `No blocked senders.`
  (`blocked-senders-empty`).
- **Words** the phone derives live in one pure module, `app/src/library/senders.ts` (+ jest test): headline, from
  line, toasts, prompt, explanation, with the missing-sender fallbacks.
- The server never follows any link. Every handler validates before its first write.

## Wire shape

- `rows.sources[*].sender_address: str | null`, `rows.sources[*].sender_pending: bool` (always present from the
  server; optional on the phone, read as null / false).
- `rows.newsletter_senders: [{id, label, status, created_at, updated_at, change_seq}]` (optional on the phone → []).
- Push action `{type: "set_sender_status", payload: {status, source_id} | {status, sender_id}}`.

## Testing

- **Identifiers (no db)** `packages/archie-db/tests/test_senders.py` (or next to the parser tests): real edge cases
  only — `news@mail.example.co.uk` → domain `example.co.uk`; `bytebytego@substack.com` → address, never domain
  `substack.com`; a Gmail address → address; List-Id with and without brackets; name normalisation; no `@` / IP →
  no domain. Parser: the fixtures' `sender_address` and `list_id` (Substack's `bytebytego.substack.com`).
- **Ingest e2e (Postgres)** `services/api/tests/e2e/test_ingest_e2e.py`: existing tests allow their sender first (a
  helper calling `senders.record`). New: unknown → pending, ready, capture present, no jobs, not in
  `covered_newsletters`, in the pull with `sender_pending: true`; allowed → jobs as today; blocked → no source;
  **sibling domain passes**: allow Morning Brew's identifiers, then a built email from `crew@morningbrew-mail.example`
  with display name "Morning Brew" is processed, and one with only a matching `List-Id` is too; **Substack
  address-level**: allowing the ByteByteGo fixture's identifiers doesn't allow a built email from
  `other@substack.com` with another name and List-Id (it's pending); allowed beats blocked when identifiers
  disagree; unknown confirmation → confirm card as today, not pending, no sender; no identifiers → dropped.
- **Sender actions e2e (Postgres)** new `services/api/tests/e2e/test_sender_actions_e2e.py`: Allow by `source_id` →
  that source and every other pending source sharing an identifier un-pended with FETCH_CONTENT queued, a pending
  source from an unrelated sender untouched, the sender row `allowed` in the pull; repeating it queues nothing more;
  Block → pending sources deleted, a later email dropped; Unblock by `sender_id` → a later email processed; Allow on
  a source whose identifiers span two existing senders merges into the oldest; malformed / both ids / foreign id
  rejected.
- **Migration** `packages/archie-db/tests/test_db_migrations.py`: existing sources keep their rows (`sender_address`
  null, `sender_pending` false); **backfill by display name**: live newsletters from " Morning  Brew" and "morning
  brew" make one allowed sender with name identifier `morning brew`; a deleted newsletter's and a confirmation's
  names make none; the Python normaliser gives the same value as the SQL.
- **CLI** (Postgres, small): `--sender morningbrew.com` → domain identifier; `--sender bytebytego@substack.com` →
  address; `--sender ByteByteGo` → name; `--sender substack.com` refused; unknown email refused.
- **App jest:** `senders.test.ts`; `join.test.ts` (pending split out, a confirmation is not pending); `brief.test.ts`
  (a pending source alone makes no "writing" brief); `actions.test.ts` (judgeSender allowed / blocked local effects
  on matching and non-matching pending sources, setSenderStatus, the queued payloads); the sync engine test covers
  the new source fields and table.
- **Maestro (free):** `maestro/sender_allowlist.yaml`, run by `maestro/run_sender_allowlist.sh` (modelled on
  `run_confirm_email.sh`): log in, deliver `morning_brew.eml` (fresh DB, so Morning Brew is unknown), flow: Library
  shows `New sender: Morning Brew`, tap Block, toast `Morning Brew blocked`, card gone; Settings → Blocked senders
  lists `Morning Brew`. The script then re-delivers the fixture with a new Message-ID and runs a second short flow
  asserting no card appears after a sync. `make maestro-allowlist` (after `reset-local-data`), README row. Allow is
  covered in pytest only (it spends).
- `run_newsletter.sh` and `run_brief.sh` deliver real newsletters on a fresh DB, so they allow their senders first
  with `docker compose exec -T api ... archie-allow-sender` or, simpler, `uv run archie-allow-sender` against the
  local dev DB (check which one `make start-local` uses), by display name.

## Not in scope

- SPF/DKIM checks.
- Allowing a sender from the phone before its first email; a list of allowed senders on the phone.
- Committing the owner's real subscriptions: they are pre-allowed in prod with the CLI after deploy.

## Build plan

Two chunks, built in parallel. The interface is the wire shape above: `rows.sources[*].sender_address` /
`sender_pending`, `rows.newsletter_senders [{id, label, status, ...}]`, and the push action `set_sender_status
{status, source_id | sender_id}`.

### Chunk 1: server (identifiers, migration + backfill, ingest, action, pull, brief, CLI)

- Files: `packages/archie-db/pyproject.toml` (+ `uv.lock`: `publicsuffixlist`, and the `archie-allow-sender`
  script), new `packages/archie-db/archie_db/senders.py` (identifiers, `SHARED_SENDER_DOMAINS`, `status_for`,
  `record`, `resolve_pending`, the CLI `main`) — or split the CLI into `archie_db/allow_sender.py` like
  `ingest_address.py`; `archie_db/models.py` (`NewsletterSender`, `NewsletterSenderIdentifier`, `SenderStatus`,
  `IdentifierKind`, the three `Source` columns), new `archie_db/migrations/versions/0015_newsletter_senders.py`
  (schema + backfill), `archie_db/briefs.py`, `services/api/archie_api/ingest/{email_message,routes}.py`,
  `services/api/archie_api/sync/{schemas,pull,actions,source_actions}.py`, new `sync/sender_actions.py`,
  `sources/routes.py`, `docs/deploy.md` (a line on `archie-allow-sender` next to `archie-set-ingest-address`), tests
  above, and `maestro/run_newsletter.sh` + `maestro/run_brief.sh` (pre-allow). Mirror commit `b013980`
  (`confirm_url`) and `7c50daf` (`published_at`) for column plumbing and an existing synced table (e.g. collections)
  for the new table. The models-vs-migrations comparison test must pass.
- Tests: the identifier/parser units, and with Postgres the ingest, sender-action, CLI, library-sync and migration
  tests (`TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test uv run pytest ... -m
  postgres`; never run docker make targets from a worktree). `make lint`.
- Depends on: none.

### Chunk 2: app (storage, sync, actions, Library card, item page, settings, Maestro)

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
  `item-block`, `item-sender-prompt`, `blocked-senders-link`, `blocked-senders-empty`, `unblock-<senderId>`.
- The Maestro flow can't run in the implementer's worktree (Docker + simulator); write it, the main agent runs it.
- Tests: `cd app && npx jest src/library src/brief src/sync src/db && npm run typecheck`.
- Depends on: none.
