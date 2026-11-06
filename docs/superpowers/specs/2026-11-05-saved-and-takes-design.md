# Saved and Takes: Favorites, Collections, Takes, and a Library ＋

**Status:** Piece 1 (Nav + Favorites) implemented on `saved-nav-favorites` (plan `docs/superpowers/plans/2026-11-05-saved-nav-favorites.md`); piece 2 (Collections) implemented on `saved-collections` (plan `docs/superpowers/plans/2026-11-05-saved-collections.md`); migration numbers moved to `0008_favorites` and `0009_collections` because M6 took 0007.

Three additions and one navigation change, decided in brainstorming on 2026-11-05. Mocks:
`2026-11-05-saved-and-takes-mocks.html` (screens 01–09). Product background is `2026-10-26-product-scope.md`; where
the two differ, this spec wins and the scope doc is updated when each piece ships.

## Decisions

- **Three different things, kept apart.**
  - **Favorites:** a star on any normal library item. Starring changes nothing else about the item.
  - **Collections:** just-for-fun scrapbooks ("Bears hype"). They are never processed and never appear anywhere on
    the learning side.
  - **Takes:** things the owner writes (opinions and talking points), with dated versions and review cards.
- **Favorites are grouped by domain** (the item's `sources.domain`), not by folders. With few favorites, domains are
  enough and starring stays one tap. Named folders are a likely later upgrade, as an optional "Move to folder" on top
  of this. They are not in this spec.
- **Collections stay out of the learning side completely.** Collection items are not `sources`. They never appear
  in the Library's All list, Domains, search, Today, Pulse, Ask, or the pipeline. The only places they show up are
  Library → Saved and the collection's own page.
- **A Take is your own writing.** There's no evidence finding or steelman in this version. Dictation uses the iOS
  keyboard mic.
- **Clean it up is an opt-in toggle in the editor.** When it's off, Archie saves the text exactly as written (for
  bullets you've already typed). When it's on, Archie rewrites the typed or dictated text into a short take: a
  one-line thesis plus main points, and an objection section when the text answers one. It keeps only the owner's
  own claims and numbers and adds nothing. The raw text is always kept.
- **Every take gets cards.** Archie writes 2–4 cards from every saved take, graded against the owner's own wording.
  Unwanted cards are swiped away like source cards. Saving a new version rewrites the take's cards and retires the
  old ones.
- **The ＋ tab goes away.** The tab bar becomes **Today · Library · Review · Ask**. Library's header gets a ＋
  button (the same filled chrome circle) that opens the add sheet over the page.
- **Takes aren't filed or searchable** in this version: no domain, no topic, no Ask. Filing them can come later.

## Screens

- **Tab bar** (`app/src/app/(tabs)/_layout.tsx`): four tabs. Delete `add.tsx` as a tab.
- **Library header** (mock 01): the title with a ＋ circle on the right. Under it, a full-width segmented control:
  **All · Domains · Saved · Takes** ("List" is renamed "All"). Search and filter chips belong to All. A starred row
  shows a small gold ★ after its domain kicker.
- **Add sheet** (mock 02, `app/src/app/add.tsx` as a modal route): URL field with Paste, then three choices.
  - **Finished** and **Queue it** work exactly as `CaptureOptions` does today, including "How'd it go?" and "Queue the
    primer too".
  - **Save to a collection** shows a dropdown (a native menu) preselected to the last collection used. Its last
    entry, "＋ New collection…", asks for a name. With no collections yet, the dropdown reads "New collection…" and
    asks on Save.
  - Below an "or" divider, **Write a take ›** opens the take editor. It needs no URL.
  - Save closes the sheet and stays on Library.
  - **The share extension** gets the same third choice with the same chips. That needs the collection list in the
    shared app-group store the extension already reads.
- **Library → Saved** (mock 03):
  - **Favorites · N:** one row per domain that has favorites, sorted by count. Each row shows the domain dot, name,
    the newest two titles and the count. Tapping a row opens that domain's favorites (mock 04,
    `app/src/app/favorites/[domain].tsx`): starred items newest-star first, with "Domain · Topic" as the kicker.
    Swipe left to unstar. No Favorites section when nothing is starred.
  - **Collections · N:** two-column tiles in the order they were created. Each tile shows a 2×2 mosaic of the newest
    four thumbnails, the name and "N saved". The last tile is "＋ New collection". Long-press a tile for Rename and
    Delete.
- **Item page** (mock 05): a ★ navbar button next to •••. It toggles the star, and the by-line adds "· ★ Favorite".
  Any source can be starred, newsletters included.
