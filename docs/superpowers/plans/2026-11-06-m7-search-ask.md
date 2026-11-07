# M7: Search and Ask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Library search that matches by words and by meaning and shows the passage that matched, plus an Ask tab whose saved, synced chats answer from the owner's library (cited), background knowledge and the web, with Make a card and Ask about this.

**Architecture:**
- DB (`0011_search_ask`): `chunks` (server only: passages with a pgvector `embedding` and a generated `tsvector`), and two synced tables, `conversations` and `messages`; `cards` gains `conversation_id` / `message_id` as a fifth origin. A tiny `archie_db/vector.py` column type stands in for the `pgvector` package (no new dependency).
- Search core (`archie_db/search.py`): keyword (`websearch_to_tsquery` + `ts_rank_cd`) and meaning (cosine `<=>`) candidate lists over the owner's live items, merged by reciprocal rank fusion; `best_per_item` for Library, raw chunks for the chat tool. Embeddings come from `archie_llm/embeddings.py` (OpenAI `text-embedding-3-small` over `httpx`, costed in `llm_calls`).
- Worker: `embed` (one job per source / topic primer / take) cuts passages (`archie_worker/chunking.py`) and replaces the item's chunks; queued when a source's text, summary or primer is written, a topic primer is written, or a take version gets its body; `archie-worker backfill-embed` queues everything once.
- API: `GET /search`; `POST /ask/conversations/{id}/messages` streams server-sent events while the server runs the tool loop (library passages go back as `search_result` blocks so citations attach; Anthropic's web search server tool for the web) and stores both messages; `POST /ask/messages/{id}/card-draft` (Haiku) and `POST /ask/cards`; push action `delete_conversation`; `/me` gains `is_whitelisted`.
- App: drizzle `0011_search_ask` and sync of the two tables; Library search calls `/search` (300 ms debounce) with the on-phone search as the offline fallback; the Ask tab (chat list, composer), the chat screen `app/src/app/ask/[id].tsx` (streaming, labelled sections, citation chips, Make a card sheet); "Ask about this" rows in the source, topic and take ••• menus; Review shows conversation cards as "From Ask".

**Tech Stack:** as M6 and Saved-and-Takes (FastAPI, SQLAlchemy/Alembic, Postgres 16/18 with pgvector; `archie-llm` over the Anthropic Python SDK 2.4 (httpx2 inside) and `httpx` for OpenAI; Expo 58 Router, drizzle + expo-sqlite, jest, Maestro, pytest-recording/vcrpy 9). **No new Python or npm packages.** The phone streams with the global `fetch`, which Expo 58 installs from `expo/fetch` (`ReadableStream` bodies work).

**Spec:** `docs/superpowers/specs/2026-11-06-m7-search-ask-design.md` (owner-approved, including the later change that puts Ask about this in the ••• menus). Mocks `2026-11-06-m7-search-ask-mocks.html` screens 01–05; where mocks and spec differ, the spec wins. Background: `2026-10-26-product-scope.md` ("Carl (chat)"), `2026-11-02-backend-architecture-design.md` ("Search and chat"), UX rules `2026-10-29-ux-and-brand-design.md`.

## Global Constraints

- **Python style:** `AGENTS.md` house style (module-qualified imports as the repo does them, e.g. `from archie_db import changes, models, search` then `search.search_chunks(...)`; classes/`typing` by name; full typing with `X | None`; `StrEnum`s for compared strings; dataclasses over tuples of >2; named parameters; guard clauses; blank-line paragraphs past ~8 lines; why-comments; docstrings on public functions/classes; `Decimal` for money).
- **Handler/route contract for outside calls:** never hold a DB transaction across an Anthropic or OpenAI call. Read into locals, `db.commit()`, call, then `changes.lock_user_writes(db, user_id)`, re-read what may have changed, write, commit (as `services/api/archie_api/review/routes.py` and the worker handlers do).
- **Whitelist:** anything that spends keys (chat, card drafts, query embeddings, passage embeddings) runs only for `user.is_whitelisted`. API refusal is `403 {"detail": "needs your own API key"}` (the review routes' wording). A non-whitelisted user's search is keyword only and their chunks are stored with `embedding` null.
- **Models:** chat `llm.SONNET` (`claude-sonnet-5-5`) with `thinking={"type": "between_tools"}` and `output_config={"effort": "medium"}` — **not** `llm.THINKING_DISABLED`, which Sonnet 5.5 rejects with a 400. Card drafts `llm.CARD_DRAFT_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)` through `llm.complete` with a JSON schema. Forced `tool_choice` (`any`/`tool`) is a 400 on Sonnet 5.5: "search the web" is forced by the system prompt only. Web search tool `{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}` (the current type for Sonnet 5.5; its dynamic filtering can add code-execution blocks to the content, which the loop passes back untouched and otherwise ignores).
- **Embeddings:** `llm.EMBEDDING_MODEL = "text-embedding-3-small"`, `models.EMBEDDING_DIMENSIONS = 1536`, batches of ≤100 inputs, $0.02 per million tokens; key `config.Settings().openai_api_key` (no key → no embeddings, never an error).
- **`llm_calls` steps (exact):** `ask` (one row per chat model round, web searches added at $10 per 1,000), `card_draft`, `embed` (one row per embeddings request). Provider `anthropic` or `openai`.
- **Wire shapes (exact, snake_case, shared by server and phone):**
  - Citation: `{"kind": "library", "title": str, "source_id": str|null, "topic_primer_id": str|null, "take_id": str|null, "owner_kind": "source_text"|"source_summary"|"source_primer"|"topic_primer"|"take", "start_seconds": float|null, "quote": str|null}` or `{"kind": "web", "title": str, "url": str, "quote": str|null}`.
  - Segment (one per answer text block, in order): `{"label": "library"|"web"|"background", "text": str, "citations": [Citation]}`. Label rule: any library citation → `library`; else any web citation → `web`; else `background`. Citations in a segment are de-duplicated (library by item + `start_seconds`, web by `url`).
  - SSE events, each `event: <name>\ndata: <json>\n\n`: `delta {"block": int, "text": str}`; `block {"block": int, "label": str, "citations": [Citation]}`; `searching {"kind": "library"|"web", "query": str}`; `done {"message_id": str}`; `error {"message": str}`. `block` numbers count text blocks across the whole answer from 0.
  - `POST /ask/conversations/{conversation_id}/messages` body `{"user_message_id": uuid, "text": str (1–4000 after strip), "web_search": bool, "about": {"kind": "source"|"topic_primer"|"take", "id": uuid} | null}` (`about` is read only when the call creates the conversation).
  - `GET /search?q=<1–200 chars>&limit=<1–50, default 20>` → `{"results": [{"item_kind", "item_id", "title", "passage", "owner_kind", "start_seconds"}]}`.
  - `POST /ask/messages/{message_id}/card-draft` → `{"question": str, "answer": str}`; `POST /ask/cards` `{"message_id", "question" (1–500), "answer" (1–2000)}` → `schemas.CardOut`.
  - Pulled rows: `rows.conversations: [{id, title, about_kind, about_source_id, about_topic_primer_id, about_take_id, created_at, updated_at, deleted_at, change_seq}]`, `rows.messages: [{id, conversation_id, role, text, segments, web_search, status, created_at, change_seq}]`; every card gains `conversation_id`, `message_id`. All optional on the phone (`?? []` / `?? null`).
  - Push action `delete_conversation {id}`; rejection "conversation not found".
- **Chat route:** `app/src/app/ask/[id].tsx`, pushed as `{ pathname: "/ask/[id]", params: { id, q?, web?, aboutKind?, aboutId?, aboutTitle? } }`. `id` is the conversation id (a new chat gets `randomUUID()` from `expo-crypto`); `q` is a first question to send on open (from the Ask tab composer), `web` is `"1"` when its globe was on; `aboutKind` (`source`|`topic_primer`|`take`), `aboutId`, `aboutTitle` start a chat about an item.
- **Migration numbers:** server `0011` (`packages/archie-db/archie_db/migrations/versions/0011_search_ask.py`, revises `0010`); app drizzle `0011_search_ask`, ending with `UPDATE sync_state SET position = 0;`.
- **Cards CHECK:** `models.CARD_ORIGIN_CHECK = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id, conversation_id) = 1"` (constraint `ck_cards_one_origin`, dropped and re-created). `message_id` is informational.
- **Copy (verbatim):** Ask tab title `Ask`; composer placeholder `Ask about anything`; chat composer placeholder `Ask a follow-up`; globe accessibility label `Search the web`; offline composer `Ask needs a connection`; not whitelisted `Ask isn't available on this account`; empty list `Ask a question about anything you've saved.`; section labels `Your library` / `Background` / `Web` (kicker style, which upper-cases); tool lines `Searching your library…` / `Searching the web…`; failed answer `Didn't finish. Try again`; button `Make a card`; sheet title `Make a card`, fields `Question` / `Answer`, placeholder while drafting `Drafting…`, failed draft `Couldn't draft one. Write it yourself.`, button `Save`; toast `Card added to Review`; menu row `Ask about this`; about chip `About: <title>`; Library offline line `Offline · searching titles and notes`; Review kicker label `From Ask`; swipe action `Delete`.
- **testIDs (new):** `search-result-<item_id>`, `search-quote-<item_id>`, `search-offline`; `ask-list`, `ask-row-<id>`, `swipe-delete-chat-<id>`, `ask-composer-input`, `ask-web-toggle`, `ask-send`, `ask-unavailable`, `ask-offline`, `ask-empty`; `chat-screen`, `chat-user-<index>`, `chat-answer-<index>`, `answer-section-<label>`, `answer-chip`, `chat-searching`, `chat-failed`, `chat-retry`, `answer-make-card-<index>`, `chat-about`; `make-card-sheet`, `card-draft-question`, `card-draft-answer`, `card-draft-save`; `menu-ask` (source ••• menu), `topic-menu-ask`, `take-menu-ask`. Existing ones stay (`library-search`, `library-search-empty`, `tab-ask`, `source-more`/`topic-more`/`take-more`, `menu-sheet`, `review-kicker`).
- **Tests:** e2e first; unit tests only for real logic; outside calls are replayed from recorded cassettes, never hand-made response bodies. **Recording a cassette:** delete it, then `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t<N> uv run pytest <test file> --record-mode=once -m postgres` (Anthropic needs `ANTHROPIC_API_KEY`, embeddings need `OPENAI_API_KEY`, both in the repo-root `.env`; only `archie_testing.recording.use_recording_api_key` reads them, only in record mode; a few cents). After recording, `rg -n "sk-ant|sk-proj|x-api-key|anthropic-organization-id|openai-organization|request-id" <cassette>` prints nothing. Anthropic cassettes match on model + the first 60 characters of the system prompt, so **every new system prompt differs from every other prompt in its first 60 characters**; a multi-round chat cassette is replayed with `allow_playback_repeats=False` so its rounds replay in order. Embedding cassettes match on the request's model and exact `input` list (Task 2). App logic tests are `*.test.ts`; pure app logic never imports a native module — keep pure helpers in their own files.
- **Never print secrets** or `.env` values.
- **Branch and worktrees:** branch `m7-ask`, worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/m7-ask`. Foundation tasks (1–3) run there serially. Each parallel-safe task runs in its own worktree from the last foundation commit (`git gtr new m7-t<N> --from-current --yes`, run inside the `m7-ask` worktree), then merges back into `m7-ask`. Never touch the main checkout except where Task 11's coordinator step says so.
- **App packages in worktrees:** a worktree's `app/node_modules` is a symlink to the main checkout's: `ln -sfn /Users/sampocs/Documents/Personal/second-brain/app/node_modules app/node_modules` (once per worktree that runs `npm`/`npx`). Keep it out of git: `grep -qx 'app/node_modules' "$(git rev-parse --git-common-dir)/info/exclude" || echo 'app/node_modules' >> "$(git rev-parse --git-common-dir)/info/exclude"`. No npm installs. **Never run `npx prettier`.**
- **Postgres from a worktree:** the container `second-brain-postgres-1` (`127.0.0.1:5434`, pgvector image) is already up from the main checkout. **Never run `make db-up`, `make db-down`, `make test-db`, `make migrate-local`, `make start-local`, `make reset-local-data` or any `make maestro*` target from a worktree.** Every task uses its own database: `docker exec second-brain-postgres-1 createdb -U archie archie_test_t<N>` (ignore "already exists"), then `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t<N> uv run pytest -m "postgres or not postgres"`.
- **Maestro:** implementers add the testIDs in their task; flows are written in Task 11 and **run only by the coordinator, from the main checkout, against the local backend**. Lessons: one `make maestro` run shares one user's data across flows, so each flow uses text no other flow uses; swipe a `SwipeRow` by screen position; after a sheet's Save wait for it to close (`notVisible: <field id>`); `hideKeyboard` before tapping below the keyboard; the dev test user isn't whitelisted — a flow that needs model output logs in with `openLink: archie://dev/login?whitelisted=1`, spends a few cents and gets its own `make` target outside `make maestro`.
- **Checks before every commit:** Python `make lint` and the relevant tests (command above). App `cd app && npm run typecheck && npx jest`.
- **Commits:** every message ends with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Out of scope:** edits through chat; answer-quality and tone tuning; searching collections; Anthropic server-side refusal fallbacks (see Decision 12); deploying, `railway config apply`, pushing or merging to `main`. The plan ends with `m7-ask` ready for a PR.

## Decisions made while planning

1. **No `pgvector` package.** It is not in `uv.lock`; a 30-line `archie_db.vector.Vector` `UserDefinedType` (`vector(1536)`, list ↔ `'[1,2,3]'` text) does what the ORM needs, and search SQL is written with `sqlalchemy.text` (`CAST(:embedding AS vector)`). Alembic reflects `vector` as an unknown type and skips comparing it, so `test_models_match_the_migrations` still passes.
2. **Sources are indexed as soon as their text is stored**, not only after analyze. Analyze never runs for a non-whitelisted user (it needs the owner's key), so indexing only after the summary would leave that account's keyword search empty and make the free `library_search.yaml` flow impossible. The text step queues `embed`; analyze and primer queue it again so their summary and primer join the index. Queueing skips an item that already has a queued `embed` job.
3. **The summary is JSON, not markdown.** `chunking.summary_markdown` renders it as `## Gist`, `## Key ideas`, `## Numbers` sections, which are then cut "by markdown sections" as the spec says.
4. **Topic primers index the current version only.** Each version is its own `topic_primers` row; the embed job deletes chunks of the topic's other versions and search joins `is_current`. A conversation about a topic primer keeps the version id it started with; the boost resolves to that topic's current primer.
5. **`messages.user_id`** is added (the spec omits it): pull pages filter every table by `user_id`, and it keeps the pull query identical to the others.
6. **Unique chunk keys are three partial unique indexes** (`(source_id, owner_kind, chunk_index) WHERE source_id IS NOT NULL`, same for `topic_primer_id` and `take_id`): a plain unique constraint over nullable owner columns would never fire. They double as the btree indexes on each owner id.
7. **Message ids:** the phone makes the user message id (`user_message_id`), the server makes the assistant's and sends it in `done`. The phone writes no message rows itself: the chat screen shows the in-flight question and streamed answer from memory until the pull brings both rows, then drops the overlay. A failed answer is stored (`status = failed`, the text so far); Try again sends the same text as a new user message. History sent to the model skips failed answers and the question before each.
8. **Deleting a chat** soft-deletes the conversation (its messages stay, hidden through it) and **keeps cards made from it**: the owner made each card on purpose, and Review's Drop removes one. A conversation card is reviewable as soon as it exists.
9. **About context** goes into the system prompt after the fixed rules (so the cassette prefix stays stable): source title, kind, gist and key ideas, and the owner's note; topic primer: topic name and the primer's first 2,000 characters; take: title, kind and body.
10. **Tool rounds:** at most 5 model requests per answer; the 5th is sent with `tool_choice={"type": "none"}` so it must answer. `pause_turn` (web search's own loop) counts as a round and is resumed by re-sending the assistant content. A `refusal` stop stores the answer as failed.
11. **Timestamps:** a passage's `start_seconds` shows as a clock (`31:20`). Tapping a search result or a library chip opens the source page; when it has a time and `item/timestampLink.timestampUrl` gives a player link with `t` (YouTube, Spotify episodes), the chip opens the player at that moment instead (the existing timestamp handling).
12. **No server-side refusal fallbacks** (`fallbacks: "default"` needs the beta client, and its interaction with `between_tools` thinking is unverified); a refusal is a failed answer the owner can retry. Revisit in the eval pass.
13. **`archie-worker backfill-embed`** is a subcommand of the existing `archie-worker` script (`main()` reads `sys.argv`), queueing `embed` for every live source with a current text or summary, every current topic primer of a live topic, and every live take whose current version has a body.
14. **Recording fix:** `archie_testing.recording` treats every `api.openai.com` request as a transcription upload, so an embeddings request could never match. The transcription matcher is narrowed to `/audio/transcriptions` paths and a new matcher compares embeddings requests by `(model, input)`.
15. **Migration 0011 resets the phone's sync position** (new tables and card columns).

---

## File Structure

```
packages/archie-db/archie_db/vector.py                                         Vector column type (T1)
packages/archie-db/archie_db/models.py                                         ChunkOwner, SearchItemKind, MessageRole, MessageStatus, JobKind.EMBED, Chunk, Conversation, Message, Card cols, CHECKs (T1)
packages/archie-db/archie_db/jobs.py                                           ITEM_KIND_KEY, ITEM_ID_KEY, enqueue_embed (T1)
packages/archie-db/archie_db/migrations/versions/0011_search_ask.py            (T1)
packages/archie-db/tests/test_db_migrations.py                                 0011 tests (T1)
conftest.py                                                                    truncate list (T1)
services/api/archie_api/sync/{schemas,pull,actions}.py, sync/conversation_actions.py   pulled rows, delete_conversation (T1)
services/api/archie_api/auth/routes.py                                         /me is_whitelisted (T1)
services/api/archie_api/ask/__init__.py                                        package (T1)
services/api/tests/e2e/test_conversations_e2e.py                               (T1)
packages/archie-db/archie_db/search.py, packages/archie-db/tests/test_search.py           (T2)
packages/archie-llm/archie_llm/{llm,embeddings}.py                             EMBEDDING_MODEL, prices, record_call, record_embedding_call, embed (T2)
packages/archie-llm/tests/test_embeddings_e2e.py (+ cassettes/embeddings_two_texts.yaml)  (T2)
packages/archie-testing/archie_testing/recording.py, packages/archie-testing/tests/test_recording.py   embeddings matcher (T2)
app/src/db/schema.ts, app/drizzle/0011_search_ask.sql (+ meta, journal, migrations.js)    (T3)
app/src/sync/{engine,transport,engine.test}.ts, app/src/db/actions.ts, app/src/db/conversations.test.ts, app/src/auth/session.ts   (T3)
app/src/ask/types.ts, app/src/review/{eligibility,kicker,useReviewData,eligibility.test,kicker.test}.ts   (T3)
services/worker/archie_worker/{chunking,backfill_embed,main}.py, handlers/{__init__,embed,_text,analyze,primer,topic_primer}.py, archie_db/takes.py   (T4)
services/worker/tests/{test_chunking,test_embed_e2e}.py (+ cassettes/embed_article.yaml)    (T4)
services/api/archie_api/search/{__init__,routes}.py, services/api/tests/e2e/test_search_e2e.py (+ cassette)   (T5)
services/api/archie_api/ask/{routes,answer,citations,context,prompts}.py, tests/e2e/test_ask_e2e.py, tests/test_ask_units.py (+ cassettes)   (T6)
services/api/archie_api/ask/{card_routes,card_prompts}.py, tests/e2e/test_ask_cards_e2e.py (+ cassette)   (T7)
services/api/archie_api/main.py                                                router includes (T5, T6, T7 — textual overlap only)
app/src/library/{serverSearch,serverSearch.test,useServerSearch}.ts, app/src/library/SearchResultsView.tsx, LibraryList.tsx   (T8)
app/src/ask/{stream,stream.test,sections,sections.test,api,useAskAvailable,useChats,useChatSession}.ts, app/src/ask/{AnswerView,Composer,MakeCardSheet,ChatRow}.tsx, app/src/app/(tabs)/ask.tsx, app/src/app/ask/[id].tsx, app/src/app/_layout.tsx   (T9)
app/src/ask/openChat.ts, app/src/item/ItemMenu.tsx, app/src/topics/TopicMenu.tsx, app/src/app/topic/[id].tsx, app/src/takes/TakeMenus.tsx   (T10)
maestro/{library_search,ask}.yaml, Makefile, maestro/README.md, docs                       (T11)
```

Overlaps between parallel tasks are textual only: `services/api/archie_api/main.py` (T5, T6, T7 each add one `include_router` line) and `app/src/app/_layout.tsx` (T9 adds the `ask/[id]` screen). Shared helpers both app tasks need (`formatClock`, the citation and segment types) live in Task 3's `app/src/ask/types.ts`. T10 pushes to the route `/ask/[id]` that T9 creates, by pathname only (typed routes are generated only when Metro runs, so a worktree's typecheck accepts it — don't commit `.expo/`); `openChat` (T10) and the chat screen (T9) agree on the route params fixed in Global Constraints (**Chat route**).

## Foundation tasks (run in `m7-ask`, serially)

### Task 1: Server data: models, migration 0011, pull of chats, `delete_conversation`, `/me` whitelisted  (tier: most capable)

**Files:**
- Create: `packages/archie-db/archie_db/vector.py`, `packages/archie-db/archie_db/migrations/versions/0011_search_ask.py`, `services/api/archie_api/sync/conversation_actions.py`, `services/api/archie_api/ask/__init__.py`, `services/api/tests/e2e/test_conversations_e2e.py`
- Modify: `packages/archie-db/archie_db/models.py`, `packages/archie-db/archie_db/jobs.py`, `packages/archie-db/tests/test_db_migrations.py`, `conftest.py` (`_TRUNCATE_TABLES`), `services/api/archie_api/sync/schemas.py`, `services/api/archie_api/sync/pull.py`, `services/api/archie_api/sync/actions.py`, `services/api/archie_api/auth/routes.py`

**Interfaces:**
- Produces:
  - `models.ChunkOwner` (`SOURCE_TEXT="source_text"`, `SOURCE_SUMMARY="source_summary"`, `SOURCE_PRIMER="source_primer"`, `TOPIC_PRIMER="topic_primer"`, `TAKE="take"`), `models.SearchItemKind` (`SOURCE="source"`, `TOPIC_PRIMER="topic_primer"`, `TAKE="take"`), `models.MessageRole` (`USER`, `ASSISTANT`), `models.MessageStatus` (`COMPLETE="complete"`, `FAILED="failed"`), `models.JobKind.EMBED = "embed"`, `models.EMBEDDING_DIMENSIONS = 1536`.
  - `models.Chunk` (`id, user_id, owner_kind, source_id, topic_primer_id, take_id, chunk_index, text, start_seconds, embedding: list[float] | None, tsv, created_at`), `models.Conversation` (`id, user_id, title, about_kind, about_source_id, about_topic_primer_id, about_take_id, created_at, updated_at, deleted_at, change_seq`), `models.Message` (`id, user_id, conversation_id, role, text, segments: list[dict] | None, web_search, status, created_at, change_seq`), `models.Card.conversation_id`, `models.Card.message_id`, `models.CARD_ORIGIN_CHECK` (five origins), `models.CONVERSATION_TITLE_LENGTH = 60`.
  - `archie_db.vector.Vector(dimensions)` and `vector.to_literal(values) -> str`.
  - `jobs.ITEM_KIND_KEY = "item_kind"`, `jobs.ITEM_ID_KEY = "item_id"`, `jobs.enqueue_embed(db, *, user_id: int, item_kind: models.SearchItemKind, item_id: uuid.UUID) -> None`.
  - `changes.touch` is **not** widened; conversations are touched with `conversation.updated_at = func.now(); conversation.change_seq = changes.next_change_seq()` (helper `conversation_actions.touch_conversation(conversation)`, public, reused by Task 6).
  - `schemas.ConversationOut`, `schemas.MessageOut`, `CardOut.conversation_id`, `CardOut.message_id`, `PulledRows.conversations`, `PulledRows.messages`, `schemas.ActionType.DELETE_CONVERSATION`.
  - `/me` returns `is_whitelisted: bool`.
  - The empty package `archie_api.ask` (Tasks 6 and 7 add modules to it).
- Review: yes (migration with a CHECK change and a generated column, sync shapes).

- [ ] **Step 1: Test DB.** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t1` (ignore "already exists"). Tests run with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t1`.

- [ ] **Step 2: Write the failing migration tests.** Append to `packages/archie-db/tests/test_db_migrations.py`:

```python
def test_0011_keeps_cards_allows_a_conversation_origin_and_indexes_chunk_words(test_database_url: str) -> None:
    """A pre-M7 card survives; a card needs exactly one of five origins; `tsv` is generated; embeddings round-trip."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0010")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub, ingest_token) VALUES ('sub', 'token')"))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO sources (id, user_id, url, normalized_url, kind, state, intent, change_seq) "
                "SELECT '00000000-0000-0000-0000-000000000001', id, 'https://example.com/a', "
                "'https://example.com/a', 'article', 'inbox', 'queue', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, kind, question, answer, fsrs_state, reps, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000c1', id, '00000000-0000-0000-0000-000000000001', "
                "'concept', 'Q?', 'A.', 'review', 2, nextval('change_seq') FROM users"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.begin() as connection:
        card = connection.execute(sqlalchemy.text("SELECT fsrs_state, reps, conversation_id FROM cards")).one()
        assert (card.fsrs_state, card.reps, card.conversation_id) == ("review", 2, None)

        connection.execute(
            sqlalchemy.text(
                "INSERT INTO conversations (id, user_id, title, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000a1', id, 'Q', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, conversation_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000a1', 'concept', 'Q?', 'A.', "
                "nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO chunks (user_id, owner_kind, source_id, chunk_index, text) "
                "SELECT id, 'source_text', '00000000-0000-0000-0000-000000000001', 0, "
                "'Stablecoins settle payments without a bank' FROM users"
            )
        )
        matched = connection.execute(
            sqlalchemy.text("SELECT count(*) FROM chunks WHERE tsv @@ websearch_to_tsquery('english', 'stablecoin')")
        ).scalar_one()
        assert matched == 1

    with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, conversation_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-000000000001', "
                "'00000000-0000-0000-0000-0000000000a1', 'concept', 'Q?', 'A.', nextval('change_seq') FROM users"
            )
        )

    with sqlalchemy.orm.Session(engine) as db:
        chunk = db.scalars(sqlalchemy.select(models.Chunk)).one()
        chunk.embedding = [0.5] + [0.0] * (models.EMBEDDING_DIMENSIONS - 1)
        db.commit()
        db.expire_all()
        stored = db.scalars(sqlalchemy.select(models.Chunk)).one().embedding
        assert stored is not None and stored[0] == 0.5 and len(stored) == models.EMBEDDING_DIMENSIONS

    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()
```

Add `import sqlalchemy.orm` to the file's imports if it isn't there.

- [ ] **Step 3: Write the failing API e2e test** `services/api/tests/e2e/test_conversations_e2e.py`:

```python
"""Saved Ask chats through the real API: the phone pulls conversations and messages, and deletes a chat with a push.

Chats are written by the server (the ask route, Task 6); these tests seed them directly. Deleting a chat keeps the
cards made from it.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

SEGMENTS = [{"label": "background", "text": "Reserves are bank money.", "citations": []}]


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _rows(authed: httpx.Client, since: int = 0) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": since}).json()["rows"]


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _seed_chat(live_stack: LiveStack, *, user_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A conversation with one question and one answer, and a card made from the answer."""
    engine = session.engine_for(live_stack.database_url)
    conversation_id, answer_id = uuid.uuid4(), uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(
            models.Conversation(
                id=conversation_id, user_id=user_id, title="How does the Fed create money?",
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        db.add_all(
            [
                models.Message(
                    id=uuid.uuid4(), user_id=user_id, conversation_id=conversation_id,
                    role=models.MessageRole.USER.value, text="How does the Fed create money?", segments=None,
                    web_search=False, status=models.MessageStatus.COMPLETE.value, change_seq=changes.next_change_seq(),
                ),
                models.Message(
                    id=answer_id, user_id=user_id, conversation_id=conversation_id,
                    role=models.MessageRole.ASSISTANT.value, text="Reserves are bank money.", segments=SEGMENTS,
                    web_search=False, status=models.MessageStatus.COMPLETE.value, change_seq=changes.next_change_seq(),
                ),
            ]
        )
        db.flush()
        db.add(
            models.Card(
                id=uuid.uuid4(), user_id=user_id, conversation_id=conversation_id, message_id=answer_id,
                kind=models.CardKind.CONCEPT.value, question="Q?", answer="A.", change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()
    return conversation_id, answer_id


def test_a_pull_carries_the_users_chats_messages_and_conversation_cards(live_stack: LiveStack) -> None:
    """Shapes as the phone stores them; another user sees none of it."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner"))
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger"))
    conversation_id, answer_id = _seed_chat(live_stack, user_id=_user_id(owner))

    rows = _rows(owner)

    [conversation] = rows["conversations"]
    assert conversation["id"] == str(conversation_id)
    assert (conversation["title"], conversation["about_kind"], conversation["deleted_at"]) == (
        "How does the Fed create money?", None, None,
    )
    assert {message["role"] for message in rows["messages"]} == {"user", "assistant"}
    answer = next(message for message in rows["messages"] if message["id"] == str(answer_id))
    assert (answer["segments"], answer["status"], answer["web_search"]) == (SEGMENTS, "complete", False)
    [card] = rows["cards"]
    assert (card["conversation_id"], card["message_id"], card["source_id"]) == (
        str(conversation_id), str(answer_id), None,
    )
    assert _rows(stranger)["conversations"] == []


def test_deleting_a_chat_soft_deletes_it_and_keeps_its_cards(live_stack: LiveStack) -> None:
    """The deleted conversation comes back on the next pull with `deleted_at`; its card stays live."""
    authed = live_stack.authed(live_stack.sign_in())
    conversation_id, _ = _seed_chat(live_stack, user_id=_user_id(authed))
    position = authed.get("/sync/pull", params={"since": 0}).json()["position"]

    [result] = _push(authed, _action("delete_conversation", {"id": str(conversation_id)}))

    assert (result["result"], result["reason"]) == ("applied", None)
    [conversation] = _rows(authed, since=position)["conversations"]
    assert conversation["deleted_at"] is not None
    assert all(card["deleted_at"] is None for card in _rows(authed)["cards"])


def test_deleting_an_unknown_or_someone_elses_chat_is_rejected(live_stack: LiveStack) -> None:
    """Both read as not found, and a malformed payload is malformed."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner"))
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger"))
    conversation_id, _ = _seed_chat(live_stack, user_id=_user_id(owner))

    results = _push(
        stranger,
        _action("delete_conversation", {"id": str(conversation_id)}),
        _action("delete_conversation", {"id": str(uuid.uuid4())}),
        _action("delete_conversation", {"id": "not-a-uuid"}),
    )

    assert [result["reason"] for result in results] == [
        "conversation not found", "conversation not found", "payload is malformed",
    ]


def test_me_says_whether_the_user_is_whitelisted(live_stack: LiveStack) -> None:
    """The Ask tab reads this to show its not-available state."""
    plain = live_stack.authed(live_stack.sign_in(apple_sub="plain"))
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))

    assert (plain.get("/me").json()["is_whitelisted"], owner.get("/me").json()["is_whitelisted"]) == (False, True)
```

(Format with `make format` after pasting; the dense call layout above is for the plan only.)

- [ ] **Step 4: Run both** — `TEST_DATABASE_URL=… uv run pytest packages/archie-db/tests/test_db_migrations.py services/api/tests/e2e/test_conversations_e2e.py -m postgres -v` — FAIL (no revision 0011, no models).

- [ ] **Step 5: The vector type** `packages/archie-db/archie_db/vector.py`:

```python
"""A pgvector `vector(n)` column without the `pgvector` package: lists of floats in, lists of floats out.

psycopg sends the literal as an untyped string, which Postgres casts to `vector` on insert; raw SQL that compares
against a parameter casts it explicitly (`CAST(:embedding AS vector)`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy.types


def to_literal(values: Sequence[float]) -> str:
    """pgvector's text form, e.g. `[0.1,0.2]`."""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def from_literal(text: str) -> list[float]:
    """The floats of pgvector's text form."""
    inner = text.strip().removeprefix("[").removesuffix("]")
    return [float(part) for part in inner.split(",")] if inner else []


class Vector(sqlalchemy.types.UserDefinedType[list[float]]):
    """`vector(dimensions)`; Alembic reflects it as an unknown type and so never reports it as changed."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        """The DDL type."""
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: sqlalchemy.Dialect) -> Callable[[Sequence[float] | None], str | None]:
        """Lists go to the database as pgvector literals."""

        def process(value: Sequence[float] | None) -> str | None:
            return None if value is None else to_literal(value)

        return process

    def result_processor(self, dialect: sqlalchemy.Dialect, coltype: object) -> Callable[[str | None], list[float] | None]:
        """pgvector's text comes back as a list of floats."""

        def process(value: str | None) -> list[float] | None:
            return None if value is None else from_literal(value)

        return process
```

If mypy objects to the processor signatures (SQLAlchemy's stubs type them as `_BindProcessorType[Any]` / `_ResultProcessorType[Any]`), annotate the returns with those names from `sqlalchemy.engine.interfaces` rather than adding ignores.

- [ ] **Step 6: Models.** In `models.py` add, beside the other enums:

```python
class ChunkOwner(StrEnum):
    """What a search passage was cut from: a source's own text, Archie's summary or primer of it, a topic primer, or a take."""

    SOURCE_TEXT = "source_text"
    SOURCE_SUMMARY = "source_summary"
    SOURCE_PRIMER = "source_primer"
    TOPIC_PRIMER = "topic_primer"
    TAKE = "take"


class SearchItemKind(StrEnum):
    """The library items search returns and a chat can be about; each owns its passages."""

    SOURCE = "source"
    TOPIC_PRIMER = "topic_primer"
    TAKE = "take"


class MessageRole(StrEnum):
    """Who wrote a chat message."""

    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    """Whether an answer finished; a failed one keeps the text that arrived."""

    COMPLETE = "complete"
    FAILED = "failed"
```

Add `EMBED = "embed"` to `JobKind`, and near the other constants:

```python
EMBEDDING_DIMENSIONS = 1536
# A chat's title is its first question, cut to this many characters.
CONVERSATION_TITLE_LENGTH = 60
CHUNK_OWNER_CHECK = "num_nonnulls(source_id, topic_primer_id, take_id) = 1"
CONVERSATION_ABOUT_CHECK = "num_nonnulls(about_source_id, about_topic_primer_id, about_take_id) <= 1"
```

Replace the card CHECK and its comment:

```python
# Exactly one origin per card; `take_version_id` and `message_id` only record which version or answer it came from.
CARD_ORIGIN_CHECK = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id, conversation_id) = 1"
```

Add to `Card` (after `take_version_id`) and extend its docstring with "or a chat (a card made from an answer, with `message_id` naming it)":

```python
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("messages.id", ondelete="CASCADE")
    )
```

Add the three tables (after `TakeVersion`; `Card` references them by table name, so order only matters for readability; `from archie_db import vector` at the top, after the sqlalchemy imports — `archie_db.vector` imports nothing from `models`):

```python
class Chunk(Base):
    """One search passage of a live item, with its words indexed for keyword search and (when paid for) an embedding.

    Server only: chunks never reach the phone. `embed` rebuilds an item's chunks from scratch.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        sqlalchemy.CheckConstraint(CHUNK_OWNER_CHECK, name="ck_chunks_one_owner"),
        # Partial, because a unique key over nullable owner columns never fires; they double as the owner lookups.
        sqlalchemy.Index(
            "uq_chunks_source",
            "source_id",
            "owner_kind",
            "chunk_index",
            unique=True,
            postgresql_where=sqlalchemy.text("source_id IS NOT NULL"),
        ),
        sqlalchemy.Index(
            "uq_chunks_topic_primer",
            "topic_primer_id",
            "owner_kind",
            "chunk_index",
            unique=True,
            postgresql_where=sqlalchemy.text("topic_primer_id IS NOT NULL"),
        ),
        sqlalchemy.Index(
            "uq_chunks_take",
            "take_id",
            "owner_kind",
            "chunk_index",
            unique=True,
            postgresql_where=sqlalchemy.text("take_id IS NOT NULL"),
        ),
        sqlalchemy.Index("ix_chunks_user_id", "user_id"),
        sqlalchemy.Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        sqlalchemy.Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    owner_kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="CASCADE")
    )
    topic_primer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topic_primers.id", ondelete="CASCADE")
    )
    take_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(sqlalchemy.Integer)
    text: Mapped[str] = mapped_column(sqlalchemy.Text)
    # Transcript passages only: where the passage's first segment starts, in seconds.
    start_seconds: Mapped[float | None] = mapped_column(sqlalchemy.Double)
    # Null when nobody paid for an embedding (no owner key); the passage still serves keyword search.
    embedding: Mapped[list[float] | None] = mapped_column(vector.Vector(EMBEDDING_DIMENSIONS))
    # Generated by Postgres from `text`; never written. Nullable as Postgres reflects a generated column.
    tsv: Mapped[str | None] = mapped_column(
        postgresql.TSVECTOR, sqlalchemy.Computed("to_tsvector('english', text)", persisted=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class Conversation(Base):
    """A saved Ask chat. The id is made on the phone; the title is the first question, cut to 60 characters.

    At most one `about_*` id is set: the item the chat was started from with Ask about this.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        sqlalchemy.Index("ix_conversations_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.CheckConstraint(CONVERSATION_ABOUT_CHECK, name="ck_conversations_one_about"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(sqlalchemy.String(200))
    # A `SearchItemKind` value naming which `about_*` id is set; null for a general chat.
    about_kind: Mapped[str | None] = mapped_column(sqlalchemy.String(16))
    about_source_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("sources.id", ondelete="SET NULL")
    )
    about_topic_primer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topic_primers.id", ondelete="SET NULL")
    )
    about_take_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class Message(Base):
    """One question or answer in a chat. An answer's `segments` are its text blocks with their labels and citations."""

    __tablename__ = "messages"
    __table_args__ = (
        sqlalchemy.Index("ix_messages_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(sqlalchemy.String(16))
    # The question, or the answer's plain text (all its segments joined) for history and copying.
    text: Mapped[str] = mapped_column(sqlalchemy.Text)
    segments: Mapped[list[dict[str, Any]] | None] = mapped_column(postgresql.JSONB)
    # The globe toggle as the question was sent.
    web_search: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    status: Mapped[str] = mapped_column(sqlalchemy.String(16))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)
```

Note `Card` is declared above `Conversation`/`Message` in the file; the string FK targets resolve at mapper configuration, so that is fine.

- [ ] **Step 7: Migration** `packages/archie-db/archie_db/migrations/versions/0011_search_ask.py`:

```python
"""Search and Ask: search passages (chunks), saved chats and their messages, and chat cards as a fifth card origin.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

from archie_db import vector

revision = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)
_FOUR_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id) = 1"
_FIVE_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id, conversation_id) = 1"
_EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    """Create `chunks`, `conversations` and `messages`, add the cards' chat columns, and widen the one-origin CHECK."""
    _create_chunks()
    _create_conversations()
    _create_messages()

    op.add_column("cards", sqlalchemy.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "cards_conversation_id_fkey", "cards", "conversations", ["conversation_id"], ["id"], ondelete="CASCADE"
    )
    op.add_column("cards", sqlalchemy.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("cards_message_id_fkey", "cards", "messages", ["message_id"], ["id"], ondelete="CASCADE")

    # Existing cards have exactly one of the first four origins, so they satisfy the wider check as they are.
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.create_check_constraint("ck_cards_one_origin", "cards", _FIVE_ORIGINS)


def _owner_column(name: str, table: str) -> sqlalchemy.Column[object]:
    return sqlalchemy.Column(
        name, postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=True
    )


def _create_chunks() -> None:
    op.create_table(
        "chunks",
        sqlalchemy.Column("id", sqlalchemy.BigInteger(), sqlalchemy.Identity(), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("owner_kind", sqlalchemy.String(16), nullable=False),
        _owner_column("source_id", "sources"),
        _owner_column("topic_primer_id", "topic_primers"),
        _owner_column("take_id", "takes"),
        sqlalchemy.Column("chunk_index", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("text", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("start_seconds", sqlalchemy.Double(), nullable=True),
        sqlalchemy.Column("embedding", vector.Vector(_EMBEDDING_DIMENSIONS), nullable=True),
        sqlalchemy.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sqlalchemy.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.CheckConstraint("num_nonnulls(source_id, topic_primer_id, take_id) = 1", name="ck_chunks_one_owner"),
    )
    for name, column in (
        ("uq_chunks_source", "source_id"),
        ("uq_chunks_topic_primer", "topic_primer_id"),
        ("uq_chunks_take", "take_id"),
    ):
        op.create_index(
            name,
            "chunks",
            [column, "owner_kind", "chunk_index"],
            unique=True,
            postgresql_where=sqlalchemy.text(f"{column} IS NOT NULL"),
        )
    op.create_index("ix_chunks_user_id", "chunks", ["user_id"])
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")


def _create_conversations() -> None:
    op.create_table(
        "conversations",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("title", sqlalchemy.String(200), nullable=False),
        sqlalchemy.Column("about_kind", sqlalchemy.String(16), nullable=True),
        sqlalchemy.Column(
            "about_source_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column(
            "about_topic_primer_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("topic_primers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column(
            "about_take_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("takes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.CheckConstraint(
            "num_nonnulls(about_source_id, about_topic_primer_id, about_take_id) <= 1", name="ck_conversations_one_about"
        ),
    )
    op.create_index("ix_conversations_user_id_change_seq", "conversations", ["user_id", "change_seq"])


def _create_messages() -> None:
    op.create_table(
        "messages",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("role", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("text", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("segments", postgresql.JSONB(), nullable=True),
        sqlalchemy.Column("web_search", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_messages_user_id_change_seq", "messages", ["user_id", "change_seq"])
    op.create_index("ix_messages_conversation_id_created_at", "messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    """Undo `upgrade`; chat cards go first so the four-origin CHECK holds again, then the three tables."""
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.execute("DELETE FROM cards WHERE conversation_id IS NOT NULL")
    op.drop_constraint("cards_message_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "message_id")
    op.drop_constraint("cards_conversation_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "conversation_id")
    op.create_check_constraint("ck_cards_one_origin", "cards", _FOUR_ORIGINS)

    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("chunks")
```

`test_models_match_the_migrations` must pass unchanged. If autogenerate reports a difference: a `Computed` mismatch only warns (it is not a diff); an index difference means the model's `sqlalchemy.Index` kwargs and the migration's `op.create_index` kwargs differ — make them identical. Never weaken the test. If the `vector` type itself shows as a diff, report it (Decision 1 assumed Alembic skips the unknown reflected type) instead of working around it.

- [ ] **Step 8: Jobs.** In `jobs.py` add `import uuid` and:

```python
# An `embed` job's payload keys: which kind of item (a `SearchItemKind`) and its id.
ITEM_KIND_KEY = "item_kind"
ITEM_ID_KEY = "item_id"


def enqueue_embed(
    db: sqlalchemy.orm.Session, *, user_id: int, item_kind: models.SearchItemKind, item_id: uuid.UUID
) -> None:
    """Queue `embed` for one item, unless one is already waiting: the job reads the item when it runs, so one is enough.

    A source's text, summary and primer are often written within seconds of each other.
    """
    waiting = db.scalar(
        sqlalchemy.select(
            sqlalchemy.exists().where(
                models.Job.kind == models.JobKind.EMBED.value,
                models.Job.status == models.JobStatus.QUEUED.value,
                models.Job.payload[ITEM_ID_KEY].astext == str(item_id),
            )
        )
    )
    if waiting:
        return

    enqueue(
        db,
        kind=models.JobKind.EMBED,
        user_id=user_id,
        payload={ITEM_KIND_KEY: item_kind.value, ITEM_ID_KEY: str(item_id)},
    )
```

Nothing calls it yet (Task 4 adds the call sites and the handler).

- [ ] **Step 9: Truncate list.** In `conftest.py` `_TRUNCATE_TABLES`, add `"chunks"`, `"messages"`, `"conversations"` before `"cards"`.

- [ ] **Step 10: Sync shapes.** In `schemas.py`: add `DELETE_CONVERSATION = "delete_conversation"` to `ActionType` (above the `SET_PREP_ME` comment); add `conversation_id: uuid.UUID | None` and `message_id: uuid.UUID | None` to `CardOut` after `take_version_id`; add

```python
class ConversationOut(pydantic.BaseModel):
    """A saved Ask chat as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    about_kind: str | None
    about_source_id: uuid.UUID | None
    about_topic_primer_id: uuid.UUID | None
    about_take_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class MessageOut(pydantic.BaseModel):
    """One chat message as the phone stores it; `segments` is null for a question."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    text: str
    segments: list[dict[str, Any]] | None
    web_search: bool
    status: str
    created_at: datetime.datetime
    change_seq: int
```

and `conversations: list[ConversationOut]`, `messages: list[MessageOut]` on `PulledRows`. In `pull.py`: `PulledTable.CONVERSATIONS = "conversations"`, `PulledTable.MESSAGES = "messages"`; two more `_changed_rows` entries (add both models to the `RowT` constraint tuple); the two lists in `PulledRows(...)`; the docstring's "ten synced tables" becomes "twelve".

- [ ] **Step 11: The action** `services/api/archie_api/sync/conversation_actions.py`:

```python
"""Push actions on saved Ask chats: only deleting one; chats themselves are written by the ask route."""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import changes, models
from sqlalchemy import orm

from archie_api.sync import rows

NO_CONVERSATION = "conversation not found"


class _DeleteConversationPayload(pydantic.BaseModel):
    id: uuid.UUID


def touch_conversation(conversation: models.Conversation) -> None:
    """Mark a changed chat so phones pull it again. Call only after `lock_user_writes` in the same transaction."""
    conversation.updated_at = sqlalchemy.func.now()
    conversation.change_seq = changes.next_change_seq()


def owned_conversation(db: orm.Session, *, user: models.User, conversation_id: uuid.UUID) -> models.Conversation | None:
    """The user's live chat with this id, or None (unknown, another user's, or deleted)."""
    conversation = db.get(models.Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id or conversation.deleted_at is not None:
        return None
    return conversation


def delete_conversation(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Soft-delete a chat; its messages stay (hidden through it) and cards made from it stay in Review."""
    parsed = rows.parse(_DeleteConversationPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    conversation = owned_conversation(db, user=user, conversation_id=parsed.id)
    if conversation is None:
        return NO_CONVERSATION

    conversation.deleted_at = sqlalchemy.func.now()
    touch_conversation(conversation)
    return None
```

Register it in `actions.HANDLERS` under a `# Ask` comment: `schemas.ActionType.DELETE_CONVERSATION: conversation_actions.delete_conversation` (and import the module).

- [ ] **Step 12: `/me`.** In `services/api/archie_api/auth/routes.py`, `MeView` gains `is_whitelisted: bool` (docstring: "whether the owner's keys pay for this user's Ask and meaning search") and `me()` passes `is_whitelisted=user.is_whitelisted`.

- [ ] **Step 13: The Ask package.** `services/api/archie_api/ask/__init__.py` containing only `"""Ask: saved chats over the owner's library, with labelled, cited answers."""`.

- [ ] **Step 14: Run** `make lint` and `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t1 uv run pytest -m "postgres or not postgres"` — all pass, including `test_models_match_the_migrations`, `test_downgrade_then_upgrade_round_trips` and `test_every_action_type_has_a_handler`. If a pre-existing pull test compares the full `rows` dict or a full card dict, add `"conversations": [], "messages": []` / `"conversation_id": None, "message_id": None` to its expectation (the only allowed change to an existing test).

- [ ] **Step 15: Commit.**

```bash
git add packages/archie-db conftest.py services/api/archie_api services/api/tests/e2e/test_conversations_e2e.py
git commit -m "Server: chunks, conversations and messages (migration 0011), chat cards, delete_conversation, /me whitelisted

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Search core, the embeddings client and its recording  (tier: most capable)

**Files:**
- Create: `packages/archie-db/archie_db/search.py`, `packages/archie-db/tests/test_search.py`, `packages/archie-llm/archie_llm/embeddings.py`, `packages/archie-llm/tests/test_embeddings_e2e.py`, `packages/archie-llm/tests/cassettes/embeddings_two_texts.yaml` (recorded)
- Modify: `packages/archie-llm/archie_llm/llm.py`, `packages/archie-testing/archie_testing/recording.py`, `packages/archie-testing/tests/test_recording.py`

**Interfaces:**
- Consumes (Task 1): `models.Chunk`, `models.ChunkOwner`, `models.SearchItemKind`, `models.EMBEDDING_DIMENSIONS`, `vector.to_literal`.
- Produces:
  - `archie_db.search`: `ItemRef(kind: models.SearchItemKind, id: uuid.UUID)` (frozen dataclass, hashable); `ChunkHit(chunk_id: int, item: ItemRef, title: str, owner_kind: models.ChunkOwner, text: str, start_seconds: float | None, score: float, keyword_match: bool)`; `search_chunks(db, *, user_id: int, query: str, query_embedding: Sequence[float] | None, limit: int, boost: ItemRef | None = None, match_any: bool = False) -> list[ChunkHit]` (best first; `match_any` ORs the query's words — the chat tool's model-written queries need recall, Library search keeps every word required); `best_per_item(hits: Sequence[ChunkHit], *, limit: int) -> list[ChunkHit]`; `passage(text: str, *, query: str, keyword_match: bool) -> str`; constants `KEYWORD_CANDIDATES = 40`, `MEANING_CANDIDATES = 40`, `RRF_K = 60`, `PASSAGE_CHARACTERS = 220`.
  - `archie_llm.llm`: `EMBEDDING_MODEL = "text-embedding-3-small"`, `EMBED_STEP = "embed"`, `ASK_STEP = "ask"`, `CARD_DRAFT_STEP = "card_draft"`, `OPENAI_PROVIDER = "openai"`, `CARD_DRAFT_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)`, `WEB_SEARCH_USD = Decimal("0.01")`, `record_call(engine, *, context, model, response: anthropic.types.Message) -> None` (public; adds web searches), `record_embedding_call(engine, *, context, tokens: int) -> None`.
  - `archie_llm.embeddings`: `OPENAI_EMBEDDINGS_URL`, `MAX_BATCH = 100`, `embed(engine, *, api_key: str, context: llm.CallContext, texts: Sequence[str], timeout_seconds: float = 60) -> list[list[float]]`, `class EmbeddingError(Exception)`. Raises `httpx.HTTPError` (incl. `HTTPStatusError` for non-2xx) or `EmbeddingError`.
  - Recording: embeddings requests replay by `(model, input)`.
- Review: yes (search SQL over every item kind, liveness filters, cost records).

- [ ] **Step 1: Test DB** `archie_test_t2`.

- [ ] **Step 2: Failing recording tests.** Append to `packages/archie-testing/tests/test_recording.py`:

```python
EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


def _embeddings_request(texts: list[str], model: str = "text-embedding-3-small") -> vcr_request.Request:
    body = json.dumps({"model": model, "input": texts}).encode()
    return vcr_request.Request("POST", EMBEDDINGS_URL, body, {"content-type": "application/json"})


def test_embeddings_requests_match_on_model_and_inputs() -> None:
    """Same inputs replay; different inputs or model don't; the transcription matcher leaves them alone."""
    recorded = _embeddings_request(["a", "b"])

    assert recording._embeddings_match(recorded, _embeddings_request(["a", "b"]))
    assert not recording._embeddings_match(recorded, _embeddings_request(["a"]))
    assert not recording._embeddings_match(recorded, _embeddings_request(["a", "b"], model="other"))
    assert recording._transcription_chunks_match(recorded, _embeddings_request(["zzz"]))
```

(add `import json`). Run `uv run pytest packages/archie-testing/tests/test_recording.py -v` — FAIL (`_embeddings_match` missing; the last assert fails because `api.openai.com` is treated as a transcription host).

- [ ] **Step 3: Recording change.** In `recording.py`:
  - `TRANSCRIPTION_PATH_SUFFIX = "/audio/transcriptions"`, `EMBEDDINGS_PATH_SUFFIX = "/embeddings"`, `_EMBEDDINGS_MATCHER = "openai_embeddings"`.
  - `_is_transcription(request) -> bool`: `request.host in TRANSCRIPTION_HOSTS and request.path.endswith(TRANSCRIPTION_PATH_SUFFIX)`; use it in `_strip_audio_upload` (instead of the host check) and in `_transcription_chunks_match` (`if not _is_transcription(recorded) and not _is_transcription(incoming): return True`).
  - New matcher, registered in `vcr_for` and appended to `match_on`:

```python
def _embeddings_match(recorded: vcr_request.Request, incoming: vcr_request.Request) -> bool:
    """OpenAI embeddings requests match on model and the exact inputs; every other request matches here."""
    if not (_is_embeddings(recorded) and _is_embeddings(incoming)):
        return True
    return _embeddings_identity(recorded) == _embeddings_identity(incoming)


def _is_embeddings(request: vcr_request.Request) -> bool:
    return request.host == OPENAI_HOST and request.path.endswith(EMBEDDINGS_PATH_SUFFIX)


def _embeddings_identity(request: vcr_request.Request) -> tuple[str, list[str]]:
    body = json.loads(request.body or b"{}")
    return str(body.get("model", "")), list(body.get("input", []))
```

  with `OPENAI_HOST = "api.openai.com"`. Update the module's comments to say embeddings replay by inputs. Run the recording tests — PASS (all of them, old ones too).

- [ ] **Step 4: `llm.py` additions.** Constants listed in Interfaces; `_PRICES[EMBEDDING_MODEL] = _Price(input_per_million=Decimal("0.02"), output_per_million=Decimal("0"))`; rename `_record_call` to public `record_call` (update the call in `complete`) and add web searches to its cost:

```python
def record_call(
    engine: sqlalchemy.Engine, *, context: CallContext, model: str, response: anthropic.types.Message
) -> None:
    """Record one answered call in its own session, so the spend is kept even if the step fails afterwards.

    Web searches the call ran (Anthropic's server tool) are added at `WEB_SEARCH_USD` each.
    """
    usage = response.usage
    searches = usage.server_tool_use.web_search_requests if usage.server_tool_use is not None else 0
    token_cost = cost_usd(model=model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
    row = models.LlmCall(
        user_id=context.user_id,
        source_id=context.source_id,
        job_id=context.job_id,
        step=str(context.step),
        provider=PROVIDER,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=token_cost + WEB_SEARCH_USD * searches,
        stop_reason=response.stop_reason,
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.add(row)
        db.commit()


def record_embedding_call(engine: sqlalchemy.Engine, *, context: CallContext, tokens: int) -> None:
    """Record one OpenAI embeddings request, billed by its input tokens."""
    row = models.LlmCall(
        user_id=context.user_id,
        source_id=context.source_id,
        job_id=context.job_id,
        step=str(context.step),
        provider=OPENAI_PROVIDER,
        model=EMBEDDING_MODEL,
        input_tokens=tokens,
        output_tokens=0,
        cost_usd=cost_usd(model=EMBEDDING_MODEL, input_tokens=tokens, output_tokens=0),
        stop_reason=None,
    )
    with sqlalchemy.orm.Session(engine) as db:
        db.add(row)
        db.commit()
```

- [ ] **Step 5: Failing embeddings e2e test** `packages/archie-llm/tests/test_embeddings_e2e.py`:

```python
"""OpenAI embeddings against a recorded real response: one vector per text, in order, with the request's cost recorded.

Re-record `embeddings_two_texts` by deleting it and running
`uv run pytest packages/archie-llm/tests/test_embeddings_e2e.py --record-mode=once -m postgres` with
`TEST_DATABASE_URL` set (a tiny fraction of a cent; needs OPENAI_API_KEY in the repo root .env).
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import models, session
from archie_llm import embeddings, llm
from archie_shared import config
from archie_testing import recording

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
TEXTS = ["The Fed creates reserves when it buys bonds.", "Stablecoins settle payments without a bank."]


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real OpenAI key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch, env_names=(config.OPENAI_API_KEY_ENV,))


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


def test_two_texts_get_two_1536_dimension_vectors_and_one_costed_record(
    engine: sqlalchemy.Engine, request: pytest.FixtureRequest
) -> None:
    """Different texts get different vectors; the call is one `embed` row billed by its input tokens."""
    user_id = _add_user(engine)
    context = llm.CallContext(user_id=user_id, source_id=None, job_id=None, step=llm.EMBED_STEP)
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)

    with recorder.use_cassette("embeddings_two_texts.yaml"):
        vectors = embeddings.embed(
            engine, api_key=config.Settings().openai_api_key or "", context=context, texts=TEXTS
        )

    assert [len(vector) for vector in vectors] == [models.EMBEDDING_DIMENSIONS] * 2
    assert vectors[0] != vectors[1]
    with sqlalchemy.orm.Session(engine) as db:
        [call] = db.scalars(sqlalchemy.select(models.LlmCall)).all()
    assert (call.step, call.provider, call.model, call.output_tokens) == ("embed", "openai", llm.EMBEDDING_MODEL, 0)
    assert call.input_tokens > 0
    assert call.cost_usd > 0


def _add_user(engine: sqlalchemy.Engine) -> int:
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub="embed-user", is_whitelisted=True)
        db.add(user)
        db.commit()
        return user.id
```

Run it — FAIL (`archie_llm.embeddings` missing).

- [ ] **Step 6: Embeddings client** `packages/archie-llm/archie_llm/embeddings.py`:

```python
"""Text embeddings from OpenAI's `text-embedding-3-small`, shared by the worker (passages) and the API (queries).

Each request is recorded in `llm_calls`. Failures are raised for the caller to retry or fall back on: `httpx.HTTPError`
for a connection failure or a non-2xx answer, `EmbeddingError` for a 2xx body that isn't one vector per text.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import sqlalchemy
from archie_db import models

from archie_llm import llm

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
# OpenAI takes up to 2,048 inputs per request; 100 keeps each request small and its retry cheap.
MAX_BATCH = 100
TIMEOUT_SECONDS = 60


class EmbeddingError(Exception):
    """OpenAI answered with a body that isn't one 1536-dimension vector per input."""


def embed(
    engine: sqlalchemy.Engine,
    *,
    api_key: str,
    context: llm.CallContext,
    texts: Sequence[str],
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> list[list[float]]:
    """One vector per text, in order, in batches of up to `MAX_BATCH` texts per request."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_BATCH):
        batch = texts[start : start + MAX_BATCH]
        vectors.extend(
            _embed_batch(engine, api_key=api_key, context=context, texts=batch, timeout_seconds=timeout_seconds)
        )
    return vectors


def _embed_batch(
    engine: sqlalchemy.Engine,
    *,
    api_key: str,
    context: llm.CallContext,
    texts: Sequence[str],
    timeout_seconds: float,
) -> list[list[float]]:
    response = httpx.post(
        OPENAI_EMBEDDINGS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": llm.EMBEDDING_MODEL, "input": list(texts)},
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    body = response.json()
    vectors = _vectors_of(body, count=len(texts))
    # Recorded once the answer is known to be usable; a malformed answer is the provider's failure, not spend we keep.
    llm.record_embedding_call(engine, context=context, tokens=int(body["usage"]["prompt_tokens"]))
    return vectors


def _vectors_of(body: Any, *, count: int) -> list[list[float]]:
    try:
        ordered = sorted(body["data"], key=lambda item: item["index"])
        vectors = [[float(value) for value in item["embedding"]] for item in ordered]
        int(body["usage"]["prompt_tokens"])
    except (KeyError, TypeError, ValueError) as error:
        raise EmbeddingError(f"embeddings answer was malformed: {error!r}") from error

    if len(vectors) != count or any(len(vector) != models.EMBEDDING_DIMENSIONS for vector in vectors):
        raise EmbeddingError(f"expected {count} vectors of {models.EMBEDDING_DIMENSIONS}")
    return vectors
```

- [ ] **Step 7: Record and replay.** Record `embeddings_two_texts` (Global Constraints' rule with `archie_test_t2`; needs `OPENAI_API_KEY`), run the secret grep on it, then run the file in replay mode — PASS.

- [ ] **Step 8: Failing search tests** `packages/archie-db/tests/test_search.py`:

```python
"""Search ranking on fixed chunks with fixed embeddings: keyword, meaning, merged, liveness and the about boost.

Embeddings are unit vectors along one axis each, so cosine distance picks exactly one chunk per query vector.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, search, session

pytestmark = pytest.mark.postgres


def _axis(index: int) -> list[float]:
    vector = [0.0] * models.EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session on the migrated test database."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as database:
        yield database
    engine.dispose()


def _user(db: sqlalchemy.orm.Session, sub: str = "searcher") -> int:
    user = models.User(apple_sub=sub)
    db.add(user)
    db.flush()
    return user.id


def _source(db: sqlalchemy.orm.Session, *, user_id: int, title: str, deleted: bool = False) -> models.Source:
    changes.lock_user_writes(db, user_id)
    url = f"https://example.com/{uuid.uuid4()}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user_id,
        url=url,
        normalized_url=url,
        title=title,
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.INBOX.value,
        intent=models.SourceIntent.QUEUE.value,
        deleted_at=sqlalchemy.func.now() if deleted else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    return source


def _take(db: sqlalchemy.orm.Session, *, user_id: int, title: str, deleted: bool = False) -> models.Take:
    take = models.Take(
        id=uuid.uuid4(),
        user_id=user_id,
        kind=models.TakeKind.OPINION.value,
        title=title,
        current_version=1,
        deleted_at=sqlalchemy.func.now() if deleted else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(take)
    db.flush()
    return take


def _topic_primer(db: sqlalchemy.orm.Session, *, user_id: int, name: str, current: bool) -> models.TopicPrimer:
    topic = models.Topic(
        id=uuid.uuid4(),
        user_id=user_id,
        domain="Macro",
        name=name,
        origin=models.TopicOrigin.USER.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(topic)
    db.flush()
    primer = models.TopicPrimer(
        id=uuid.uuid4(),
        user_id=user_id,
        topic_id=topic.id,
        version=1,
        is_current=current,
        content={"markdown": ""},
        change_seq=changes.next_change_seq(),
    )
    db.add(primer)
    db.flush()
    return primer


def _chunk(
    db: sqlalchemy.orm.Session,
    *,
    owner: models.Source | models.Take | models.TopicPrimer,
    text: str,
    index: int = 0,
    embedding: list[float] | None = None,
    owner_kind: models.ChunkOwner | None = None,
) -> models.Chunk:
    columns = {
        models.Source: ("source_id", models.ChunkOwner.SOURCE_TEXT),
        models.Take: ("take_id", models.ChunkOwner.TAKE),
        models.TopicPrimer: ("topic_primer_id", models.ChunkOwner.TOPIC_PRIMER),
    }
    column, default_kind = columns[type(owner)]
    chunk = models.Chunk(
        user_id=owner.user_id,
        owner_kind=(owner_kind or default_kind).value,
        chunk_index=index,
        text=text,
        embedding=embedding,
        **{column: owner.id},
    )
    db.add(chunk)
    db.flush()
    return chunk


def test_keyword_search_finds_stemmed_words_and_skips_deleted_items(db: sqlalchemy.orm.Session) -> None:
    """'stablecoin' finds 'Stablecoins'; a deleted source and a deleted take never come back."""
    user_id = _user(db)
    live = _source(db, user_id=user_id, title="Payments")
    gone = _source(db, user_id=user_id, title="Gone", deleted=True)
    dead_take = _take(db, user_id=user_id, title="Old take", deleted=True)
    _chunk(db, owner=live, text="Stablecoins settle payments without a bank in the middle.")
    _chunk(db, owner=gone, text="Stablecoins were in this deleted article.")
    _chunk(db, owner=dead_take, text="Stablecoins are my deleted opinion.")

    hits = search.search_chunks(db, user_id=user_id, query="stablecoin", query_embedding=None, limit=10)

    assert [(hit.item.id, hit.title, hit.keyword_match) for hit in hits] == [(live.id, "Payments", True)]


def test_meaning_search_ranks_by_cosine_distance(db: sqlalchemy.orm.Session) -> None:
    """With no shared words, the chunk whose embedding points the query's way comes first."""
    user_id = _user(db)
    near = _source(db, user_id=user_id, title="Near")
    far = _source(db, user_id=user_id, title="Far")
    _chunk(db, owner=near, text="Reserves at the central bank.", embedding=_axis(1))
    _chunk(db, owner=far, text="Football results.", embedding=_axis(2))

    hits = search.search_chunks(db, user_id=user_id, query="zzqx", query_embedding=_axis(1), limit=10)

    assert [hit.title for hit in hits] == ["Near", "Far"]
    assert not hits[0].keyword_match


def test_a_chunk_found_both_ways_outranks_one_found_once(db: sqlalchemy.orm.Session) -> None:
    """Rank fusion sums 1/(60+rank) over both lists."""
    user_id = _user(db)
    both = _source(db, user_id=user_id, title="Both")
    words_only = _source(db, user_id=user_id, title="Words")
    meaning_only = _source(db, user_id=user_id, title="Meaning")
    _chunk(db, owner=words_only, text="Money printing and money printing again.")
    _chunk(db, owner=both, text="Money printing is a loose phrase.", embedding=_axis(3))
    _chunk(db, owner=meaning_only, text="Reserves are created by asset purchases.", embedding=_axis(4))

    hits = search.search_chunks(db, user_id=user_id, query="money printing", query_embedding=_axis(3), limit=10)

    assert hits[0].title == "Both"
    assert {hit.title for hit in hits} == {"Both", "Words", "Meaning"}


def test_best_per_item_keeps_each_items_best_chunk(db: sqlalchemy.orm.Session) -> None:
    """Two matching chunks of one source make one result, the better-ranked one."""
    user_id = _user(db)
    source = _source(db, user_id=user_id, title="Fed")
    best = _chunk(db, owner=source, index=0, text="Quantitative easing. Quantitative easing. Quantitative easing.")
    _chunk(db, owner=source, index=1, text="A passing mention of quantitative easing.")

    hits = search.search_chunks(db, user_id=user_id, query="quantitative easing", query_embedding=None, limit=80)
    grouped = search.best_per_item(hits, limit=20)

    assert [hit.chunk_id for hit in grouped] == [best.id]


def test_only_current_topic_primers_and_the_users_own_items_are_searched(db: sqlalchemy.orm.Session) -> None:
    """An old primer version and another user's chunk never match."""
    user_id = _user(db)
    other_id = _user(db, sub="other")
    current = _topic_primer(db, user_id=user_id, name="Monetary plumbing", current=True)
    stale = _topic_primer(db, user_id=user_id, name="Old plumbing", current=False)
    theirs = _source(db, user_id=other_id, title="Theirs")
    _chunk(db, owner=current, text="Central banks set the price of reserves.")
    _chunk(db, owner=stale, text="Central banks in the old version.")
    _chunk(db, owner=theirs, text="Central banks belong to someone else.")

    hits = search.search_chunks(db, user_id=user_id, query="central banks", query_embedding=None, limit=10)

    assert [(hit.item.kind, hit.title) for hit in hits] == [(models.SearchItemKind.TOPIC_PRIMER, "Monetary plumbing")]


def test_match_any_finds_a_passage_with_only_some_of_the_words(db: sqlalchemy.orm.Session) -> None:
    """The chat tool's queries match on any word; Library search needs them all."""
    user_id = _user(db)
    source = _source(db, user_id=user_id, title="Fed")
    _chunk(db, owner=source, text="The Fed buys bonds and pays with reserves.")

    strict = search.search_chunks(db, user_id=user_id, query="fed printing", query_embedding=None, limit=10)
    loose = search.search_chunks(
        db, user_id=user_id, query="fed printing", query_embedding=None, limit=10, match_any=True
    )

    assert (strict, [hit.title for hit in loose]) == ([], ["Fed"])


def test_the_about_boost_lifts_the_items_own_passages(db: sqlalchemy.orm.Session) -> None:
    """Equal matches: the boosted item's chunk comes first."""
    user_id = _user(db)
    first = _source(db, user_id=user_id, title="First")
    about = _take(db, user_id=user_id, title="My take")
    _chunk(db, owner=first, text="Tariffs raise prices.")
    _chunk(db, owner=about, text="Tariffs raise prices.")
    boost = search.ItemRef(kind=models.SearchItemKind.TAKE, id=about.id)

    hits = search.search_chunks(db, user_id=user_id, query="tariffs", query_embedding=None, limit=10, boost=boost)

    assert hits[0].item == boost


@pytest.mark.parametrize(
    ("text", "query", "keyword_match", "expected_start", "contains"),
    [
        ("Short text.", "short", True, "Short", "Short text."),
        ("x " * 200 + "the Fed doesn't print money in that sense " + "y " * 200, "printing", True, "…", "print money"),
        ("Opening words " + "z " * 300, "unrelated", False, "Opening words", "Opening words"),
    ],
)
def test_passage_is_about_220_characters_around_the_first_matched_term(
    text: str, query: str, keyword_match: bool, expected_start: str, contains: str
) -> None:
    """A stemmed term is found mid-text; a meaning-only hit shows the start."""
    snippet = search.passage(text, query=query, keyword_match=keyword_match)

    assert snippet.startswith(expected_start)
    assert contains in snippet
    assert len(snippet) <= search.PASSAGE_CHARACTERS + 2
```

The `passage` cases don't need Postgres but sit in a Postgres-marked file; that's fine (the marker only grants sockets).

Run — FAIL (`archie_db.search` missing).

- [ ] **Step 9: Search** `packages/archie-db/archie_db/search.py`:

```python
"""Search over the owner's passages: keyword (Postgres full text) and meaning (pgvector), merged by rank fusion.

`search_chunks` returns ranked passages (the chat's `search_library` tool uses them as they are); `best_per_item`
keeps each item's best passage for Library search. Only live items are searched: a deleted or merged source, a deleted
take, or a topic primer that is no longer current or whose topic was removed or merged never comes back.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm

from archie_db import models, vector

KEYWORD_CANDIDATES = 40
MEANING_CANDIDATES = 40
# Reciprocal rank fusion's damping constant: a chunk scores 1 / (RRF_K + rank) in each list it appears in.
RRF_K = 60
# Ask about this puts the item's own passages first among equals without hiding a much better match elsewhere.
ABOUT_BOOST = 1 / (RRF_K + 1)
PASSAGE_CHARACTERS = 220

# Words too common to place a passage on.
_STOP_WORDS = frozenset(
    {"a", "an", "and", "are", "about", "did", "does", "for", "from", "how", "in", "is", "of", "on", "the", "that",
     "this", "to", "was", "what", "who", "why", "with"}
)
_TERM = re.compile(r"[\w']+")
# Postgres matches stems ("printing" finds "print"), so a term is located by its first letters.
_STEM_TRIM = 3
_MIN_STEM = 4

_LIVE_CHUNKS = """
FROM chunks c
LEFT JOIN sources s ON s.id = c.source_id
LEFT JOIN topic_primers tp ON tp.id = c.topic_primer_id
LEFT JOIN topics t ON t.id = tp.topic_id
LEFT JOIN takes k ON k.id = c.take_id
WHERE c.user_id = :user_id
  AND (
    (c.source_id IS NOT NULL AND s.deleted_at IS NULL AND s.merged_into_id IS NULL)
    OR (c.topic_primer_id IS NOT NULL AND tp.is_current AND t.removed_at IS NULL AND t.merged_into_id IS NULL)
    OR (c.take_id IS NOT NULL AND k.deleted_at IS NULL)
  )
"""
_COLUMNS = """
SELECT c.id, c.owner_kind, c.source_id, c.topic_primer_id, c.take_id, c.text, c.start_seconds,
       COALESCE(s.title, s.url, t.name, k.title) AS title
"""
_KEYWORD_SQL = sqlalchemy.text(
    _COLUMNS
    + _LIVE_CHUNKS
    + """
  AND c.tsv @@ websearch_to_tsquery('english', :query)
ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', :query)) DESC, c.id
LIMIT :limit
"""
)
_MEANING_SQL = sqlalchemy.text(
    _COLUMNS
    + _LIVE_CHUNKS
    + """
  AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> CAST(:embedding AS vector), c.id
LIMIT :limit
"""
)


@dataclass(frozen=True)
class ItemRef:
    """A library item: a source, a topic primer (one version) or a take."""

    kind: models.SearchItemKind
    id: uuid.UUID


@dataclass(frozen=True)
class ChunkHit:
    """One ranked passage and the item it belongs to; `keyword_match` says the words matched, not only the meaning."""

    chunk_id: int
    item: ItemRef
    title: str
    owner_kind: models.ChunkOwner
    text: str
    start_seconds: float | None
    score: float
    keyword_match: bool


def search_chunks(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    query: str,
    query_embedding: Sequence[float] | None,
    limit: int,
    boost: ItemRef | None = None,
    match_any: bool = False,
) -> list[ChunkHit]:
    """The user's best `limit` passages for `query`, best first; meaning search runs only with `query_embedding`.

    Keyword search needs every word unless `match_any`, which needs any one (more matched words still rank higher).
    """
    keyword_query = " or ".join(_TERM.findall(query)) if match_any else query
    keyword_rows = (
        db.execute(_KEYWORD_SQL, {"user_id": user_id, "query": keyword_query, "limit": KEYWORD_CANDIDATES}).all()
        if keyword_query.strip()
        else []
    )
    meaning_rows = (
        db.execute(
            _MEANING_SQL,
            {"user_id": user_id, "embedding": vector.to_literal(query_embedding), "limit": MEANING_CANDIDATES},
        ).all()
        if query_embedding is not None
        else []
    )
    return _fuse(keyword_rows=keyword_rows, meaning_rows=meaning_rows, boost=boost)[:limit]


def best_per_item(hits: Sequence[ChunkHit], *, limit: int) -> list[ChunkHit]:
    """Each item once, by its best passage, keeping the order of `hits` (best first)."""
    best: dict[ItemRef, ChunkHit] = {}
    for hit in hits:
        best.setdefault(hit.item, hit)
    return list(best.values())[:limit]


def passage(text: str, *, query: str, keyword_match: bool) -> str:
    """About 220 characters of `text` around the first query term it contains, or its start for a meaning-only hit."""
    flat = " ".join(text.split())
    if len(flat) <= PASSAGE_CHARACTERS:
        return flat

    position = _first_term_position(flat, query=query) if keyword_match else None
    if position is None:
        return flat[:PASSAGE_CHARACTERS].rstrip() + "…"

    # A third of the window before the term, so the reader sees what leads into it.
    start = max(0, position - PASSAGE_CHARACTERS // 3)
    end = min(len(flat), start + PASSAGE_CHARACTERS)
    start = max(0, end - PASSAGE_CHARACTERS)
    snippet = flat[start:end].strip()
    return f"{'…' if start > 0 else ''}{snippet}{'…' if end < len(flat) else ''}"


def _fuse(
    *, keyword_rows: Sequence[sqlalchemy.Row[object]], meaning_rows: Sequence[sqlalchemy.Row[object]], boost: ItemRef | None
) -> list[ChunkHit]:
    """Reciprocal rank fusion over the two candidate lists, plus the about boost; ties fall to the lower chunk id."""
    scores: dict[int, float] = {}
    rows: dict[int, sqlalchemy.Row[object]] = {}
    for rank, row in enumerate(keyword_rows, start=1):
        scores[row.id] = scores.get(row.id, 0.0) + 1 / (RRF_K + rank)
        rows[row.id] = row
    for rank, row in enumerate(meaning_rows, start=1):
        scores[row.id] = scores.get(row.id, 0.0) + 1 / (RRF_K + rank)
        rows[row.id] = row

    keyword_ids = {row.id for row in keyword_rows}
    hits = []
    for chunk_id, row in rows.items():
        item = _item_of(row)
        score = scores[chunk_id] + (ABOUT_BOOST if item == boost else 0.0)
        hits.append(
            ChunkHit(
                chunk_id=chunk_id,
                item=item,
                title=row.title,
                owner_kind=models.ChunkOwner(row.owner_kind),
                text=row.text,
                start_seconds=row.start_seconds,
                score=score,
                keyword_match=chunk_id in keyword_ids,
            )
        )
    return sorted(hits, key=lambda hit: (-hit.score, hit.chunk_id))


def _item_of(row: sqlalchemy.Row[object]) -> ItemRef:
    if row.source_id is not None:
        return ItemRef(kind=models.SearchItemKind.SOURCE, id=row.source_id)
    if row.topic_primer_id is not None:
        return ItemRef(kind=models.SearchItemKind.TOPIC_PRIMER, id=row.topic_primer_id)
    return ItemRef(kind=models.SearchItemKind.TAKE, id=row.take_id)


def _first_term_position(text: str, *, query: str) -> int | None:
    lowered = text.lower()
    positions = []
    for term in _TERM.findall(query.lower()):
        if term in _STOP_WORDS:
            continue
        stem = term if len(term) <= _MIN_STEM else term[: max(_MIN_STEM, len(term) - _STEM_TRIM)]
        found = lowered.find(stem)
        if found >= 0:
            positions.append(found)
    return min(positions, default=None)
```

Typing note: `sqlalchemy.Row[object]` attribute access (`row.id`) needs `Row[Any]`; use `sqlalchemy.Row[Any]` (import `Any`) if mypy complains. Format the `_STOP_WORDS` set with `make format`.

- [ ] **Step 10: Run** `make lint` and the full suite with `archie_test_t2` — pass (the embeddings cassette replays).

- [ ] **Step 11: Commit.**

```bash
git add packages/archie-db/archie_db/search.py packages/archie-db/tests/test_search.py packages/archie-llm packages/archie-testing
git commit -m "Search core (keyword + meaning, rank fusion), OpenAI embeddings client, embeddings replay

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: App data layer: schema 0011, sync of chats, `deleteConversation`, shared Ask types, chat cards in Review  (tier: most capable)

**Files:**
- Create: `app/src/ask/types.ts`, `app/src/ask/types.test.ts`, `app/src/db/conversations.test.ts`, `app/drizzle/0011_search_ask.sql` (+ `app/drizzle/meta/0011_snapshot.json`, journal entry — generated)
- Modify: `app/src/db/schema.ts`, `app/drizzle/migrations.js` (generated), `app/src/sync/engine.ts` (pulled types), `app/src/sync/transport.ts`, `app/src/sync/engine.test.ts`, `app/src/db/actions.ts`, `app/src/auth/session.ts` (+ `session.test.ts` if it lists wiped tables), `app/src/review/{eligibility,kicker,useReviewData,testCards}.ts`, `app/src/review/{eligibility,kicker}.test.ts`

**Interfaces:**
- Consumes (Task 1): the pulled `conversations` / `messages` rows and card columns; push action `delete_conversation {id}`.
- Produces:
  - Drizzle tables `schema.conversations` (`id, title, aboutKind, aboutSourceId, aboutTopicPrimerId, aboutTakeId, createdAt, updatedAt, deletedAt`) and `schema.messages` (`id, conversationId, role, text, segments` (JSON text or null), `webSearch` (0/1), `status, createdAt`); `schema.cards.conversationId`, `schema.cards.messageId`.
  - `@/ask/types`: `AnswerLabel = "library" | "web" | "background"`, `OwnerKind`, `LibraryCitation`, `WebCitation`, `Citation`, `AnswerSegment`, `AskEvent`, `AboutKind = "source" | "topic_primer" | "take"`, `ConversationRow`, `MessageRow`, `parseSegments(json: string | null): AnswerSegment[]`, `formatClock(seconds: number): string` (`1880` → `"31:20"`, `3723` → `"1:02:03"`), `ANSWER_LABEL_TEXT: Record<AnswerLabel, string>` (`Your library`, `Background`, `Web`).
  - `@/db/actions`: `deleteConversation(db: AppDb, conversationId: string): void` (sets `deletedAt`, queues `delete_conversation`).
  - Review: `CardOrigin` gains `{ kind: "conversation"; conversationId: string }`; `ReviewData.conversationsById: Map<string, ConversationRow>`; `makeReviewData({ …, conversations?: ConversationRow[] })`; conversation cards are reviewable at once; `cardKicker` returns `{ label: "From Ask", suffix: undefined, domain }` with the about item's domain (source's domain, the topic primer's topic's domain, the take kind's `TAKE_KIND_DOMAIN`), else `null` (which `Kicker` shows as Other).
- Review: yes (migration with a cards change, sync rejection rules, sign-out wipe, review eligibility).

- [ ] **Step 1: Symlink node_modules** (Global Constraints).

- [ ] **Step 2: Schema.** In `app/src/db/schema.ts` add **at the end of the `cards` definition** (so drizzle emits two `ALTER TABLE … ADD`, not a rebuild):

```ts
  // A card made from an Ask answer: the chat and the answer it came from.
  conversationId: text("conversation_id"),
  messageId: text("message_id"),
```

and, at the end of the file:

```ts
// Saved Ask chats, written by the server and pulled; the phone only deletes one (an outbox action).
export const conversations = sqliteTable("conversations", {
  id: text("id").primaryKey(),
  title: text("title").notNull(),
  aboutKind: text("about_kind"),
  aboutSourceId: text("about_source_id"),
  aboutTopicPrimerId: text("about_topic_primer_id"),
  aboutTakeId: text("about_take_id"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});

export const messages = sqliteTable("messages", {
  id: text("id").primaryKey(),
  conversationId: text("conversation_id").notNull(),
  role: text("role").notNull(),
  text: text("text").notNull(),
  // An answer's segments as JSON (`AnswerSegment[]`); null for a question.
  segments: text("segments"),
  webSearch: integer("web_search").notNull().default(0),
  status: text("status").notNull(),
  createdAt: text("created_at").notNull(),
});
```

- [ ] **Step 3: Generate the migration.** `cd app && npx drizzle-kit generate --name search_ask`. **Read the SQL.** Expected: `CREATE TABLE \`conversations\``, `CREATE TABLE \`messages\``, `ALTER TABLE \`cards\` ADD \`conversation_id\` text;` and `ALTER TABLE \`cards\` ADD \`message_id\` text;`, nothing else. If drizzle emits a `__new_cards` rebuild instead, its `INSERT INTO __new_cards (...) SELECT ... FROM cards` must list every column the phone's `cards` has after `0010` (id, source_id, topic_primer_id, brief_id, take_id, take_version_id, kind, question, answer, created_at, deleted_at, fsrs_state, stability, difficulty, due_at, last_review_at, reps, lapses, expires_at) — fix it by hand. Then append to `app/drizzle/0011_search_ask.sql`:

```sql
--> statement-breakpoint
-- Chats, their messages and the cards' chat columns reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;
```

Confirm `app/drizzle/migrations.js` imports `m0011` and the journal has the `0011_search_ask` entry.

- [ ] **Step 4: Shared Ask types** `app/src/ask/types.ts`:

```ts
import type * as schema from "@/db/schema";

/** Where an answer's text came from, read off its citations (never the model's own claim). */
export type AnswerLabel = "library" | "web" | "background";
export type OwnerKind = "source_text" | "source_summary" | "source_primer" | "topic_primer" | "take";
export type AboutKind = "source" | "topic_primer" | "take";

// Wire shapes stay snake_case: they are stored as the server sent them, in `messages.segments`.
export type LibraryCitation = {
  kind: "library";
  title: string;
  source_id: string | null;
  topic_primer_id: string | null;
  take_id: string | null;
  owner_kind: OwnerKind;
  start_seconds: number | null;
  quote: string | null;
};
export type WebCitation = { kind: "web"; title: string; url: string; quote: string | null };
export type Citation = LibraryCitation | WebCitation;
export type AnswerSegment = { label: AnswerLabel; text: string; citations: Citation[] };

/** One server-sent event of an answer stream. */
export type AskEvent =
  | { type: "delta"; block: number; text: string }
  | { type: "block"; block: number; label: AnswerLabel; citations: Citation[] }
  | { type: "searching"; kind: "library" | "web"; query: string }
  | { type: "done"; message_id: string }
  | { type: "error"; message: string };

export type ConversationRow = typeof schema.conversations.$inferSelect;
export type MessageRow = typeof schema.messages.$inferSelect;

export const ANSWER_LABEL_TEXT: Record<AnswerLabel, string> = {
  library: "Your library",
  background: "Background",
  web: "Web",
};

const LABELS = new Set<string>(["library", "web", "background"]);

/** A stored answer's segments; anything malformed (an older or newer shape) reads as no segments. */
export function parseSegments(json: string | null): AnswerSegment[] {
  if (!json) return [];
  try {
    const parsed: unknown = JSON.parse(json);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (segment): segment is AnswerSegment =>
        typeof segment === "object" &&
        segment !== null &&
        LABELS.has((segment as AnswerSegment).label) &&
        typeof (segment as AnswerSegment).text === "string" &&
        Array.isArray((segment as AnswerSegment).citations),
    );
  } catch {
    return [];
  }
}

/** 1880 → "31:20", 3723 → "1:02:03": how a passage's time is shown. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = String(whole % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}
```

`app/src/ask/types.test.ts`:

```ts
import { formatClock, parseSegments } from "./types";

describe("formatClock", () => {
  it("shows minutes and seconds, and hours once there are any", () => {
    expect([formatClock(0), formatClock(1880.6), formatClock(3723)]).toEqual(["0:00", "31:20", "1:02:03"]);
  });
});

describe("parseSegments", () => {
  it("keeps well-formed segments and drops the rest", () => {
    const good = { label: "web", text: "T", citations: [] };
    expect(parseSegments(JSON.stringify([good, { label: "other", text: "x", citations: [] }, 3]))).toEqual([good]);
    expect([parseSegments(null), parseSegments("{oops")]).toEqual([[], []]);
  });
});
```

- [ ] **Step 5: Failing data tests** `app/src/db/conversations.test.ts`:

```ts
import { eq } from "drizzle-orm";

import { createDbSyncStore } from "@/sync/transport";

import { deleteConversation } from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";
import { makeTestDb } from "./testDb";

jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

const conversation = (overrides: Record<string, unknown> = {}) => ({
  id: "chat1",
  title: "How does the Fed create money?",
  about_kind: null,
  about_source_id: null,
  about_topic_primer_id: null,
  about_take_id: null,
  created_at: "2026-11-06T10:00:00Z",
  updated_at: "2026-11-06T10:00:00Z",
  deleted_at: null,
  change_seq: 3,
  ...overrides,
});
const message = (overrides: Record<string, unknown> = {}) => ({
  id: "m2",
  conversation_id: "chat1",
  role: "assistant",
  text: "Reserves.",
  segments: [{ label: "background", text: "Reserves.", citations: [] }],
  web_search: false,
  status: "complete",
  created_at: "2026-11-06T10:00:05Z",
  change_seq: 4,
  ...overrides,
});
const page = (rows: Record<string, unknown[]>, position: number) => ({
  rows: { sources: [], artifacts: [], cards: [], ...rows },
  position,
  more: false,
});
const chat = (db: AppDb) => db.select().from(schema.conversations).where(eq(schema.conversations.id, "chat1")).get();

describe("chats on the phone", () => {
  it("a pull stores conversations, messages (segments as JSON) and chat cards", async () => {
    const db = makeTestDb();
    const store = createDbSyncStore(db);

    await store.applyPage(
      page(
        {
          conversations: [conversation()],
          messages: [message()],
          cards: [
            {
              id: "c1", source_id: null, kind: "concept", question: "Q?", answer: "A.",
              created_at: "2026-11-06T10:01:00Z", deleted_at: null, change_seq: 5,
              conversation_id: "chat1", message_id: "m2",
            },
          ],
        },
        5,
      ) as never,
    );

    expect(chat(db)).toMatchObject({ title: "How does the Fed create money?", deletedAt: null });
    const [stored] = db.select().from(schema.messages).all();
    expect(stored).toMatchObject({ conversationId: "chat1", role: "assistant", webSearch: 0, status: "complete" });
    expect(JSON.parse(stored.segments!)).toEqual(message().segments);
    expect(db.select().from(schema.cards).get()).toMatchObject({ conversationId: "chat1", messageId: "m2" });
  });

  it("deleteConversation hides the chat at once and queues delete_conversation; an older pull doesn't undo it", async () => {
    const db = makeTestDb();
    const store = createDbSyncStore(db);
    await store.applyPage(page({ conversations: [conversation()] }, 3) as never);

    deleteConversation(db, "chat1");
    await store.applyPage(page({ conversations: [conversation({ change_seq: 6 })] }, 6) as never);

    expect(chat(db)?.deletedAt).not.toBeNull();
    const [entry] = db.select().from(schema.outbox).all();
    expect([entry.type, JSON.parse(entry.payload)]).toEqual(["delete_conversation", { id: "chat1" }]);
  });

  it("a rejected delete_conversation rewinds so the next pull restores the chat", async () => {
    const db = makeTestDb();
    const store = createDbSyncStore(db);
    await store.applyPage(page({ conversations: [conversation()] }, 3) as never);
    deleteConversation(db, "chat1");
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "conversation not found");

    expect(await store.getPosition()).toBe(0);
  });
});
```

(Check `createDbSyncStore`'s real signature and `rejectAction`'s name in `transport.ts`/`engine.ts` and adapt the calls; the existing `engine.test.ts` uses `createDbSyncStore(db)` and `store.rejectAction(entry.id, reason)`.) Add to `engine.test.ts`: `"0011_search_ask"` in the `it.each` list of migrations that reset the position, and a copy of the 0010 card-survival test for 0011 (run every migration before `0011_search_ask`, insert the same card plus `take_id = NULL`, run 0011, expect the row with `conversation_id: null, message_id: null`).

Run `cd app && npx jest src/db/conversations.test.ts src/ask src/sync` — FAIL.

- [ ] **Step 6: Sync.** In `engine.ts` add

```ts
export type PulledConversation = {
  id: string;
  title: string;
  about_kind: string | null;
  about_source_id: string | null;
  about_topic_primer_id: string | null;
  about_take_id: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  change_seq: number;
};
export type PulledMessage = {
  id: string;
  conversation_id: string;
  role: string;
  text: string;
  segments: unknown[] | null;
  web_search: boolean;
  status: string;
  created_at: string;
  change_seq: number;
};
```

`PulledCard` gains `conversation_id?: string | null; message_id?: string | null`; `PullPage.rows` gains `conversations?: PulledConversation[]; messages?: PulledMessage[]`; extend the `SyncStore` comment: "a rejected delete_conversation rewinds". In `transport.ts`: `const CONVERSATION_ACTIONS = new Set(["delete_conversation"]);` joins `rowIsNotSource`; cards set `conversationId: card.conversation_id ?? null, messageId: card.message_id ?? null`; after the take versions loop:

```ts
        for (const conversation of page.rows.conversations ?? []) {
          if (unsent.has(conversation.id)) continue;
          const values = {
            title: conversation.title,
            aboutKind: conversation.about_kind,
            aboutSourceId: conversation.about_source_id,
            aboutTopicPrimerId: conversation.about_topic_primer_id,
            aboutTakeId: conversation.about_take_id,
            createdAt: conversation.created_at,
            updatedAt: conversation.updated_at,
            deletedAt: conversation.deleted_at,
          };
          tx.insert(schema.conversations)
            .values({ id: conversation.id, ...values })
            .onConflictDoUpdate({ target: schema.conversations.id, set: values })
            .run();
        }

        for (const message of page.rows.messages ?? []) {
          const values = {
            conversationId: message.conversation_id,
            role: message.role,
            text: message.text,
            segments: message.segments === null ? null : JSON.stringify(message.segments),
            webSearch: message.web_search ? 1 : 0,
            status: message.status,
            createdAt: message.created_at,
          };
          tx.insert(schema.messages)
            .values({ id: message.id, ...values })
            .onConflictDoUpdate({ target: schema.messages.id, set: values })
            .run();
        }
```

Update the "keeps its local copy" comment to include chats.

- [ ] **Step 7: Action and wipe.** `actions.ts`: `"delete_conversation"` joins `ActionType`; add

```ts
/** Deletes a saved chat (cards made from it stay in Review). */
export function deleteConversation(db: AppDb, conversationId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    tx.update(schema.conversations)
      .set({ deletedAt: now, updatedAt: now })
      .where(eq(schema.conversations.id, conversationId))
      .run();
    enqueue(tx, "delete_conversation", { id: conversationId });
  });
}
```

`session.ts` sign-out wipe deletes `schema.conversations` and `schema.messages` (and its test, if it lists tables, expects them).

- [ ] **Step 8: Review.** `eligibility.ts`:

```ts
type ConversationRow = typeof schema.conversations.$inferSelect;
// ReviewData gains:
  conversationsById: Map<string, ConversationRow>;
// CardOrigin gains (before "unknown"):
  | { kind: "conversation"; conversationId: string }
// cardOrigin, after the take line:
  if (card.conversationId) return { kind: "conversation", conversationId: card.conversationId };
// isReviewable, a new case:
    // The owner made a chat card from an answer they just read, so it is reviewable at once.
    case "conversation":
      return true;
// makeReviewData: rows gain `conversations?: ConversationRow[]`, and
    conversationsById: new Map((rows.conversations ?? []).map((conversation) => [conversation.id, conversation])),
```

Update the `isReviewable` doc comment ("chat cards at once"). `kicker.ts`:

```ts
  if (origin.kind === "conversation") {
    return { label: "From Ask", suffix: undefined, domain: conversationDomain(origin.conversationId, data) };
  }
```

with, in `kicker.ts`:

```ts
/** The domain colour of what a chat was about: a source's domain, a topic primer's topic's, a take kind's; else none. */
function conversationDomain(conversationId: string, data: ReviewData): string | null {
  const conversation = data.conversationsById.get(conversationId);
  if (!conversation) return null;
  if (conversation.aboutSourceId) return data.sourcesById.get(conversation.aboutSourceId)?.domain ?? null;
  if (conversation.aboutTopicPrimerId) {
    const primer = data.topicPrimersById.get(conversation.aboutTopicPrimerId);
    return primer ? (data.topicsById.get(primer.topicId)?.domain ?? null) : null;
  }
  if (conversation.aboutTakeId) {
    const take = data.takesById.get(conversation.aboutTakeId);
    return take ? TAKE_KIND_DOMAIN[asTakeKind(take.kind)] : null;
  }
  return null;
}
```

Update the docstring of `cardKicker` ("From Ask" for chat cards). `useReviewData.ts`: `conversations: database.select().from(schema.conversations)` in `reviewQueries`, passed through in `readReviewData` and `useReviewData`. `testCards.ts`: `cardRow` gains `conversationId: null, messageId: null`; `reviewData` accepts `conversations`. Tests: in `kicker.test.ts`

```ts
  it("reads From Ask in the about item's colour for a chat card, else Other", () => {
    const chatData = reviewData([], {
      conversations: [
        conversationRow({ id: "about-source", aboutKind: "source", aboutSourceId: "s1" }),
        conversationRow({ id: "general" }),
      ],
    });
    const chatCard = (conversationId: string) => cardRow({ sourceId: null, conversationId });

    expect(cardKicker(chatCard("about-source"), chatData)).toEqual({ label: "From Ask", suffix: undefined, domain: "AI" });
    expect(cardKicker(chatCard("general"), chatData)).toEqual({ label: "From Ask", suffix: undefined, domain: null });
  });
```

(add a `conversationRow` factory to `testCards.ts` with every column null/`"Q"`/fixed dates), and in `eligibility.test.ts` "a chat card is reviewable at once" (`isReviewable(cardRow({ sourceId: null, conversationId: "x" }), reviewData([]))` is `true`; a deleted one is `false`).

- [ ] **Step 9: Run** `cd app && npm run typecheck && npx jest` — all pass.

- [ ] **Step 10: Commit.**

```bash
git add app/src app/drizzle
git commit -m "App: drizzle 0011, chats sync, deleteConversation, Ask types, chat cards in Review

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Parallel-safe tasks

Every task below depends only on Tasks 1–3 and runs in its own worktree (`git gtr new m7-t<N> --from-current --yes` inside the `m7-ask` worktree), with its own test database `archie_test_t<N>`.

### Task 4: Worker: cutting passages, the `embed` job, its queue points, `archie-worker backfill-embed`  (tier: standard)

**Files:**
- Create: `services/worker/archie_worker/chunking.py`, `services/worker/archie_worker/handlers/embed.py`, `services/worker/archie_worker/backfill_embed.py`, `services/worker/tests/test_chunking.py`, `services/worker/tests/test_embed_e2e.py`, `services/worker/tests/cassettes/embed_article.yaml` (recorded)
- Modify: `services/worker/archie_worker/handlers/__init__.py`, `handlers/_text.py`, `handlers/analyze.py`, `handlers/primer.py`, `handlers/topic_primer.py`, `services/worker/archie_worker/main.py`, `packages/archie-db/archie_db/takes.py`; existing tests' job-list expectations only where an added `embed` job now appears

**Interfaces:**
- Consumes: Task 1 (`models.Chunk`, `models.ChunkOwner`, `models.SearchItemKind`, `models.JobKind.EMBED`, `jobs.enqueue_embed`, `jobs.ITEM_KIND_KEY`, `jobs.ITEM_ID_KEY`); Task 2 (`embeddings.embed`, `embeddings.EmbeddingError`, `llm.EMBED_STEP`, `search.ItemRef`).
- Produces: `chunking.Passage(owner_kind, text, start_seconds)`, `chunking.text_passages`, `chunking.segment_passages`, `chunking.markdown_passages`, `chunking.summary_markdown`, `chunking.TARGET_WORDS = 300`, `chunking.OVERLAP_WORDS = 50`; `handlers.embed.handle`; `backfill_embed.backfill_all(db) -> int`; `archie-worker backfill-embed`.
- Depends on: Tasks 1-3.
- Review: yes (outside call, the lock contract, replacing chunks, liveness, cost).

- [ ] **Step 1: Test DB** `archie_test_t4`.

- [ ] **Step 2: Failing cutting tests** `services/worker/tests/test_chunking.py`:

```python
"""Cutting passages: ~300-word windows with a 50-word overlap at sentence ends, transcript start times, sections."""

from __future__ import annotations

from archie_db import models
from archie_worker import chunking, content

# Eight words each; ten per paragraph.
SENTENCES = [f"Sentence number {index} is about stablecoins and payments." for index in range(90)]
TEXT = "\n\n".join(" ".join(SENTENCES[start : start + 10]) for start in range(0, 90, 10))


def test_text_is_cut_into_windows_of_at_most_300_words_that_overlap_by_whole_sentences() -> None:
    """37 sentences, then 37 starting 6 back (48 overlapping words), then the last 28: every sentence is covered."""
    passages = chunking.text_passages(TEXT, owner_kind=models.ChunkOwner.SOURCE_TEXT)

    assert len(passages) == 3
    assert all(len(passage.text.split()) <= chunking.TARGET_WORDS for passage in passages)
    assert passages[0].text.endswith(SENTENCES[36]) and passages[1].text.startswith(SENTENCES[31])
    assert passages[2].text.startswith(SENTENCES[62]) and passages[2].text.endswith(SENTENCES[89])
    assert all(passage.start_seconds is None for passage in passages)


def test_a_transcript_passage_keeps_its_first_segments_start() -> None:
    """100 ten-word segments five seconds apart: 30 per window, 5 overlapping."""
    segments = [content.Segment(start=index * 5.0, text=" ".join(["word"] * 10)) for index in range(100)]

    passages = chunking.segment_passages(segments)

    assert [passage.start_seconds for passage in passages] == [0.0, 125.0, 250.0, 375.0]
    assert {passage.owner_kind for passage in passages} == {models.ChunkOwner.SOURCE_TEXT}


def test_markdown_is_cut_section_by_section() -> None:
    """Each heading starts a passage, even when the sections are short."""
    markdown = "Intro line.\n\n## Reserves\n\nBanks hold reserves.\n\n## Rates\n\nThe Fed sets a rate."

    passages = chunking.markdown_passages(markdown, owner_kind=models.ChunkOwner.TOPIC_PRIMER)

    assert [passage.text for passage in passages] == [
        "Intro line.",
        "## Reserves Banks hold reserves.",
        "## Rates The Fed sets a rate.",
    ]


def test_the_summary_becomes_gist_key_ideas_and_numbers_sections() -> None:
    """The analyze JSON reads as the source page shows it."""
    summary = {
        "gist": "The Fed creates reserves.",
        "key_ideas": [{"timestamp": "31:20", "idea": "It buys bonds."}],
        "numbers": [{"timestamp": None, "fact": "$6.6T balance sheet."}],
    }

    markdown = chunking.summary_markdown(summary)

    assert markdown == (
        "## Gist\n\nThe Fed creates reserves.\n\n## Key ideas\n\n- It buys bonds.\n\n## Numbers\n\n- $6.6T balance sheet."
    )
```

Run `uv run pytest services/worker/tests/test_chunking.py -v` — FAIL.

- [ ] **Step 3: Cutting** `services/worker/archie_worker/chunking.py`:

```python
"""Cutting an item's words into search passages of about 300 words with a 50-word overlap.

Passages break at sentence ends (paragraph ends are sentence ends too); a sentence longer than a passage is cut at word
counts. A transcript is cut from its timed segments and each passage keeps its first segment's start. Summaries and
primers are cut section by section, so a heading always starts a passage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from archie_db import models

from archie_worker import content

TARGET_WORDS = 300
OVERLAP_WORDS = 50

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)


@dataclass(frozen=True)
class Passage:
    """One search passage before it is stored: what it was cut from, its text, and a transcript passage's start."""

    owner_kind: models.ChunkOwner
    text: str
    start_seconds: float | None


@dataclass(frozen=True)
class _Unit:
    """The smallest piece a passage is built from: a sentence, or one timed segment."""

    text: str
    start: float | None
    words: int


def text_passages(text: str, *, owner_kind: models.ChunkOwner) -> list[Passage]:
    """Plain text cut at sentence ends."""
    return [
        Passage(owner_kind=owner_kind, text=window_text, start_seconds=None)
        for window_text, _ in _pack(_sentence_units(text))
    ]


def segment_passages(segments: Sequence[content.Segment]) -> list[Passage]:
    """A transcript cut at segment ends; each passage starts when its first segment does."""
    units = [
        _Unit(text=" ".join(segment.text.split()), start=segment.start, words=len(segment.text.split()))
        for segment in segments
        if segment.text.strip()
    ]
    return [
        Passage(owner_kind=models.ChunkOwner.SOURCE_TEXT, text=window_text, start_seconds=start)
        for window_text, start in _pack(units)
    ]


def markdown_passages(markdown: str, *, owner_kind: models.ChunkOwner) -> list[Passage]:
    """Markdown cut at its headings first, then each section at sentence ends."""
    return [passage for section in _sections(markdown) for passage in text_passages(section, owner_kind=owner_kind)]


def summary_markdown(summary: Mapping[str, Any]) -> str:
    """The analyze summary (gist, key ideas, numbers) as markdown sections, the way the source page shows it."""
    ideas = "\n".join(f"- {item['idea']}" for item in summary.get("key_ideas", []))
    numbers = "\n".join(f"- {item['fact']}" for item in summary.get("numbers", []))
    sections = [
        f"## Gist\n\n{summary.get('gist', '')}",
        f"## Key ideas\n\n{ideas}" if ideas else "",
        f"## Numbers\n\n{numbers}" if numbers else "",
    ]
    return "\n\n".join(section for section in sections if section)


def _sections(markdown: str) -> list[str]:
    starts = [match.start() for match in _HEADING.finditer(markdown) if match.start() > 0]
    bounds = [0, *starts, len(markdown)]
    sections = (markdown[start:end].strip() for start, end in zip(bounds, bounds[1:], strict=False))
    return [section for section in sections if section]


def _sentence_units(text: str) -> list[_Unit]:
    units = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        flat = " ".join(paragraph.split())
        for sentence in _SENTENCE_END.split(flat) if flat else []:
            words = sentence.split()
            # A sentence longer than a passage (a transcript without punctuation, a list) is cut at word counts.
            for start in range(0, len(words), TARGET_WORDS):
                piece = words[start : start + TARGET_WORDS]
                units.append(_Unit(text=" ".join(piece), start=None, words=len(piece)))
    return units


def _pack(units: Sequence[_Unit]) -> list[tuple[str, float | None]]:
    """Whole units, greedily, up to TARGET_WORDS per window.

    Each new window opens with the previous window's last units (at most OVERLAP_WORDS of them), so the sentence that
    spans a boundary is whole in one of the two passages.
    """
    windows: list[list[_Unit]] = []
    current: list[_Unit] = []
    for unit in units:
        if current and _words(current) + unit.words > TARGET_WORDS:
            windows.append(current)
            current = _overlap(current)
            # Carried-over words that would themselves overflow the window are dropped.
            if _words(current) + unit.words > TARGET_WORDS:
                current = []
        current.append(unit)
    if current:
        windows.append(current)
    return [(" ".join(unit.text for unit in window), window[0].start) for window in windows]


def _overlap(window: Sequence[_Unit]) -> list[_Unit]:
    kept: list[_Unit] = []
    for unit in reversed(window):
        if _words(kept) + unit.words > OVERLAP_WORDS:
            break
        kept.insert(0, unit)
    return kept


def _words(units: Sequence[_Unit]) -> int:
    return sum(unit.words for unit in units)
```

Note the markdown test's expected texts: a section's newlines collapse to spaces (`"## Reserves Banks hold reserves."`) — keep the heading marker; it is harmless in a passage and reads as a heading to the model. Run the cutting tests — PASS.

- [ ] **Step 4: Failing embed e2e test** `services/worker/tests/test_embed_e2e.py`:

```python
"""`embed` end to end: real jobs in a real Postgres, OpenAI replayed from a recorded real response.

Re-record `embed_article` by deleting it and running
`uv run pytest services/worker/tests/test_embed_e2e.py --record-mode=once -m postgres` with `TEST_DATABASE_URL` set
(a tiny fraction of a cent; needs OPENAI_API_KEY in the repo root .env).
"""

from __future__ import annotations

import pathlib
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, session
from archie_shared import config
from archie_testing import recording
from archie_worker import backfill_embed, handlers, loop

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
ARTICLE = "Stablecoins settle about ten trillion dollars a year. They move dollars without a bank in the middle."
SUMMARY = {
    "gist": "Stablecoins already move dollars at scale.",
    "key_ideas": [{"timestamp": None, "idea": "They settle without a bank."}],
    "numbers": [{"timestamp": None, "fact": "About $10T a year."}],
}


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real OpenAI key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch, env_names=(config.OPENAI_API_KEY_ENV,))


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


def test_a_paid_source_gets_text_and_summary_chunks_with_embeddings(
    engine: sqlalchemy.Engine, request: pytest.FixtureRequest
) -> None:
    """Text and summary passages, numbered per kind, each with a 1536-dimension embedding and one costed request."""
    source_id = _add_source(engine, whitelisted=True)
    _enqueue(engine, source_id)

    with recording.vcr_for(request, cassette_dir=CASSETTE_DIR).use_cassette("embed_article.yaml"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    chunks = _chunks(engine)
    assert [(chunk.owner_kind, chunk.chunk_index) for chunk in chunks] == [
        ("source_summary", 0),
        ("source_summary", 1),
        ("source_summary", 2),
        ("source_text", 0),
    ]
    assert all(chunk.embedding is not None and len(chunk.embedding) == models.EMBEDDING_DIMENSIONS for chunk in chunks)
    [call] = _llm_calls(engine)
    assert (call.step, call.provider, call.source_id) == ("embed", "openai", source_id)
    assert [job.status for job in _jobs(engine)] == ["done"]


def test_without_the_owners_keys_chunks_are_stored_with_no_embedding_and_rebuilt_on_rerun(
    engine: sqlalchemy.Engine,
) -> None:
    """No cassette: any request would fail the job. A second run replaces, never duplicates."""
    source_id = _add_source(engine, whitelisted=False)
    _enqueue(engine, source_id)
    loop.run_one(engine, handlers=handlers.HANDLERS)
    first_ids = {chunk.id for chunk in _chunks(engine)}

    _enqueue(engine, source_id)
    loop.run_one(engine, handlers=handlers.HANDLERS)

    chunks = _chunks(engine)
    assert len(chunks) == len(first_ids) and not ({chunk.id for chunk in chunks} & first_ids)
    assert all(chunk.embedding is None for chunk in chunks)
    assert _llm_calls(engine) == []


def test_a_deleted_source_gets_no_chunks(engine: sqlalchemy.Engine) -> None:
    """Deleted before the job ran: nothing is written."""
    source_id = _add_source(engine, whitelisted=False, deleted=True)
    _enqueue(engine, source_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _chunks(engine) == []


def test_a_new_topic_primer_version_replaces_the_old_versions_chunks(engine: sqlalchemy.Engine) -> None:
    """Only the current version is searchable."""
    user_id = _add_user(engine, whitelisted=False)
    old_id, new_id = _add_topic_primers(engine, user_id=user_id)
    _enqueue(engine, old_id, kind=models.SearchItemKind.TOPIC_PRIMER, user_id=user_id, current=False)
    _enqueue(engine, new_id, kind=models.SearchItemKind.TOPIC_PRIMER, user_id=user_id)

    loop.run_one(engine, handlers=handlers.HANDLERS)
    loop.run_one(engine, handlers=handlers.HANDLERS)

    assert {chunk.topic_primer_id for chunk in _chunks(engine)} == {new_id}


def test_backfill_queues_every_live_item_once(engine: sqlalchemy.Engine) -> None:
    """A live source with text, the current topic primer and a take with a body; a deleted source is skipped."""
    user_id = _add_user(engine, whitelisted=False)
    _add_source(engine, whitelisted=False, user_id=user_id)
    _add_source(engine, whitelisted=False, user_id=user_id, deleted=True)
    _add_topic_primers(engine, user_id=user_id)
    _add_take(engine, user_id=user_id)

    with sqlalchemy.orm.Session(engine) as db:
        queued = backfill_embed.backfill_all(db)
        db.commit()
        again = backfill_embed.backfill_all(db)
        db.commit()

    assert (queued, again) == (3, 0)
    assert sorted(job.payload[jobs.ITEM_KIND_KEY] for job in _jobs(engine)) == ["source", "take", "topic_primer"]
```

Helpers at the bottom of the file (write them out; each opens a `sqlalchemy.orm.Session(engine)`, takes `changes.lock_user_writes`, uses `changes.next_change_seq()` for synced rows and commits):
- `_add_user(engine, *, whitelisted: bool) -> int` (unique `apple_sub` via `uuid.uuid4().hex`).
- `_add_source(engine, *, whitelisted: bool, user_id: int | None = None, deleted: bool = False) -> uuid.UUID`: a READY article source (makes a user when `user_id` is None) with `pipeline.write_artifact(... kind=TEXT, content={"text": ARTICLE} ...)` and `pipeline.write_artifact(... kind=SUMMARY, content={"summary": SUMMARY, ...rest of the analysis shape not needed...})` — the embed job reads only `content["summary"]`; store `{"summary": SUMMARY}`.
- `_add_topic_primers(engine, *, user_id) -> tuple[uuid.UUID, uuid.UUID]`: a topic with version 1 (`is_current=False`, markdown `"## Old\n\nReserves before."`) and version 2 (`is_current=True`, `"## Reserves\n\nBanks hold reserves at the Fed."`).
- `_add_take(engine, *, user_id) -> uuid.UUID`: a take with version 1 whose `body` is `"Stablecoins are the real use."`.
- `_enqueue(engine, item_id, *, kind=SOURCE, user_id=None, current=True)`: `jobs.enqueue(db, kind=EMBED, user_id=<the item's user>, payload={jobs.ITEM_KIND_KEY: kind.value, jobs.ITEM_ID_KEY: str(item_id)})` (use `jobs.enqueue`, not `enqueue_embed`, so a test can queue twice). `current` is unused documentation of intent — drop it if lint objects.
- `_chunks` (ordered by `owner_kind, chunk_index`), `_jobs` (by id), `_llm_calls`.

The expected summary chunk list assumes `summary_markdown(SUMMARY)` gives three sections (Gist, Key ideas, Numbers) and the article text one passage. Run — FAIL.

- [ ] **Step 5: The handler** `services/worker/archie_worker/handlers/embed.py`:

```python
"""`embed`: rebuild one item's search passages (a source, a topic primer or a take) from scratch, with embeddings.

Follows the loop's handler contract: read the item's words and commit, call OpenAI holding no transaction, then lock
the user's writes, check the item is still live, and replace its chunks in one go, so running it again only rebuilds
the same passages. A user without the owner's keys, or a server without an OpenAI key, gets passages with no
embedding: they still serve keyword search. On its last attempt a failed embeddings call stores the passages without
embeddings rather than leaving the item unsearchable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, pipeline, search, takes
from archie_llm import embeddings, llm
from archie_shared import config, logging

from archie_worker import chunking, content

_logger = logging.get_logger(logging.LoggerName.WORKER, "embed")


@dataclass(frozen=True)
class _EmbedRun:
    """What the job needs after its read transaction: the item, its passages, and who pays for embeddings."""

    item: search.ItemRef
    user_id: int
    passages: list[chunking.Passage]
    # None when nobody pays: the user isn't whitelisted or the server has no OpenAI key.
    api_key: str | None
    context: llm.CallContext
    last_attempt: bool


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Cut the item's passages, embed them when paid for, and replace the item's chunks."""
    run = _prepare(db, job)
    if run is None:
        return

    vectors = _embed(db, run)

    changes.lock_user_writes(db, run.user_id)
    if not _is_live(db, run.item):
        return
    _replace_chunks(db, run=run, vectors=vectors)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _EmbedRun | None:
    item = search.ItemRef(
        kind=models.SearchItemKind(job.payload[jobs.ITEM_KIND_KEY]), id=uuid.UUID(job.payload[jobs.ITEM_ID_KEY])
    )
    passages = _passages(db, item) if _is_live(db, item) else None
    user = db.get_one(models.User, job.user_id)
    openai_key = config.Settings().openai_api_key or None
    run = (
        None
        if passages is None
        else _EmbedRun(
            item=item,
            user_id=user.id,
            passages=passages,
            api_key=openai_key if user.is_whitelisted else None,
            context=llm.CallContext(
                user_id=user.id,
                source_id=item.id if item.kind == models.SearchItemKind.SOURCE else None,
                job_id=job.id,
                step=llm.EMBED_STEP,
            ),
            last_attempt=job.attempts >= job.max_attempts,
        )
    )
    # No transaction is held during the OpenAI call.
    db.commit()
    return run


def _passages(db: sqlalchemy.orm.Session, item: search.ItemRef) -> list[chunking.Passage]:
    if item.kind == models.SearchItemKind.SOURCE:
        return _source_passages(db, source_id=item.id)
    if item.kind == models.SearchItemKind.TOPIC_PRIMER:
        primer = db.get_one(models.TopicPrimer, item.id)
        return chunking.markdown_passages(primer.content["markdown"], owner_kind=models.ChunkOwner.TOPIC_PRIMER)

    take = db.get_one(models.Take, item.id)
    version = takes.current_version(db, take=take)
    if version is None or version.body is None:
        return []
    return chunking.markdown_passages(version.body, owner_kind=models.ChunkOwner.TAKE)


def _source_passages(db: sqlalchemy.orm.Session, *, source_id: uuid.UUID) -> list[chunking.Passage]:
    """The source's own text (timed when it is a transcript), then Archie's summary and primer of it."""
    passages: list[chunking.Passage] = []
    text = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.TEXT)
    if text is not None:
        segments = content.segments_of(text.content)
        passages += (
            chunking.segment_passages(segments)
            if segments
            else chunking.text_passages(text.content[content.TEXT_KEY], owner_kind=models.ChunkOwner.SOURCE_TEXT)
        )

    summary = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.SUMMARY)
    if summary is not None:
        passages += chunking.markdown_passages(
            chunking.summary_markdown(summary.content["summary"]), owner_kind=models.ChunkOwner.SOURCE_SUMMARY
        )

    primer = pipeline.current_artifact(db, source_id=source_id, kind=models.ArtifactKind.PRIMER)
    if primer is not None:
        passages += chunking.markdown_passages(primer.content["markdown"], owner_kind=models.ChunkOwner.SOURCE_PRIMER)
    return passages


def _is_live(db: sqlalchemy.orm.Session, item: search.ItemRef) -> bool:
    """Whether search may show the item now (read again after the lock: the owner may have deleted it meanwhile)."""
    if item.kind == models.SearchItemKind.SOURCE:
        source = db.get(models.Source, item.id)
        if source is not None:
            db.refresh(source)
        return source is not None and source.deleted_at is None and source.merged_into_id is None
    if item.kind == models.SearchItemKind.TOPIC_PRIMER:
        primer = db.get(models.TopicPrimer, item.id)
        if primer is None:
            return False
        db.refresh(primer)
        topic = db.get_one(models.Topic, primer.topic_id)
        return primer.is_current and topic.removed_at is None and topic.merged_into_id is None

    take = db.get(models.Take, item.id)
    if take is not None:
        db.refresh(take)
    return take is not None and take.deleted_at is None


def _embed(db: sqlalchemy.orm.Session, run: _EmbedRun) -> list[list[float]] | None:
    if run.api_key is None or not run.passages:
        return None

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    _logger.info("Embedding %d passages of %s %s", len(run.passages), run.item.kind, run.item.id)
    try:
        return embeddings.embed(
            engine, api_key=run.api_key, context=run.context, texts=[passage.text for passage in run.passages]
        )
    except (httpx.HTTPError, embeddings.EmbeddingError) as error:
        if not run.last_attempt:
            raise
        # Out of retries: the passages still serve keyword search, and a later save or the backfill embeds them.
        _logger.warning("Storing %s %s without embeddings: %r", run.item.kind, run.item.id, error)
        return None


def _replace_chunks(db: sqlalchemy.orm.Session, *, run: _EmbedRun, vectors: list[list[float]] | None) -> None:
    db.execute(sqlalchemy.delete(models.Chunk).where(_owned_by(db, run.item)))

    indexes: dict[models.ChunkOwner, int] = {}
    owner = {
        models.SearchItemKind.SOURCE: "source_id",
        models.SearchItemKind.TOPIC_PRIMER: "topic_primer_id",
        models.SearchItemKind.TAKE: "take_id",
    }[run.item.kind]
    for position, passage in enumerate(run.passages):
        index = indexes.get(passage.owner_kind, 0)
        indexes[passage.owner_kind] = index + 1
        db.add(
            models.Chunk(
                user_id=run.user_id,
                owner_kind=passage.owner_kind.value,
                chunk_index=index,
                text=passage.text,
                start_seconds=passage.start_seconds,
                embedding=vectors[position] if vectors is not None else None,
                **{owner: run.item.id},
            )
        )


def _owned_by(db: sqlalchemy.orm.Session, item: search.ItemRef) -> sqlalchemy.ColumnElement[bool]:
    """The chunks this job replaces; for a topic primer, every version's, since only the current one is searchable."""
    if item.kind == models.SearchItemKind.SOURCE:
        return models.Chunk.source_id == item.id
    if item.kind == models.SearchItemKind.TAKE:
        return models.Chunk.take_id == item.id

    topic_id = db.get_one(models.TopicPrimer, item.id).topic_id
    versions = sqlalchemy.select(models.TopicPrimer.id).where(models.TopicPrimer.topic_id == topic_id)
    return models.Chunk.topic_primer_id.in_(versions)
```

Register it in `handlers/__init__.py`: `models.JobKind.EMBED: HandlerSpec(run=embed.handle)` with the comment `# No failure hook: an item without chunks is only missing from search until its next save or the backfill.`

- [ ] **Step 6: Queue points.**
  - `handlers/_text.py` `store_text`: after `write_artifact`, `jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)` (Decision 2; extend the docstring: "and queues its search passages").
  - `handlers/analyze.py`: the same call right after the summary is written; `handlers/primer.py`: right after the primer artifact is written; `handlers/clean_text.py` needs nothing (analyze follows it).
  - `handlers/topic_primer.py` `handle`: after `write_topic_primer`, `jobs.enqueue_embed(db, user_id=topic.user_id, item_kind=models.SearchItemKind.TOPIC_PRIMER, item_id=primer.id)`.
  - `packages/archie-db/archie_db/takes.py` `enqueue_step`: after queueing, `if kind == models.JobKind.TAKE_CARDS: jobs.enqueue_embed(db, user_id=version.user_id, item_kind=models.SearchItemKind.TAKE, item_id=version.take_id)` — every path that gives a version its body queues `take_cards`, so this is the one place (docstring: "…and, once the version has its body, the take's search passages").

- [ ] **Step 7: Backfill** `services/worker/archie_worker/backfill_embed.py`:

```python
"""`archie-worker backfill-embed`: queue `embed` for every live item that existed before search, once after deploy.

Every live source with a current text or summary, every current topic primer of a live topic, and every live take
whose current version has a body. Items already waiting for `embed` are skipped, so running it twice queues nothing.
"""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session
from archie_shared import config, logging

_logger = logging.get_logger(logging.LoggerName.WORKER, "backfill_embed")


def main() -> None:
    """Queue the jobs against `DATABASE_URL` and report how many."""
    logging.configure()
    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        count = backfill_all(db)
        db.commit()
    _logger.info("Queued embed for %d items", count)


def backfill_all(db: sqlalchemy.orm.Session) -> int:
    """Queue one `embed` per live item, in the caller's transaction; returns how many were queued."""
    items = [*_sources(db), *_topic_primers(db), *_takes(db)]
    queued = 0
    for user_id, kind, item_id in items:
        changes.lock_user_writes(db, user_id)
        before = _queued_count(db)
        jobs.enqueue_embed(db, user_id=user_id, item_kind=kind, item_id=item_id)
        queued += _queued_count(db) - before
    return queued
```

with `_sources` (`select(Source.user_id, Source.id)` where live, not merged, and `exists` a current `text` or `summary` artifact), `_topic_primers` (current primers joined to live, unmerged topics), `_takes` (live takes joined to their current version with a non-null body), each yielding `(user_id, models.SearchItemKind.X, id)` rows — typed as a small frozen dataclass `_Item(user_id, kind, item_id)` rather than tuples of three — and `_queued_count(db)` counting queued `embed` jobs. (`enqueue_embed` returns nothing, so the count difference tells whether it queued.)

In `services/worker/archie_worker/main.py` make `main()` dispatch: `if sys.argv[1:] == ["backfill-embed"]: backfill_embed.main(); return` before starting the loop (docstring: "`archie-worker backfill-embed` queues search passages for existing items instead").

- [ ] **Step 8: Record and replay.** Record `embed_article` (Global Constraints, `archie_test_t4`), secret grep, replay — PASS.

- [ ] **Step 9: Existing tests.** Run the full suite with `archie_test_t4`. Tests that list jobs after a text, summary, primer, topic primer or take step now also see an `embed` job: add it to their expectations (the only allowed change). A worker e2e test that sets `OPENAI_API_KEY` for a whitelisted user and runs every queued job (the podcast/transcribe ones) would now make an unrecorded embeddings request: in that test only, stop the loop before the `embed` job or assert it as queued — never record a cassette for an unrelated test.

- [ ] **Step 10: Run** `make lint` and the full suite — pass.

- [ ] **Step 11: Commit.**

```bash
git add services/worker packages/archie-db/archie_db/takes.py services/api/tests
git commit -m "Worker: cut passages, embed job, queue it after text/summary/primer/topic primer/take, backfill-embed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: API: `GET /search`  (tier: standard)

**Files:**
- Create: `services/api/archie_api/search/__init__.py`, `services/api/archie_api/search/routes.py`, `services/api/tests/e2e/test_search_e2e.py`, `services/api/tests/e2e/cassettes/search_query.yaml` (recorded)
- Modify: `services/api/archie_api/main.py` (`app.include_router(search_routes.router)`)

**Interfaces:**
- Consumes: Task 1 models; Task 2 `search.search_chunks`, `search.best_per_item`, `search.passage`, `search.KEYWORD_CANDIDATES`, `search.MEANING_CANDIDATES`, `embeddings.embed`, `llm.EMBED_STEP`.
- Produces: `GET /search` (shape in Global Constraints); `archie_api.search.routes.query_embedding(engine, *, user_id: int, is_whitelisted: bool, query: str) -> list[float] | None` (public, but Task 6 keeps its own equivalent so no parallel task imports another's code).
- Depends on: Tasks 1-3.
- Review: yes (whitelist gate before spending, no transaction across the OpenAI call).

- [ ] **Step 1: Test DB** `archie_test_t5`.

- [ ] **Step 2: Failing e2e test** `services/api/tests/e2e/test_search_e2e.py`:

```python
"""`GET /search` through the real API: keyword search for everyone, meaning search for whitelisted users.

Chunks are seeded directly (the worker's `embed` job writes them in production). OpenAI is replayed from a recorded
real response; re-record `search_query` by deleting it and running
`uv run pytest services/api/tests/e2e/test_search_e2e.py --record-mode=once -m postgres` (needs OPENAI_API_KEY).
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_shared import config
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
LONG = "Filler words about the weather. " * 20 + "The Fed doesn't print money in the sense people think. " + "More. " * 40


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real OpenAI key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch, env_names=(config.OPENAI_API_KEY_ENV,))


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _seed(live_stack: LiveStack, *, user_id: int, title: str, chunks: list[dict[str, Any]], deleted: bool = False) -> str:
    """A source with these chunks (`text`, optional `owner_kind`, `start_seconds`, `embedding`)."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        url = f"https://example.com/{uuid.uuid4()}"
        source = models.Source(
            id=uuid.uuid4(), user_id=user_id, url=url, normalized_url=url, title=title,
            kind=models.SourceKind.PODCAST.value, state=models.SourceState.INBOX.value,
            intent=models.SourceIntent.QUEUE.value, deleted_at=sqlalchemy.func.now() if deleted else None,
            change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        for index, chunk in enumerate(chunks):
            db.add(
                models.Chunk(
                    user_id=user_id, source_id=source.id, chunk_index=index, text=chunk["text"],
                    owner_kind=chunk.get("owner_kind", models.ChunkOwner.SOURCE_TEXT.value),
                    start_seconds=chunk.get("start_seconds"), embedding=chunk.get("embedding"),
                )
            )
        db.commit()
        source_id = str(source.id)
    engine.dispose()
    return source_id


def test_keyword_search_returns_items_with_the_passage_that_matched(live_stack: LiveStack) -> None:
    """One result per item, its best passage trimmed around the term, with the transcript time; deleted items never."""
    authed = live_stack.authed(live_stack.sign_in())
    user_id = _user_id(authed)
    podcast = _seed(
        live_stack, user_id=user_id, title="How the Fed creates money",
        chunks=[{"text": LONG, "start_seconds": 1880.0}, {"text": "Printing is a loose word."}],
    )
    _seed(live_stack, user_id=user_id, title="Deleted", chunks=[{"text": "Money printing."}], deleted=True)

    response = authed.get("/search", params={"q": "money printing"})

    assert response.status_code == 200
    [result] = response.json()["results"]
    assert (result["item_kind"], result["item_id"], result["title"]) == ("source", podcast, "How the Fed creates money")
    assert "print money" in result["passage"] and len(result["passage"]) <= 222
    assert (result["owner_kind"], result["start_seconds"]) == ("source_text", 1880.0)


def test_a_user_without_the_owners_keys_gets_keyword_search_only(live_stack: LiveStack) -> None:
    """No embeddings request is made (no cassette here), and nothing is spent."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=False))
    _seed(live_stack, user_id=_user_id(authed), title="Reserves", chunks=[{"text": "Reserves at the Fed."}])

    assert authed.get("/search", params={"q": "zzqx"}).json()["results"] == []
    assert _llm_calls(live_stack) == []


def test_meaning_search_finds_a_passage_without_the_words_and_costs_one_embed_call(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """A whitelisted query is embedded once; a chunk with an embedding comes back though no word matches."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    axis = [0.0] * models.EMBEDDING_DIMENSIONS
    axis[0] = 1.0
    source_id = _seed(
        live_stack, user_id=_user_id(authed), title="Monetary plumbing",
        chunks=[{"text": "Central banks set the price of reserves.", "embedding": axis}],
    )

    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    with recorder.use_cassette("search_query.yaml"):
        results = authed.get("/search", params={"q": "who controls money printing"}).json()["results"]

    assert [result["item_id"] for result in results] == [source_id]
    assert results[0]["passage"] == "Central banks set the price of reserves."
    [call] = _llm_calls(live_stack)
    assert (call.step, call.provider) == ("embed", "openai")


def test_a_bad_query_is_422_and_signed_out_is_401(live_stack: LiveStack) -> None:
    """Empty and overlong queries are refused before any work."""
    authed = live_stack.authed(live_stack.sign_in())

    assert authed.get("/search", params={"q": ""}).status_code == 422
    assert authed.get("/search", params={"q": "x" * 201}).status_code == 422
    assert live_stack.client.get("/search", params={"q": "x"}).status_code == 401


def _llm_calls(live_stack: LiveStack) -> list[models.LlmCall]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        calls = list(db.scalars(sqlalchemy.select(models.LlmCall)))
    engine.dispose()
    return calls
```

Run — FAIL (404 for `/search`).

- [ ] **Step 3: Route** `services/api/archie_api/search/__init__.py` (`"""Library search over the owner's passages."""`) and `services/api/archie_api/search/routes.py`:

```python
"""`GET /search`: Library search, merging keyword and meaning matches into items with the passage that matched.

Meaning search embeds the query with the owner's OpenAI key, so it runs only for whitelisted users; everyone gets
keyword search. No transaction is held during the embeddings call, and a failed call falls back to keyword search.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import fastapi
import httpx
import pydantic
import sqlalchemy
from archie_db import models, search
from archie_llm import embeddings, llm
from archie_shared import config, logging
from sqlalchemy import orm

from archie_api import deps

MAX_QUERY_LENGTH = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
QUERY_TIMEOUT_SECONDS = 5

router = fastapi.APIRouter(tags=["search"])
_logger = logging.get_logger(logging.LoggerName.API, "search")


class SearchResultView(pydantic.BaseModel):
    """One item and the passage of it that matched best."""

    item_kind: models.SearchItemKind
    item_id: uuid.UUID
    title: str
    passage: str
    owner_kind: models.ChunkOwner
    start_seconds: float | None


class SearchView(pydantic.BaseModel):
    """Items, best first."""

    results: list[SearchResultView]


@router.get("/search")
def search_library(
    q: Annotated[str, fastapi.Query(min_length=1, max_length=MAX_QUERY_LENGTH)],
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
    limit: Annotated[int, fastapi.Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> SearchView:
    """The user's live items matching `q`, each once with its best passage."""
    query = q.strip()
    if not query:
        raise fastapi.HTTPException(status_code=422, detail="query is empty")
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    user_id, is_whitelisted = user.id, user.is_whitelisted

    # No transaction is held during the embeddings call.
    db.commit()
    embedding = query_embedding(engine, user_id=user_id, is_whitelisted=is_whitelisted, query=query)

    hits = search.search_chunks(
        db,
        user_id=user_id,
        query=query,
        query_embedding=embedding,
        limit=search.KEYWORD_CANDIDATES + search.MEANING_CANDIDATES,
    )
    return SearchView(
        results=[
            SearchResultView(
                item_kind=hit.item.kind,
                item_id=hit.item.id,
                title=hit.title,
                passage=search.passage(hit.text, query=query, keyword_match=hit.keyword_match),
                owner_kind=hit.owner_kind,
                start_seconds=hit.start_seconds,
            )
            for hit in search.best_per_item(hits, limit=limit)
        ]
    )


def query_embedding(
    engine: sqlalchemy.Engine, *, user_id: int, is_whitelisted: bool, query: str
) -> list[float] | None:
    """The query's embedding for a whitelisted user on a server with an OpenAI key; None otherwise or on failure."""
    api_key = config.Settings().openai_api_key
    if not is_whitelisted or not api_key:
        return None

    context = llm.CallContext(user_id=user_id, source_id=None, job_id=None, step=llm.EMBED_STEP)
    try:
        [vector] = embeddings.embed(
            engine, api_key=api_key, context=context, texts=[query], timeout_seconds=QUERY_TIMEOUT_SECONDS
        )
    except (httpx.HTTPError, embeddings.EmbeddingError) as error:
        # Keyword results are still worth showing; the phone can't tell the difference.
        _logger.warning("Query embedding failed, searching by keyword only: %r", error)
        return None
    return vector
```

The user's id and whitelist flag are read into locals before the commit (which expires `user`), so nothing reopens a transaction during the call.

Mount it in `main.py`: `from archie_api.search import routes as search_routes` and `app.include_router(search_routes.router)`.

- [ ] **Step 4: Record and replay** `search_query` (`archie_test_t5`; secret grep), replay — PASS. Run `make lint` and the full suite — pass.

- [ ] **Step 5: Commit.**

```bash
git add services/api
git commit -m "API: GET /search, keyword for everyone and meaning for whitelisted users

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: API: the Ask stream (tool loop, citations, labels, saving)  (tier: most capable)

**Files:**
- Create: `services/api/archie_api/ask/prompts.py`, `services/api/archie_api/ask/citations.py`, `services/api/archie_api/ask/context.py`, `services/api/archie_api/ask/answer.py`, `services/api/archie_api/ask/routes.py`, `services/api/tests/test_ask_units.py`, `services/api/tests/e2e/test_ask_e2e.py`, cassettes `services/api/tests/e2e/cassettes/{ask_library,ask_web,ask_unauthorized}.yaml` (recorded)
- Modify: `services/api/archie_api/main.py` (`app.include_router(ask_routes.router)`)

**Interfaces:**
- Consumes: Task 1 (`models.Conversation`, `models.Message`, `MessageRole`, `MessageStatus`, `SearchItemKind`, `CONVERSATION_TITLE_LENGTH`, `conversation_actions.touch_conversation`, `conversation_actions.owned_conversation`); Task 2 (`search.search_chunks(..., match_any=True)`, `search.ChunkHit`, `search.ItemRef`, `embeddings.embed`, `llm.record_call`, `llm.ASK_STEP`, `llm.EMBED_STEP`, `llm.SONNET`).
- Produces: `POST /ask/conversations/{conversation_id}/messages` (SSE; Global Constraints shapes); `archie_api.ask.routes.router` (prefix `/ask`) — Task 7 adds its own router with the same prefix.
- Depends on: Tasks 1-3.
- Review: yes (streaming, the tool loop, auth, persisting on failure and on disconnect, spend).

- [ ] **Step 1: Test DB** `archie_test_t6`.

- [ ] **Step 2: Failing unit tests** `services/api/tests/test_ask_units.py` (pure logic: labels from citations, de-duplication, history pairs; SDK model objects are built directly, no HTTP):

```python
"""Ask's pure logic: a text block's label comes from its citations; history keeps only finished question-answer pairs."""

from __future__ import annotations

import uuid

import anthropic.types
from archie_db import models, search

from archie_api.ask import citations, context

HIT = search.ChunkHit(
    chunk_id=7,
    item=search.ItemRef(kind=models.SearchItemKind.SOURCE, id=uuid.UUID(int=1)),
    title="Odd Lots",
    owner_kind=models.ChunkOwner.SOURCE_TEXT,
    text="The Fed pays with reserves.",
    start_seconds=1880.0,
    score=1.0,
    keyword_match=True,
)
PASSAGES = {citations.source_key(HIT): HIT}


def _library(cited: str = "The Fed pays with reserves.") -> anthropic.types.CitationsSearchResultLocation:
    return anthropic.types.CitationsSearchResultLocation(
        type="search_result_location", source=citations.source_key(HIT), title="Odd Lots", cited_text=cited,
        search_result_index=0, start_block_index=0, end_block_index=1,
    )


def _web(url: str = "https://www.federalreserve.gov/x") -> anthropic.types.CitationsWebSearchResultLocation:
    return anthropic.types.CitationsWebSearchResultLocation(
        type="web_search_result_location", url=url, title="The Fed", cited_text="$6.6T", encrypted_index="e",
    )


def _block(text: str, cited: list[object] | None) -> anthropic.types.TextBlock:
    return anthropic.types.TextBlock(type="text", text=text, citations=cited)


def test_a_block_citing_the_library_is_library_even_with_a_web_citation_too() -> None:
    """Library wins; both kinds of chip are kept, each once."""
    segment = citations.segment_of(_block("It pays with reserves.", [_library(), _library(), _web()]), passages=PASSAGES)

    assert segment.label == citations.AnswerLabel.LIBRARY
    assert [citation["kind"] for citation in segment.citations] == ["library", "web"]
    assert segment.citations[0] == {
        "kind": "library", "title": "Odd Lots", "source_id": str(uuid.UUID(int=1)), "topic_primer_id": None,
        "take_id": None, "owner_kind": "source_text", "start_seconds": 1880.0, "quote": "The Fed pays with reserves.",
    }


def test_web_only_is_web_and_no_citations_is_background() -> None:
    """An unknown library source (not from this answer's searches) is ignored."""
    stray = _library().model_copy(update={"source": "archie:chunk:999"})

    assert citations.segment_of(_block("Balance sheet.", [_web()]), passages=PASSAGES).label == citations.AnswerLabel.WEB
    assert citations.segment_of(_block("Printing is shorthand.", None), passages=PASSAGES).label == (
        citations.AnswerLabel.BACKGROUND
    )
    assert citations.segment_of(_block("Hm.", [stray]), passages=PASSAGES).label == citations.AnswerLabel.BACKGROUND


def test_history_keeps_finished_pairs_only_and_the_last_twenty_messages() -> None:
    """A failed answer drops with its question; the history alternates user / assistant from the oldest kept pair."""
    def message(role: models.MessageRole, text: str, status: models.MessageStatus = models.MessageStatus.COMPLETE):
        return context.HistoryMessage(role=role, text=text, status=status)

    rows = [message(models.MessageRole.USER, "q0"), message(models.MessageRole.ASSISTANT, "a0", models.MessageStatus.FAILED)]
    for index in range(1, 13):
        rows += [message(models.MessageRole.USER, f"q{index}"), message(models.MessageRole.ASSISTANT, f"a{index}")]

    history = context.history_messages(rows)

    assert len(history) == context.HISTORY_MESSAGES
    assert history[0] == {"role": "user", "content": "q3"} and history[-1] == {"role": "assistant", "content": "a12"}
```

Run `uv run pytest services/api/tests/test_ask_units.py -v` — FAIL.

- [ ] **Step 3: Prompts** `services/api/archie_api/ask/prompts.py`:

```python
"""Ask's system prompt and tools. The fixed rules come first, so every chat's prompt shares its first 60 characters."""

from __future__ import annotations

from typing import Any

ASK_SYSTEM = """You are Archie's Ask, answering the owner's questions from their own library first. Archie is \
their personal library of the articles, newsletters, podcasts and videos they saved, with Archie's summaries and \
primers of them, topic primers, and the owner's own takes.

How to answer:
- Search the owner's library with search_library first, unless the question plainly isn't about anything they could \
have saved (small talk, arithmetic). Search again with other words if the first search finds nothing useful.
- Base library claims only on search results, so they carry citations.
- Then add background knowledge only where the library doesn't cover the question, in its own paragraph and without \
citations. Never present background knowledge as coming from the library.
- Search the web for recent or fast-changing facts (prices, office holders, this year's numbers), when the owner asks \
you to look something up, and whenever this prompt says a web search is required. Base web claims only on web \
results.
- Keep answers short and in plain language: a few short paragraphs at most. Define a technical term the first time \
you use it. No headings, and no bullet lists unless the owner asks for a list.
- If neither the library nor the web has the answer and you don't know it, say so plainly."""

WEB_REQUIRED = "A web search is required for this question: search the web before you answer."

ABOUT_INTRO = (
    "This chat is about one item in the owner's library, described below. Searches rank its passages first; "
    "answer about it unless the owner clearly asks about something else."
)

SEARCH_LIBRARY_TOOL: dict[str, Any] = {
    "name": "search_library",
    "description": (
        "Search the owner's saved library: article and newsletter text, podcast and video transcripts, Archie's "
        "summaries and primers of them, topic primers, and the owner's own takes. Call this first for any question "
        "the owner's reading could bear on. Returns up to 8 passages to cite."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to look for, in a few words."}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
    "eager_input_streaming": True,
}

# The current web search tool for Sonnet 5.5; three searches per request keeps an answer quick and cheap.
WEB_SEARCH_TOOL: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}


def system_prompt(*, about: str | None, web_required: bool) -> str:
    """The rules, then the about item (for Ask about this), then the web requirement when the globe was on."""
    parts = [ASK_SYSTEM]
    if about:
        parts.append(f"{ABOUT_INTRO}\n<about>\n{about}\n</about>")
    if web_required:
        parts.append(WEB_REQUIRED)
    return "\n\n".join(parts)
```

- [ ] **Step 4: Citations** `services/api/archie_api/ask/citations.py`:

```python
"""Turning the model's text blocks into labelled segments: the label is read off the block's citations.

A block citing a library passage (a `search_result` this answer's searches returned) is `library`; else one citing a
web result is `web`; else `background`. Library passages go to the model as `search_result` blocks whose `source` is
`source_key(hit)`, so a citation's `source` leads back to the passage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import anthropic.types
from archie_db import models, search

QUOTE_CHARACTERS = 300
_SOURCE_PREFIX = "archie:chunk:"


class AnswerLabel(StrEnum):
    """Where a segment of an answer came from."""

    LIBRARY = "library"
    WEB = "web"
    BACKGROUND = "background"


@dataclass(frozen=True)
class Segment:
    """One text block of an answer with its label and de-duplicated citations, in the stored wire shape."""

    label: AnswerLabel
    text: str
    citations: list[dict[str, Any]]

    def to_wire(self) -> dict[str, Any]:
        """The shape stored in `messages.segments` and sent in the `block` event."""
        return {"label": self.label.value, "text": self.text, "citations": self.citations}


def source_key(hit: search.ChunkHit) -> str:
    """The `source` a passage's `search_result` block carries, which its citations echo back."""
    return f"{_SOURCE_PREFIX}{hit.chunk_id}"


def search_result_block(hit: search.ChunkHit) -> dict[str, Any]:
    """A library passage as the model sees it: citable, titled with its item and where in the item it sits."""
    return {
        "type": "search_result",
        "source": source_key(hit),
        "title": _result_title(hit),
        "content": [{"type": "text", "text": hit.text}],
        "citations": {"enabled": True},
    }


def segment_of(block: anthropic.types.TextBlock, *, passages: Mapping[str, search.ChunkHit]) -> Segment:
    """The block's segment: its label from its citations, and each cited item or link once."""
    library: list[dict[str, Any]] = []
    web: list[dict[str, Any]] = []
    for citation in block.citations or []:
        if citation.type == "search_result_location":
            hit = passages.get(citation.source)
            if hit is not None:
                library.append(_library_citation(hit, quote=citation.cited_text))
        elif citation.type == "web_search_result_location":
            web.append(
                {
                    "kind": "web",
                    "title": citation.title or citation.url,
                    "url": citation.url,
                    "quote": citation.cited_text[:QUOTE_CHARACTERS],
                }
            )

    label = AnswerLabel.LIBRARY if library else AnswerLabel.WEB if web else AnswerLabel.BACKGROUND
    return Segment(label=label, text=block.text, citations=_unique([*library, *web]))


def _library_citation(hit: search.ChunkHit, *, quote: str) -> dict[str, Any]:
    item_id = str(hit.item.id)
    return {
        "kind": "library",
        "title": hit.title,
        "source_id": item_id if hit.item.kind == models.SearchItemKind.SOURCE else None,
        "topic_primer_id": item_id if hit.item.kind == models.SearchItemKind.TOPIC_PRIMER else None,
        "take_id": item_id if hit.item.kind == models.SearchItemKind.TAKE else None,
        "owner_kind": hit.owner_kind.value,
        "start_seconds": hit.start_seconds,
        "quote": quote[:QUOTE_CHARACTERS],
    }


def _unique(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[object, ...]] = set()
    kept = []
    for citation in found:
        key = (
            (citation["source_id"], citation["topic_primer_id"], citation["take_id"], citation["start_seconds"])
            if citation["kind"] == "library"
            else (citation["url"],)
        )
        if key not in seen:
            seen.add(key)
            kept.append(citation)
    return kept


_OWNER_NAMES = {
    models.ChunkOwner.SOURCE_SUMMARY: "Archie's summary",
    models.ChunkOwner.SOURCE_PRIMER: "Archie's primer",
    models.ChunkOwner.TOPIC_PRIMER: "topic primer",
    models.ChunkOwner.TAKE: "the owner's own take",
}


def _result_title(hit: search.ChunkHit) -> str:
    if hit.owner_kind == models.ChunkOwner.SOURCE_TEXT and hit.start_seconds is not None:
        minutes, seconds = divmod(int(hit.start_seconds), 60)
        return f"{hit.title} (at {minutes}:{seconds:02d})"
    name = _OWNER_NAMES.get(hit.owner_kind)
    return f"{hit.title} ({name})" if name else hit.title
```

- [ ] **Step 5: Context** `services/api/archie_api/ask/context.py`:

```python
"""What a chat's model call is given besides the question: earlier messages, and the about item's details and boost."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy
from archie_db import models, pipeline, search, takes
from sqlalchemy import orm

HISTORY_MESSAGES = 20
ABOUT_PRIMER_CHARACTERS = 2000


@dataclass(frozen=True)
class HistoryMessage:
    """The parts of a stored message that history needs."""

    role: models.MessageRole
    text: str
    status: models.MessageStatus


def history(db: orm.Session, *, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    """The conversation's earlier finished exchanges as Messages API turns, oldest first."""
    stored = db.scalars(
        sqlalchemy.select(models.Message)
        .where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at, models.Message.id)
    ).all()
    return history_messages(
        [
            HistoryMessage(
                role=models.MessageRole(row.role), text=row.text, status=models.MessageStatus(row.status)
            )
            for row in stored
        ]
    )


def history_messages(rows: Sequence[HistoryMessage]) -> list[dict[str, Any]]:
    """Question-answer pairs whose answer finished, as plain text (no citations), the last `HISTORY_MESSAGES` of them.

    A failed answer is dropped with its question, so the history always alternates and starts with a question.
    """
    turns: list[dict[str, Any]] = []
    for question, answer in zip(rows, rows[1:], strict=False):
        is_pair = question.role == models.MessageRole.USER and answer.role == models.MessageRole.ASSISTANT
        if is_pair and answer.status == models.MessageStatus.COMPLETE and answer.text.strip():
            turns += [{"role": "user", "content": question.text}, {"role": "assistant", "content": answer.text}]
    return turns[-HISTORY_MESSAGES:]


def about_text(db: orm.Session, *, conversation: models.Conversation) -> str | None:
    """The about item's title, summary and the owner's note, for the system prompt; None for a general chat."""
    if conversation.about_source_id is not None:
        return _source_text(db, source_id=conversation.about_source_id)
    if conversation.about_topic_primer_id is not None:
        primer = _current_primer(db, primer_id=conversation.about_topic_primer_id)
        if primer is None:
            return None
        topic = db.get_one(models.Topic, primer.topic_id)
        return f"Topic primer: {topic.name}\n\n{primer.content['markdown'][:ABOUT_PRIMER_CHARACTERS]}"
    if conversation.about_take_id is not None:
        take = db.get_one(models.Take, conversation.about_take_id)
        version = takes.current_version(db, take=take)
        body = (version.body or version.raw_body) if version is not None else ""
        return f"The owner's own {takes.KIND_NAMES[models.TakeKind(take.kind)]}: {take.title}\n\n{body}"
    return None


def boost(db: orm.Session, *, conversation: models.Conversation) -> search.ItemRef | None:
    """The item whose passages rank first; a topic primer is boosted as its topic's current version."""
    if conversation.about_source_id is not None:
        return search.ItemRef(kind=models.SearchItemKind.SOURCE, id=conversation.about_source_id)
    if conversation.about_take_id is not None:
        return search.ItemRef(kind=models.SearchItemKind.TAKE, id=conversation.about_take_id)
    if conversation.about_topic_primer_id is not None:
        primer = _current_primer(db, primer_id=conversation.about_topic_primer_id)
        return search.ItemRef(kind=models.SearchItemKind.TOPIC_PRIMER, id=primer.id) if primer else None
    return None


def _current_primer(db: orm.Session, *, primer_id: uuid.UUID) -> models.TopicPrimer | None:
    """The current version of the topic primer `primer_id` is a version of (the chat may predate a rewrite)."""
    started_with = db.get(models.TopicPrimer, primer_id)
    if started_with is None:
        return None
    return db.scalars(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == started_with.topic_id, models.TopicPrimer.is_current
        )
    ).one_or_none()


def _source_text(db: orm.Session, *, source_id: uuid.UUID) -> str:
    source = db.get_one(models.Source, source_id)
    lines = [f"{source.kind.capitalize()}: {source.title or source.url}"]
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    if summary is not None:
        content = summary.content["summary"]
        lines.append(f"Gist: {content['gist']}")
        lines += [f"- {item['idea']}" for item in content.get("key_ideas", [])]
    if source.note:
        lines.append(f"The owner's note: {source.note}")
    return "\n".join(lines)
```

- [ ] **Step 6: The loop** `services/api/archie_api/ask/answer.py`:

```python
"""One Ask answer: the tool loop against Sonnet 5.5, streamed as server-sent events, then saved.

The server runs up to `MAX_ROUNDS` model requests: `search_library` (run here, results returned as citable
`search_result` blocks) and Anthropic's web search tool (run by Anthropic). Text streams as `delta` events; each
finished text block becomes a labelled `block`; a tool run shows as `searching`. The answer is stored when the stream
ends — complete, or failed with whatever text arrived (also when the phone hangs up mid-answer). Every model round is
recorded in `llm_calls` (step `ask`). No database transaction is open while the model works.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import anthropic
import httpx
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, search
from archie_llm import embeddings, llm
from archie_shared import logging

from archie_api.ask import citations, prompts
from archie_api.sync import conversation_actions

MAX_ROUNDS = 5
MAX_TOKENS = 4000
LIBRARY_RESULTS = 8
REQUEST_TIMEOUT_SECONDS = 120
QUERY_TIMEOUT_SECONDS = 5
FAILED_MESSAGE = "Didn't finish. Try again"
# Answers should start fast: thinking only between tool calls, at medium effort (Sonnet 5.5 rejects "disabled").
THINKING: dict[str, str] = {"type": "between_tools"}
OUTPUT_CONFIG: dict[str, str] = {"effort": "medium"}

_logger = logging.get_logger(logging.LoggerName.API, "ask")


class EventName(StrEnum):
    """The server-sent events of an answer stream."""

    DELTA = "delta"
    BLOCK = "block"
    SEARCHING = "searching"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    """One server-sent event."""

    name: EventName
    data: dict[str, Any]

    def sse(self) -> str:
        """The event on the wire."""
        return f"event: {self.name.value}\ndata: {json.dumps(self.data)}\n\n"


@dataclass(frozen=True)
class AnswerRequest:
    """Everything one answer needs, read before the stream starts so no request-scoped session is used."""

    user_id: int
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    web_search: bool
    system: str
    messages: list[dict[str, Any]]
    boost: search.ItemRef | None
    anthropic_key: str
    # None: the chat's library search is keyword only.
    openai_key: str | None


@dataclass
class _Progress:
    """The answer so far: finished segments and the text of the block still streaming."""

    segments: list[citations.Segment] = field(default_factory=list)
    partial: str = ""


class AnswerRefusedError(Exception):
    """The model declined to answer; stored as a failed answer the owner can retry."""


def stream(engine: sqlalchemy.Engine, request: AnswerRequest) -> Iterator[str]:
    """The answer's events as SSE text, ending with `done` or `error`; the answer is saved either way."""
    progress = _Progress()
    try:
        for event in _run(engine, request=request, progress=progress):
            yield event.sse()
    except GeneratorExit:
        # The phone hung up: keep what arrived so the chat shows "Didn't finish" rather than nothing.
        _save(engine, request=request, progress=progress, failed=True)
        raise
    except (anthropic.APIError, AnswerRefusedError, ValueError) as error:
        # ValueError: the SDK could not parse the stream (e.g. a tool input that isn't JSON).
        _logger.warning("Answer failed for conversation %s: %r", request.conversation_id, error)
        _save(engine, request=request, progress=progress, failed=True)
        yield Event(name=EventName.ERROR, data={"message": FAILED_MESSAGE}).sse()
        return

    message_id = _save(engine, request=request, progress=progress, failed=False)
    yield Event(name=EventName.DONE, data={"message_id": str(message_id)}).sse()


def _run(engine: sqlalchemy.Engine, *, request: AnswerRequest, progress: _Progress) -> Iterator[Event]:
    """The tool loop; the last round may not call tools, so it has to answer."""
    client = anthropic.Anthropic(api_key=request.anthropic_key, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)
    context = llm.CallContext(user_id=request.user_id, source_id=None, job_id=None, step=llm.ASK_STEP)
    messages = list(request.messages)
    passages: dict[str, search.ChunkHit] = {}

    for round_number in range(1, MAX_ROUNDS + 1):
        tool_choice = {"type": "none"} if round_number == MAX_ROUNDS else {"type": "auto"}
        with client.messages.stream(
            model=llm.SONNET,
            max_tokens=MAX_TOKENS,
            system=request.system,
            messages=messages,
            tools=[prompts.SEARCH_LIBRARY_TOOL, prompts.WEB_SEARCH_TOOL],
            tool_choice=tool_choice,
            thinking=THINKING,
            output_config=OUTPUT_CONFIG,
        ) as response_stream:
            for stream_event in response_stream:
                yield from _events_of(stream_event, progress=progress, passages=passages)
            response = response_stream.get_final_message()
        llm.record_call(engine, context=context, model=llm.SONNET, response=response)

        if response.stop_reason == "refusal":
            raise AnswerRefusedError(str(response.stop_details))
        # Web search's own loop paused; re-sending the turn resumes it.
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            return

        messages.append({"role": "assistant", "content": response.content})
        results = [_search_library(engine, request=request, tool_use=tool_use, passages=passages) for tool_use in tool_uses]
        messages.append({"role": "user", "content": results})


def _events_of(
    stream_event: Any, *, progress: _Progress, passages: dict[str, search.ChunkHit]
) -> Iterator[Event]:
    """The phone's events for one SDK stream event; most SDK events have none."""
    if stream_event.type == "text":
        progress.partial += stream_event.text
        yield Event(name=EventName.DELTA, data={"block": len(progress.segments), "text": stream_event.text})
        return
    if stream_event.type != "content_block_stop":
        return

    block = stream_event.content_block
    if block.type == "text":
        segment = citations.segment_of(block, passages=passages)
        progress.segments.append(segment)
        progress.partial = ""
        data = {"block": len(progress.segments) - 1, "label": segment.label.value, "citations": segment.citations}
        yield Event(name=EventName.BLOCK, data=data)
    elif block.type == "tool_use" and block.name == prompts.SEARCH_LIBRARY_TOOL["name"]:
        yield Event(name=EventName.SEARCHING, data={"kind": "library", "query": _query_of(block.input) or ""})
    elif block.type == "server_tool_use" and block.name == prompts.WEB_SEARCH_TOOL["name"]:
        yield Event(name=EventName.SEARCHING, data={"kind": "web", "query": _query_of(block.input) or ""})


def _search_library(
    engine: sqlalchemy.Engine,
    *,
    request: AnswerRequest,
    tool_use: anthropic.types.ToolUseBlock,
    passages: dict[str, search.ChunkHit],
) -> dict[str, Any]:
    """Run `search_library` and answer with citable passages; a bad input goes back as an error the model can fix."""
    query = _query_of(tool_use.input)
    if not query:
        error = json.dumps({"INVALID_JSON": json.dumps(tool_use.input)})
        return {"type": "tool_result", "tool_use_id": tool_use.id, "is_error": True, "content": error}

    embedding = _query_embedding(engine, request=request, query=query)
    with sqlalchemy.orm.Session(engine) as db:
        hits = search.search_chunks(
            db,
            user_id=request.user_id,
            query=query,
            query_embedding=embedding,
            limit=LIBRARY_RESULTS,
            boost=request.boost,
            match_any=True,
        )
    passages.update({citations.source_key(hit): hit for hit in hits})

    content: list[dict[str, Any]] = [citations.search_result_block(hit) for hit in hits] or [
        {"type": "text", "text": "Nothing in the owner's library matched."}
    ]
    return {"type": "tool_result", "tool_use_id": tool_use.id, "content": content}


def _query_of(tool_input: object) -> str | None:
    """The `query` string of a tool input, or None when the input isn't one (eager streaming skips validation)."""
    if not isinstance(tool_input, dict):
        return None
    query = tool_input.get("query")
    return query.strip() if isinstance(query, str) and query.strip() else None


def _query_embedding(engine: sqlalchemy.Engine, *, request: AnswerRequest, query: str) -> list[float] | None:
    if request.openai_key is None:
        return None
    context = llm.CallContext(user_id=request.user_id, source_id=None, job_id=None, step=llm.EMBED_STEP)
    try:
        [vector] = embeddings.embed(
            engine, api_key=request.openai_key, context=context, texts=[query], timeout_seconds=QUERY_TIMEOUT_SECONDS
        )
    except (httpx.HTTPError, embeddings.EmbeddingError) as error:
        _logger.warning("Chat query embedding failed, searching by keyword only: %r", error)
        return None
    return vector


def _save(engine: sqlalchemy.Engine, *, request: AnswerRequest, progress: _Progress, failed: bool) -> uuid.UUID:
    """Store the answer and give the question, the answer and the chat new positions, so the phone pulls them."""
    segments = list(progress.segments)
    # A block cut off mid-stream has no citations yet; keep its words as background so the owner sees them.
    if progress.partial.strip():
        segments.append(citations.Segment(label=citations.AnswerLabel.BACKGROUND, text=progress.partial, citations=[]))
    message_id = uuid.uuid4()

    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, request.user_id)
        db.add(
            models.Message(
                id=message_id,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                role=models.MessageRole.ASSISTANT.value,
                text="".join(segment.text for segment in segments).strip(),
                segments=[segment.to_wire() for segment in segments],
                web_search=request.web_search,
                status=(models.MessageStatus.FAILED if failed else models.MessageStatus.COMPLETE).value,
                change_seq=changes.next_change_seq(),
            )
        )
        question = db.get_one(models.Message, request.user_message_id)
        question.change_seq = changes.next_change_seq()
        conversation_actions.touch_conversation(db.get_one(models.Conversation, request.conversation_id))
        db.commit()
    return message_id
```

Notes for the implementer: `client.messages.stream` accepts `thinking`, `output_config` and `tool_choice` in SDK 2.4 (check the signature in `anthropic/resources/messages/messages.py` if mypy complains; pass `tool_choice` typed as `anthropic.types.ToolChoiceParam`). Appending `response.content` (SDK block objects, including thinking and web-search blocks) to `messages` is how the SDK expects a turn to be sent back. Line lengths: run `make format`.

- [ ] **Step 7: The route** `services/api/archie_api/ask/routes.py`:

```python
"""`POST /ask/conversations/{id}/messages`: ask a question in a chat and stream the answer as server-sent events.

The first question creates the chat (its title is the question, cut to 60 characters; `about` ties it to an item).
The question is stored before the stream starts. Only whitelisted users may ask: answers spend the owner's keys.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import fastapi
import fastapi.responses
import pydantic
import sqlalchemy
from archie_db import changes, models
from archie_shared import config
from sqlalchemy import orm

from archie_api import deps
from archie_api.ask import answer, context, prompts
from archie_api.sync import conversation_actions

MAX_QUESTION_LENGTH = 4000
_NEEDS_KEY = "needs your own API key"

router = fastapi.APIRouter(prefix="/ask", tags=["ask"])


class AboutIn(pydantic.BaseModel):
    """The item a new chat is about."""

    kind: models.SearchItemKind
    id: uuid.UUID


class AskRequest(pydantic.BaseModel):
    """A question; the phone makes its id so the question it shows is the one the server stores."""

    user_message_id: uuid.UUID
    text: str = pydantic.Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    web_search: bool = False
    about: AboutIn | None = None


@router.post("/conversations/{conversation_id}/messages")
def ask(
    conversation_id: uuid.UUID,
    body: AskRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> fastapi.responses.StreamingResponse:
    """Store the question, then stream the answer (`delta`, `block`, `searching`, then `done` or `error`)."""
    question = " ".join(body.text.split())
    if not question:
        raise fastapi.HTTPException(status_code=422, detail="question is empty")
    if not user.is_whitelisted:
        raise fastapi.HTTPException(status_code=403, detail=_NEEDS_KEY)
    settings = config.Settings()
    if not settings.anthropic_api_key:
        raise fastapi.HTTPException(status_code=503, detail="Ask isn't set up")

    changes.lock_user_writes(db, user.id)
    if db.get(models.Message, body.user_message_id) is not None:
        raise fastapi.HTTPException(status_code=409, detail="message id already used")
    conversation = _conversation(db, user=user, conversation_id=conversation_id, question=question, about=body.about)
    request = answer.AnswerRequest(
        user_id=user.id,
        conversation_id=conversation.id,
        user_message_id=body.user_message_id,
        web_search=body.web_search,
        system=prompts.system_prompt(
            about=context.about_text(db, conversation=conversation), web_required=body.web_search
        ),
        # Read before the question is added, so the history holds only earlier exchanges.
        messages=[*context.history(db, conversation_id=conversation.id), {"role": "user", "content": question}],
        boost=context.boost(db, conversation=conversation),
        anthropic_key=settings.anthropic_api_key,
        openai_key=settings.openai_api_key or None,
    )
    db.add(
        models.Message(
            id=body.user_message_id,
            user_id=user.id,
            conversation_id=conversation.id,
            role=models.MessageRole.USER.value,
            text=question,
            segments=None,
            web_search=body.web_search,
            status=models.MessageStatus.COMPLETE.value,
            change_seq=changes.next_change_seq(),
        )
    )
    conversation_actions.touch_conversation(conversation)
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)

    # Committed before streaming: the stream holds no transaction and saves the answer in its own session.
    db.commit()
    return fastapi.responses.StreamingResponse(
        answer.stream(engine, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _conversation(
    db: orm.Session, *, user: models.User, conversation_id: uuid.UUID, question: str, about: AboutIn | None
) -> models.Conversation:
    """The user's live chat, or a new one with this id; another user's or a deleted chat is a 404."""
    existing = db.get(models.Conversation, conversation_id)
    if existing is not None:
        if conversation_actions.owned_conversation(db, user=user, conversation_id=conversation_id) is None:
            raise fastapi.HTTPException(status_code=404, detail="conversation not found")
        return existing

    conversation = models.Conversation(
        id=conversation_id,
        user_id=user.id,
        title=question[: models.CONVERSATION_TITLE_LENGTH],
        change_seq=changes.next_change_seq(),
    )
    if about is not None:
        _set_about(db, user=user, conversation=conversation, about=about)
    db.add(conversation)
    db.flush()
    return conversation


def _set_about(db: orm.Session, *, user: models.User, conversation: models.Conversation, about: AboutIn) -> None:
    """Tie the new chat to the user's live item, or 404."""
    if about.kind == models.SearchItemKind.SOURCE:
        source = db.get(models.Source, about.id)
        live = source is not None and source.user_id == user.id and source.deleted_at is None
        conversation.about_source_id = about.id
    elif about.kind == models.SearchItemKind.TOPIC_PRIMER:
        primer = db.get(models.TopicPrimer, about.id)
        live = primer is not None and primer.user_id == user.id
        conversation.about_topic_primer_id = about.id
    else:
        take = db.get(models.Take, about.id)
        live = take is not None and take.user_id == user.id and take.deleted_at is None
        conversation.about_take_id = about.id
    if not live:
        raise fastapi.HTTPException(status_code=404, detail="about item not found")
    conversation.about_kind = about.kind.value
```

Mount in `main.py`: `from archie_api.ask import routes as ask_routes`, `app.include_router(ask_routes.router)`.

- [ ] **Step 8: Failing e2e test** `services/api/tests/e2e/test_ask_e2e.py`:

```python
"""Ask through the real API: a library-cited answer, a web-cited answer, a failed stream, and the refusals.

Anthropic is replayed from recorded real responses, in order (`allow_playback_repeats=False`: a multi-round answer
replays round by round). Re-record a cassette by deleting it and running
`uv run pytest services/api/tests/e2e/test_ask_e2e.py --record-mode=once -m postgres` (a few cents of Sonnet 5.5 and
one or two web searches; needs ANTHROPIC_API_KEY). `ask_unauthorized` is recorded with a deliberately wrong key.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_shared import config
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
PASSAGE = (
    "The Fed creates money by buying bonds from banks and paying for them with newly created reserves. "
    "Those reserves sit in the banks' accounts at the Fed; they are not cash in anyone's pocket."
)
QUESTION = "How does the Fed create money, going by what I saved?"


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay (no OpenAI key: keyword search in the tool)."""
    recording.use_recording_api_key(request, monkeypatch)


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=False)


def _ask(authed: httpx.Client, conversation_id: str, **body: Any) -> list[tuple[str, dict[str, Any]]]:
    """POST the question and parse the server-sent events."""
    payload = {"user_message_id": str(uuid.uuid4()), "text": QUESTION, "web_search": False, **body}
    with authed.stream("POST", f"/ask/conversations/{conversation_id}/messages", json=payload, timeout=180) as response:
        assert response.status_code == 200, response.read()
        raw = "".join(response.iter_text())
    events = []
    for chunk in raw.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _seed_source(live_stack: LiveStack, *, user_id: int) -> str:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        url = "https://example.com/fed"
        source = models.Source(
            id=uuid.uuid4(), user_id=user_id, url=url, normalized_url=url, title="How the Fed creates money",
            kind=models.SourceKind.ARTICLE.value, state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value, change_seq=changes.next_change_seq(),
        )
        db.add(source)
        db.flush()
        db.add(
            models.Chunk(
                user_id=user_id, source_id=source.id, owner_kind=models.ChunkOwner.SOURCE_TEXT.value,
                chunk_index=0, text=PASSAGE,
            )
        )
        db.commit()
        source_id = str(source.id)
    engine.dispose()
    return source_id


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _llm_steps(live_stack: LiveStack) -> list[str]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        steps = list(db.scalars(sqlalchemy.select(models.LlmCall.step)))
    engine.dispose()
    return steps


def test_an_answer_from_the_library_cites_the_passage_and_is_saved(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """A library search runs, a block is labelled library with a chip naming the source, and the chat is pulled."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id = _seed_source(live_stack, user_id=_user_id(authed))
    conversation_id = str(uuid.uuid4())

    with _replay(request, "ask_library"):
        events = _ask(authed, conversation_id, about={"kind": "source", "id": source_id})

    names = [name for name, _ in events]
    assert any(name == "searching" and data["kind"] == "library" and data["query"] for name, data in events)
    assert "delta" in names and names[-1] == "done"
    library_blocks = [data for name, data in events if name == "block" and data["label"] == "library"]
    assert library_blocks and any(
        citation["source_id"] == source_id for block in library_blocks for citation in block["citations"]
    )

    rows = _rows(authed)
    [conversation] = rows["conversations"]
    assert (conversation["title"], conversation["about_kind"], conversation["about_source_id"]) == (
        QUESTION[:60], "source", source_id,
    )
    answer = next(message for message in rows["messages"] if message["role"] == "assistant")
    assert (answer["id"], answer["status"]) == (events[-1][1]["message_id"], "complete")
    assert any(segment["label"] == "library" for segment in answer["segments"])
    assert set(_llm_steps(live_stack)) == {"ask"} and len(_llm_steps(live_stack)) >= 2


def test_with_the_globe_on_the_answer_searches_the_web_and_cites_links(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """A web search runs and a block is labelled web with a link chip."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))

    with _replay(request, "ask_web"):
        events = _ask(
            authed, str(uuid.uuid4()), text="What is the Fed's current target range for the federal funds rate?",
            web_search=True,
        )

    assert any(name == "searching" and data["kind"] == "web" for name, data in events)
    web_blocks = [data for name, data in events if name == "block" and data["label"] == "web"]
    assert web_blocks and all(citation["url"].startswith("http") for citation in web_blocks[0]["citations"])
    assert events[-1][0] == "done"


def test_a_failed_stream_ends_with_error_and_is_stored_as_failed(
    live_stack: LiveStack, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorded with a wrong key: Anthropic answers 401, so the answer is stored failed and the question kept."""
    monkeypatch.setenv(config.ANTHROPIC_API_KEY_ENV, "sk-ant-wrong-key")
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))

    with _replay(request, "ask_unauthorized"):
        events = _ask(authed, str(uuid.uuid4()))

    assert events == [("error", {"message": "Didn't finish. Try again"})]
    statuses = {message["role"]: message["status"] for message in _rows(authed)["messages"]}
    assert statuses == {"user": "complete", "assistant": "failed"}


def test_refusals_happen_before_any_model_call(live_stack: LiveStack) -> None:
    """Not whitelisted 403; someone else's or a deleted chat 404; a reused question id 409; a bad about item 404."""
    plain = live_stack.authed(live_stack.sign_in(apple_sub="plain"))
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    other = live_stack.authed(live_stack.sign_in(apple_sub="other", is_whitelisted=True))
    payload = {"user_message_id": str(uuid.uuid4()), "text": "Hi", "web_search": False}
    chat_id = str(uuid.uuid4())
    _seed_chat(live_stack, user_id=_user_id(owner), conversation_id=chat_id, message_id=payload["user_message_id"])

    assert plain.post(f"/ask/conversations/{uuid.uuid4()}/messages", json=payload).status_code == 403
    fresh = {**payload, "user_message_id": str(uuid.uuid4())}
    assert other.post(f"/ask/conversations/{chat_id}/messages", json=fresh).status_code == 404
    assert owner.post(f"/ask/conversations/{uuid.uuid4()}/messages", json=payload).status_code == 409
    bad_about = {**fresh, "about": {"kind": "take", "id": str(uuid.uuid4())}}
    assert owner.post(f"/ask/conversations/{uuid.uuid4()}/messages", json=bad_about).status_code == 404
    assert owner.post(f"/ask/conversations/{uuid.uuid4()}/messages", json={**fresh, "text": "  "}).status_code == 422
    assert _llm_steps(live_stack) == []
```

`_seed_chat(live_stack, *, user_id, conversation_id, message_id)` inserts a conversation and one user message with that id (as Task 1's test file does). Run `-k refusals` first (no cassette needed) — FAIL until Steps 3–7 exist, then PASS.

- [ ] **Step 9: Record and replay.** Record `ask_library` and `ask_web` with the real key (`archie_test_t6`). For `ask_unauthorized`, run that one test in record mode with the real key **unused**: the test sets `sk-ant-wrong-key` after the fixture, so the recorded response is Anthropic's real 401 (the same approach as `services/worker/tests/cassettes/analyze_unauthorized.yaml`). Secret grep all three. Replay the file — PASS. If a recorded answer has no library-labelled block (the model answered from background), that is a prompt problem: tighten `ASK_SYSTEM` (keep its first 60 characters) and re-record; don't loosen the test.

- [ ] **Step 10: Run** `make lint` and the full suite with `archie_test_t6` — pass.

- [ ] **Step 11: Commit.**

```bash
git add services/api
git commit -m "API: Ask streams cited, labelled answers (library tool + web search), saved complete or failed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: API: Make a card (`card-draft` and `cards`)  (tier: standard)

**Files:**
- Create: `services/api/archie_api/ask/card_prompts.py`, `services/api/archie_api/ask/card_routes.py`, `services/api/tests/e2e/test_ask_cards_e2e.py`, `services/api/tests/e2e/cassettes/ask_card_draft.yaml` (recorded)
- Modify: `services/api/archie_api/main.py` (`app.include_router(ask_card_routes.router)`)

**Interfaces:**
- Consumes: Task 1 (`models.Message`, `models.Conversation`, `models.Card.conversation_id/message_id`, `schemas.CardOut`); Task 2 (`llm.CARD_DRAFT_MODELS`, `llm.CARD_DRAFT_STEP`, `llm.complete`).
- Produces: `POST /ask/messages/{message_id}/card-draft` → `{question, answer}`; `POST /ask/cards` → `CardOut` (Global Constraints shapes).
- Depends on: Tasks 1-3.
- Review: no.

- [ ] **Step 1: Test DB** `archie_test_t7`.

- [ ] **Step 2: Failing e2e test** `services/api/tests/e2e/test_ask_cards_e2e.py`:

```python
"""Make a card through the real API: Haiku drafts one card from an answer; saving adds a concept card from the chat.

Re-record `ask_card_draft` by deleting it and running
`uv run pytest services/api/tests/e2e/test_ask_cards_e2e.py --record-mode=once -m postgres` (a fraction of a cent).
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
QUESTION = "How does the Fed actually create money?"
ANSWER = (
    "It buys bonds from banks and pays with newly created reserves. Those reserves sit at the Fed; they aren't "
    "cash in anyone's pocket."
)


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real key while recording, a placeholder on replay."""
    recording.use_recording_api_key(request, monkeypatch)


def _user_id(authed: httpx.Client) -> int:
    return authed.get("/me").json()["user_id"]


def _seed_answer(live_stack: LiveStack, *, user_id: int) -> tuple[str, str]:
    """A chat with one question and its answer; returns the chat id and the answer id."""
    engine = session.engine_for(live_stack.database_url)
    conversation_id, answer_id = uuid.uuid4(), uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        db.add(models.Conversation(id=conversation_id, user_id=user_id, title=QUESTION, change_seq=changes.next_change_seq()))
        db.flush()
        for message_id, role, text in ((uuid.uuid4(), models.MessageRole.USER, QUESTION), (answer_id, models.MessageRole.ASSISTANT, ANSWER)):
            db.add(
                models.Message(
                    id=message_id, user_id=user_id, conversation_id=conversation_id, role=role.value, text=text,
                    segments=None, web_search=False, status=models.MessageStatus.COMPLETE.value,
                    change_seq=changes.next_change_seq(),
                )
            )
            db.flush()
        db.commit()
    engine.dispose()
    return str(conversation_id), str(answer_id)


def test_a_draft_is_one_question_and_answer_from_the_answer(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """One Haiku call, recorded as `card_draft`; the draft's numbers come from the answer."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    _, answer_id = _seed_answer(live_stack, user_id=_user_id(authed))

    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    with recorder.use_cassette("ask_card_draft.yaml", allow_playback_repeats=True):
        response = authed.post(f"/ask/messages/{answer_id}/card-draft")

    assert response.status_code == 200
    draft = response.json()
    assert draft["question"].strip().endswith("?") and draft["answer"].strip()
    assert _llm_steps(live_stack) == ["card_draft"]


def test_saving_adds_a_new_concept_card_from_the_chat(live_stack: LiveStack) -> None:
    """The card reaches the phone through pull with its chat and answer; it starts new, like every new card."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    conversation_id, answer_id = _seed_answer(live_stack, user_id=_user_id(authed))

    response = authed.post("/ask/cards", json={"message_id": answer_id, "question": " Q? ", "answer": "A."})

    assert response.status_code == 200
    card = response.json()
    assert (card["kind"], card["question"], card["fsrs_state"]) == ("concept", "Q?", "new")
    assert (card["conversation_id"], card["message_id"], card["source_id"]) == (conversation_id, answer_id, None)
    pulled = authed.get("/sync/pull", params={"since": 0}).json()["rows"]["cards"]
    assert [row["id"] for row in pulled] == [card["id"]]


def test_refusals(live_stack: LiveStack) -> None:
    """Drafting needs the owner's keys (403); someone else's or an unknown answer is 404; empty fields 422."""
    owner = live_stack.authed(live_stack.sign_in(apple_sub="owner", is_whitelisted=True))
    plain = live_stack.authed(live_stack.sign_in(apple_sub="plain"))
    _, answer_id = _seed_answer(live_stack, user_id=_user_id(owner))

    assert plain.post(f"/ask/messages/{answer_id}/card-draft").status_code == 403
    assert owner.post(f"/ask/messages/{uuid.uuid4()}/card-draft").status_code == 404
    assert plain.post("/ask/cards", json={"message_id": answer_id, "question": "Q?", "answer": "A."}).status_code == 404
    assert owner.post("/ask/cards", json={"message_id": answer_id, "question": "", "answer": "A."}).status_code == 422
    assert _llm_steps(live_stack) == []


def _llm_steps(live_stack: LiveStack) -> list[str]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        steps = list(db.scalars(sqlalchemy.select(models.LlmCall.step)))
    engine.dispose()
    return steps
```

Run — FAIL.

- [ ] **Step 3: Prompt** `services/api/archie_api/ask/card_prompts.py`:

```python
"""The Make a card prompt: one review card drafted from one Ask answer, for the owner to edit before saving."""

from __future__ import annotations

from typing import Any

CARD_DRAFT_SYSTEM = """You draft one spaced-repetition review card from an answer the owner just read in Archie's \
Ask chat.

Pick the single most useful idea in the answer and write:
- question: one short, specific question (under 20 words) that the answer's idea answers. End it with "?".
- answer: the accepted answer in 1-2 plain sentences.
Use only what the answer says: never add a fact, name or number that isn't in it."""

CARD_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
    "required": ["question", "answer"],
    "additionalProperties": False,
}


def card_draft_message(*, question: str | None, answer: str) -> str:
    """The owner's question (when there is one) and the answer to draft from."""
    asked = f"<question>\n{question}\n</question>\n\n" if question else ""
    return f"{asked}<answer>\n{answer}\n</answer>"
```

- [ ] **Step 4: Routes** `services/api/archie_api/ask/card_routes.py`:

```python
"""Make a card from an Ask answer: Haiku drafts it (owner's key, whitelisted only), the owner's edit is saved.

The draft call holds no transaction. A saved card is a `concept` card whose origin is the chat (`conversation_id`),
with `message_id` naming the answer; it starts new, as every new card does, and reaches the phone through pull.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import anthropic
import fastapi
import pydantic
import sqlalchemy
from archie_db import changes, models
from archie_llm import llm
from archie_shared import config, logging
from sqlalchemy import orm

from archie_api import deps
from archie_api.ask import card_prompts
from archie_api.sync import schemas

DRAFT_MAX_TOKENS = 1000
_NEEDS_KEY = "needs your own API key"

router = fastapi.APIRouter(prefix="/ask", tags=["ask"])
_logger = logging.get_logger(logging.LoggerName.API, "ask_cards")


class CardDraftView(pydantic.BaseModel):
    """A drafted card for the owner to edit."""

    question: str
    answer: str


class _Draft(pydantic.BaseModel):
    """The model's JSON."""

    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)


class CardIn(pydantic.BaseModel):
    """The card as the owner edited it."""

    message_id: uuid.UUID
    question: str = pydantic.Field(min_length=1, max_length=500)
    answer: str = pydantic.Field(min_length=1, max_length=2000)


@router.post("/messages/{message_id}/card-draft")
def card_draft(
    message_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> CardDraftView:
    """Draft one card from the answer with Haiku (Sonnet if Haiku gives no usable answer)."""
    if not user.is_whitelisted:
        raise fastapi.HTTPException(status_code=403, detail=_NEEDS_KEY)
    answer = _owned_answer(db, user=user, message_id=message_id)
    user_message = card_prompts.card_draft_message(question=_question_before(db, answer=answer), answer=answer.text)
    context = llm.CallContext(user_id=user.id, source_id=None, job_id=None, step=llm.CARD_DRAFT_STEP)
    api_key = config.Settings().require_anthropic_api_key()
    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)

    # No transaction is held during the model call.
    db.commit()
    try:
        completion = llm.complete(
            engine,
            api_key=api_key,
            context=context,
            models=llm.CARD_DRAFT_MODELS,
            system=card_prompts.CARD_DRAFT_SYSTEM,
            user_message=user_message,
            max_tokens=DRAFT_MAX_TOKENS,
            json_schema=card_prompts.CARD_DRAFT_SCHEMA,
        )
        draft = _Draft.model_validate_json(completion.text)
    except (anthropic.APIError, llm.ModelOutputError, pydantic.ValidationError) as error:
        _logger.warning("Card draft failed: %r", error)
        raise fastapi.HTTPException(status_code=502, detail="draft failed") from error
    return CardDraftView(question=draft.question.strip(), answer=draft.answer.strip())


@router.post("/cards")
def create_card(
    body: CardIn,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.CardOut:
    """Save the owner's card; Review offers it at once."""
    question, answer_text = body.question.strip(), body.answer.strip()
    if not question or not answer_text:
        raise fastapi.HTTPException(status_code=422, detail="card is empty")

    changes.lock_user_writes(db, user.id)
    answer = _owned_answer(db, user=user, message_id=body.message_id)
    card = models.Card(
        id=uuid.uuid4(),
        user_id=user.id,
        conversation_id=answer.conversation_id,
        message_id=answer.id,
        kind=models.CardKind.CONCEPT.value,
        question=question,
        answer=answer_text,
        change_seq=changes.next_change_seq(),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return schemas.CardOut.model_validate(card)


def _owned_answer(db: orm.Session, *, user: models.User, message_id: uuid.UUID) -> models.Message:
    """The user's answer in a live chat, or 404."""
    message = db.get(models.Message, message_id)
    conversation = db.get(models.Conversation, message.conversation_id) if message is not None else None
    is_owned = (
        message is not None
        and conversation is not None
        and conversation.user_id == user.id
        and conversation.deleted_at is None
        and message.role == models.MessageRole.ASSISTANT
        and bool(message.text.strip())
    )
    if not is_owned:
        raise fastapi.HTTPException(status_code=404, detail="answer not found")
    assert message is not None
    return message


def _question_before(db: orm.Session, *, answer: models.Message) -> str | None:
    """The owner's question the answer replied to."""
    return db.scalar(
        sqlalchemy.select(models.Message.text)
        .where(
            models.Message.conversation_id == answer.conversation_id,
            models.Message.role == models.MessageRole.USER.value,
            models.Message.created_at <= answer.created_at,
        )
        .order_by(models.Message.created_at.desc(), models.Message.id.desc())
        .limit(1)
    )
```

Mount in `main.py`: `from archie_api.ask import card_routes as ask_card_routes`, `app.include_router(ask_card_routes.router)`. Make sure `CARD_DRAFT_SYSTEM`'s first 60 characters differ from every other prompt (`rg -n '"""You' services packages` and compare).

- [ ] **Step 5: Record and replay** `ask_card_draft` (`archie_test_t7`; secret grep), replay — PASS. If the recorded draft adds a number the answer lacks, tighten the prompt and re-record.

- [ ] **Step 6: Run** `make lint` and the full suite — pass.

- [ ] **Step 7: Commit.**

```bash
git add services/api
git commit -m "API: Make a card from an Ask answer (Haiku draft, save as a chat card)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: App: Library search over the server, with the passage that matched  (tier: standard)

**Files:**
- Create: `app/src/library/serverSearch.ts`, `app/src/library/serverSearch.test.ts`, `app/src/library/useServerSearch.ts`, `app/src/library/SearchResultsView.tsx`
- Modify: `app/src/library/LibraryList.tsx` (`SearchResults` uses the server's results while online)

**Interfaces:**
- Consumes: `GET /search` (Global Constraints); Task 3's `formatClock` from `@/ask/types`; existing `apiFetch`, `useSession`, `SourceRow`, `ItemRow`, `TakeRow`, `timestampUrl`, `useTakesData`.
- Produces: `serverSearch.ts`: `SEARCH_DEBOUNCE_MS = 300`, `type ServerSearchResult = { itemKind: "source" | "topic_primer" | "take"; itemId: string; title: string; passage: string; ownerKind: OwnerKind; startSeconds: number | null }`, `parseSearchResults(body: unknown): ServerSearchResult[]`, `type SearchState = { status: "idle" | "loading" | "ready" | "failed"; results: ServerSearchResult[] }`, `searchView({ query, online, state }): { mode: "server" | "local"; offlineLine: boolean }`, `createDebouncer(ms: number): { run(task: () => void): void; cancel(): void }`; `useServerSearch(query: string): { view: …; results: ServerSearchResult[] }`.
- Depends on: Tasks 1-3.
- Review: no.

- [ ] **Step 1: Symlink node_modules.**

- [ ] **Step 2: Failing tests** `app/src/library/serverSearch.test.ts`:

```ts
import { createDebouncer, parseSearchResults, searchView } from "./serverSearch";

describe("parseSearchResults", () => {
  it("maps the server's rows and drops malformed ones", () => {
    const body = {
      results: [
        {
          item_kind: "source",
          item_id: "s1",
          title: "Odd Lots",
          passage: "…the Fed doesn't print money…",
          owner_kind: "source_text",
          start_seconds: 1880,
        },
        { item_kind: "mystery", item_id: "x" },
      ],
    };

    expect(parseSearchResults(body)).toEqual([
      {
        itemKind: "source",
        itemId: "s1",
        title: "Odd Lots",
        passage: "…the Fed doesn't print money…",
        ownerKind: "source_text",
        startSeconds: 1880,
      },
    ]);
    expect(parseSearchResults(null)).toEqual([]);
  });
});

describe("searchView", () => {
  const ready = { status: "ready" as const, results: [] };

  it("shows the server's results once they arrive while online", () => {
    expect(searchView({ query: "fed", online: true, state: ready })).toEqual({ mode: "server", offlineLine: false });
  });

  it("keeps on-phone matching while the request runs, without the offline line", () => {
    expect(searchView({ query: "fed", online: true, state: { status: "loading", results: [] } })).toEqual({
      mode: "local",
      offlineLine: false,
    });
  });

  it("falls back to on-phone matching with the offline line when offline or the request failed", () => {
    expect(searchView({ query: "fed", online: false, state: ready })).toEqual({ mode: "local", offlineLine: true });
    expect(searchView({ query: "fed", online: true, state: { status: "failed", results: [] } })).toEqual({
      mode: "local",
      offlineLine: true,
    });
  });
});

describe("createDebouncer", () => {
  it("runs only the last task, 300 ms after the last keystroke", () => {
    jest.useFakeTimers();
    const ran: string[] = [];
    const debouncer = createDebouncer(300);

    debouncer.run(() => ran.push("f"));
    jest.advanceTimersByTime(200);
    debouncer.run(() => ran.push("fe"));
    jest.advanceTimersByTime(299);
    expect(ran).toEqual([]);
    jest.advanceTimersByTime(1);
    expect(ran).toEqual(["fe"]);

    debouncer.run(() => ran.push("fed"));
    debouncer.cancel();
    jest.advanceTimersByTime(1000);
    expect(ran).toEqual(["fe"]);
    jest.useRealTimers();
  });
});
```

Run `cd app && npx jest src/library/serverSearch.test.ts` — FAIL.

- [ ] **Step 3: Pure logic** `app/src/library/serverSearch.ts`:

```ts
import type { OwnerKind } from "@/ask/types";

/** Typing waits this long before asking the server, so a word costs one request, not one per letter. */
export const SEARCH_DEBOUNCE_MS = 300;

export type ServerSearchResult = {
  itemKind: "source" | "topic_primer" | "take";
  itemId: string;
  title: string;
  passage: string;
  ownerKind: OwnerKind;
  startSeconds: number | null;
};

export type SearchState = { status: "idle" | "loading" | "ready" | "failed"; results: ServerSearchResult[] };

const ITEM_KINDS = new Set(["source", "topic_primer", "take"]);

/** The `/search` body as rows; anything malformed is dropped. */
export function parseSearchResults(body: unknown): ServerSearchResult[] {
  const results = (body as { results?: unknown } | null)?.results;
  if (!Array.isArray(results)) return [];
  return results.flatMap((row) => {
    const item = row as Record<string, unknown>;
    if (!ITEM_KINDS.has(item.item_kind as string) || typeof item.item_id !== "string") return [];
    return [
      {
        itemKind: item.item_kind as ServerSearchResult["itemKind"],
        itemId: item.item_id,
        title: String(item.title ?? ""),
        passage: String(item.passage ?? ""),
        ownerKind: item.owner_kind as OwnerKind,
        startSeconds: typeof item.start_seconds === "number" ? item.start_seconds : null,
      },
    ];
  });
}

/**
 * Which results the list shows: the server's once they arrive online; meanwhile, offline, or after a failed request,
 * today's on-phone matching — with the offline line only when the server can't answer.
 */
export function searchView(input: {
  query: string;
  online: boolean;
  state: SearchState;
}): { mode: "server" | "local"; offlineLine: boolean } {
  if (!input.online || input.state.status === "failed") return { mode: "local", offlineLine: true };
  if (input.state.status === "ready") return { mode: "server", offlineLine: false };
  return { mode: "local", offlineLine: false };
}

/** Runs the last task given, `ms` after the last call. */
export function createDebouncer(ms: number): { run(task: () => void): void; cancel(): void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const cancel = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  return {
    run(task) {
      cancel();
      timer = setTimeout(() => {
        timer = null;
        task();
      }, ms);
    },
    cancel,
  };
}
```

Run the test — PASS.

- [ ] **Step 4: The hook** `app/src/library/useServerSearch.ts`:

```ts
import * as Network from "expo-network";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";

import {
  createDebouncer,
  parseSearchResults,
  SEARCH_DEBOUNCE_MS,
  searchView,
  type SearchState,
  type ServerSearchResult,
} from "./serverSearch";

/** The server's search for `query`, 300 ms after typing stops; superseded requests are aborted. */
export function useServerSearch(query: string): {
  view: ReturnType<typeof searchView>;
  results: ServerSearchResult[];
} {
  const session = useSession();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const [state, setState] = useState<SearchState>({ status: "idle", results: [] });
  const debouncer = useRef(createDebouncer(SEARCH_DEBOUNCE_MS));

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed || !online || !session.sessionKey) {
      debouncer.current.cancel();
      setState({ status: "idle", results: [] });
      return;
    }

    const controller = new AbortController();
    setState((previous) => ({ status: "loading", results: previous.results }));
    debouncer.current.run(() => {
      apiFetch(`/search?q=${encodeURIComponent(trimmed)}`, { sessionKey: session.sessionKey, signal: controller.signal })
        .then((body) => setState({ status: "ready", results: parseSearchResults(body) }))
        .catch(() => {
          if (!controller.signal.aborted) setState({ status: "failed", results: [] });
        });
    });
    return () => controller.abort();
  }, [query, online, session.sessionKey]);

  const view = useMemo(() => searchView({ query, online, state }), [query, online, state]);
  return { view, results: state.results };
}
```

- [ ] **Step 5: The rows** `app/src/library/SearchResultsView.tsx`: a `GroupedList` of server results. Each row has `testID={`search-result-${itemId}`}` and is the usual row for its kind plus a quote under it (`testID={`search-quote-${itemId}`}`, `variant="secondary"`, `tone="ink2"`, `numberOfLines={2}`):
  - `source`: look the source up in `data.sources` by id; render `SourceRow` (tapping opens the source page). If `startSeconds !== null`, prefix the quote with `formatClock(startSeconds) + " · "`, and make the quote pressable: when `timestampUrl(source, formatClock(startSeconds))` differs from `source.url`, `Linking.openURL` it (opens the player at that time — Decision 11); otherwise it opens the source page too. A source not on the phone yet renders an `ItemRow` with `artwork={{ imageUrl: null, domain: null, monogram: result.title.slice(0, 1).toUpperCase() }}`, `kicker={{ domain: null }}`, the result's title, meta `""`, pushing `/source/[id]`.
  - `topic_primer`: find the primer in `data.topicPrimers` (current primers) and its topic in `data.topics`; render the same `ItemRow` as `LibraryList`'s `TopicPrimerItem` (kicker suffix `Topic primer`, pushes `/topic/[id]` with the topic id). Not found locally → skip the row.
  - `take`: find it in `useTakesData()`; render `TakeRow` (`now={new Date()}`); not found → skip.
  - `passage` comes from the server already trimmed (about 220 characters, with `…`).

- [ ] **Step 6: Wire into the list.** In `LibraryList.tsx`, `SearchResults` calls `useServerSearch(props.query)`. When `view.mode === "server"`: render `SearchResultsView` with the results, or the existing empty text (`testID="library-search-empty"`, `No matches for “…”`) when there are none. Otherwise render today's local matches exactly as now. When `view.offlineLine`, show above the results `<Text testID="search-offline" variant="secondary" tone="ink3">Offline · searching titles and notes</Text>`.

- [ ] **Step 7: Run** `cd app && npm run typecheck && npx jest` — pass.

- [ ] **Step 8: Commit.**

```bash
git add app/src/library
git commit -m "App: Library search asks the server and shows the passage that matched; offline falls back

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: App: the Ask tab, the chat screen (streaming, labelled sections, chips) and Make a card  (tier: most capable)

**Files:**
- Create: `app/src/ask/stream.ts`, `app/src/ask/stream.test.ts`, `app/src/ask/sections.ts`, `app/src/ask/sections.test.ts`, `app/src/ask/api.ts`, `app/src/ask/useAskAvailable.ts`, `app/src/ask/useChats.ts`, `app/src/ask/useChatSession.ts`, `app/src/ask/ChatRow.tsx`, `app/src/ask/Composer.tsx`, `app/src/ask/AnswerView.tsx`, `app/src/ask/MakeCardSheet.tsx`, `app/src/app/ask/[id].tsx`
- Modify: `app/src/app/(tabs)/ask.tsx`, `app/src/app/_layout.tsx` (`<Stack.Screen name="ask/[id]" />` inside the signed-in guard)

**Interfaces:**
- Consumes: Task 1 (`/me` `is_whitelisted`); Task 3 (`schema.conversations`, `schema.messages`, `deleteConversation`, `@/ask/types`); the API shapes of Tasks 6 and 7 as fixed in Global Constraints (no code from them); the **Chat route** params (Global Constraints).
- Produces: the route `app/src/app/ask/[id].tsx`; `@/ask/sections`: `groupSections`, `chipText`, `applyEvent`, `liveView`, `EMPTY_LIVE`, `relativeTime`, `rowPreview`; `@/ask/stream`: `SseParser`, `streamAnswer`.
- Depends on: Tasks 1-3.
- Review: yes (streaming client, the overlay hand-over to pulled rows, offline and not-whitelisted states).

- [ ] **Step 1: Symlink node_modules.**

- [ ] **Step 2: Failing pure tests.** `app/src/ask/stream.test.ts`:

```ts
import { SseParser } from "./stream";

describe("SseParser", () => {
  it("turns frames into events, across chunk boundaries, and skips unknown or broken ones", () => {
    const parser = new SseParser();

    const first = parser.push('event: delta\ndata: {"block": 0, "text": "It bu');
    const second = parser.push('ys"}\n\nevent: mystery\ndata: {}\n\nevent: block\ndata: {broken\n\n');
    const third = parser.push('event: done\r\ndata: {"message_id": "m2"}\r\n\r\n');

    expect(first).toEqual([]);
    expect(second).toEqual([{ type: "delta", block: 0, text: "It buys" }]);
    expect(third).toEqual([{ type: "done", message_id: "m2" }]);
  });
});
```

`app/src/ask/sections.test.ts`:

```ts
import type { AnswerSegment, LibraryCitation, WebCitation } from "./types";
import { applyEvent, chipText, EMPTY_LIVE, groupSections, liveView, relativeTime, rowPreview } from "./sections";

const library = (overrides: Partial<LibraryCitation> = {}): LibraryCitation => ({
  kind: "library",
  title: "Odd Lots",
  source_id: "s1",
  topic_primer_id: null,
  take_id: null,
  owner_kind: "source_text",
  start_seconds: null,
  quote: null,
  ...overrides,
});
const web: WebCitation = { kind: "web", title: "The Fed", url: "https://www.federalreserve.gov/x", quote: null };

describe("groupSections", () => {
  it("joins consecutive blocks with the same label and drops empty ones", () => {
    const segments: AnswerSegment[] = [
      { label: "library", text: "It buys bonds.", citations: [library({ start_seconds: 1880 })] },
      { label: "library", text: "Reserves sit at the Fed.", citations: [library({ start_seconds: 1880 })] },
      { label: "background", text: "  ", citations: [] },
      { label: "background", text: "Printing is shorthand.", citations: [] },
      { label: "web", text: "About $6.6T.", citations: [web] },
    ];

    expect(groupSections(segments)).toEqual([
      { label: "library", text: "It buys bonds. Reserves sit at the Fed.", citations: [library({ start_seconds: 1880 })] },
      { label: "background", text: "Printing is shorthand.", citations: [] },
      { label: "web", text: "About $6.6T.", citations: [web] },
    ]);
  });
});

describe("chipText", () => {
  it("names the item, with its time, Summary or Primer; a link shows its site", () => {
    expect(chipText(library({ start_seconds: 1880 }))).toBe("Odd Lots · 31:20");
    expect(chipText(library({ owner_kind: "source_summary" }))).toBe("Odd Lots · Summary");
    expect(chipText(library({ owner_kind: "topic_primer", title: "Monetary plumbing" }))).toBe(
      "Monetary plumbing · Primer",
    );
    expect(chipText(library({ owner_kind: "take", title: "My take" }))).toBe("My take");
    expect(chipText(web)).toBe("federalreserve.gov");
  });
});

describe("applyEvent and liveView", () => {
  it("shows streaming text unlabelled until its block ends, then as a labelled section", () => {
    const events = [
      { type: "searching", kind: "library", query: "fed" },
      { type: "delta", block: 0, text: "It buys " },
      { type: "delta", block: 0, text: "bonds." },
    ] as const;
    const streaming = events.reduce(applyEvent, EMPTY_LIVE);

    expect(liveView(streaming)).toEqual({ sections: [], streamingText: "It buys bonds.", searching: null });

    const finished = applyEvent(streaming, { type: "block", block: 0, label: "library", citations: [library()] });
    expect(liveView(finished).sections).toEqual([{ label: "library", text: "It buys bonds.", citations: [library()] }]);
    expect(applyEvent(finished, { type: "done", message_id: "m2" }).messageId).toBe("m2");
    expect(applyEvent(finished, { type: "error", message: "x" }).failed).toBe(true);
  });

  it("shows the searching line until text arrives", () => {
    const live = applyEvent(EMPTY_LIVE, { type: "searching", kind: "web", query: "fed funds rate" });
    expect(liveView(live).searching).toBe("web");
  });
});

describe("relativeTime and rowPreview", () => {
  const now = new Date(2026, 10, 6, 15, 0);

  it("reads like the mock: minutes, hours, Yesterday, weekday, then a date", () => {
    expect(relativeTime(new Date(2026, 10, 6, 14, 55).toISOString(), now)).toBe("5m");
    expect(relativeTime(new Date(2026, 10, 6, 13, 0).toISOString(), now)).toBe("2h");
    expect(relativeTime(new Date(2026, 10, 5, 9, 0).toISOString(), now)).toBe("Yesterday");
    expect(relativeTime(new Date(2026, 10, 3, 9, 0).toISOString(), now)).toBe("Tue");
    expect(relativeTime(new Date(2026, 9, 2, 9, 0).toISOString(), now)).toBe("Oct 2");
  });

  it("previews the last answer's first line after its label", () => {
    const segments: AnswerSegment[] = [{ label: "background", text: "Apple's buybacks run about $90B.\nMore.", citations: [] }];
    expect(rowPreview(segments)).toBe("Background: Apple's buybacks run about $90B.");
    expect(rowPreview([])).toBe("");
  });
});
```

Run `cd app && npx jest src/ask` — FAIL.

- [ ] **Step 3: Pure logic.** `app/src/ask/sections.ts`:

```ts
import { ANSWER_LABEL_TEXT, formatClock, type AnswerLabel, type AnswerSegment, type AskEvent, type Citation } from "./types";

/** A labelled run of an answer: consecutive blocks with the same label shown as one section. */
export type Section = { label: AnswerLabel; text: string; citations: Citation[] };

type LiveBlock = { text: string; label: AnswerLabel | null; citations: Citation[] };

/** An answer as it streams in: blocks so far, the tool running now, and how it ended. */
export type LiveAnswer = {
  blocks: LiveBlock[];
  searching: "library" | "web" | null;
  messageId: string | null;
  failed: boolean;
};

export const EMPTY_LIVE: LiveAnswer = { blocks: [], searching: null, messageId: null, failed: false };

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

/** Sections from an answer's segments: empty text dropped, same-label neighbours joined, each chip once. */
export function groupSections(segments: AnswerSegment[]): Section[] {
  const sections: Section[] = [];
  for (const segment of segments) {
    const text = segment.text.trim();
    if (!text) continue;
    const last = sections.at(-1);
    if (last && last.label === segment.label) {
      last.text = `${last.text} ${text}`;
      last.citations = uniqueCitations([...last.citations, ...segment.citations]);
    } else {
      sections.push({ label: segment.label, text, citations: uniqueCitations(segment.citations) });
    }
  }
  return sections;
}

/** What a citation chip says. */
export function chipText(citation: Citation): string {
  if (citation.kind === "web") return hostOf(citation.url) ?? citation.title;
  if (citation.start_seconds !== null) return `${citation.title} · ${formatClock(citation.start_seconds)}`;
  if (citation.owner_kind === "source_summary") return `${citation.title} · Summary`;
  if (citation.owner_kind === "source_primer" || citation.owner_kind === "topic_primer") {
    return `${citation.title} · Primer`;
  }
  return citation.title;
}

/** One stream event applied to the answer so far. */
export function applyEvent(live: LiveAnswer, event: AskEvent): LiveAnswer {
  switch (event.type) {
    case "delta": {
      const blocks = [...live.blocks];
      const block = blocks[event.block] ?? { text: "", label: null, citations: [] };
      blocks[event.block] = { ...block, text: block.text + event.text };
      return { ...live, blocks, searching: null };
    }
    case "block": {
      const blocks = [...live.blocks];
      const block = blocks[event.block] ?? { text: "", label: null, citations: [] };
      blocks[event.block] = { ...block, label: event.label, citations: event.citations };
      return { ...live, blocks };
    }
    case "searching":
      return { ...live, searching: event.kind };
    case "done":
      return { ...live, messageId: event.message_id, searching: null };
    case "error":
      return { ...live, failed: true, searching: null };
  }
}

/** What the screen shows of a live answer: finished blocks as sections, the block still streaming as plain text. */
export function liveView(live: LiveAnswer): {
  sections: Section[];
  streamingText: string;
  searching: "library" | "web" | null;
} {
  const finished = live.blocks.filter((block): block is LiveBlock & { label: AnswerLabel } => block.label !== null);
  return {
    sections: groupSections(finished.map((block) => ({ label: block.label, text: block.text, citations: block.citations }))),
    streamingText: live.blocks
      .filter((block) => block.label === null)
      .map((block) => block.text)
      .join(""),
    searching: live.searching,
  };
}

/** "5m", "2h", "Yesterday", "Tue", "Oct 2": a chat row's time. */
export function relativeTime(iso: string, now: Date): string {
  const then = new Date(iso);
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 60) return `${Math.max(1, minutes)}m`;
  if (minutes < 24 * 60 && then.getDate() === now.getDate()) return `${Math.floor(minutes / 60)}h`;

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const daysAgo = Math.ceil((startOfToday - then.getTime()) / DAY_MS);
  if (daysAgo <= 1) return "Yesterday";
  if (daysAgo < 7) return WEEKDAYS[then.getDay()];
  return `${MONTHS[then.getMonth()]} ${then.getDate()}`;
}

/** A chat row's second line: the last answer's first line after its label, e.g. "Background: Apple's…". */
export function rowPreview(segments: AnswerSegment[]): string {
  const [first] = groupSections(segments);
  if (!first) return "";
  return `${ANSWER_LABEL_TEXT[first.label]}: ${first.text.split("\n")[0]}`;
}

function uniqueCitations(citations: Citation[]): Citation[] {
  const seen = new Set<string>();
  return citations.filter((citation) => {
    const key =
      citation.kind === "web"
        ? citation.url
        : `${citation.source_id ?? citation.topic_primer_id ?? citation.take_id}:${citation.start_seconds ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function hostOf(url: string): string | null {
  return URL.canParse(url) ? new URL(url).hostname.replace(/^www\./, "") : null;
}
```

Note `groupSections` joins with a space (not a blank line) so a section reads as one paragraph, as in the mock; `rowPreview` splits on `\n` inside the first section's text. Adjust the sections test's expected joined text if you change the joiner — keep code and test in agreement.

`app/src/ask/stream.ts`:

```ts
import { API_URL, ClientError, NetworkError, UnauthorizedError } from "@/api/client";

import type { AboutKind, AskEvent } from "./types";

export type AskBody = {
  user_message_id: string;
  text: string;
  web_search: boolean;
  about: { kind: AboutKind; id: string } | null;
};

const EVENT_TYPES = new Set(["delta", "block", "searching", "done", "error"]);

/** Server-sent events from text chunks that may split a frame anywhere. */
export class SseParser {
  private buffer = "";

  push(chunk: string): AskEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const frames = this.buffer.split("\n\n");
    this.buffer = frames.pop() ?? "";
    return frames.flatMap((frame) => {
      const event = parseFrame(frame);
      return event ? [event] : [];
    });
  }
}

function parseFrame(frame: string): AskEvent | null {
  let name = "";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!EVENT_TYPES.has(name)) return null;
  try {
    return { type: name, ...(JSON.parse(data.join("\n")) as object) } as AskEvent;
  } catch {
    return null;
  }
}

/**
 * Asks the question and calls `onEvent` for each event as it arrives. Expo's global fetch (`expo/fetch`) streams the
 * response body. Throws `UnauthorizedError`, `ClientError` (403/404/409/422) or `NetworkError` (offline, 5xx, a cut
 * connection); the caller treats a thrown stream as a failed answer.
 */
export async function streamAnswer(input: {
  conversationId: string;
  body: AskBody;
  sessionKey: string;
  signal?: AbortSignal;
  onEvent: (event: AskEvent) => void;
}): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/ask/conversations/${input.conversationId}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${input.sessionKey}`,
      },
      body: JSON.stringify(input.body),
      signal: input.signal,
    });
  } catch (error) {
    throw new NetworkError(String(error));
  }
  if (response.status === 401) throw new UnauthorizedError("401 from ask");
  if (response.status >= 500) throw new NetworkError(`${response.status} from ask`);
  if (!response.ok) throw new ClientError(`${response.status} from ask`);

  const reader = response.body?.getReader();
  if (!reader) throw new NetworkError("ask answered without a stream");
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true })).forEach(input.onEvent);
    }
  } catch (error) {
    throw new NetworkError(String(error));
  }
  parser.push(`${decoder.decode()}\n\n`).forEach(input.onEvent);
}
```

`app/src/ask/api.ts`:

```ts
import { apiFetch } from "@/api/client";

export type CardDraft = { question: string; answer: string };

/** Haiku's draft of one card from an answer. */
export async function fetchCardDraft(messageId: string, sessionKey: string): Promise<CardDraft> {
  const body = (await apiFetch(`/ask/messages/${messageId}/card-draft`, { method: "POST", sessionKey })) as CardDraft;
  return { question: String(body.question ?? ""), answer: String(body.answer ?? "") };
}

/** Saves the owner's card; it reaches Review through the next pull. */
export async function saveCard(input: { messageId: string; question: string; answer: string; sessionKey: string }) {
  await apiFetch("/ask/cards", {
    method: "POST",
    sessionKey: input.sessionKey,
    body: { message_id: input.messageId, question: input.question.trim(), answer: input.answer.trim() },
  });
}
```

Run `cd app && npx jest src/ask` — PASS.

- [ ] **Step 4: Data hooks.** `app/src/ask/useAskAvailable.ts`:

```ts
import { useEffect, useState } from "react";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";

// One `/me` per session key: whether the owner's keys pay for this account's Ask doesn't change while signed in.
let cached: { key: string; whitelisted: boolean } | null = null;

/** true / false once `/me` answered; null while unknown (offline at launch), which the screens treat as available. */
export function useAskAvailable(): boolean | null {
  const { sessionKey } = useSession();
  const [available, setAvailable] = useState<boolean | null>(
    cached && cached.key === sessionKey ? cached.whitelisted : null,
  );

  useEffect(() => {
    if (!sessionKey) return;
    if (cached?.key === sessionKey) {
      setAvailable(cached.whitelisted);
      return;
    }
    let live = true;
    apiFetch("/me", { sessionKey })
      .then((me) => {
        const whitelisted = (me as { is_whitelisted?: boolean }).is_whitelisted === true;
        cached = { key: sessionKey, whitelisted };
        if (live) setAvailable(whitelisted);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [sessionKey]);

  return available;
}
```

`app/src/ask/useChats.ts`:

```ts
import { and, asc, desc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import type { ConversationRow, MessageRow } from "./types";

export type ChatListItem = { conversation: ConversationRow; lastAnswer: MessageRow | null };

/** Live chats, newest activity first, each with its latest answer. */
export function useChats(): ChatListItem[] {
  const { data: conversations } = useLiveQuery(
    db
      .select()
      .from(schema.conversations)
      .where(isNull(schema.conversations.deletedAt))
      .orderBy(desc(schema.conversations.updatedAt)),
  );
  const { data: answers } = useLiveQuery(
    db
      .select()
      .from(schema.messages)
      .where(eq(schema.messages.role, "assistant"))
      .orderBy(asc(schema.messages.createdAt)),
  );

  return useMemo(() => {
    const latest = new Map(answers.map((answer) => [answer.conversationId, answer]));
    return conversations.map((conversation) => ({ conversation, lastAnswer: latest.get(conversation.id) ?? null }));
  }, [conversations, answers]);
}

/** One chat and its messages, oldest first. */
export function useChat(conversationId: string): { conversation: ConversationRow | null; messages: MessageRow[] } {
  const { data: conversations } = useLiveQuery(
    db.select().from(schema.conversations).where(eq(schema.conversations.id, conversationId)),
  );
  const { data: messages } = useLiveQuery(
    db
      .select()
      .from(schema.messages)
      .where(and(eq(schema.messages.conversationId, conversationId)))
      .orderBy(asc(schema.messages.createdAt), asc(schema.messages.id)),
  );
  return { conversation: conversations[0] ?? null, messages };
}
```

`app/src/ask/useChatSession.ts` (the in-flight question and its streamed answer, until the pull brings both rows — Decision 7):

```ts
import { randomUUID } from "expo-crypto";
import { useCallback, useEffect, useRef, useState } from "react";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { requestSync } from "@/sync/useSync";

import { applyEvent, EMPTY_LIVE, type LiveAnswer } from "./sections";
import { streamAnswer } from "./stream";
import type { AboutKind, MessageRow } from "./types";

export type PendingQuestion = { userMessageId: string; text: string; webSearch: boolean; live: LiveAnswer };

/**
 * Sending a question and showing its answer as it streams. The overlay stays until the pulled rows hold the question
 * and its answer (or the stream failed and the question arrived), so nothing flickers or shows twice.
 */
export function useChatSession(input: {
  conversationId: string;
  messages: MessageRow[];
  about: { kind: AboutKind; id: string } | null;
}): { pending: PendingQuestion | null; send: (text: string, webSearch: boolean) => void } {
  const { sessionKey } = useSession();
  const [pending, setPending] = useState<PendingQuestion | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  // Hand over to the pulled rows once they hold what the overlay shows.
  useEffect(() => {
    if (!pending) return;
    const hasQuestion = input.messages.some((message) => message.id === pending.userMessageId);
    const hasAnswer = pending.live.messageId !== null && input.messages.some((m) => m.id === pending.live.messageId);
    if (hasQuestion && (hasAnswer || pending.live.failed)) setPending(null);
  }, [input.messages, pending]);

  const send = useCallback(
    (text: string, webSearch: boolean) => {
      const question = text.trim();
      if (!question || !sessionKey || pending) return;

      const userMessageId = randomUUID();
      const update = (change: (live: LiveAnswer) => LiveAnswer) =>
        setPending((current) => (current && current.userMessageId === userMessageId ? { ...current, live: change(current.live) } : current));
      setPending({ userMessageId, text: question, webSearch, live: EMPTY_LIVE });
      controller.current = new AbortController();

      streamAnswer({
        conversationId: input.conversationId,
        // The server reads `about` only when this question creates the chat.
        body: { user_message_id: userMessageId, text: question, web_search: webSearch, about: input.messages.length === 0 ? input.about : null },
        sessionKey,
        signal: controller.current.signal,
        onEvent: (event) => update((live) => applyEvent(live, event)),
      })
        .catch((error) => {
          if (error instanceof UnauthorizedError) void clearSession();
          update((live) => ({ ...live, failed: true, searching: null }));
        })
        .finally(() => requestSync());
    },
    [input.conversationId, input.messages.length, input.about, pending, sessionKey],
  );

  return { pending, send };
}
```

(If the question never reached the server — offline at send — the overlay keeps the failed state until the screen closes; Try again sends it again.)

- [ ] **Step 5: Components.**

`app/src/ask/AnswerView.tsx` — one answer: labelled sections (label `Text variant="kicker" tone="ink2"` with `ANSWER_LABEL_TEXT`, `testID={`answer-section-${label}`}` on the section's `View`), each section's text (`variant="body"`), then its chips (a wrapping row of `Pressable` chips, `testID="answer-chip"`, `theme.colors.press` background, `theme.radii.chip`, `Text variant="secondary"` with `chipText(citation)`); the streaming text (unlabelled `body`); the searching line (`testID="chat-searching"`, `Searching your library…` / `Searching the web…`, `tone="ink3"`). Props: `{ sections: Section[]; streamingText?: string; searching?: "library" | "web" | null; failed?: boolean; onRetry?: () => void; onMakeCard?: () => void; index: number }`. When `failed`: `Text testID="chat-failed"` `Didn't finish. Try again` as a `Pressable` (`testID="chat-retry"`) calling `onRetry`. When `onMakeCard` (a complete stored answer): a secondary `Button` `Make a card` with `testID={`answer-make-card-${index}`}`. Chip press (Decision 11):

```ts
function openCitation(citation: Citation, router: Router): void {
  if (citation.kind === "web") {
    void Linking.openURL(citation.url);
    return;
  }
  if (citation.source_id) {
    const source = db.select().from(schema.sources).where(eq(schema.sources.id, citation.source_id)).get();
    if (source && citation.start_seconds !== null) {
      const atTime = timestampUrl(source, formatClock(citation.start_seconds));
      if (atTime !== source.url) {
        void Linking.openURL(atTime);
        return;
      }
    }
    router.push({ pathname: "/source/[id]", params: { id: citation.source_id } });
    return;
  }
  if (citation.topic_primer_id) {
    const primer = db.select().from(schema.topicPrimers).where(eq(schema.topicPrimers.id, citation.topic_primer_id)).get();
    if (primer) router.push({ pathname: "/topic/[id]", params: { id: primer.topicId } });
    return;
  }
  if (citation.take_id) router.push({ pathname: "/take/[id]", params: { id: citation.take_id } });
}
```

`app/src/ask/Composer.tsx` — a row: `TextField` (`testID="ask-composer-input"`, `multiline`, `placeholder` from props), a globe `Pressable` (`testID="ask-web-toggle"`, `accessibilityLabel="Search the web"`, `Ionicons` `globe-outline`/`globe`, `accessibilityState={{ selected: web }}`, tinted `theme.colors.chrome` when on), and a send `Pressable` (`testID="ask-send"`, `Ionicons` `arrow-up-circle`, disabled while empty or `disabled`). Props `{ placeholder: string; disabled: boolean; disabledLabel?: string; onSend: (text: string, web: boolean) => void; initialWeb?: boolean }`. When `disabled`, render `Text testID="ask-offline" tone="ink3"` with `disabledLabel` (`Ask needs a connection`) instead of the field. Sending clears the field and turns the globe off.

`app/src/ask/ChatRow.tsx` — `Pressable` `testID={`ask-row-${conversation.id}`}` with the title (`headline`, one line), `rowPreview(parseSegments(lastAnswer?.segments ?? null))` (`secondary`, `ink2`, one line) and `relativeTime(conversation.updatedAt, now)` (`secondary`, `ink3`) on the right; pushes `{ pathname: "/ask/[id]", params: { id } }`.

`app/src/ask/MakeCardSheet.tsx` — a `BottomSheet` (`testID="make-card-sheet"`) titled `Make a card` (`headline`); on open it calls `fetchCardDraft(messageId, sessionKey)` and fills two `TextField`s (`testID="card-draft-question"` / `"card-draft-answer"`, labels `Question` / `Answer`, multiline); while drafting both are empty and editable with placeholder `Drafting…`; a failed draft leaves them empty with the line `Couldn't draft one. Write it yourself.` (`tone="ink3"`). `Button` `Save` (`testID="card-draft-save"`, disabled while either field is blank or saving) calls `saveCard`, then `requestSync()`, `haptic("success")`, `onSaved()` and closes. Props `{ messageId: string | null; visible: boolean; onClose: () => void; onSaved: () => void }`.

- [ ] **Step 6: The chat screen** `app/src/app/ask/[id].tsx`:

```tsx
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Network from "expo-network";
import { useEffect, useMemo, useRef, useState } from "react";
import { View } from "react-native";

import { AnswerView } from "@/ask/AnswerView";
import { Composer } from "@/ask/Composer";
import { MakeCardSheet } from "@/ask/MakeCardSheet";
import { groupSections, liveView } from "@/ask/sections";
import { parseSegments, type AboutKind } from "@/ask/types";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { useChat } from "@/ask/useChats";
import { useChatSession } from "@/ask/useChatSession";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Toast } from "@/ui/Toast";

type Params = { id: string; q?: string; web?: string; aboutKind?: AboutKind; aboutId?: string; aboutTitle?: string };

export default function ChatScreen() {
  const theme = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<Params>();
  const { conversation, messages } = useChat(params.id);
  const available = useAskAvailable();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const about = params.aboutKind && params.aboutId ? { kind: params.aboutKind, id: params.aboutId } : null;
  const { pending, send } = useChatSession({ conversationId: params.id, messages, about });
  const [cardFor, setCardFor] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // A question typed on the Ask tab is sent once, when the screen opens.
  const sentFirst = useRef(false);
  useEffect(() => {
    if (sentFirst.current || !params.q || messages.length > 0) return;
    sentFirst.current = true;
    send(params.q, params.web === "1");
  }, [params.q, params.web, messages.length, send]);

  const aboutTitle = params.aboutTitle ?? null;
  const turns = useMemo(() => messages.filter((message) => message.id !== pending?.userMessageId), [messages, pending]);

  return (
    <Screen
      title={conversation?.title ?? "Ask"}
      onBack={router.back}
      footer={
        <View style={{ gap: theme.spacing.sm }}>
          {aboutTitle ? (
            <Text testID="chat-about" variant="secondary" tone="ink2">
              About: {aboutTitle}
            </Text>
          ) : null}
          {available === false ? (
            <Text testID="ask-unavailable" tone="ink2">
              Ask isn't available on this account
            </Text>
          ) : (
            <Composer
              placeholder="Ask a follow-up"
              disabled={!online}
              disabledLabel="Ask needs a connection"
              onSend={send}
            />
          )}
        </View>
      }
    >
      <View testID="chat-screen" style={{ gap: theme.spacing.lg }}>
        {turns.map((message, index) =>
          message.role === "user" ? (
            <UserBubble key={message.id} text={message.text} index={index} />
          ) : (
            <AnswerView
              key={message.id}
              index={index}
              sections={groupSections(parseSegments(message.segments))}
              failed={message.status === "failed"}
              onRetry={() => retry(turns, index, send)}
              onMakeCard={message.status === "complete" ? () => setCardFor(message.id) : undefined}
            />
          ),
        )}
        {pending ? (
          <>
            <UserBubble text={pending.text} index={turns.length} />
            <AnswerView
              index={turns.length + 1}
              {...liveView(pending.live)}
              failed={pending.live.failed}
              onRetry={() => send(pending.text, pending.webSearch)}
            />
          </>
        ) : null}
      </View>
      <MakeCardSheet
        messageId={cardFor}
        visible={cardFor !== null}
        onClose={() => setCardFor(null)}
        onSaved={() => setToast("Card added to Review")}
      />
      {toast ? <Toast message={toast} onHide={() => setToast(null)} /> : null}
    </Screen>
  );
}

/** Try again on a stored failed answer: send its question again, with the globe as it was. */
function retry(
  turns: { role: string; text: string; webSearch: number }[],
  answerIndex: number,
  send: (text: string, web: boolean) => void,
): void {
  const question = turns.slice(0, answerIndex).findLast((turn) => turn.role === "user");
  if (question) send(question.text, question.webSearch === 1);
}

function UserBubble({ text, index }: { text: string; index: number }) {
  const theme = useTheme();
  return (
    <View
      testID={`chat-user-${index}`}
      style={{
        alignSelf: "flex-end",
        maxWidth: "85%",
        backgroundColor: theme.colors.press,
        borderRadius: theme.radii.card,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
      }}
    >
      <Text>{text}</Text>
    </View>
  );
}
```

`AnswerView` receives `testID={`chat-answer-${index}`}` on its root. The pending overlay's question is hidden from `turns` once pulled, so it never shows twice. Register the route in `app/src/app/_layout.tsx` (`<Stack.Screen name="ask/[id]" />`, inside the signed-in guard).

- [ ] **Step 7: The Ask tab** `app/src/app/(tabs)/ask.tsx`:

```tsx
import { randomUUID } from "expo-crypto";
import * as Network from "expo-network";
import { useRouter } from "expo-router";
import { View } from "react-native";

import { ChatRow } from "@/ask/ChatRow";
import { Composer } from "@/ask/Composer";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { useChats } from "@/ask/useChats";
import { deleteConversation } from "@/db/actions";
import { db } from "@/db/client";
import { SwipeRow } from "@/library/SwipeRow";
import { requestSync } from "@/sync/useSync";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { useNow } from "@/ui/useNow";

export default function AskScreen() {
  const router = useRouter();
  const chats = useChats();
  const available = useAskAvailable();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const now = useNow();

  if (available === false) {
    return (
      <Screen title="Ask">
        <Text testID="ask-unavailable" tone="ink2">
          Ask isn't available on this account
        </Text>
      </Screen>
    );
  }

  return (
    <Screen
      title="Ask"
      footer={
        <Composer
          placeholder="Ask about anything"
          disabled={!online}
          disabledLabel="Ask needs a connection"
          onSend={(text, web) =>
            router.push({ pathname: "/ask/[id]", params: { id: randomUUID(), q: text, web: web ? "1" : "0" } })
          }
        />
      }
    >
      {chats.length === 0 ? (
        <Text testID="ask-empty" tone="ink2">
          Ask a question about anything you've saved.
        </Text>
      ) : (
        <View testID="ask-list">
          <GroupedList>
            {chats.map(({ conversation, lastAnswer }) => (
              <SwipeRow
                key={conversation.id}
                actions={[
                  {
                    key: "delete",
                    label: "Delete",
                    tone: "missed",
                    testID: `swipe-delete-chat-${conversation.id}`,
                    onPress: () => {
                      deleteConversation(db, conversation.id);
                      haptic("success");
                      requestSync();
                    },
                  },
                ]}
              >
                <ChatRow conversation={conversation} lastAnswer={lastAnswer} now={now} />
              </SwipeRow>
            ))}
          </GroupedList>
        </View>
      )}
    </Screen>
  );
}
```

Check `Screen`'s `footer` placement above the tab bar (the Ask tab is inside `(tabs)`, whose `TabBarInsetContext` keeps the footer clear of the bar); if the footer sits under the bar, pad it with the `TabBarInsetContext` value.

- [ ] **Step 8: Run** `cd app && npm run typecheck && npx jest` — pass. Start nothing on a simulator (the coordinator runs Maestro in Task 11).

- [ ] **Step 9: Commit.**

```bash
git add app/src/ask app/src/app
git commit -m "App: Ask tab and chat screen with streamed, labelled, cited answers and Make a card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: App: "Ask about this" in the source, topic and take ••• menus  (tier: standard)

**Files:**
- Create: `app/src/ask/openChat.ts`
- Modify: `app/src/item/ItemMenu.tsx`, `app/src/topics/TopicMenu.tsx`, `app/src/app/topic/[id].tsx`, `app/src/takes/TakeMenus.tsx`

**Interfaces:**
- Consumes: the **Chat route** (Global Constraints) — the screen itself comes from Task 9; this task only pushes the pathname. `AboutKind` from Task 3.
- Produces: `openChat(router: Router, about: { kind: AboutKind; id: string; title: string }): void`.
- Depends on: Tasks 1-3.
- Review: no.

- [ ] **Step 1: Symlink node_modules.**

- [ ] **Step 2: The helper** `app/src/ask/openChat.ts`:

```ts
import { randomUUID } from "expo-crypto";
import type { Router } from "expo-router";

import type { AboutKind } from "./types";

/** A new chat about one item (Ask about this): its passages rank first and the composer shows "About: <title>". */
export function openChat(router: Router, about: { kind: AboutKind; id: string; title: string }): void {
  router.push({
    pathname: "/ask/[id]",
    params: { id: randomUUID(), aboutKind: about.kind, aboutId: about.id, aboutTitle: about.title },
  });
}
```

(`Router` is exported by expo-router 58 as a type; if not, type the parameter as `ReturnType<typeof useRouter>`.)

- [ ] **Step 3: Source menu.** In `ItemMenu.tsx` add a first group row (above `Remind me later…`, ending its own group so `Remind me later…` gets `startsGroup: true`):

```ts
    {
      testID: "menu-ask",
      label: "Ask about this",
      onPress: () => openChat(router, { kind: "source", id: source.id, title: source.title ?? source.url }),
    },
```

and update the component's doc comment's grouping list (`[Ask about this] [Remind me later…, …] …`).

- [ ] **Step 4: Topic menu.** `TopicMenu` gains an optional prop `askPrimer?: { id: string; title: string }` (set by the topic page only, when the topic has a current primer). When set, the first row is `{ label: "Ask about this", testID: "topic-menu-ask", onPress: () => openChat(router, { kind: "topic_primer", id: askPrimer.id, title: askPrimer.title }) }`. In `app/src/app/topic/[id].tsx` pass `askPrimer={primer ? { id: primer.id, title: topic.name } : undefined}` using the page's current primer row (the page already reads it for its primer toggle; reuse that variable). Chip long-press menus elsewhere pass nothing, so they are unchanged.

- [ ] **Step 5: Take menu.** In `TakeMenus.tsx` the first row is `{ label: "Ask about this", testID: "take-menu-ask", onPress: () => openChat(router, { kind: "take", id: take.id, title: take.title }) }` (add `const router = useRouter();`), and `Change kind` gets `startsGroup: true`.

`MenuSheet` runs a row's `onPress` after the sheet has dismissed (see its existing comment), so pushing a route from it is safe.

- [ ] **Step 6: Run** `cd app && npm run typecheck && npx jest` — pass (typed routes aren't generated in a worktree, so the `/ask/[id]` pathname typechecks without Task 9's file).

- [ ] **Step 7: Commit.**

```bash
git add app/src/ask/openChat.ts app/src/item/ItemMenu.tsx app/src/topics/TopicMenu.tsx "app/src/app/topic/[id].tsx" app/src/takes/TakeMenus.tsx
git commit -m "App: Ask about this in the source, topic and take menus

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Integration task (serial, in `m7-ask`, after Tasks 4–10 are merged)

### Task 11: Merge check, Maestro flows, docs, full verification  (tier: standard; Maestro runs by the coordinator)

**Files:**
- Modify: `maestro/library_search.yaml`, `Makefile`, `maestro/README.md`, `docs/superpowers/specs/2026-10-26-product-scope.md`, `docs/superpowers/specs/2026-11-02-backend-architecture-design.md`, `docs/deploy.md`
- Create: `maestro/ask.yaml`

**Interfaces:**
- Consumes: everything above (testIDs in Global Constraints).
- Depends on: Tasks 1-10.
- Review: no.

- [ ] **Step 1: Merge.** Merge each task branch into `m7-ask` (`git merge m7-t<N>` for N = 4…10); resolve the textual overlaps (`main.py` router includes; `_layout.tsx`). Remove the task worktrees with `git gtr rm m7-t<N> --delete-branch`.

- [ ] **Step 2: Suites.** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t11` (ignore "already exists"); `make lint`; `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t11 uv run pytest -m "postgres or not postgres"` — all pass with every cassette replaying; `cd app && npm run typecheck && npx jest` — pass. `make scaffold` lists nothing new.

- [ ] **Step 3: `maestro/library_search.yaml`** — keep its add-and-wait steps, then check the server's quote (the article's text is indexed when it is fetched, with no keys — Decision 2):

```yaml
- tapOn:
    id: "library-search"
- inputText: "work hard"
# Keyword search runs on the server once typing stops; the passage that matched shows under the row.
- extendedWaitUntil:
    visible:
      id: "search-quote-.*"
    timeout: 15000
    optional: true
# The embed job may not have run yet: type the query again to search once more.
- runFlow:
    when:
      notVisible:
        id: "search-quote-.*"
    commands:
      - eraseText
      - inputText: "work hard"
      - extendedWaitUntil:
          visible:
            id: "search-quote-.*"
          timeout: 15000
- assertVisible: ".*How to Work Hard.*"
- eraseText
- inputText: "zzqx nothing"
- extendedWaitUntil:
    visible:
      id: "library-search-empty"
    timeout: 10000
```

- [ ] **Step 4: `maestro/ask.yaml`** (paid: a few cents of Sonnet, Haiku and embeddings; own target):

```yaml
# Ask: finish an article, ask about it on the Ask tab, see a YOUR LIBRARY section, Make a card, and find the chat in
# the list. Needs the owner's keys in .env (analyze, embeddings, Sonnet 5.5 and one Haiku draft: a few cents); local
# backend only; run it through `make maestro-ask`.
appId: com.sampocs.archie
---
- runFlow: login.yaml
- openLink: archie://dev/login?whitelisted=1
- extendedWaitUntil:
    visible: "Open"
    timeout: 5000
    optional: true
- tapOn:
    text: "Open"
    optional: true
- extendedWaitUntil:
    visible: "Library"
    timeout: 15000
- tapOn:
    id: "library-add"
- runFlow:
    when:
      notVisible:
        id: "add-url"
    commands:
      - tapOn:
          id: "library-add"
- extendedWaitUntil:
    visible:
      id: "add-url"
    timeout: 5000
- tapOn:
    id: "add-url"
- inputText: "https://paulgraham.com/greatwork.html"
- tapOn:
    id: "intent-finished"
- tapOn:
    id: "add-save"
- extendedWaitUntil:
    visible: ".*How to Do Great Work.*"
    timeout: 90000
# Give analyze and embed time to index the summary (the Library row's status settles when analyze is done).
- extendedWaitUntil:
    notVisible: ".*Processing.*"
    timeout: 120000
- tapOn:
    id: "tab-ask"
- tapOn:
    id: "ask-composer-input"
- inputText: "What does Paul Graham say about choosing what to work on, from what I saved?"
- tapOn:
    id: "ask-send"
- extendedWaitUntil:
    visible:
      id: "chat-screen"
    timeout: 5000
- extendedWaitUntil:
    visible:
      id: "answer-section-library"
    timeout: 120000
- extendedWaitUntil:
    visible:
      id: "answer-make-card-.*"
    timeout: 60000
- tapOn:
    id: "answer-make-card-.*"
- extendedWaitUntil:
    visible:
      id: "card-draft-question"
    timeout: 5000
# The draft fills both fields; Save is enabled once it has.
- extendedWaitUntil:
    visible:
      id: "card-draft-save"
      enabled: true
    timeout: 30000
- tapOn:
    id: "card-draft-save"
- extendedWaitUntil:
    notVisible:
      id: "card-draft-question"
    timeout: 10000
- assertVisible: "Card added to Review"
- tapOn:
    id: "screen-back"
- extendedWaitUntil:
    visible:
      id: "ask-row-.*"
    timeout: 15000
```

Check the add sheet's intent testIDs (`intent-finished` / `intent-queue`) and the back button's testID against `maestro/review.yaml` and `Screen.tsx`, and use what they use.

- [ ] **Step 5: Makefile and README.** Add

```make
# Ask: answers, embeddings and a card draft spend real API credits (a few cents); see maestro/README.md.
maestro-ask: reset-local-data
	@PATH="$(MAESTRO_PATH)" maestro test maestro/ask.yaml
```

add `maestro-ask` to `.PHONY`; in `maestro/README.md` list `ask.yaml` (paid, `make maestro-ask`) and say `library_search.yaml` now checks the server's quote. Add `make maestro-ask` to the AGENTS.md Commands bullet that lists the paid flows.

- [ ] **Step 6: Docs.** Product scope ("Carl (chat)") and the architecture doc ("Search and chat"): point at the M7 spec as what shipped — saved, synced chats; labels from citations; Make a card; Ask about this in the ••• menus; Sonnet 5.5 with `between_tools` thinking; `text-embedding-3-small`; indexing at fetch time (Decision 2). `docs/deploy.md`: after deploying M7, run `railway ssh` (or the project's documented way to run a one-off command) `archie-worker backfill-embed` once; `OPENAI_API_KEY` is already set.

- [ ] **Step 7: Coordinator: Maestro from the main checkout.** Check out `m7-ask` in the main checkout (or use `free-up-main` if needed), `make migrate-local`, `make start-local` in one terminal, then `make maestro` (all free flows, including the new `library_search.yaml`) and `make maestro-ask`. Fix what fails in `m7-ask` and re-run.

- [ ] **Step 8: Commit.**

```bash
git add maestro Makefile AGENTS.md docs
git commit -m "M7: Maestro search and Ask flows, maestro-ask target, docs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Self-review notes

- **Spec coverage:** indexing of every owner kind (T4: text, summary, primer, topic primer, take; collections never); unread inbox items (indexed at fetch, whatever their state); deleted items excluded (T2 joins, T4 liveness); Library search online/offline (T8); saved, listed, synced, deletable chats (T1, T3, T9); labels from citations with search_result blocks and the web tool (T6, T9); Make a card with a fifth origin (T1, T7, T9, T3 Review kicker "From Ask"); Ask about this in the three ••• menus, not the primer screen (T10, about context and boost in T6); whitelist (T5, T6, T7, phone states in T9); models (Global Constraints); titles cut to 60 (T6); embeddings and costs (T2, T4); backfill (T4, deploy note T11); `/search` steps 1–4 and response (T2, T5); the stream events, 5 rounds, history of 20, failed status and retry (T6, T9); card draft/create (T7); `delete_conversation` (T1, T3); `llm_calls` steps (T2, T6, T7); tests listed in the spec (T2, T4, T5, T6, T7 Python; T3, T8, T9 jest; T11 Maestro).
- **Recorded cassettes** (each by its task's executor, with the command in Global Constraints): `packages/archie-llm/tests/cassettes/embeddings_two_texts.yaml` (T2, OpenAI), `services/worker/tests/cassettes/embed_article.yaml` (T4, OpenAI), `services/api/tests/e2e/cassettes/search_query.yaml` (T5, OpenAI), `ask_library.yaml`, `ask_web.yaml`, `ask_unauthorized.yaml` (T6, Anthropic; the last with a deliberately wrong key), `ask_card_draft.yaml` (T7, Anthropic).
- **Prompt prefixes:** `ASK_SYSTEM` ("You are Archie's Ask, answering the owner's questions from th…") and `CARD_DRAFT_SYSTEM` ("You draft one spaced-repetition review card from an answer t…") differ from every existing prompt's first 60 characters.
