# M7: Search and Ask

**Status:** approved in brainstorming on 2026-11-06 (the owner deferred the technical choices). Mocks:
`2026-11-06-m7-search-ask-mocks.html` (screens 01–05). Product background is `2026-10-26-product-scope.md` ("Carl
(chat)") and `2026-11-02-backend-architecture-design.md` ("Search and chat"); where they differ, this spec wins and
those docs are updated when M7 ships. It also supersedes the Saved-and-Takes line "Takes aren't searchable … no Ask":
takes are now indexed, searchable and askable.

## Decisions

- **Search and Ask ship together; edits through chat come later** (the next milestone).
- **Everything the owner owns that has words is indexed**, except collections (which stay out of the learning side):
  - a source's text: article and newsletter text, podcast and video transcripts (passages keep their start time);
  - a source's summary and its primer (Archie's writing about that source);
  - topic primers;
  - takes (current version only).
  Unread inbox items are included. Deleted sources and takes drop out of results.
- **Library search** shows items, each with the one passage that matched best. Online it is the server's merged
  keyword + meaning search; offline it falls back to today's on-phone search (`app/src/library/search.ts`).
- **Ask conversations are saved, listed and synced.** They live on the server, sync to the phone through the normal
  pull, and stay readable offline. Sending needs a connection. A chat can be deleted with a swipe.
