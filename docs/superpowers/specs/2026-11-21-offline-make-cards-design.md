# Done or Make cards, and cards that wait for a connection: design

Owner-approved direction (2026-11-21), with mocks. Today a note's single Done button makes cards: in an Ask chat when
online, or by the `note_cards` worker job when offline, which wrote cards the owner never saw (cards that "showed up
prematurely"). Now the owner chooses, and offline cards wait for the chat instead of being written blind.

## What the owner sees

**Note page footer** (shown while a note waits for its refresh, as now: cards on, not refreshed, write-up written):

- Two buttons side by side, **Done** (secondary) and **Make cards** (primary), each one line (`numberOfLines={1}`),
  equal width.
- **Done**: marks the note refreshed with no cards (`refresh_note` with `make_cards: false`), goes back, and the toast
  reads "Note done".
- **Make cards**, online with Ask available: as now: marks the note refreshed (`make_cards: false`) and opens the chat
  about the note with `Make cards` sent.
- **Make cards**, offline (and Ask not known to be unavailable): the button reads **Make cards later**, and a one-line
  note above the buttons reads "Offline · cards will wait on Today until you're back". Tapping marks the note
  refreshed (`make_cards: false`), records the note as **waiting for cards**, goes back, and the toast reads "Cards
  saved for later".
- **Make cards** for an account where Ask is unavailable: the old path (`make_cards: true`, the worker writes them, the
  existing "N review cards added" toast). This is the only way `note_cards` is still reached from Done.

**Today banner** (picked: C, a slim banner):

- At the top of Today, above the task cards, while at least one note is waiting, the phone is online, and Ask is known
  to be available.
- One note: "Cards waiting for **Pricing Power**" with "Finish ›" on the right. More than one: "Cards waiting for
  **2 notes**".
- Tapping it opens the oldest waiting note's chat (the same `openChat` with about = the note and `Make cards` sent) and
  removes that note from the waiting list at once. A draft abandoned in the chat stays in Ask history; the banner does
  not come back for it. The next waiting note, if any, takes the banner.
- No dismiss control. Not wanting the cards = open the chat and leave.
- A waiting note that was deleted, or had its cards turned off, is dropped from the list silently (and never shown).

## State

- A new **local-only** SQLite table `waiting_note_cards` (`source_id` text primary key, `waiting_at` text ISO). It is
  never synced and never touched by pulls: the phone that tapped Done is the one that shows the banner. A Drizzle
  migration adds it.
- Actions: `markNoteCardsWaiting(db, sourceId)` (insert or ignore) and `clearNoteCardsWaiting(db, sourceId)`.
- The banner's input is the table joined with live sources: keep rows whose source exists, is not deleted, is a note,
  and has cards on; order by `waiting_at`, oldest first. Rows that fail the filter are deleted when the banner reads
  them, so the list does not grow.

## Offline, for tests

The app reads connectivity from `expo-network` in several places, and the simulator is never offline. A small
`useOnline()` hook (expo-network's connected and internet-reachable, as the note page computes today) gains a dev-only
override, set by `archie://dev/offline?on=1` / `?on=0` (Release builds ignore it, like `dev/login`). Only the note
page footer and the Today banner use the hook in this change; other screens keep their own checks.

## Edge cases

- Done or Make cards tapped twice: the existing once-per-visit guard covers both buttons.
- Ask availability unknown (`null`) and online: Make cards waits too (as offline), since a chat that can't answer would
  leave the note without cards; the banner shows once Ask is known available. If it turns out unavailable, the note
  stays waiting with no banner.
- The banner never shows offline, so a tap always has a connection to start the chat.

## Docs

`2026-10-26-product-scope.md` gains a line under notes: Done or Make cards; offline, cards wait on Today's banner.
`2026-11-10-note-cards-in-chat-design.md`'s offline bullet is superseded; add a one-line pointer to this spec.

## Testing

- Unit: the banner model (`waitingBanner(rows, sources)` → `null` | `{ sourceId, title, count }`): ordering, the
  filter (deleted, cards off, non-note), one vs many; the footer model (`noteDoneFooter(askAvailable, online)` →
  labels, offline note, and which path Make cards takes), replacing `noteDone`.
- Maestro, `notes.yaml` (spends nothing on models): assert both buttons; set offline via the dev link; assert
  "Make cards later" and the offline note; tap it; assert the toast; set online; open Today; assert the banner text;
  tap it; assert the chat about the note opened (the first message "Make cards" is visible). The chat's model answer is
  not awaited (the test user isn't whitelisted, so it fails cheaply). Tapping plain Done on the second note asserts
  "Note done".

## Build plan

One chunk; the pieces share the note page and Today and are small.

**Chunk 1: footer, waiting list, banner, dev offline**
Depends on: none.

- `app/src/db/schema.ts` + a generated migration: `waiting_note_cards`.
- `app/src/db/actions.ts`: `markNoteCardsWaiting`, `clearNoteCardsWaiting`.
- `app/src/notes/refresher.ts`: replace `noteDone` with `noteDoneFooter(askAvailable, online)` returning
  `{ makeCardsLabel, offlineNote: string | null, makeCards: "chat" | "later" | "worker" }`; tests in
  `refresher.test.ts`.
- `app/src/notes/waiting.ts` (new): `waitingBanner(rows, sources)` and its tests; a `useWaitingBanner()` hook reading
  the table live and pruning dropped rows.
- `app/src/ui/useOnline.ts` (new) with the dev override; `app/src/app/dev/offline.tsx` (new) sets it and goes back.
- `app/src/app/source/[id].tsx`: the two-button footer and the three Make cards paths; plain Done's "Note done" toast
  (through the existing pending-toast plumbing, which gains an optional message).
- `app/src/app/(tabs)/today.tsx`: the banner above the task cards (testID `today-cards-waiting`), online only.
- `maestro/notes.yaml`: the steps above. Docs edits above.
