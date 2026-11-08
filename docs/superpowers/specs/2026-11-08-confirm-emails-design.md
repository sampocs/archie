# Signup confirmation emails

**Status:** designed 2026-11-08 from the owner's approved mocks (`2026-11-08-confirm-emails-mocks.html`). Product
background is `2026-10-26-product-scope.md` (newsletters arrive at the owner's Archie address and wait in Inbox for the
brief); the ingest endpoint is `2026-11-04-m3-all-sources-design.md`. Where they differ, this spec wins.

## Problem

Subscribing to a newsletter with the Archie address (or pointing Gmail forwarding at it) sends a "confirm your
signup" email there. Today it becomes an ordinary newsletter: it is summarised, gets review cards, is embedded and
counts toward the brief, and the owner has no good way to click its link. Instead it should show up as a small card
that asks to be confirmed, and cost nothing.

## Decisions

- **Detection happens on ingest, on the server, without a model.** `email_message.parse` gains
  `ParsedEmail.confirm_url: str | None`. An email is a confirmation when either:
  - **Generic:** its HTML has an `https://` link (at most 2,048 characters) whose text, lower-cased with whitespace
    collapsed, is one of `confirm signup`, `confirm sign up`, `confirm your signup`, `confirm subscription`,
    `confirm your subscription`, `confirm my subscription`, `confirm your email`, `confirm email`,
    `confirm email address`, `confirm your email address`, `verify email`, `verify your email`,
    `verify email address`, `verify your email address`, `yes, subscribe me`, `yes, subscribe me to this list`,
    `activate`, `activate account`, `activate your account`, `activate subscription`,
    `activate your subscription` — **and** its subject, lower-cased, contains `confirm`, `verify` or `activate`. The
    first such link wins. The subject check is what keeps a regular issue with a stray "Confirm subscription" link
    from qualifying. The link finder follows `_WebVersionLinkFinder` (an `html.parser.HTMLParser`), generalised so
    both finders share one class that takes the set of link texts; unquoted `href` values (TLDR's
    `<a href=https://…>`) parse the same.
  - **Gmail forwarding:** the From address is `forwarding-noreply@google.com` and the subject contains
    `Forwarding Confirmation`; the link is the first `https://mail-settings.google.com/mail/vf-…` URL in the plain
    text (the `uf-` link next to it cancels, and is never taken).
  - Nothing else. `web_url`, `text`, `sender` and the rest are parsed exactly as today.
- **The server never follows the link.** It only stores it. Only the owner opens it, from the phone.
- **Storage:** a nullable `sources.confirm_url varchar(2048)` (server migration `0014_confirm_url`, phone drizzle
  `0014`), synced to the phone as `confirm_url` / `confirmUrl`. No backfill: confirmation emails already in prod stay
  ordinary newsletters.
- **Ingest of a confirmation** (`ingest/routes.py::_insert_newsletter`): the source is stored as any newsletter is
  (Inbox, queue intent, title, sender, message id, its capture so "Open the full email" works) with `confirm_url` set,
  `processing = ready`, and **no jobs queued**: it is never fetched, summarised, carded, embedded or briefed, and costs
  nothing. A confirmation with no readable text still stores the capture-less source as ready (the link is what
  matters). Redelivery dedupes on the message id as today.
- **The brief ignores confirmations:** `archie_db.briefs.covered_newsletters` adds `confirm_url IS NULL`, and the
  phone's `todayBrief` count skips sources with `confirmUrl` set, so they never make Today say "Writing your brief…".
- **Library:** every waiting confirmation (a live source with `confirmUrl` set) shows as a **confirm card** at the top
  of Library's All mode, above the list on every filter chip (All, Queued, Done, Inbox, …), newest first. It is never
  shown in Library's lists, sections, search results, Domains or Saved, nor on Today: `joinLibrary` splits
  confirmations out into `LibraryData.confirmations` so every other reader of `data.sources` stops seeing them. The
  filter counts are computed from `data.sources`, so they no longer count confirmations either.