- **Collection page** (mock 06, `app/src/app/collection/[id].tsx`): kicker "Collection · N saved" and the name as
  the title.
  - The body is a feed of posts, newest first. Each post shows a 16:9 thumbnail (with ▶ and the duration for video),
    the author, "X video", "YouTube" or the site, the date saved, the caption or title, and the owner's note in
    italics if there is one.
  - Tapping a post opens the original URL (`Linking.openURL`). Nothing plays inside Archie.
  - Long-press a post for Edit note, Move to… and Remove. The ••• menu has Rename and Delete collection.
  - A post with no image gets a tile in a neutral color with the site name.
- **Library → Takes** (mock 07): filter chips All · Opinions · Talking points with counts. The list is sorted by most
  recently updated. Each row has a ❝ tile, a kind kicker (Talking point in the Startups blue, Opinion in the History
  plum), the title, and "Updated <date> · N versions · N cards" ("Written <date>" when there's only one version;
  "N versions" is hidden at 1).
- **Take page** (mock 08, `app/src/app/take/[id].tsx`):
  - The kind kicker, the title, and mono "Updated <date> · version N".
  - When the current version came from Clean it up: "Cleaned up from your dictation · See what you said ›", which
    shows the raw text read-only. While the cleanup is running, the page shows the raw text under "Cleaning up…".
  - The body, rendered as markdown (headings, bullets, emphasis).
  - **Cards from this · N:** each card's question with its due date. A card can be swiped away.
  - **Earlier versions › N:** the version list. Opening a version shows it read-only with "Restore this version",
    which saves it as a new version.
  - The navbar has **Edit**. The ••• menu has Change kind and Delete take.