- **Labels come from citations, not from the model's own tags.** The chat uses Anthropic search-result content blocks
  for library passages and the server web search tool, so text carries its citations. Citations split the model's
  text into many blocks mid-sentence, so labels are decided **per paragraph** (a run of text blocks up to a blank
  line or a tool call): a paragraph is labelled by any citation inside it. Text written before a tool call ("Let me
  search…") is dropped from the saved answer.
  - a paragraph citing library passages is **your library** (chips naming the item, with a timestamp for audio/video,
    and "Summary" / "Primer" when the passage came from one);
  - a paragraph citing web results (and no library passage) is **web** (link chips);
  - a paragraph with no citations is **background**.
  Consecutive paragraphs with the same label are shown as one labelled section.
- **Make a card** is the only thing an answer turns into: Haiku drafts one card from the answer, the owner edits it
  in a sheet, and Save adds it to Review. The card's origin is the conversation (a fifth card origin).
- **Ask about this** is an entry in the ••• menu of source pages, topic pages (asking about the topic primer) and take
  pages; there is no button on the page itself, and the primer screen gets nothing (its source's menu covers it). It
  starts a chat tied to that item: the item's title, summary and the owner's note go into the system prompt, and that item's passages get a
  boost in search.
- **Whitelisted only for anything that spends keys.** Chat, card drafts and query embeddings use the owner's keys.
  A non-whitelisted account sees an Ask tab that says Ask isn't available on this account; its search is keyword
  only, and its chunks are stored without embeddings.
- **Models:** Sonnet 5.5 (`llm.SONNET`) for chat, without extended thinking so answers start fast; Haiku
  (`llm.HAIKU`) for card drafts. Chat titles aren't generated: a chat's title is its first question, cut to 60
  characters.
- **Embeddings:** OpenAI `text-embedding-3-small` (1536 dimensions), as the architecture doc says, through `httpx`
  like `speech.py`. `OPENAI_API_KEY` is already set on Railway.

## Data (server, migration 0011)

- **`chunks`**: `id` bigint identity; `user_id`; `owner_kind` (`StrEnum ChunkOwner`: `source_text`,
  `source_summary`, `source_primer`, `topic_primer`, `take`); exactly one of `source_id`, `topic_primer_id`,
  `take_id` (check constraint, like cards); `chunk_index`; `text`; `start_seconds` (double, null except transcript
  passages); `embedding vector(1536)` null; `tsv tsvector` generated always from `text` (English config); `created_at`.
  Indexes: HNSW on `embedding` (cosine), GIN on `tsv`, btree on each owner id. Unique (owner kind, owner id,
  chunk_index). Cascades from its owner.
- **`conversations`**: `id` uuid (made on the phone); `user_id`; `title`; `about_kind` + about id columns
  (`about_source_id`, `about_topic_primer_id`, `about_take_id`, all null for a general chat; at most one set);
  `created_at`, `updated_at`, `deleted_at`, `change_seq`.
- **`messages`**: `id` uuid; `conversation_id` (cascade); `role` (`user` / `assistant`); `text` (the user's words, or
  the assistant's plain text for search and copy); `segments` JSONB (assistant only: `[{label, text, citations}]`,
  each citation `{kind: library|web, title, source_id?, topic_primer_id?, take_id?, owner_kind?, start_seconds?, url?,
  quote?}`); `web_search` bool (the toggle as sent); `status` (`complete` / `failed`); `created_at`, `change_seq`.
- **`cards`**: add `conversation_id` (null, cascade on delete) and `message_id`; the origin check becomes
  `num_nonnulls(source_id, topic_primer_id, brief_id, take_id, conversation_id) = 1`.
- **Phone (drizzle 0011)**: `conversations`, `messages`, and the two card columns; pulled like other tables
  (`services/api/archie_api/sync/pull.py`, `rows.py`). Chunks never reach the phone.

## Indexing (worker)

- **`JobKind.EMBED`**, one job per owner (a source, a topic primer or a take). It rebuilds that owner's chunks from
  scratch in one transaction: delete the old ones, cut, embed, insert. Safe to run again.
- **When it is queued:** after `analyze` writes a source's summary; after `primer` writes a source's primer; after a
  topic primer is written; after a take version is saved (raw save, or after `clean_take`). A source that is fetched
  again re-runs analyze, which re-queues embed.
- **Cutting:** about 300 words per passage with a 50-word overlap, breaking at paragraph or sentence ends. Transcript
  passages are built from timed segments and keep the first segment's start. Summaries and primers are cut by their
  markdown sections.
- **Embedding:** batches of up to 100 passages per request, cost recorded in `llm_calls` like other calls
  (`text-embedding-3-small` at $0.02 per million tokens). No owner key (non-whitelisted) → chunks are stored with
  `embedding` null and still serve keyword search.
- **Backfill:** a one-shot command (`archie-worker backfill-embed`) queues an embed job for every live source with
  a summary, every topic primer and every take. It is run once against production after deploy.

## Search (API)

- **`GET /search?q=&limit=20`** (signed in). Steps:
  1. keyword: top 40 chunks by `ts_rank_cd` against `websearch_to_tsquery('english', q)`;
  2. meaning (whitelisted with a key): embed `q`, top 40 chunks by cosine distance;
  3. merge with reciprocal rank fusion (`1 / (60 + rank)`, summed across the two lists);
  4. group by item (source, topic primer, take), keep each item's best chunk, return the top `limit` items.
  Only the owner's live items are searched (a deleted source or take is filtered by a join).
- **Response:** `{results: [{item_kind, item_id, title, passage, owner_kind, start_seconds}]}`. `passage` is the
  chunk text trimmed to about 220 characters around the first matched term (or the chunk start for a meaning-only
  hit).
- The chat's `search_library` tool calls the same function, returning the top 8 chunks (not grouped) with an optional
  boost for the conversation's about item.

## Ask (API)

- **`POST /ask/conversations/{id}/messages`** `{text, web_search, about?}` → a server-sent event stream. The first
  message creates the conversation (title from the text, about item from `about`). The user message is stored first.
  Events: `delta {block, text}` while text streams; `block {block, label, citations}` when a text block ends;
  `searching {kind: library|web, query}` when a tool runs; `done {message_id}`; `error {message}`.
- **The loop:** the system prompt carries the rules (library first, then background, then the web; search the web
  for recent or fast-changing facts or when the toggle is on or the owner says "look it up"; cite every library or
  web claim; short answers in plain language) plus the about item's context. Tools: `search_library` (client tool,
  executed by the server, results returned as `search_result` content blocks so citations attach) and Anthropic's
  web search server tool. The server runs up to 5 tool rounds per message. The previous messages of the conversation
  (last 20) are sent as history, rebuilt from `text` (assistant history without citations).
- **Forcing the web:** with `web_search` on, the system prompt requires a web search before answering. (If the API
  accepts `tool_choice` naming the web search tool, the plan may use that instead.)
- **Saving:** the assistant message is stored when the stream ends, with its segments, and both messages get a new
  `change_seq` so the phone pulls them. A stream that fails midway stores the assistant message with
  `status = failed` and whatever text arrived; the phone shows "Didn't finish. Try again" with a retry that resends
  the same question.
- **`POST /ask/messages/{id}/card-draft`** → `{question, answer}` (Haiku). **`POST /ask/cards`** `{message_id,
  question, answer}` → creates a `concept` card with `conversation_id` and `message_id`, new FSRS state, due now; it
  reaches the phone through pull. **Deleting a chat** is an outbox action (`delete_conversation`), like other phone
  actions.
- Every call is recorded in `llm_calls` (chat steps `ask`, `card_draft`; embeddings `embed`).

## Screens (app)

- **Library search** (mock 01): typing in All's search bar waits 300 ms, then calls `/search`. Results replace the
  list: each row is the usual item row plus a quote under it (the passage, ink2, two lines). Tapping opens the item;
  a transcript hit opens the source page at that time (the existing timestamp handling). Offline, or while the
  request fails, the list keeps today's on-phone matching and shows "Offline · searching titles and notes".
- **Ask tab** (mock 02): title "Ask", a list of chats (title, first line of the last answer, relative time), newest
  first, swipe to delete. A composer pinned above the tab bar starts a new chat. Offline: chats stay readable and the
  composer is disabled with "Ask needs a connection". Non-whitelisted: an empty state saying Ask isn't available on
  this account.
- **Chat screen** (mock 03, `app/src/app/ask/[id].tsx`): the owner's messages right-aligned in a press-coloured
  bubble; answers full width as labelled sections. A section starts with a small label (YOUR LIBRARY / BACKGROUND /
  WEB, in the kicker style) and ends with citation chips. Library chips open the item (at the timestamp when there
  is one); web chips open the link in the browser. While streaming, text appears as it arrives, unlabelled, and a
  "Searching your library…" / "Searching the web…" line shows during tool runs. The composer has a globe toggle for
  "Search the web" and a send button.
- **Under each answer:** "Make a card" (mock 04). It opens a bottom sheet with the drafted question and answer in
  editable fields; Save adds the card and shows a toast "Card added to Review".
- **Ask about this** (mock 05): an "Ask about this" row in the ••• menu (`app/src/item/ItemMenu.tsx` on the source
  page, and the existing menus on the topic and take pages). It opens a new chat screen with an "About: <title>" chip
  above the composer.
- **Review:** a conversation card's kicker reads "FROM ASK" with the about item's domain colour when there is one
  (else Other).

## Testing

- **Python (pytest, Postgres):** cutting (word windows, transcript start times, markdown sections); the embed job
  replacing an owner's chunks; search ranking on fixed chunks with fixed embeddings (keyword only, meaning only, and
  merged; deleted items excluded; grouping keeps the best chunk); the ask stream against recorded Anthropic
  responses (a library-cited answer, a web-cited answer, a failed stream stored as failed); card draft and card
  creation; whitelist checks. OpenAI embedding calls are replayed from cassettes.
- **App (jest):** grouping streamed blocks into labelled sections; citation chip text; the search debounce and
  offline fallback choice; drizzle migration test for 0011.
- **Maestro:** `library_search.yaml` checks a result shows its quote (keyword search needs no keys). A paid
  `ask.yaml` (`make maestro-ask`): finish an article, open Ask, ask about it, see a YOUR LIBRARY section, Make a card,
  see the toast, and the chat listed on the Ask tab.

## Not in M7

- Edits through chat (next milestone).
- Answer quality and tone tuning (the final eval pass).
- Searching collections.