- **The confirm card** (matching mock 1): a surface card with an envelope tile (`Ionicons` `mail-outline` on the
  chrome colour), the headline, a secondary line `{from} · {time}`, and two pill buttons, **Confirm** (primary,
  chrome) and **Dismiss** (secondary, press). Tapping the card's text opens the item page.
  - Headline: `Confirm your {sender} signup`; Gmail forwarding: `Confirm Gmail forwarding`. A missing sender reads
    `Confirm your newsletter signup`.
  - From: the sender; for Gmail forwarding `From {address}`, the address taken from the subject's
    `Receive Mail from {address}` (falling back to the sender).
  - Time: the same relative time label Library rows use for a source's arrival.
  - A source is Gmail forwarding on the phone when its `confirmUrl` starts with `https://mail-settings.google.com/`.
- **Confirm** opens `confirmUrl` with `expo-web-browser`'s `openBrowserAsync` (an in-app browser sheet). When the
  sheet closes (the promise resolves, whatever the result type), the phone calls `deleteSource` (the existing offline
  sync action), asks for a sync, and shows the toast `{sender} signup confirmed` (Gmail forwarding: `Gmail forwarding
  confirmed`). **Dismiss** calls `deleteSource` without opening anything, and shows no toast. Both work offline,
  like any delete (Confirm needs a connection only for the page itself).
- **Item page** (`app/src/app/source/[id].tsx`, mock 4) for a confirmation: kicker `Newsletter · Signup confirmation`,
  title and by-line as today; in place of the badge line, actions, summary, note and cards it shows the prompt
  `This email asks you to confirm your {sender} signup.` (Gmail: `This email asks you to confirm Gmail forwarding.`),
  the explanation `Confirm opens the newsletter's link. Once you're done, Archie deletes this email, and {sender}'s
  issues start arriving as normal newsletters.` (Gmail: `Confirm opens Google's link. Once you're done, Archie
  deletes this email, and forwarded mail starts arriving as normal newsletters.`), and the same Confirm and Dismiss.
  "Open the full email" stays. After Confirm (sheet closed) or Dismiss the page deletes the source and goes back
  (`router.back()`); the toast is Library's only.
- The words the phone derives (headline, from line, toast, item prompt) live in one pure module,
  `app/src/library/confirmations.ts`, with a jest test, because the Gmail branch and the subject parsing are real
  logic.

## Wire shape

`rows.sources[*].confirm_url: str | null` (always present from the server; optional on the phone, read as null when
absent). Nothing else changes.

## Testing

- **Fixtures** (committed, scrubbed with `scripts/scrub_newsletter_email.py`, then every tracking link replaced by
  a placeholder; no real token, id or personal address remains):
  `services/api/tests/fixtures/newsletters/tldr_confirm.eml` (TLDR's real signup email: unquoted
  `href=https://example.com/confirm-signup` reading "Confirm Signup", subject "TLDR - Confirm your signup") and
  `gmail_forwarding.eml` (Gmail's real forwarding confirmation, link `https://mail-settings.google.com/mail/vf-example`,
  cancel link `…/uf-example`, subject `(Gmail Forwarding Confirmation - Receive Mail from owner@example.com`).
- **Parser (pytest, no database)** in `services/api/tests/test_email_message.py`: TLDR → `confirm_url ==
  "https://example.com/confirm-signup"`; Gmail → the `vf-example` link (not `uf-`); Morning Brew and the Substack
  fixture → `None`; a built message with a "Confirm subscription" link but a subject without confirm/verify/activate
  → `None`; an `http://` confirm link → `None`; a "Verify your email" link with a "Please verify" subject → the link.
- **Ingest e2e (Postgres)** in `services/api/tests/e2e/test_ingest_e2e.py`: posting the TLDR fixture stores a source
  with `confirm_url` set, `processing == ready`, its capture present, **no jobs** for it, and it is not in
  `covered_newsletters` while an ordinary ready inbox newsletter is; it reaches the phone's pull with `confirm_url`.
  The Gmail fixture is stored the same way with its `vf-` link.
- **Migration** in `packages/archie-db/tests/test_db_migrations.py`: an existing source keeps its row with
  `confirm_url` null (as `0012_published_at` is tested).
- **App (jest):** `confirmations.test.ts` (headline, from line, toast and prompt for TLDR-like, missing-sender and
  Gmail rows); `brief.test.ts` (a confirmation alone makes no "writing" brief); `join.test.ts` (confirmations are
  split out of `sources`); the sync engine test that stores pulled sources covers `confirmUrl`.
