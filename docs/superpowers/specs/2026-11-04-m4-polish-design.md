# M4 Polish: item actions, primers as resources, readable newsletters

Feedback from living in the M4 build on a phone. The mocks the owner approved are in
`2026-11-04-m4-polish-mocks.html` (the rounds that won: 00 graphite, 02d F′, 04b badge line, 06b primer button,
07 queued primers with 07b option G, 05 tab A). Product behavior otherwise stays as in
`2026-11-04-m4-library-today-design.md`; where they disagree, this spec wins.

## Decisions

- **Graphite stays the chrome.** Forest is only the icon and wordmark.
- **An item page shows where the item is** in one line under the title: a small mono badge (`INBOX`, `QUEUED`, `DONE`)
  and, for the inbox, "In your next brief" plus an "Add to queue" text link (F′). No status card, no queue number.
  The date moves into the header byline ("Morning Brew · Wed, Nov 4"; "Dwarkesh Podcast · 2h 41m · Added Mon").
- **At most one primary and one secondary button.**
  - Queued: **"Mark as done"** (opens the finish sheet) + the **primer button**.
  - Inbox: no buttons; the badge line's link does Read later.
  - Consumed: the primer button alone (secondary style, full width is fine).
- **The primer is a resource, not a task.**
  - Podcasts, articles and videos always have a primer (unchanged). The primer button reads "◆ Primer · N min" and
    opens the primer screen; once opened it reads "✓ Primed" (signal green, still tappable).
  - Newsletters get a primer only on request: "Create primer" → "Writing primer…" (disabled) → "◆ Primer · N min".
  - While a non-newsletter's primer is still being written the button reads "Writing primer…" (disabled).
  - The collapsed "Background you might need" section is removed; the button replaces it.
  - N is the primer's reading time: words / 220, rounded up, minimum 1.
- **Prep me is gone**, everywhere: the item page, Today's Up next chips, the capture options and share sheet (replaced
  by "Queue the primer", below), the `prep_me` column and the `set_prep_me` action.
- **Today has no primers.** "Primers ready" is removed. Today is Up next + the newsletters count.
- **Topic primers live on their topic page.** A topic whose current primer is unopened shows an unread dot in Domains
  (the same 10px `--unread` dot artwork uses).
- **Queued primers.** A primer can be put in the queue as its own entry, linked back to its item:
  - From the finish sheet: picking "Parts lost me" shows one row, **ticked by default**, "Queue the primer · ◆ N min ·
    so you can come back to it" (option G). Save queues it unless unticked. No "Read now".
  - From any item's ••• menu: "Queue the primer" (subtitle "Adds it to your queue as its own item"); when already
    queued it reads "Primer is queued" and tapping it removes it from the queue.
  - From capture (share sheet / + tab): the old Prep me switch becomes "Queue the primer too" (queued intent only).
  - In the queue (Library Queued, Today Up next) it is a row: ◆ tile in the item's domain color, kicker
    "<Domain> · Primer", title "Primer: <item title>", meta "N min read" or "Writing primer…". It drags, and swipes
    like a queued source (Done, Snooze, Remove from queue).
  - Opening it shows the primer screen with "For: <item title> ›" linking to the item and a primary "Mark as done",
    which removes it from the queue and marks the primer opened. Opening alone marks it opened but leaves it queued.
  - For a newsletter without a primer, queueing it also requests one; the row reads "Writing primer…".
  - A done (or never-queued) primer has no row of its own: it's reached from its item, or the Library's Primers filter.
- **Library Primers filter** lists every source that has a primer (not only prepped ones), plus topic primers.
- **••• menu, by frequency:** [Remind me later…, Mark as unread (inbox newsletters)] [Queue the primer, Make review
  cards (inbox/briefed only; subtitle "Marks it done and writes a primer"), Change topic, Wrong episode? (podcasts)]
  [Delete]. "Make review cards" is the old Go deeper (same action).
