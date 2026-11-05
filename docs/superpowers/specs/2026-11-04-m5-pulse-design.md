# M5 Pulse: the newsletter brief

Know the water-cooler stories in about two minutes without reading every newsletter. The owner approved the mocks in
`2026-11-04-m5-pulse-mocks.html` (Today preview B, brief layout D, the end of the brief, the story page). Product
background: "Pulse" in `2026-10-26-product-scope.md`; where they differ, this spec wins.

## Decisions

- **The brief is read, not browsed.** Every story is a complete headline + two or three sentences (what happened, then
  why it matters). Going deeper is optional: "Sources · N ›" opens the story page.
- **Rolling.** The open brief is rewritten in the background whenever a newsletter finishes processing, so it is ready
  (and offline) when the owner opens Today. One brief is open per user at a time.
- **"Since you last checked" = Done.** The brief covers every unbriefed newsletter (inbox state), however old —
  after weeks away it's still one brief, kept short by ranking. Tapping "Done ✓" marks exactly the newsletters the
  phone showed as `briefed` and closes the brief; anything that arrived while you were reading starts the next one.
- **News vs essays** (from `sources.newsletter_kind`, set by `file_topic`): news newsletters are split into stories;
  essays are never split or grouped. Essays appear at the end under "Worth reading" as a list (sender, subject, a
  one-line pitch = the essay's summary gist, and "＋ Queue"), so several can be compared before choosing. A newsletter
  with `newsletter_kind` null is treated as news.
- **Ordering:** stories are grouped by domain. Domains are ordered by their most important story; stories within a
  domain by importance. The top stories (at most 10 across all domains) are shown in full; the rest become one-line
  "Also happening" items.
- **Stories are awareness.** They never become library items or cards. Going deeper on one newsletter (its item page:
  full email, Open original, Make review cards, queue) is the path to keeping something.
- **No notifications. No weekly quiz** (moves to M6 with cards). **No embeddings** (M7): one LLM call groups, ranks
  and writes.

## Screens (mocks: 01 B preview, 01b D, 02)

- **Today:** the "Newsletters · N waiting" row is replaced by the brief preview card at the top of Today when an open
  brief has content: "Your brief", mono "N stories · M min", the first three story headlines, a line
  "+ X more" / "+ X more, and Y essays" when there are more, and "Read the brief ›". While the first version of a
  brief is still being written (newsletters waiting, no content yet) the card reads "Writing your brief…" with the
  newsletter count. No card when there is nothing unbriefed.
- **Brief screen** (`app/src/app/brief.tsx`, full screen with back): title "<Weekday>'s brief" (the phone's today),
  mono "since <Mon|yesterday|today> · M min" (since = the oldest newsletter it covers), a thin reading-progress bar
  under the header; then per domain (layout D): a heading row (10px rounded square in the domain color, domain label
  17pt bold, mono "N stories"), and one white card holding that domain's stories, each: headline (15.5 semibold),
  body (14.5, the "why it matters" sentence in ink-2), and a "Sources · N ›" link. Then "Also happening" (mono label,
  bulleted one-liners) inside a card, "Worth reading" with its count and a card of essay rows ("＋ Queue" turns into
  "✓ Queued"), then a full-width primary "Done ✓" and the hint "Marks these stories and the essays you didn't queue as
  briefed. The next newsletter starts a new brief."
- **Story page** (`app/src/app/brief/story/[index].tsx` — stories are addressed by brief id + index): domain kicker
  "<Domain> · Story", the headline as the title, the story's longer `detail` paragraph, and "Covered by": one row per
  source newsletter (monogram tile in the domain color, sender, subject · weekday) opening `/source/[id]`.
- Reading time M = ceil(words of all story bodies, their "why" sentences and also lines / 220), minimum 1.
- Library: briefed newsletters already show the "Briefed" tag; unchanged.

## Data

Migration `0006_briefs`:

```
briefs
  id uuid pk, user_id fk users, status text ('open' | 'done'), content jsonb null,
  source_ids uuid[] not null default '{}',      -- every newsletter the current content covers (news + essays)
  since timestamptz null,                        -- oldest covered newsletter's created_at
  version int not null default 0,                -- bumped on every rewrite
  created_at, updated_at, done_at null, change_seq bigint
  unique (user_id) where status = 'open'
```

`content` (written by the worker, validated with pydantic on write):

```json
{
  "domains": [
    {"domain": "Politics", "stories": [
      {"headline": "...", "body": "...", "why": "..." , "detail": "...", "importance": 9, "source_ids": ["..."]}
    ]}
  ],
  "also": [{"text": "...", "source_ids": ["..."]}],
  "essays": [{"source_id": "...", "pitch": "..."}]
}
```

`domain` stores the domain's display name (the `archie_shared.domains.Domain` value, e.g. "Politics"), matched case-insensitively; `importance` 1–10; `why` may be empty. Domains and
stories are stored already ordered. Every `source_ids` entry must be one of the brief's covered newsletters (ids the
model returns that aren't are dropped; a story left with none is dropped).

Sync: the pull gains `briefs: list[BriefOut]` (`id, status, content, source_ids, since, version, created_at,
updated_at, done_at, change_seq`), only the user's open brief and done briefs from the last 7 days. The phone stores
them in a drizzle `briefs` table (content and source_ids as JSON text) with a re-pull migration.

Action `finish_brief {id, source_ids}`: `source_ids` are the newsletters the phone showed. Rejects only when the
brief isn't the user's or isn't open. Marks the given ids that are the user's newsletters still in `inbox` as
`briefed` (queued or consumed ones are left alone), sets status `done`, `done_at`. If any unbriefed newsletters remain
(e.g. one landed while the owner was reading), it enqueues `update_brief`, so the next brief holds only the new ones.
The phone applies it optimistically (brief done, those newsletters briefed).

## Worker: `update_brief`

- New `JobKind.UPDATE_BRIEF`, payload `{user_id}`. Enqueued when a newsletter source becomes READY (from
  `pipeline.finish_step`) and when `finish_brief` leaves unbriefed newsletters behind. At most one QUEUED
  `update_brief` per user (enqueue is skipped if one is queued; a running one doesn't block a new one, so a newsletter
  that lands mid-run triggers a follow-up).
- Steps:
  1. Load (or create) the user's open brief. Collect covered newsletters: the user's newsletter sources in `inbox`
     state, READY, not deleted, however old.
  2. If none: leave an existing open brief's content as is when it has none, else clear it (content null,
     source_ids empty) — e.g. after every covered newsletter was queued. Done.
  3. Essays: `{source_id, pitch = summary gist}` from their current summary artifact; no LLM call.
  4. News: one call (`BRIEF_MODELS = ModelPair(primary=SONNET, fallback=OPUS)`), input = each news newsletter's id,
     sender, subject, date and current cleaned text (each truncated to 30k characters; newest first, text goes in
     until 150k characters are spent, then older ones are given as their summary — gist, key ideas, numbers — until
     60k summary characters are spent; older newsletters than that are deferred: left out of the call and out of the
     brief's `source_ids` and `since`, so Done doesn't brief them, they stay in the inbox, and a later brief covers
     them once this one is Done. Nothing is dropped), plus the domain list and the
     owner's topics for relevance. Tool/JSON output = the content shape above minus essays; the model writes at most 12 stories in full and puts other
     news in `also`. The style guide used by
     summaries applies (one reading voice). If there are no news newsletters, skip the call.
  5. Validate, drop unknown source ids, order domains by their top story's importance and stories within a domain by
     importance, keep at most 10 stories (the rest move to `also` as their headline), write content, source_ids, since,
     bump version and change_seq.
- Failure: the job retries per the usual policy; a failed update leaves the previous content in place (the brief is
  never set to an error state).
- Cost: one Sonnet call per update; roughly 5–15¢ with a few newsletters.

## Out of scope

Weekly quiz (M6), notifications, embeddings (M7), multiple topics per story, editing or dismissing single stories,
re-briefing done briefs.

## Testing

- Worker e2e with a recorded Sonnet cassette on the real fixtures: Morning Brew as news and `substack_bytebytego` as
  the essay → domains ordered by top importance, every source id valid, the essay listed with its gist, ≤ 10 stories.
- Unit tests for the post-processing (ordering, the 10-story cap moving the rest to `also`, dropping unknown source
  ids and stories left without sources) on hand-written content — this is the logic that could be wrong.
- Worker/API e2e: newsletter READY enqueues one `update_brief` (a second READY while one is queued adds none);
  `finish_brief` briefs only the given ids still in the inbox, rejects a closed brief, and a newsletter it didn't
  include lands in the next brief.
- App jest: reading time, "since" label, preview card lines, ordering is taken as stored.
- Maestro `brief.yaml` (+ `run_brief.sh`, real keys, a few cents): deliver two newsletters through `/ingest/email`,
  wait for the preview, open the brief, open a story and see "Covered by", go back, queue the essay, tap Done, the
  preview disappears.

## Build plan

Three chunks. 2 builds against the contract above (not 1's code) and runs in parallel with 1; 3 follows both.

**Chunk 1 — server** (`packages/archie-db`, `services/api`, `services/worker`): migration 0006 + `Brief` model;
`BriefOut` in the pull (open + last 7 days of done); `finish_brief` action + e2e; `JobKind.UPDATE_BRIEF`, enqueue
from `finish_step` for newsletters with the one-queued rule; worker handler `update_brief` + prompt in `prompts.py` +
`BRIEF_MODELS`; content pydantic model; cassette test. Depends on: none.

**Chunk 2 — app** (`app/src`): drizzle migration + `briefs` table + transport mapping; `finishBrief` action
(optimistic); brief helpers (reading time, since label, preview lines) with jest; Today preview card replacing the
newsletters row; brief screen and story page per the mocks; "＋ Queue" uses the existing `readLater`. Depends on: the
contract above.

**Chunk 3 — Maestro + docs**: `maestro/brief.yaml`, `run_brief.sh`, Makefile `maestro-brief`, `maestro/README.md`;
product-scope and backend-architecture docs updated (brief rules, briefs table, no Pulse quiz until M6). Depends on:
1 and 2 merged.