- **Maestro (free, no model):** `maestro/confirm_email.yaml`, run by `maestro/run_confirm_email.sh` (modelled on
  `run_newsletter.sh`: log in, deliver `tldr_confirm.eml` through `/ingest/email`, then run the flow) and
  `make maestro-confirm` (after `reset-local-data`), with a row in `maestro/README.md`. The flow opens Library, sees
  the "Confirm your TLDR signup" card, taps Confirm, closes the browser sheet (taps "Done"), and asserts the card is
  gone and the toast "TLDR signup confirmed" showed. The link is `https://example.com/confirm-signup`, which is safe to
  open.

## Not in scope

- Backfilling or re-detecting confirmation emails already stored.
- Following the link on the server, or detecting whether the confirmation succeeded.
- Confirmations that are not emails (e.g. a captured web page), and other forwarding providers.

## Build plan

Two chunks, built in parallel. The only interface between them is the synced field `confirm_url` (string or null) on
`rows.sources`.

### Chunk 1: server (parser, storage, ingest, brief)

- Files: `services/api/archie_api/ingest/email_message.py`, `services/api/archie_api/ingest/routes.py`,
  `packages/archie-db/archie_db/models.py` (`Source.confirm_url: Mapped[str | None] = mapped_column(String(2048))`),
  new `packages/archie-db/archie_db/migrations/versions/0014_confirm_url.py` (revision `"0014"`, down `"0013"`),
  `packages/archie-db/archie_db/briefs.py`, `services/api/archie_api/sync/schemas.py` (and wherever source rows are
  built for the pull), tests above. Mirror commit `7c50daf` (`published_at`) for the column plumbing.
- Generalise `_WebVersionLinkFinder` into one finder class parameterised by link texts; keep `_web_url` behaviour
  identical. Constants for the texts, the Gmail sender, subject marker and `vf-` prefix; `MAX_CONFIRM_URL_LENGTH =
  2048` (reuse the routes' `MAX_URL_LENGTH` if it can be shared without an import cycle).
- `_insert_newsletter`: a confirmation is READY with no `enqueue_steps`; a non-confirmation is unchanged.
- Fixtures are already committed on the branch; do not edit them.
- Tests: parser units, ingest e2e, migration test (as listed under Testing). Run `uv run pytest
  services/api/tests/test_email_message.py` and, with Postgres, the ingest e2e and migration tests (see AGENTS.md for
  `TEST_DATABASE_URL`; never run docker make targets from a worktree).
- Depends on: none.

### Chunk 2: app (sync, Library card, item page, brief, Maestro)

- Files: new `app/drizzle/0014_confirm_url.sql` (`ALTER TABLE sources ADD confirm_url text;` then `UPDATE
  sync_state SET position = 0;`), `app/drizzle/meta/0014_snapshot.json` + `_journal.json` + `migrations.js` (generated
  the way 0012/0013 were, `npx drizzle-kit generate` with a custom name, then append the re-pull), `app/src/db/schema.ts`
  (`confirmUrl: text("confirm_url")`), `app/src/sync/transport.ts` (+ engine mapping and its test, as `publishedAt`),
  `app/src/library/join.ts` (`confirmations`), new `app/src/library/confirmations.ts` (+ test), new
  `app/src/library/ConfirmCard.tsx` (one card; `ConfirmCards` list rendered at the top of `LibraryList` in All mode on
  every filter), `app/src/brief/brief.ts`, `app/src/app/source/[id].tsx` (confirmation branch; item kicker via
  `ItemHeader`), `app/src/library/testRows.ts`, Maestro files and `Makefile` target `maestro-confirm`.
- testIDs: `confirm-card-<sourceId>`, `confirm-card-confirm`, `confirm-card-dismiss` (inside each card),
  `item-confirm`, `item-dismiss`, `item-confirm-prompt`.
- The Maestro flow cannot be run inside the implementer's worktree (it needs Docker and the simulator); write it,
  and the main agent runs it.
- Tests: `cd app && npx jest src/library src/brief src/sync && npm run typecheck`.
- Depends on: none.