- **Newsletters behave like articles once queued:** finishing a queued newsletter re-runs `analyze`, so it gets cards
  (today only Go deeper did). "Create primer" and queueing a primer write a newsletter's primer.
- **The middle tab** is a filled chrome circle (46pt) with a white +, no label (option A). Its testID stays `tab-add`.

## Fixes

- **Readable full email.**
  - The email's HTML is reduced with trafilatura `output_format="markdown"` (headings and paragraphs kept), falling back
    to the plain part as today.
  - A new worker step `clean_text` (Haiku, Sonnet fallback, like `file_topic`) runs before `analyze` for newsletters.
    It numbers the text's blank-line-separated paragraphs, asks which are ads, sponsor notes, referral blocks, trivia,
    word-of-the-day, sign-offs, footers, "forwarded to you" and unsubscribe boilerplate, and writes a new current
    `text` artifact without them (content gains `"cleaned": true`; the original stays as a non-current version). The
    model returns only paragraph numbers. If it would drop more than 60% of the paragraphs, the text is kept as is.
    `analyze` and `/sources/{id}/text` read the current text, so both get the cleaned one.
  - The app renders the full email with each single line break as its own paragraph, which also fixes emails already
    stored as one-line-per-paragraph text.
- **Link to the original.** The parser also takes the web version from an HTML link whose text is one of "View
  Online", "View in browser", "View in your browser", "Read online", "View this email in your browser" (case-insensitive,
  https only), after List-Post and the Substack line. A newsletter whose url is not `newsletter:` shows
  "Open original ›" beside "Open the full email ›".
- **Rough numbers** render as the brand reference does: a white card, one row per fact separated by hairlines, the
  sentence in Geist 15, the figures in it (`$6.34 billion`, `98%`, `228`, `4.952%`, `+6.0 bps`, `$45k+`) in Geist Mono
  medium, and the timestamp chip on the right.
- **Library rows** lose the extra sender line under newsletters (the meta already says "Newsletter · Morning Brew").
- **Dragging** lifts the whole row as a rounded card (card radius, full card width, surface background, shadow, scale
  1.02), not a square inset rectangle.
- **Secondary buttons** are white surface cards with the card shadow, the same height and radius as primary
  (`Button` variant `secondary`), used for the primer button; nothing uses the flat grey chip style for actions.
- **Feedback on "Add to queue":** a toast "Added to your queue" with Undo (undo sends the reverse: the item returns to
  the inbox). Server: a new action `return_to_inbox` (queued newsletter → inbox, clears `queue_position`).

## Data and sync contract

Migration `0005_queued_primers` (Postgres) and the matching drizzle migration (phone):
- `sources.prep_me` dropped.
- `sources.primer_queue_position` double, null = not queued.
- `sources.primer_snoozed_until` timestamptz, null.

Sync source row: remove `prep_me`; add `primer_queue_position: float | null`, `primer_snoozed_until: datetime | null`.

Queue positions share one space: `rows.top_queue_position` returns one less than the lowest of queued sources'
`queue_position` and queued primers' `primer_queue_position`.

Actions (all validate before writing; payload fields in snake_case):

| Action | Payload | Effect |
|---|---|---|
| `queue_primer` (new) | `id`, `queued: bool` | queued → `primer_queue_position = top`, clears `primer_snoozed_until`; for a newsletter with no current primer and no primer job pending, enqueue `primer` and set processing to `processing`. Unqueue → null. Rejects deleted/missing sources. |
| `request_primer` (new) | `id` | Newsletter only, ready, no current primer: enqueue `primer`, processing → `processing`. Otherwise reject. |
| `return_to_inbox` (new) | `id` | Queued newsletter → `inbox`, `queue_position` null. |
| `set_queue_position` | `id`, `position`, `target: "source" \| "source_primer"` (default `source`) | `source_primer` requires a queued primer and sets `primer_queue_position`. |
| `snooze` | `target` gains `"source_primer"` | Sets `primer_snoozed_until`; snoozing returns it to the top like a source. |
| `finish_source` | adds `queue_primer: bool = false` | After consuming: if `queue_primer`, as `queue_primer` above. If the source is a newsletter, re-run `analyze` (processing → `processing`) so it gets cards. The "lost" reaction no longer sets anything else. |
| `add_source` | `prep_me` → `queue_primer: bool` | Queued intent only (same validation as before). |
| `set_prep_me` | removed | |
| `set_primer_opened` | unchanged | Also used by "Mark as done" on a queued primer, together with `queue_primer {queued: false}`. |

