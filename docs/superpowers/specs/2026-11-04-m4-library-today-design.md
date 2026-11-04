# M4: Library, Today, topics and item states

> Milestone 4 of the [backend architecture roadmap](2026-11-02-backend-architecture-design.md#roadmap). Builds on
> [M2](2026-11-03-m2-capture-pipeline-design.md) and [M3](2026-11-04-m3-all-sources-design.md). Screens follow the
> [UX spec](2026-10-29-ux-and-brand-design.md); the M4 mockups are in
> [2026-11-04-m4-library-today-mocks.html](2026-11-04-m4-library-today-mocks.html) (published for review at
> https://claude.ai/artifact/R757wtbzzXabzyQZTwLXNe). Where this spec and the mocks disagree, this spec wins.

**Status:** Approved by the owner 2026-11-04 after a brainstorm with mocks.

## Goal

The user can live in the app:

1. **Today** shows primers ready to read, the top of their queue, and how many newsletters are waiting.
2. **Library** lists everything, filterable and searchable offline, with a **Domains** view of domains → topics.
3. **Item pages** follow the UX spec, and the user moves items between states: finish, prep, read/unread, snooze,
   go deeper, read later, change topic, fix a podcast match, delete.
4. **Topics** are a curated list per user: Archie files into it, adds topics only when nothing fits, and never makes
   near-duplicates; the user adds, renames, merges and removes topics (removed ones are blocked and restorable).
5. **Topic primers** give general background for a topic, separate from a source's own primer.

## Out of scope (and where it goes)

The roadmap changes with this milestone: **Pulse moves up to M5**, right after M4, so the newsletter backlog gets its
brief soon. Cards + review become M6, search + chat M7 (the other numbers shift by one; see Roadmap below).

- The brief / Pulse (M5). M4 ships the Briefed state, the newsletter kind (news vs essay) and the waiting count.
- The Review card on Today and card due dates (M6). M4's item page lists a consumed source's cards without due dates.
- Related items, the Ask bar and merged server search (M7). M4's search is local.
- Books (the Library's Books chip waits for books).
- Notifications of any kind. Snoozes return silently.
- Adding domains. The domain list is fixed in code.

## States

`SourceState` already has `queued`, `inbox`, `briefed` and `consumed`. M4 makes the transitions real:

| Action | From | Result |
|---|---|---|
| Finish (with optional reaction and note) | queued | `consumed`; reaction "lost" also sets `prep_me` |
| Go deeper | inbox, briefed | `consumed`; enqueues `primer` and re-runs `analyze` so it gets cards |
| Read later | inbox, briefed | `queued`, at the top of the queue |
| Mark read / unread | inbox, briefed newsletters | sets / clears `read_at` (the blue dot) |
| Briefed | inbox | set by M5's brief; nothing in M4 sets it |

Rules:
- **Cards only for consumed sources.** `analyze` keeps generating cards for every educational non-newsletter source,
  but the phone shows a source's cards only once it's consumed, and M6's review will only schedule those. A
  newsletter gets cards only after Go deeper (the re-run `analyze` sees `state == consumed`).
- **Primers** are still built for every non-newsletter source. "Prep me" and "Parts lost me" only decide whether it
  is pushed to Today's Primers ready.
- A **primer is unread** until opened: sources get `primer_opened_at`, topic primers get `opened_at`. Primers ready
  lists primers that are pushed (prep_me) and unread; opening one sets the time. "Mark unread" clears it.
- **Snooze:** `snoozed_until` on sources and topic primers. While it's in the future the item is hidden from Up next,
  Primers ready, the inbox count and (M5) the brief, and the Library lists it under "Snoozed". When it passes, the
  item shows again and, if queued, sits at the top of the queue (its position is reset to the top when snoozed).
  Choices: Tonight (18:00, hidden after 17:00), Tomorrow 09:00, This weekend (Saturday 09:00), Next week (Monday
  09:00), or a picked date at 09:00, all in the phone's time zone, sent as UTC. The phone decides what's visible, so
  it works offline.
- **Queue order:** `queue_position` (a float) on queued sources; lower is higher in the list. New queued sources,
  Read later and snooze reset it to `min − 1`. Reordering sends the dragged item's new position, the midpoint of its
  new neighbours (computed on the phone). Up next shows the first three visible queued items.

## Domains and topics

**Domains** are a fixed list in code (shared by worker and app), each with a light and dark color:

Macro, Finance, Trading, Crypto, Startups, AI, Politics, Geopolitics, Sports, Geography, History, Software
engineering, Other. The six existing colors stay; the new ones are muted hues at the same lightness (light / dark):
Trading `#4F6F8A`/`#8FB0CC`, Politics `#8A4F4F`/`#D58E8E`, Geopolitics `#5E6B3A`/`#A9B77A`, Sports
`#3A7A7A`/`#7CC2C2`, Geography `#7A6248`/`#C7A783`, Software engineering `#5A5F6E`/`#A3A8B8`, Other
`#77736A`/`#A9A59B`.

**Topics** are per user, in a new synced table:

`topics`: `id` (UUID, phone-generated for user-added ones), `user_id`, `domain`, `name`, `origin`
(`starter` | `archie` | `user`), `removed_at` (removed = blocked), `merged_into_id`, `created_at`, `updated_at`,
`change_seq`. Unique on `(user_id, lower(name))` among rows not merged.

**Sources** gain `domain` and `topic_id` (null until filed, or when nothing fitting is allowed).

### Starting topics

`archie_shared/topics.py` holds `STARTER_TOPICS` (domain → topic names) and `OWNER_TOPICS` (the owner's picks; topic
names aren't private). The owner's list, as chosen in the brainstorm:

- **Macro:** Fed & monetary policy; Interest rates & bonds; Inflation; Liquidity & the Fed's balance sheet; Dollar &
  currencies; Jobs & the labor market; Government debt & deficits; Recessions & the business cycle; Macro & risk
  assets; Tariffs & trade
- **Finance:** Investing fundamentals; Stocks & public markets; Venture capital; Private equity; Banking; Valuing
  companies; IPOs & M&A
- **Trading:** Market structure; Market making; Derivatives & options; Perpetual futures; Liquidity & volume; Risk
  management; Trading strategies; Quant trading
- **Crypto:** Bitcoin; Ethereum; Rollups & L2s; Cosmos & IBC; Solana; DeFi; Stablecoins; Staking & restaking;
  Tokenomics; Data availability & modular chains; Zero knowledge; Crypto regulation; Crypto investing
- **Startups:** Startup ideas; Product-market fit; Growth & marketing; Fundraising; Founder lessons
- **AI:** AI products & agents; Models & AI labs; Chips & Nvidia; Data centers & hyperscalers; Energy & power; AI
  business & economics; AI policy & safety
- **Politics:** US politics & elections; The Trump administration; Congress & legislation; Regulation; Courts & the
  law; Political economy
- **Geopolitics:** US–China; Taiwan & chips; Russia & Ukraine; Middle East; Europe; Trade wars & sanctions; Defense &
  military; Global institutions
- **Sports:** NFL play schemes; NFL contracts & the salary cap; NFL draft & team building; Quarterbacks; Sports
  business
- **Geography:** Countries & capitals; Physical geography; Population & cities; Natural resources; Borders & regions;
  Climate
- **History:** US history; The world wars; The Cold War; Ancient history; Economic & financial history; History of
  technology; Empires
- **Software engineering:** Frontend & mobile; Backend & APIs; Data engineering & databases; DevOps & cloud; AI/ML
  engineering; Languages & tools

`STARTER_TOPICS` is this list plus Personal finance & taxes, Insurance (Finance) and College football (Sports).

- **The owner:** on sign-in, a user whose email is in `OWNER_EMAILS` and who has no topics gets `OWNER_TOPICS` as
  `starter` topics, the three extra starter topics as removed (so they're restorable), and `topics_chosen_at` set.
- **Everyone else:** `users.topics_chosen_at` is null until they finish the **topic picker**, shown once after first
  sign-in: the starter list grouped by domain, **nothing selected**, plus "add your own" per domain. Submitting sends
  `choose_topics`; unpicked starter topics are not created (they aren't "removed", just absent).
- **Existing sources** are re-filed once, by a migration-time backfill: a `file_topic` job for every live,
  analyzed source of every user who has topics (users without topics are filed when they pick).

### Filing (`file_topic` job)

A new cheap step decides a source's domain and topic, so filing is one function used everywhere:

- **Runs:** after `analyze` for every source; for each source of a removed topic; for the backfill; after the picker.
- **Input:** the source's title, kind, and its summary (gist, key ideas, analyze's own domain/topic/tags as hints),
  plus the user's live topics (`domain › name`) and their removed topic names.
- **Model:** `llm.FILE_TOPIC_MODELS` = Haiku with Sonnet fallback (as `ANALYZE_MODELS`), JSON schema output:
  `{domain: <enum>, topic: string, is_new: bool, newsletter_kind: "news" | "essay" | null}`.
- **Prompt rules:** reuse an existing topic whenever one fits, even loosely; propose a new topic only when nothing
  fits, short and reusable, never a near-duplicate of an existing or removed topic; `newsletter_kind` only for
  newsletters (news = a digest of short items; essay = one piece of writing worth reading whole).
- **Server guard (not just the prompt):** the returned name is matched case- and punctuation-insensitively against
  live topics (→ that topic) and removed topics (→ `topic_id` null, domain kept). Otherwise a new `archie` topic is
  created. The model's domain must be in the enum or it becomes Other.
- Writes `sources.domain`, `topic_id`, `newsletter_kind` (new column, newsletters only) and bumps `change_seq`.
- A source's filing never blocks it from being READY: `file_topic` is not one of `required_artifacts`.
- Cost: well under $0.001 per source.

### Topic actions

| Action | Effect |
|---|---|
| Add topic (domain, name) | `user` topic, then a `topic_primer` job |
| Rename | Changes the name; refused if it collides with another live topic |
| Merge A into B | A's sources move to B; A gets `merged_into_id` and disappears |
| Remove | `removed_at` set; its sources get `file_topic` jobs (with A now among the removed) |
| Restore | `removed_at` cleared; nothing is re-filed back automatically |
| Change a source's topic | Sets `topic_id` (any live topic) and `domain` to the topic's |
| Write a primer | Enqueues `topic_primer` for a topic with no primer |

Removed topics are listed in **Settings → Removed topics** (a new screen off the account sheet), each with Restore.

## Topic primers

A new synced table `topic_primers`: `id`, `user_id`, `topic_id`, `version`, `is_current`, `content` (markdown, same
shape as source primers), `model`, `prompt_version`, `opened_at`, `snoozed_until`, `created_at`, `change_seq`.

The `topic_primer` job writes the general background for a topic ("How the Fed works"): same models (`PRIMER_MODELS`), voice and length
as source primers, prompt `topic-primer-v1`, input is the domain and topic name plus the titles of the user's sources
in it (for emphasis, not as material to summarize). Primers for topics the user adds are pushed to Primers ready;
"Write a primer" on any topic page makes one on request and also pushes it.

## Artwork

Sources gain `image_url`, filled where the pipeline already reads the source:

- Podcasts: the RSS item's `itunes:image`, else the channel's, else iTunes Lookup `artworkUrl600`.
- YouTube: `https://i.ytimg.com/vi/<id>/hqdefault.jpg`.
- Articles and links: the page's `og:image` (made absolute), read by `fetch_title`/the article fetcher.
- X: the author's avatar from fxtwitter (drawn as a circle).
- Newsletters: none (monogram).

The app loads it with `expo-image` (disk cache, so it shows offline after the first load). Missing or failed images
fall back to the monogram tile in the domain's color.

## Podcast match correction

"Wrong episode?" in the item page's ••• menu (podcasts only, online only):

- `GET /sources/{id}/episodes` lists the feed's items within ±30 days of the matched one (title, date, duration,
  guid), from the show's registered feed.
- Choosing one sends `choose_episode {source_id, guid}`: the source's resolved episode is replaced, its text,
  summary, primer and cards are retired (new versions come), transcript chunks are deleted, and `fetch_content`
  runs again.

## Phone ↔ server

New push actions (each idempotent, applied under the user's write lock like `add_source`):

`finish_source`, `set_prep_me`, `set_read`, `set_primer_opened` (source or topic primer), `snooze` (source or topic
primer; `until` null = unsnooze), `set_queue_position`, `go_deeper`, `read_later`, `delete_source`, `add_topic`,
`rename_topic`, `merge_topic`, `remove_topic`, `restore_topic`, `set_source_topic`, `request_topic_primer`,
`choose_topics`, `choose_episode`.

Each writes the phone's row optimistically in the same local transaction as its outbox entry (as `add_source` does);
the pulled row replaces it. A rejected action shows the existing rejected-sync message.

Pull gains `topics` and `topic_primers` (merged into the same position-ordered pages), and sources carry the new
columns. `GET /me` gains `topics_chosen` so the app knows to show the picker.

## Screens (app)

As the mocks show; details beyond them:

- **Today:** "Today" + mono date; Primers ready (pushed and unread, newest first, each with the unread dot); Up next
  (top 3 + "See all N ›" → Library on the Queued filter, each with a Prep me chip); Newsletters ("N newsletters
  waiting for your brief", senders, "since <day>" → Library on the Inbox filter). Each section hides when empty; an
  empty Today shows one calm line pointing at ＋.
- **Library List:** search field; filter chips All · Queued · Done · Inbox · Primers with counts; sections "This
  week" / "Earlier" by `created_at` (the Queued filter instead shows the queue in order, drag handles, then
  "Snoozed"). Rows: artwork, domain kicker, two-line title, meta, status tag (Queued, Done, Unread, Read, Briefed,
  Primer, Processing, Failed).
- **Swipe left** on a row: queued → Snooze, Finished; newsletter → Snooze, Mark read/unread; primer → Snooze, Mark
  read/unread. Done items → Delete.
- **Search** (local, case-insensitive, as you type): title, sender, domain, topic name, and the summary's gist and key
  ideas. Results use the list layout.
- **Library Domains:** domains with items, by count; done/queued/inbox bar; chips for topics with items plus the
  user's own (outlined); long-press a chip → Rename, Merge into…, Remove; "＋ Add a topic you want to understand".
- **Topic page:** kicker, name, counts; the topic primer (or "Write a primer" card); items newest first; ••• →
  Rename, Merge into…, Remove.
- **Item page:** cover beside kicker/by-line/reaction chip and topic chip; title; action row by state (queued: I
  finished it + Prep me; inbox/briefed: Go deeper + Read later; consumed: none); Gist; Key ideas; Rough numbers with
  timestamp chips; Background you might need (collapsed; opening it marks the primer opened); Your note; Cards from
  this (consumed only); ••• → Change topic, Snooze, Mark unread (newsletters), Wrong episode? (podcasts), Delete.
  Newsletters add "Open the full email" (the stored text, rendered).
- **Timestamp chips** open the source at that moment: YouTube `?t=<s>`, Spotify and Apple episode URLs with `t=`
  where supported, else the episode link.
- **Finish sheet:** How'd it go? (Easy / Mostly followed / Parts lost me) + optional note (typed; the mic waits for
  voice input) + Save. Also reached from the swipe.
- **Snooze sheet:** the five choices with their resolved times; a date picker for "Pick a date…".
- **Topic picker:** shown when `topics_chosen` is false, before the tabs.
- **Settings → Removed topics:** list + Restore.
- Haptics per the UX spec's table (selection for chips/toggles, light for push/pop, success for Saved/Finish).

## Data (migration `0004_library`)

- `topics`, `topic_primers` (new).
- `sources`: `domain`, `topic_id`, `image_url`, `queue_position`, `read_at`, `snoozed_until`, `primer_opened_at`,
  `newsletter_kind`.
- `users`: `topics_chosen_at`.
- Backfill: `queue_position` for queued sources by `created_at` (newest lowest); `primer_opened_at = now()` for
  existing sources (nothing old floods Primers ready); `read_at = now()` for existing newsletters; then, after
  deploy, the owner's topics are seeded at next sign-in and a one-off `archie-refile-sources` command enqueues
  `file_topic` for every live source of users with topics.
- Phone: drizzle migration adding the same columns and tables.

## Testing

- **API e2e (Postgres, real stack):** every new action, including idempotency and rejection (wrong user, bad
  state transition, name collisions); pull pages with topics and topic primers; `/me` `topics_chosen`; owner seeding;
  the picker; `GET /sources/{id}/episodes` against a recorded feed.
- **Worker:** `file_topic` with recorded Haiku responses (existing topic reused, new topic created, removed topic
  refused, newsletter kind set); `topic_primer` recorded; artwork extraction from recorded pages and feeds;
  `choose_episode` re-run; Go deeper re-analyze makes cards for a newsletter.
- **Unit (real logic only):** queue position midpoint, snooze time choices (time zones, "Tonight" after 17:00), the
  visibility rules (snoozed, unread, pushed), topic-name normalization, search matching.
- **Maestro** (local backend, simulator): finish a queued item; reorder the queue; snooze and see it in Snoozed;
  search; add, remove and restore a topic; open a primer from Today and see its dot clear; newsletter Go deeper
  (delivered through `/ingest/email`); the topic picker for a non-owner user.

## Roadmap change

The architecture doc's roadmap table becomes: 4 Library + Today (this), **5 Pulse**, 6 Cards + review, 7 Search +
chat, 8 Notes import, 9 App Store. Updated in the same PR.

## Follow-ups

- Source primers that skip what the topic primer covers (prompt work; needs real examples).
- Voice input for the finish sheet's note (mic, as the share sheet will get it).
- Snooze on cards (M6).
