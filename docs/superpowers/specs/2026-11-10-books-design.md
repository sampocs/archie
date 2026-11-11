# Books

Mocks: `2026-11-10-books-mocks.html` (approved, with one change: a book added as Reading also queues its primer in Up
next). Card rules for books come from workshop rounds with the owner on four of their own book notes (the notes and
the hand-tuned cards stay outside the repo).

## Why

The owner reads non-fiction and wants two things from Archie: a spoiler-free primer when starting a book, and a
refresher plus review cards when finishing it, months later. Books are shared from Goodreads (the main path) or typed
into the + sheet. Separately, three old Google Docs of book notes become finished books once (the bootstrap), with
hand-tuned cards released over a few weeks so they don't land in reviews at once.

## What changes

1. A new source kind, **book**, and a new reading state, **reading**. A book is one item for its whole life:
   added as Reading or Finished, and finishing later moves the same item to Finished.
2. **Adding:** the + sheet treats text that isn't a URL as a book title (Find book); a shared Goodreads book link is a
   book. Archie looks the book up, the owner confirms the match and picks Reading or Finished. There is no "want to
   read": the owner tracks that in Goodreads.
3. **Reading:** a spoiler-free book primer is written and **queued in Up next** right away. The book itself never
   shows on Today or in Up next; it lives in Library under a new **Reading** filter.