- **Take editor** (mock 09, `app/src/app/take/edit.tsx`, with `?id=` for an existing take): an Opinion | Talking
  point toggle (default Talking point), a title field and a multiline markdown body. Save is disabled until there is
  a title and body. Below the body, a **Clean it up** switch ("Archie turns this into a short take with main points.
  Your words and claims only."). It's off for a new take and remembers its last setting per take. Editing a cleaned
  version opens the cleaned text, not the raw text. Cancel discards. The hint reads "Saving makes version N+1 and
  rewrites this take's cards."
- **Empty states:** Takes shows "Things you think, in your own words" with a "Write a take" button. Saved with
  nothing in it shows "Star items to keep them here, or save something just for fun to a collection."

## Data

The end-state schema (migrations are split per piece; see Build order). Every table follows the existing conventions: a `user_id` foreign key,
`created_at` and `updated_at`, a soft-delete `deleted_at`, and `change_seq` from the shared sequence, so pull ships
them like every other row.

```
sources
  + favorited_at timestamptz null              -- null = not starred

collections
  id uuid pk, user_id, name text not null, position real not null,
  created_at, updated_at, deleted_at null, change_seq

collection_items
  id uuid pk, user_id, collection_id uuid fk collections on delete cascade,
  url text not null, kind text not null,       -- CollectionItemKind: x | youtube | link
  title text null, author text null, image_url text null, duration_seconds int null,
  note text null,
  metadata_status text not null default 'pending',   -- pending | ready | failed
  created_at, updated_at, deleted_at null, change_seq

takes
  id uuid pk, user_id, kind text not null,     -- TakeKind: opinion | talking_point
  title text not null, current_version int not null,
  created_at, updated_at, deleted_at null, change_seq

take_versions
  id uuid pk, user_id, take_id uuid fk takes on delete cascade, version int not null,
  body text null,                              -- what the take page shows; null while cleanup is running
  raw_body text not null,                      -- what the owner typed or dictated
  cleaned boolean not null,                    -- Clean it up was on for this version
  created_at, change_seq
  unique (take_id, version)

cards
  ~ source_id, artifact_id become nullable
  + take_id uuid null fk takes on delete cascade
  + take_version_id uuid null fk take_versions
  check: exactly one of (source_id, take_id) is set
```

- A take's title and kind live on `takes`, so renaming or changing the kind doesn't make a new version. Only the body
  is versioned.
- `CardKind` gains `take`. Take cards use the same FSRS fields and reviews as M6 cards.
- The phone's drizzle schema mirrors these tables.

## Phone actions (outbox)

Each one is applied to the local database right away and has a handler in `services/api/archie_api/sync/`:

| Action | Payload | Server effect |
|---|---|---|
| `set_favorite` | source_id, favorited (bool) | sets or clears `favorited_at` |
| `create_collection` | id, name | inserts it at the end |
| `update_collection` | id, name?, position?, deleted? | rename, reorder, delete (soft-deletes its items too) |
| `add_collection_item` | id, collection_id, url, note? | inserts it and queues a `fetch_collection_item` job |
| `update_collection_item` | id, note?, collection_id?, deleted? | edit note, move or remove |
| `save_take` | id, kind, title, body, clean (bool) | creates or updates the take; inserts a new `take_versions` row when the body changed (`raw_body` = body; `body` = body, or null with `clean`); queues `clean_take` when `clean`, otherwise `take_cards` |
| `update_take` | id, kind?, title?, deleted? | change kind, rename or delete without a new version |
| `restore_take_version` | take_id, version | copies that version (body, raw_body, cleaned) into a new version without re-cleaning; queues `take_cards` |

Client-made ids (like `add_source`) let a just-saved item show up offline. A collection item saved to an unknown or
deleted collection is rejected.

## Worker

- **`fetch_collection_item`** fills `title`, `author`, `image_url` and `duration_seconds`, then sets
  `metadata_status`.
  - X: the existing fxtwitter → vxtwitter fetcher (media thumbnail, author, text, video duration).
  - YouTube: the existing metadata lookup.
  - Anything else: the page's `og:title` / `og:image`.
  - One attempt plus the standard retries. A failure leaves the post with its URL and a neutral tile. There's no
    Retry button, since nothing is lost.
- **`clean_take`** (Sonnet 5.5 for writing quality, in the reading voice) turns `raw_body` into markdown and sets
  `body`, then queues `take_cards`.
  - The prompt forbids new facts, numbers or arguments, and keeps the owner's hedges and stance.
  - It writes only to the version it was queued for. If retries run out, `body` falls back to `raw_body`, and the
    page says "Couldn't clean this up" with a Try again that re-queues it.
- **`take_cards`** (Haiku 5.5, retried with the fallback model like other steps) reads the take's current version and
  writes 2–4 cards. It soft-deletes the take's previous cards first, so review history stays on the old card rows.
  - The answers must use the owner's own words and claims. The prompt forbids adding facts or arguments that aren't
    in the text.
  - Typical questions: the main points, rough numbers the take cites, and the answer to a named objection.
  - The cards are logged in `llm_calls` like every other call.
  - It never runs for a version that is no longer current. A save that lands while the job is running starts a
    fresh job.

## Testing

- **Server e2e** (Postgres, `@pytest.mark.postgres`):
  - each new action through `/sync/push`, then `/sync/pull`;
  - the exactly-one-of check on cards;
  - deleting a collection soft-deletes its items;
  - saving a take with an unchanged body makes no new version.
- **Worker:**
  - `fetch_collection_item` for an X video and a YouTube link, replayed from recorded cassettes;
  - `clean_take` with a recorded cassette on a rambling dictation, checking it keeps the take's claims and adds no
    numbers that aren't in the raw text;
  - `take_cards` with a recorded Anthropic cassette, checking 2–4 cards that cite only the take's own claims;
  - retiring old cards on a new version.
- **App jest:**
  - Favorites grouping by domain (counts, order, empty domains hidden);
  - that collection items never reach `useLibraryData` or search (the boundary that matters most);
  - the take version and "Written/Updated" label logic.
- **Maestro:**
  - star an item, then find it under Saved → its domain;
  - make a collection from the add sheet and save a link into it, checking it shows on the collection page and not
    in All;
  - write a take, edit it, and see version 2 and "Earlier versions";
  - write a take with Clean it up on, against the recorded cleanup, and see "See what you said".
- **Manual:** the share extension's collection choice, since the share sheet can't be automated.

## Build order

Each piece gets its own plan and PR, in this order. Pieces 1 and 2 don't depend on M6; piece 3 does.

1. **Nav + Favorites.** Depends on: none.
   - Tab bar to four tabs, the Library header ＋ and four-way segmented control, the add sheet as a modal route
     (Finished / Queue only at this stage).
   - `sources.favorited_at` + `set_favorite`, the ★ on the item page and rows, Library → Saved with the Favorites
     section, and the favorites-by-domain page.
2. **Collections.** Depends on: 1 (the Saved tab and the add sheet).
   - The `collections` and `collection_items` tables and actions, `fetch_collection_item`, the collection choice in
     the add sheet and share extension, collection tiles in Saved, and the collection page.
   - Key decision: collection items live in their own tables, so no existing query needs a filter.
3. **Takes.** Depends on: 1 (the Takes segment) and M6 merged (FSRS, Review and card rows on the phone).
   - The `takes` and `take_versions` tables and the cards change, `save_take` / `update_take` /
     `restore_take_version`, the `clean_take` and `take_cards` jobs, and the Takes list, take page, version viewer and editor.
   - Key decision: the cards' `source_id` / `artifact_id` become nullable, with the exactly-one check. Review shows
     take cards with a "Your take" kicker instead of a domain.

Migrations are split per piece (`0007_favorites`, `0008_collections`, `0009_takes`), with numbers taken at merge
time if M6 lands one first. The combined schema above is the end state.

## Open questions (defaults chosen)

- **＋ on Today too?** Default: no. Library only, since most saves come from the share sheet.
- **Take dates.** Default: a new version is made only on Save with a changed body. The list shows "Written" (first
  version) until a second version exists, then "Updated".