Worker: when a `primer` job finishes for a newsletter, the source returns to `ready` (its required artifacts are
satisfied); `required_artifacts` stays summary-only for newsletters. `analyze` re-runs for a consumed newsletter make
cards (existing rule). `clean_text` is a new `JobKind`; `steps_after_text(newsletter) = [clean_text, analyze]`; a
retry with a cleaned current text skips `clean_text`.

## Out of scope

- One topic per source stays (M5's brief splits newsletters into stories, each filed on its own).
- Re-cleaning newsletters already stored (they get the paragraph rendering fix only).
- Using the "lost" reaction to schedule cards (M6).

## Testing

- API: one e2e test per new or changed action through `/sync` (including shared queue positions and the newsletter
  primer/analyze enqueues); `test_actions.py` keeps asserting every ActionType has a handler.
- Worker: `clean_text` e2e with a recorded Haiku cassette on the Morning Brew fixture (drops the referral block,
  keeps the stories); parser test for the "View Online" link and markdown output on the same fixture.
- App: jest for the combined queue order (sources + primers), primer reading time, figure highlighting in rough
  numbers, and paragraph splitting; Maestro flows updated for the new copy (`today_primer` becomes a queued-primer
  flow: finish with Parts lost me → primer row in Up next → open → Mark as done), plus the inbox "Add to queue" + Undo.

## Build plan

Three chunks; 1 and 3 have no dependencies, 2 builds against the contract above and can start in parallel with 1.

**Chunk 1 — backend** (`packages/archie-db`, `services/api`, `services/worker`). Migration 0005 + models; sync row
fields; the action table above (new handlers in `source_actions.py`, schemas, capture's `queue_primer`, removing
`set_prep_me`); shared `top_queue_position`; email parser (markdown + View Online); `clean_text` job (prompt in
`prompts.py`, handler, `llm.CLEAN_TEXT_MODELS`, pipeline steps and retry); newsletter primer → ready. Tests as above.
Depends on: none.

**Chunk 2 — app model and screens** (`app/src`). Drizzle migration + schema; `db/actions.ts` (queuePrimer,
requestPrimer, returnToInbox, finish with queuePrimer, setQueuePosition target, snooze target; remove setPrepMe);
transport mapping; library model: a queue entry type `{ kind: "source" } | { kind: "primer" }` ordered together
(`queueOrder`/`upNext`), Primers filter = sources with a primer + topic primers, remove `primersReady`; Today (remove
Primers ready and Prep me chips; Up next renders primer entries); Library queue (primer rows, drag with target,
swipes); new primer screen route `app/src/app/primer/[id].tsx` (source primer: For-link, Mark as done when queued,
marks opened on open); item page (badge line, byline date, actions per state, primer button states, ••• menu
entries, Add to queue toast with Undo, Open original link, full email paragraph split); finish sheet "Queue the
primer" row; capture/share "Queue the primer too"; Domains unread dot for unopened topic primers. Maestro flows
updated. Depends on: chunk 1's contract (not its code).

**Chunk 3 — visual fixes** (`app/src`): tab bar filled + circle; `Button` secondary surface style; Rough numbers
card with mono figures; Library row sender line removed; drag lift as a rounded card. Depends on: none. Overlaps
chunk 2 in `source/[id].tsx` and `LibraryList.tsx`; chunk 3 keeps its edits to `SummarySections`, the sender line
and `ReorderableQueue`, and merges first.