4. **Finishing:** "Finished it" on the book page (or sharing the book's Goodreads link again, or adding as Finished)
   takes optional thoughts. Archie researches the book on the web and writes a refresher and cards; the thoughts
   steer both.
5. **Book cards** follow the workshop rule: the model first names the book's kind, which sets the count.
6. **Grader:** a "Name three…" question is got_it when three correct items are named.
7. **Cards can start later:** a card can carry `available_at`; it stays out of reviews until then.
8. **Stored detail allows 4 lines** (the writing rule still asks for at most 3; a fourth comes only from a hand edit).
9. **Bootstrap:** a one-off script imports the three books as Finished, with their notes and hand-tuned cards.

## Data

Alembic `0019_books` and drizzle `0019_books` (journal and `migrations.js` updated together):

| Table | Column | Type | Notes |
|---|---|---|---|
| `sources` | `author` | `String(300)`, nullable | The book's author(s) as one display string. Synced (`SourceOut.author`, app `sources.author`). |
| `cards` | `available_at` | timestamptz, nullable | Not reviewable before this. Synced (`CardOut.available_at`, app `cards.availableAt`). |

Both are nullable with no backfill, so no forced re-pull. Enums (Python `StrEnum`s; the app compares string literals):

- `SourceKind.BOOK = "book"`.
- `SourceState.READING = "reading"`.
- `JobKind.WRITE_BOOK = "write_book"`, `JobKind.BOOK_CARDS = "book_cards"`.

A book's `url` is the Goodreads book URL when it came from Goodreads, else the Open Library work URL
(`https://openlibrary.org/works/OL…W`), else (bootstrap with no match) `book:<slugified title>`. `normalized_url`
dedupes as for links. `image_url` is the cover. `title` is the book's title. `intent` is `finished` for both states
(it is unused for books).

`card_rows.MAX_DETAIL_LINES` becomes 4. `cards.CARD_RULES` is unchanged (0-3 lines).

## Book lookup

`POST /books/lookup` (API, `deps.current_user`; 401 otherwise), body `{query: str}` (1-500 chars), returns
`{title, author, year, cover_url, url}` (`author`, `year`, `cover_url` may be null) or 404 `{"detail": "No book
found"}`. New module `archie_api/books/` (`routes.py`, `lookup.py`).

- **A Goodreads book URL** (host `goodreads.com` after `normalize_url`, path starting `/book/show/`): GET the page
  with `Accept: text/html,application/xhtml+xml`, `Accept-Language: en-US,en;q=0.9` and a browser `User-Agent`
  (Goodreads answers 503 without them; its search page answers a 202 bot challenge, so search never goes there).
  Parse the `application/ld+json` block whose `@type` is `Book`: `name` → title, the first `author[].name` (all
  names joined with ", ") → author, `image` → cover. Year: none in the JSON-LD; leave null. The URL is the canonical
  `og:url` (else the input).
- **Anything else** is a title search: Open Library `GET https://openlibrary.org/search.json?q=<query>&limit=1&
  fields=key,title,author_name,first_publish_year,cover_i`. URL `https://openlibrary.org<key>`, cover
  `https://covers.openlibrary.org/b/id/<cover_i>-L.jpg` when `cover_i` is set.
- 8 s timeout per request; a network failure or non-200 → 502 `{"detail": "Couldn't reach the book lookup"}`.

Tests replay recorded responses (cassettes) for one Goodreads page, one Open Library hit and one miss.

## Adding a book (`add_book` sync action)

The app pushes `add_book` through `POST /sync/push` (registered beside `add_source`; module
`archie_api/sync/book_actions.py`). Payload:

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | client id, as `add_source` |
| `url` | str | http(s), ≤2048 |
| `title` | str | 1-500 |
| `author` | str \| null | ≤300 |
| `image_url` | str \| null | http(s), ≤2048 |
| `state` | `"reading"` \| `"finished"` | |
| `note` | str \| null | ≤2000; the owner's thoughts; only with `finished` |

- **New book:** a `Source(kind=BOOK, processing=PROCESSING)` with the fields above.
  - `reading`: state `READING`; enqueue `PRIMER`; **queue the primer** (`rows.queue_primer`, which sets
    `primer_queue_position` to the top).
  - `finished`: state `CONSUMED`, `note` stored; enqueue `WRITE_BOOK`.
- **Same book already there** (same `normalized_url`, not deleted, same user): store the new row as a merged
  duplicate (as `add_source` does with `merged_into_id`). If the existing book is `READING` and the new state is
  `finished`, finish the existing book exactly as `finish_source` does (below), carrying the note. Otherwise nothing
  else changes.

## Finishing (`finish_source`)

`finish_source` accepts a `BOOK` in state `READING` (it still rejects other non-queued sources). For a book it sets
`CONSUMED`, stores `note` (the thoughts; `reaction` must be null for a book, else reject), sets
`processing=PROCESSING` and enqueues `WRITE_BOOK`. A queued primer stays queued.

## Pipeline

- `steps_after_text` is not used for books (books have no fetched text).
- `required_artifacts` for a book depends on its state: a `READING` book needs `PRIMER`; a `CONSUMED` book needs
  `SUMMARY`. `finish_step` therefore marks a reading book READY when its primer lands and a finished book READY when
  its refresher lands. Give `required_artifacts` the source (or its state) rather than only the kind, and keep the
  other kinds' results unchanged.
- `WRITE_BOOK` max 2 attempts, `BOOK_CARDS` max 2 (as `WRITE_NOTE`).
- `steps_to_retry` for a book: `PRIMER` for a reading book without one, `WRITE_BOOK` for a finished book without a
  summary.

## LLM: web search in worker calls

`llm.complete` gains `tools: Sequence[Mapping[str, Any]] | None = None`, passed through to `messages.create`.
`archie_llm` gets one shared constant `WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search",
"max_uses": 5}`; Ask keeps its own (`max_uses: 3`, `allowed_callers`). The worker reads the final text block(s) of
the response; `record_call` already counts web search requests. If the API rejects `output_config.format` together
with a server tool, `WRITE_BOOK` makes two calls instead: research (tools, plain text, Sonnet) then structure (no
tools, the JSON schema, Haiku, fed the research text). Decide by recording; note which in the handler docstring.

## Book primer (`PRIMER` for a book)

The primer handler branches on `kind == BOOK`: no text artifact is needed; prompt `BOOK_PRIMER_SYSTEM` (version
`book-primer-v1`) with `WEB_SEARCH_TOOL`, models `PRIMER_MODELS`. Input: title, author, today's date. It writes the
usual PRIMER artifact and **no foundation cards** (the book's cards come when it's finished).

`BOOK_PRIMER_SYSTEM` (in the reading voice): a spoiler-free primer for someone about to start the book: who the
author is and why they wrote it; the background the book assumes (the field, the era, the key terms); the questions
the book sets out to answer. Never its conclusions, its twists or how a narrative ends. A 4-6 minute read. Search the
web when the book is not well known to you.

## Refresher (`WRITE_BOOK`)

New handler `handlers/write_book.py`. Input: title, author, today, the owner's thoughts (`source.note`) and, for a
bootstrap book, its notes (`source.note_markdown`). Prompt `BOOK_WRITE_UP_SYSTEM` (version `book-write-up-v1`),
models `NOTE_WRITE_UP_MODELS` (Sonnet, Opus fallback), `WEB_SEARCH_TOOL`, schema `NOTE_WRITE_UP_SCHEMA`.

`BOOK_WRITE_UP_SYSTEM`: a refresher someone who read the book can reread to remember it: what the book argues and
teaches. Research the book on the web (reviews, summaries, author interviews) for its main ideas. When notes are
given, they set the direction (cover what they cover, keep their emphasis, spell out shorthand, fill gaps, correct
what's wrong). The owner's thoughts name what stuck with them: give those ideas weight. Never mention the notes, the
thoughts or the owner; write about the book ("Kahneman argues…"). Output fields as the note write-up: gist (2-4
sentences on what it's about and its central argument), key_ideas (usually 4-10, each with a bolded lead phrase),
numbers, domain, topic, tags, concepts, is_educational.

It writes the SUMMARY artifact (timestamps null) and a TEXT artifact holding the summary text (so search and Ask
index the book), then enqueues `EMBED`, `FILE_TOPIC` and, **only when the book has no live cards**, `BOOK_CARDS`
(bootstrap books arrive with their cards). It finishes the pipeline step as `write_note` does.

## Book cards (`BOOK_CARDS`)

New handler `handlers/book_cards.py`, models Sonnet (Opus fallback; `BOOK_CARDS_MODELS`), prompt
`BOOK_CARDS_SYSTEM` (version `book-cards-v1`), from the workshop:

> You write review cards for a book the user read, so they remember what it teaches. You get the user's notes or
> thoughts on the book (if any) and a refresher of it.
>
> First decide what kind of book it is, in book_kind; that sets how many cards it gets, however long the book or the
> notes are:
> - how_to: a how-to or beginner's guide (to a game, a tool, a process): 4-6 cards.
> - idea: an idea book (one argument or field, told through stories and studies): 6-10 cards.
> - textbook: a dense textbook or reference covering many separate systems or ideas: 10-15 cards.
> Stay inside the range: choose the ideas that matter most. Order the cards from most to least important.
>
> What to card: one card per core idea, never one per fact: its key concepts, how its mechanisms work ("why does X
> cause Y"), and a few rough numbers worth knowing. What the user's thoughts or notes dwell on is a strong candidate
> and comes first; fill with the book's own main ideas. Prefer a contrast between two things ("declarative vs
> imperative") over a card that asks to recite a list. When recognizing the items of a list is itself worth
> remembering, ask for some of them ("Name three…") and give the whole list as the answer. Never card a
> chapter-by-chapter walk-through, an anecdote (who did what, when, where), a name or date that only matters inside
> the book, or a single study's details: a study gets a card only when it is the evidence for one of the book's core
> ideas, and then the card asks what it showed. A number card is a lasting figure about the subject, never a detail
> of one person's story or one experiment.
>
> Each card is of kind concept, mechanism or number, worded from the refresher. Never mention the notes, the
> thoughts, the refresher or the user in a card.
>
> {cards.CARD_RULES}

Schema: `{book_kind: "how_to"|"idea"|"textbook", cards: [...]}` (cards as `NOTE_CARDS_SCHEMA`). The handler caps the
list at 6 / 10 / 15 by kind (`BOOK_CARD_CAPS`), then inserts cards like `note_cards` (source origin,
`artifact_id` = the summary).

## Grader

`GRADE_SYSTEM` gains, after the Numbers paragraph:

> Lists: when the question asks for a number of items ("Name three…"), naming that many correct items from the
> accepted answer is got_it, in any order; fewer correct items is partly.

## Cards that start later

`available_at` (server and app). The app's `review/eligibility.ts` `isReviewable` also requires `availableAt` null or
≤ now, so a waiting card is in no session (due or ahead), no due count and no Today review count. The item page's
cards section still lists it. Card writers leave it null; only the bootstrap sets it.

## Bootstrap

`POST /books/import` (whitelisted users only, like `/notes/write-ups`), body `{books: [BookImportIn]}` (≤10):

| Field | Type |
|---|---|
| `title`, `author` | str, str \| null |
| `url`, `image_url` | str \| null (from a lookup) |
| `notes_markdown` | str (≤200,000) |
| `cards` | `[{kind, question, answer, detail: [str] (≤4), available_at: datetime}]` (≤40) |

Each becomes a `BOOK` source in state `CONSUMED`, `note_markdown` = the notes (the book page shows "See your notes ›"
with the existing original-note sheet), its cards inserted as given, and `WRITE_BOOK` enqueued (spaced 60 s apart as
note write-ups are). `url` falls back to `book:<slug>`. Re-importing the same `normalized_url` is a no-op for that
book (returns it as `skipped`). Response `{created: [id], skipped: [title]}`.

`scripts/import_books.py <file.json>` (house style as `import_bear.py`): reads a local JSON file of books (kept
outside the repo), looks each title up through `/books/lookup` for url and cover (keeps going without a match), and
posts them to `/books/import` with the session key from the environment, as `import_bear.py` does. It prints counts
only, never note text.

## App

- **Kinds and labels:** `kindLabel("book")` → "Book"; `itemBadge("reading")` → "Reading"; library `statusTag`
  gives "Reading" for a reading book; the byline of a book is its author.
- **Library:** a **Reading** filter between Queued and Done (`LibraryFilter` `"reading"`: state `reading`); Done
  includes finished books; All includes everything. Reading books are not queueable (no queue swipe; server
  `_NOT_QUEUEABLE` gains `book`).
- **Today / Up next:** unchanged logic. A reading book is never in it (it isn't `queued`); its queued primer is,
  through `primerQueuePosition`.
- **+ sheet (`add.tsx`):** placeholder "Link or book title"; `keyboardType="default"` (the URL keyboard has no space
  bar), `autoCapitalize="none"`. When the text is not an http(s) URL: the link options hide and the button reads
  **Find book**. It calls `/books/lookup` (online only; offline or a 502 → "Couldn't look that up. Try again when
  you're online."; 404 → "No book found. Check the title."). The match shows as a card (cover, title, author ·
  year), "Not it? Edit the title and search again.", a **Reading | Finished** segmented control (Reading default),
  and under Finished a "What stuck with you? (optional)" box. **Add book** writes an optimistic `kind: "book"` row
  and the `add_book` action (`addBook` in `db/actions.ts`), then closes.
- **Share extension:** a shared Goodreads book link (`goodreads.com/book/show/…`) shows book mode: the match (via
  `/books/lookup`, falling back to the shared title with no cover), the Reading | Finished control and the thoughts
  box, then posts `add_book`. The deep-link fallback carries `book=1`, `title`, `state`, `note`; `share.tsx` calls
  `addBook`.
- **Book page** (`source/[id].tsx` branch for `kind === "book"`):
  - Header: the cover as a 2:3 portrait tile (ArtworkTile gains a portrait shape), kicker (domain once filed) and
    title, byline `author · Book`.
  - Reading: badge "Reading · since <added date>", the primer card (existing `PrimerButton`), a primary **Finished
    it** button, and in Cards "Cards come when you finish the book."
  - Finished it opens the `FinishSheet` in a book variant: title "Finished <title>", the optional thoughts box
    ("What stuck with you?"), no reaction chips or queue-primer option, **Done** → `finishSource` with the note.
  - Finished: badge "Finished <date>", the refresher (`SummarySections`), "Your note" (the thoughts), "Background
    you might need" (the primer) when there is one, "See your notes ›" when `noteMarkdown` is set, and the cards.
  - Processing: the usual processing line while the primer or refresher is being written.

## Error handling

- Lookup failures never block: the + sheet shows the message and keeps the text; the share sheet falls back to the
  shared title.
- `WRITE_BOOK` failing twice leaves the book FAILED with the usual retry (`steps_to_retry`).
- A book's primer failing leaves it FAILED with retry; the queued primer entry shows nothing until it exists (as for
  other queued primers).

## Testing

- API e2e: lookup (Goodreads page, Open Library hit and miss, via cassettes); `add_book` reading (primer queued,
  PRIMER job) and finished (WRITE_BOOK job); duplicate add finishing a reading book; `finish_source` on a reading book;
  `finish_source` rejecting a reaction on a book; `/books/import` (cards with `available_at`, skipped re-import,
  whitelisted only); sync pull carries `author` and `available_at`.
- Worker e2e with recorded Anthropic cassettes: book primer (no foundation cards), `write_book` (summary, text,
  embed/file_topic/book_cards queued; no book_cards when cards exist), `book_cards` (caps by kind).
- Unit: `required_artifacts` by state; the lookup JSON-LD parser on a trimmed fixture; the app's `isReviewable` with
  `availableAt`; library filter `reading`; the + sheet's URL-vs-title rule.
- Maestro `make maestro-books` (spends a few cents: one book primer): + sheet → type a title → Find book → Reading →
  Add book → the book under Library ▸ Reading and its primer in Up next. It uses the live Open Library lookup.

## Build plan

### Chunk A: backend (API, worker, DB, script)

Files: `archie_db/models.py`, migration `0019_books.py`, `archie_db/pipeline.py`, `archie_db/card_rows.py`,
`archie_llm/llm.py` (+ `WEB_SEARCH_TOOL`), `archie_api/books/{__init__,routes,lookup}.py` (+ router mount),
`archie_api/sync/{book_actions,source_actions,actions,schemas}.py`, `archie_api/review/prompts.py`,
`archie_worker/handlers/{primer,write_book,book_cards,__init__}.py`, `archie_worker/prompts.py`,
`scripts/import_books.py`, tests and cassettes.

Produces the wire contract the app uses: `POST /books/lookup`, the `add_book` action, `finish_source` for books,
`SourceOut.author`, `CardOut.available_at`.

Key decisions: `required_artifacts` takes the state; one web-search constant; `book_cards` only when no live cards.

Depends on: none.

### Chunk B: app

Files: `app/drizzle/0019_books.sql` (+ journal, `migrations.js`), `src/db/schema.ts`, `src/sync/engine.ts` (pull
fields), `src/db/actions.ts` (`addBook`, `finishSource` note for books), `src/api` client for lookup, `src/app/add.tsx`,
`src/share/{ShareSheet,submit,resolveShare}.tsx/ts`, `src/app/share.tsx`, `src/app/source/[id].tsx`,
`src/ui/FinishSheet.tsx`, `src/ui/ArtworkTile.tsx`, `src/ui/sourceLabels.ts`, `src/library/{sections,visibility,
LibraryList}.ts(x)`, `src/review/eligibility.ts`, `maestro/books.yaml`, Makefile `maestro-books`, `maestro/README.md`.

Consumes chunk A's contract exactly as written in this spec (field names, action name, response shapes).

Key decisions: book mode is decided by "not an http(s) URL" in the + sheet and by the Goodreads book path in the
share sheet; no "want to read".

Depends on: none (codes against the contract above; the Maestro run happens after both merge).
