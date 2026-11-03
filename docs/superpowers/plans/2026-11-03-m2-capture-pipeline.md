# Milestone 2 Capture → Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The user shares an article from Safari or a post from X through the iOS share sheet and, minutes later, reads its summary, primer and cards in Library.

**Architecture:**
- Backend: `add_source` classifies and de-duplicates the URL and stores any Safari capture; the worker runs `fetch_content` → (`analyze`, `primer`) as jobs; model output lands in versioned `source_artifacts` and `cards`, every model call in `llm_calls`; pull returns sources, artifacts and cards by one change position.
- App: the local DB gains artifacts and cards; Library shows processing status and Retry; an item page shows the summary, primer and cards; a share extension posts `add_source` straight to the API using the session key from a shared Keychain group.

**Tech Stack:** as M1, plus `anthropic` (Python SDK), `trafilatura`, `python-dotenv` (tests only), `expo-share-extension`.

**Spec:** `docs/superpowers/specs/2026-11-03-m2-capture-pipeline-design.md`. Read it before any task: it is the source of truth for behavior; this plan is the order, the shapes and the names.

## Global Constraints

- **Python style:** the house style in `AGENTS.md` (module-qualified imports, full typing with `X | None`, `StrEnum`s, dataclasses over tuples of >2, named parameters, guard clauses, blank-line paragraphs past ~8 lines, why-comments only, docstrings on public functions/classes).
- **Tests:** e2e first; a unit test only for logic that could plausibly be wrong; outside calls replayed from recorded real responses (cassettes), never hand-written bodies. The one allowed edit is the refusal cassette (Task 7), which says so in a comment.
- **Never print secrets** or `.env` values. Cassettes must not contain `x-api-key`, `authorization`, `cookie` or `set-cookie` headers — check with `grep -ril "x-api-key\|sk-ant" <cassette dir>` returning nothing before committing.
- **Models:** analyze `claude-haiku-5-5` → fallback `claude-sonnet-5-5`; primer `claude-sonnet-5-5` → fallback `claude-opus-5-5`. Max output tokens: analyze 8000, primer 6000. Prices per M tokens (in/out): Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10, Opus 5.5 $4/$20.
- **Limits:** model input text capped at 200,000 characters; capture text ≤ 400,000 characters, capture title ≤ 500; note ≤ 2,000; article page fetch 15 s total, 5 MB; article needs ≥ 50 words, X ≥ 1 word.
- **Sync:** ≤ 50 actions per push; ≤ 500 rows per pull page across all tables; every write to a synced row (sources, source_artifacts with kind summary/primer, cards) happens after `changes.lock_user_writes` and sets `change_seq = changes.next_change_seq()`.
- **Payload keys** on the wire are snake_case (`prep_me`, `processing_error`, `merged_into_id`, `source_id`, `is_current`).
- **Keychain group:** `3W3H65F89G.com.sampocs.archie.shared`. **Bundle ids:** app `com.sampocs.archie`, extension whatever `expo-share-extension` generates (`com.sampocs.archie.ShareExtension`).
- **Commits:** every message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MN7nukQAsqfkk3GiAq6NkX
  ```
- **Branch:** `m2-pipeline` (worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/m2-pipeline`). Wave tasks get their own worktrees branched from the last foundation commit.
- **Checks before every commit:** `make lint` and the relevant tests; `make test-db` needs `make db-up` (local Postgres on 5434). App: `cd app && npm run typecheck && npm test`.

---

## File Structure

```
packages/archie-shared/archie_shared/urls.py        normalize_url, detect_kind, x_post_id          (T1)
packages/archie-shared/archie_shared/config.py      + anthropic_api_key                           (T1)
packages/archie-db/archie_db/models.py              new enums, columns, tables                     (T1)
packages/archie-db/archie_db/migrations/versions/0002_capture_pipeline.py                         (T1)
packages/archie-db/archie_db/pipeline.py            artifact versions, processing status, steps   (T2)
services/worker/archie_worker/loop.py               HandlerSpec, PermanentJobError, hooks          (T2)
services/worker/archie_worker/errors.py             PermanentJobError, reasons                    (T2)
services/worker/archie_worker/llm.py                model calls, fallback, llm_calls, prices       (T3)
packages/archie-testing/archie_testing/recording.py VCR config + recording key                    (T3)
app/src/db/schema.ts, actions.ts, app/drizzle/0001_*.sql, app/src/sync/{engine,transport}.ts     (T4)
app/src/capture/{CaptureOptions.tsx, extractUrl.ts}                                               (T4)
services/api/archie_api/sync/{actions,pull,schemas}.py, sync/capture.py                           (T5)
services/worker/archie_worker/handlers/fetch_content.py, archie_worker/content/{article,x}.py     (T6)
services/worker/archie_worker/handlers/{analyze,primer}.py, archie_worker/prompts.py              (T7)
app/src/app/(tabs)/{library,add}.tsx, app/src/app/source/[id].tsx, app/src/app/share.tsx,
  app/src/ui/Markdown.tsx                                                                         (T8)
app/index.share.tsx, app/src/share/{ShareSheet.tsx,submit.ts}, app/preprocessing.js,
  app/plugins/withSharedKeychain.js, app/src/auth/session.ts, app/app.config.ts                   (T9)
services/api/tests/e2e/test_pipeline_e2e.py, maestro/source_page.yaml, .railway/railway.ts, docs  (T10)
```

## Foundation tasks (run serially)

### Task 1: URLs, settings, schema and migration

**Files:**
- Create: `packages/archie-shared/archie_shared/urls.py`, `packages/archie-shared/tests/test_urls.py`
- Modify: `packages/archie-shared/archie_shared/config.py`, `packages/archie-db/archie_db/models.py`, `conftest.py` (`_TRUNCATE_TABLES`), `.env.example`
- Create: `packages/archie-db/archie_db/migrations/versions/0002_capture_pipeline.py`

**Interfaces:**
- Produces:
  - `archie_shared.urls.normalize_url(url: str) -> str`
  - `archie_shared.urls.detect_kind(url: str) -> archie_shared.urls.UrlKind` where `UrlKind(StrEnum)`: `ARTICLE="article"`, `X="x"`, `YOUTUBE="youtube"`, `PODCAST="podcast"` (models' `SourceKind` uses the same values plus `LINK`; `archie_shared` can't import `archie_db`)
  - `archie_shared.urls.x_post_id(url: str) -> str | None`
  - `Settings.anthropic_api_key: str | None` and `Settings.require_anthropic_api_key() -> str` (raises `ConfigError`)
  - In `models`: `SourceKind` + `ARTICLE, X, YOUTUBE, PODCAST`; `ProcessingStatus(StrEnum)`: `PENDING, PROCESSING, READY, FAILED, UNSUPPORTED`; `Reaction(StrEnum)`: `EASY="easy", MOSTLY="mostly", LOST="lost"`; `ArtifactKind(StrEnum)`: `TEXT, SUMMARY, PRIMER`; `CardKind(StrEnum)`: `CONCEPT, MECHANISM, NUMBER`; `JobKind` + `FETCH_CONTENT="fetch_content", ANALYZE="analyze", PRIMER="primer"`; `SYNCED_ARTIFACT_KINDS = frozenset({ArtifactKind.SUMMARY, ArtifactKind.PRIMER})`
  - Tables below.
- Review: yes (migration).

**Columns** (all names exact):
- `sources` adds: `processing String(16) NOT NULL server_default 'pending'`, `processing_error Text NULL`, `reaction String(16) NULL`, `note Text NULL`, `prep_me Boolean NOT NULL server_default false`, `normalized_url String(2048) NOT NULL` (migration: add nullable, `UPDATE sources SET normalized_url = url`, set NOT NULL; also `UPDATE sources SET processing = 'unsupported'` for existing rows, which are M1 `link` rows), `merged_into_id UUID NULL FK sources.id`. Index `ix_sources_user_id_normalized_url` on (user_id, normalized_url).
- `source_captures`: `source_id UUID PK FK sources.id ON DELETE CASCADE`, `title Text NULL`, `text Text NOT NULL`, `created_at`.
- `source_artifacts`: `id UUID PK`, `user_id BigInteger FK users CASCADE`, `source_id UUID FK sources CASCADE`, `kind String(16)`, `version Integer`, `content JSONB`, `is_current Boolean`, `model String(64) NULL`, `prompt_version String(32) NULL`, `derived_from_id UUID NULL FK source_artifacts.id`, `instruction Text NULL`, `created_at`, `change_seq BigInteger`. Unique (source_id, kind, version). Partial unique index `uq_source_artifacts_current` on (source_id, kind) `WHERE is_current`. Index (user_id, change_seq).
- `cards`: `id UUID PK`, `user_id`, `source_id FK CASCADE`, `artifact_id UUID FK source_artifacts`, `kind String(16)`, `question Text`, `answer Text`, `created_at`, `updated_at`, `deleted_at NULL`, `change_seq`. Index (user_id, change_seq).
- `llm_calls`: `id BigInteger Identity PK`, `user_id FK CASCADE`, `source_id UUID NULL FK sources ON DELETE SET NULL`, `job_id BigInteger NULL FK jobs ON DELETE SET NULL`, `step String(32)`, `provider String(16)`, `model String(64)`, `input_tokens Integer`, `output_tokens Integer`, `cost_usd Numeric(12, 6)`, `stop_reason String(32) NULL`, `created_at`. Index (user_id, created_at).

**URL rules** (from the spec, verbatim): lowercase scheme and host; drop leading `www.`, `mobile.`, `m.`; drop the fragment; drop query params `utm_*`, `si`, `s`, `t`, `ref`, `fbclid`, `gclid`; drop a trailing `/` from the path; X URLs (`x.com`, `twitter.com`, any of those prefixes) with `/status/<id>` or `/article/<id>` normalize to `https://x.com/i/status/<id>`. Kinds: X host + post id → `x`; `youtube.com`, `youtu.be` → `youtube`; `open.spotify.com`, `podcasts.apple.com` → `podcast`; else `article`. An X host without a post id (a profile) is `article`.

- [ ] **Step 1: Write `test_urls.py`** (unit, no DB). Cases, one test each:
  - `normalize_url("https://WWW.Example.com/a/?utm_source=x&id=3#frag") == "https://example.com/a?id=3"`
  - Spotify share text noise: `normalize_url("https://open.spotify.com/episode/abc?si=123&utm_source=native-share-menu") == "https://open.spotify.com/episode/abc"`
  - `normalize_url("https://twitter.com/sama/status/2107691261776052633?s=20") == "https://x.com/i/status/2107691261776052633"`, and the `mobile.x.com` and `/article/2033603974675227095` forms
  - Query order of kept params is preserved
  - `detect_kind` for each kind, including `https://x.com/naval` → `article` and `https://youtu.be/xyz` → `youtube`
  - `x_post_id` returns the id for status and article URLs, None otherwise
- [ ] **Step 2: Run** `uv run pytest packages/archie-shared/tests/test_urls.py` — fails (module missing).
- [ ] **Step 3: Implement `urls.py`** with `urllib.parse`; constants for the dropped params and host prefixes. Run the tests — pass.
- [ ] **Step 4: Settings.** Add `anthropic_api_key: str | None = None` and `require_anthropic_api_key()` matching `require_database_url`'s style; add `ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"` and use it in root `conftest.py`'s `_SECRET_ENV_VARS` (replacing the literal). Add `ANTHROPIC_API_KEY=` with a comment to `.env.example`.
- [ ] **Step 5: Models and migration.** Add enums, columns and the four new tables to `models.py` (follow the existing docstring style: each class says *why*). Write `0002_capture_pipeline.py` by hand (match `0001_initial.py`'s style), including the backfill updates. Add `source_captures, source_artifacts, cards, llm_calls` to the front of `_TRUNCATE_TABLES` in `conftest.py`.
- [ ] **Step 6: Run** `make db-up && make test-db` — `test_db_migrations.py` (models match migrations) and every M1 test pass. Also `uv run alembic downgrade -1` then upgrade works if the M1 migration supports downgrade (write `downgrade()` for 0002).
- [ ] **Step 7: Commit** "Schema for the capture pipeline: artifacts, cards, captures, llm_calls; URL normalizing".

### Task 2: Worker contract and pipeline helpers

**Files:**
- Create: `packages/archie-db/archie_db/pipeline.py`, `packages/archie-db/tests/test_pipeline.py`
- Create: `services/worker/archie_worker/errors.py`
- Modify: `services/worker/archie_worker/loop.py`, `services/worker/archie_worker/handlers/__init__.py`, `services/worker/archie_worker/handlers/fetch_title.py`, `services/worker/tests/test_worker_e2e.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces:
  - `archie_db.pipeline.SOURCE_ID_KEY = "source_id"` (job payload key; `fetch_title.SOURCE_ID_KEY` re-exports or uses it)
  - `pipeline.current_artifact(db, *, source_id: uuid.UUID, kind: models.ArtifactKind) -> models.SourceArtifact | None`
  - `pipeline.write_artifact(db, *, source: models.Source, kind: models.ArtifactKind, content: dict[str, Any], model: str | None, prompt_version: str | None) -> models.SourceArtifact` — caller holds the user lock; inserts version max+1 with `is_current=True`, sets the previous current row's `is_current=False` (flush that first, so the partial unique index never sees two), gives both rows new `change_seq`, returns the new row. `id = uuid.uuid4()`.
  - `pipeline.set_processing(db, *, source: models.Source, status: models.ProcessingStatus, error: str | None = None) -> None` — caller holds the lock; sets `processing`, `processing_error` (None unless failed), `updated_at`, `change_seq`.
  - `pipeline.finish_step(db, *, source: models.Source) -> None` — caller holds the lock; sets READY when both a current summary and a current primer exist, else leaves it.
  - `pipeline.steps_to_retry(db, *, source_id: uuid.UUID) -> list[models.JobKind]` — no current `text` → `[FETCH_CONTENT]`; else the steps whose artifact (summary → ANALYZE, primer → PRIMER) has no current row; if both exist → `[ANALYZE, PRIMER]`.
  - `pipeline.enqueue_steps(db, *, source: models.Source, steps: list[models.JobKind]) -> None` — one `jobs.enqueue` per step with payload `{SOURCE_ID_KEY: str(source.id)}`, in the given order.
  - `archie_worker.errors.PermanentJobError(reason: str)` with attribute `.reason`; `errors.FailureReason(StrEnum)`: `TEXT_MISSING = "Couldn't read this page. Share it from Safari to capture it."`, `NEEDS_API_KEY = "Add your own API key in Settings (coming soon)."`, `GAVE_UP = "Processing failed. Tap Retry."`
  - `loop.FailureHook = Callable[[sqlalchemy.orm.Session, models.Job, str], None]` (the str is the user-facing reason)
  - `@dataclass(frozen=True) class loop.HandlerSpec: run: Handler; on_final_failure: FailureHook | None = None`
  - `run_one(engine, *, handlers: Mapping[models.JobKind, HandlerSpec]) -> bool` (signature type changes from `Handler` to `HandlerSpec`)
  - `handlers.HANDLERS: dict[models.JobKind, loop.HandlerSpec]`
  - `handlers.mark_source_failed(db, job, reason) -> None` — the shared `FailureHook` for pipeline steps: lock, refresh the source, skip if deleted, `pipeline.set_processing(FAILED, error=reason)`.
- Review: yes (state machine, concurrency).

Behavior changes in `loop.py`:
- `claim_next` orders by `next_run_at, id` so jobs enqueued in one transaction run in enqueue order (replayed cassettes depend on it).
- `_record_failure`: a `PermanentJobError` fails the job at once (`last_error = reason`). A job out of attempts fails as now. In both cases, when the spec has `on_final_failure`, call it in the same transaction with `error.reason` (permanent) or `FailureReason.GAVE_UP`.
- **Handler contract** (write it in `loop.py`'s module docstring and on `Handler`): a handler that makes an outside call must first read what it needs into locals and call `db.commit()`, so no connection or transaction is held during the call; then it takes `changes.lock_user_writes` and writes. The loop marks the job done in the same session after the handler returns. Update `fetch_title.handle` to commit after reading `source.url`/`user_id` and before `_fetch_page`.

- [ ] **Step 1: Tests for `pipeline.py`** (`@pytest.mark.postgres`, real DB via `migrated_database_url`): versions increment and only the newest is current (old row kept, content unchanged, both change_seq raised); `finish_step` sets READY only after both artifacts; `steps_to_retry` for the three situations.
- [ ] **Step 2: Tests in `test_worker_e2e.py`:** a handler raising `PermanentJobError` fails its job after one attempt and calls the hook with its reason; a job exhausting attempts calls the hook with `GAVE_UP`; two jobs enqueued in one transaction run in enqueue order; existing fetch_title tests pass with `HandlerSpec` (use small test-only handlers registered in a dict for the hook tests).
- [ ] **Step 3: Implement** `errors.py`, `pipeline.py`, the loop changes, the `HANDLERS` change (`FETCH_TITLE: HandlerSpec(run=fetch_title.handle)`), and fetch_title's commit-before-fetch.
- [ ] **Step 4: Run** `make test-db && make lint` — all pass.
- [ ] **Step 5: Commit** "Worker: permanent failures, failure hooks, no transaction held across outside calls; artifact versions".

### Task 3: Model calls, cost records and recording

**Files:**
- Create: `services/worker/archie_worker/llm.py`, `services/worker/tests/test_llm.py`
- Create: `packages/archie-testing/archie_testing/recording.py`
- Modify: `services/worker/pyproject.toml` (add `anthropic`), `packages/archie-testing/pyproject.toml` (add `vcrpy`/`pytest-recording` is already root dev; add `python-dotenv`), `services/worker/tests/test_worker_e2e.py` (use `recording.vcr_for`)

**Interfaces:**
- Consumes: Task 1 (`LlmCall`, `Settings.require_anthropic_api_key`), Task 2 (`PermanentJobError`, `FailureReason`).
- Produces:
  - `llm.HAIKU = "claude-haiku-5-5"`, `llm.SONNET = "claude-sonnet-5-5"`, `llm.OPUS = "claude-opus-5-5"`
  - `@dataclass(frozen=True) class llm.ModelPair: primary: str; fallback: str`; `llm.ANALYZE_MODELS = ModelPair(HAIKU, SONNET)`, `llm.PRIMER_MODELS = ModelPair(SONNET, OPUS)`
  - `llm.cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> Decimal`
  - `@dataclass(frozen=True) class llm.CallContext: user_id: int; source_id: uuid.UUID; job_id: int; step: models.JobKind`
  - `@dataclass(frozen=True) class llm.Completion: model: str; text: str` (text is the JSON string for schema calls)
  - `llm.api_key_for(user: models.User) -> str` — not whitelisted → `PermanentJobError(FailureReason.NEEDS_API_KEY)`; whitelisted → `Settings().require_anthropic_api_key()`
  - `llm.complete(engine: sqlalchemy.Engine, *, api_key: str, context: CallContext, models: ModelPair, system: str, user_message: str, max_tokens: int, json_schema: dict[str, Any] | None = None) -> Completion`
  - `llm.ModelOutputError(Exception)` — raised when both models stop with `refusal` or `max_tokens`
  - `archie_testing.recording.vcr_for(request: pytest.FixtureRequest, *, cassette_dir: pathlib.Path) -> vcr.VCR`
  - `archie_testing.recording.use_recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None`
- Review: yes (money, outside calls).

`complete` behavior:
- `anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=300)`; `client.messages.create(model=..., max_tokens=..., system=system, messages=[{"role": "user", "content": user_message}], **({"output_config": {"format": {"type": "json_schema", "schema": json_schema}}} if json_schema else {}))`.
- After each response, insert one `LlmCall` (provider `anthropic`, `response.usage.input_tokens`/`output_tokens`, `cost_usd`, `stop_reason`) in its **own** short `sqlalchemy.orm.Session(engine)` + commit, so the cost is recorded even if the step fails afterwards.
- `stop_reason` in (`refusal`, `max_tokens`) → log and try `models.fallback` once; if that also stops that way → `ModelOutputError`. API errors propagate (the loop retries them).
- Return the concatenated text blocks.

`recording.vcr_for`: `record_mode` from `--record-mode` or `"none"`; `filter_headers=["authorization", "x-api-key", "cookie", "set-cookie", "anthropic-organization-id", "request-id"]`; `decode_compressed_response=True`; registers a matcher `anthropic_prompt` that, for `api.anthropic.com` requests, compares the request JSON's `model` and the first 60 characters of `system`; `match_on=["method", "scheme", "host", "path", "anthropic_prompt"]` (non-Anthropic requests compare equal under the matcher). `use_recording_api_key`: in record mode, read `ANTHROPIC_API_KEY` from the repo root `.env` with `dotenv.dotenv_values` and `monkeypatch.setenv` it; otherwise set `ANTHROPIC_API_KEY=sk-ant-replay-only`. Never print it.

- [ ] **Step 1: Unit tests** (`test_llm.py`): `cost_usd` for each model (e.g. Haiku 1,000,000 in + 1,000,000 out = `Decimal("0.60")`), unknown model raises `KeyError`.
- [ ] **Step 2: Recorded test** (`@pytest.mark.postgres`): record a tiny real Haiku call (system "Reply with the word ok.", user "hi", max_tokens 16) with `--record-mode=once`; assert `complete` returns text and one `llm_calls` row with tokens > 0 and `cost_usd > 0`. Record a second real call with `max_tokens=1` (it stops with `max_tokens`) and check the fallback path: with `ModelPair(HAIKU, HAIKU)` and max_tokens 1, both stop on `max_tokens` → `ModelOutputError` and two rows. Record: `ANTHROPIC_API_KEY` is read from `.env` by the fixture; the suite run is `uv run pytest services/worker/tests/test_llm.py --record-mode=once -m postgres`.
- [ ] **Step 3: Implement** `llm.py` and `recording.py`; switch `test_worker_e2e.py`'s `replay` fixture to `recording.vcr_for`.
- [ ] **Step 4: Verify** replay works offline: `make test-db`; `grep -ril "x-api-key\|sk-ant-api" services/worker/tests/cassettes` prints nothing.
- [ ] **Step 5: Commit** "Model calls with fallback and cost records; recording helpers".

### Task 4: App data layer for M2

**Files:**
- Modify: `app/src/db/schema.ts`, `app/src/db/actions.ts`, `app/src/db/actions.test.ts`, `app/src/sync/engine.ts`, `app/src/sync/transport.ts`, `app/src/sync/engine.test.ts`
- Create: `app/drizzle/0001_*.sql` (via `npm run db:generate`), `app/src/capture/extractUrl.ts`, `app/src/capture/extractUrl.test.ts`, `app/src/capture/CaptureOptions.tsx`, `app/src/capture/types.ts`

**Interfaces:**
- Consumes: the wire shapes from Task 5 (below).
- Produces:
  - `schema.sources` adds `processing` (text not null default "pending"), `processingError`, `reaction`, `note`, `prepMe` (integer not null default 0), `mergedIntoId`.
  - `schema.artifacts`: `id` PK, `sourceId`, `kind`, `version` (integer), `content` (JSON text), `isCurrent` (integer), `createdAt`.
  - `schema.cards`: `id` PK, `sourceId`, `kind`, `question`, `answer`, `createdAt`, `deletedAt`.
  - `types.ts`: `export type Intent = "finished" | "queue"; export type Reaction = "easy" | "mostly" | "lost"; export type CaptureChoice = { intent: Intent | null; reaction: Reaction | null; note: string; prepMe: boolean }; export const EMPTY_CHOICE: CaptureChoice`
  - `addSource(db, input: { url: string; intent: Intent; reaction?: Reaction | null; note?: string | null; prepMe?: boolean }): Promise<string>` — payload `{id, url, intent, reaction, note, prep_me}` (omit null/empty fields); local row `processing: "pending"`.
  - `retrySource(db, sourceId: string): Promise<void>` — local `processing = "processing"`, `processingError = null`; outbox `{type: "retry_source", payload: {id: sourceId}}`; one transaction.
  - `extractFirstUrl(text: string): string | null` — first `https?://` URL, trailing `)`, `.`, `,`, `"`, `'` trimmed.
  - `<CaptureOptions value={choice} onChange={setChoice} />` — Finished / Queue it buttons; Finished reveals three reaction chips (Easy / Mostly followed / Parts lost me) and a note `TextField` ("Anything confusing?"); Queue reveals a Prep me switch. testIDs: `intent-finished`, `intent-queue`, `reaction-easy|mostly|lost`, `capture-note`, `prep-me`. Uses only `@/theme/*` components and `react-native` (the share extension imports it).
  - engine types: `PulledSource` adds `processing, processing_error, reaction, note, prep_me, merged_into_id`; `PulledArtifact = { id, source_id, kind, version, content: unknown, is_current: boolean, created_at }`; `PulledCard = { id, source_id, kind, question, answer, created_at, deleted_at }`; `PullPage.rows = { sources, artifacts, cards }`.
  - `createDbSyncStore.applyPage` upserts all three (server copy wins; the unsent-source skip still applies to sources only). `rejectAction` already flags by payload `id`, which `retry_source` also carries.
- Review: yes (sync).

- [ ] **Step 1: Tests.** `extractUrl.test.ts` (Spotify text "Listen to this https://open.spotify.com/episode/x?si=1", a URL in parentheses, no URL → null). `engine.test.ts`/`actions.test.ts` (better-sqlite3, as M1): a pulled page with artifacts and cards is stored and re-pulling the same rows updates in place; `retrySource` writes the outbox entry and the local status; `addSource` with reaction/note puts them in the payload as `prep_me`/`reaction`/`note`.
- [ ] **Step 2: Implement** schema + `npm run db:generate` (commit the generated SQL, snapshot, journal and `migrations.js` update), types, actions, store, `CaptureOptions`.
- [ ] **Step 3: Run** `cd app && npm run typecheck && npm test` — pass.
- [ ] **Step 4: Commit** "App: local artifacts and cards, capture options, retry action".

## Parallel-safe tasks

Every task below depends only on Tasks 1–4. Each runs in its own worktree from the last foundation commit.

### Task 5: Capture API: add_source, merge, retry_source, multi-table pull

**Files:**
- Create: `services/api/archie_api/sync/capture.py` (the add_source logic, moved out of `actions.py`), `services/api/tests/test_capture.py`
- Modify: `services/api/archie_api/sync/{actions,pull,schemas}.py`, `services/api/tests/e2e/test_sync_e2e.py`

**Interfaces:**
- Consumes: Task 1 (`urls`, models), Task 2 (`pipeline.enqueue_steps`, `pipeline.steps_to_retry`, `pipeline.set_processing`).
- Produces (wire shapes Task 4 already consumes):
  - `ActionType`: `ADD_SOURCE`, `RETRY_SOURCE = "retry_source"`.
  - add_source payload: `{id, url, intent, reaction?, note?, prep_me?, capture?: {title?, text}}`.
  - `SourceOut` adds `processing: str, processing_error: str | None, reaction: str | None, note: str | None, prep_me: bool, merged_into_id: uuid.UUID | None`.
  - `ArtifactOut`: `id, source_id, kind, version, content: dict[str, Any], is_current: bool, created_at, change_seq`.
  - `CardOut`: `id, source_id, kind, question, answer, created_at, deleted_at, change_seq`.
  - `PulledRows`: `sources: list[SourceOut], artifacts: list[ArtifactOut], cards: list[CardOut]`.
- Review: yes (sync ordering, state machine).

Rules (spec "Capture" and "API and sync"):
- **Validation** rejects (as M1, with a reason): reaction not in `Reaction`; reaction given with intent queue; prep_me true with intent finished; note > 2,000; capture text > 400,000 or empty; capture title > 500.
- **New source:** `kind = detect_kind(url)`; `normalized_url = normalize_url(url)`; article/x → `processing=pending` and `enqueue_steps([FETCH_CONTENT])`; youtube/podcast → `processing=unsupported` and the M1 `FETCH_TITLE` job. A capture inserts a `source_captures` row.
- **Duplicate** (same user, same `normalized_url`, `deleted_at IS NULL`): insert the phone's row with `deleted_at=now()`, `merged_into_id=existing.id`, its own change_seq; update the existing source: intent/state move forward only (queued → consumed when the new intent is finished); reaction/note/prep_me overwrite when given; a capture is stored when the existing source has none, and if the existing source is `failed` the pipeline restarts (`set_processing(PROCESSING)`, `enqueue_steps(steps_to_retry)`); new change_seq. Result `applied`.
- **retry_source `{id}`:** the user's own, non-deleted source in `failed` (anything else → `rejected` "source is not failed"): `set_processing(PROCESSING)`, `enqueue_steps(steps_to_retry(...))`.
- **Pull:** query sources, artifacts (`kind IN SYNCED_ARTIFACT_KINDS`) and cards each `WHERE user_id = :u AND change_seq > :since ORDER BY change_seq LIMIT 500`; merge by change_seq; keep the lowest 500; `position` = the last kept change_seq (or `since`); `more` = any table returned 500 rows or rows were cut. Put the merge in a small pure function and unit-test it.

- [ ] **Step 1: Unit tests** (`test_capture.py`): the pull page merge (rows from three lists, cut at the limit, position correct, `more` set when a table was full even if under 500 total after cut).
- [ ] **Step 2: E2e tests** (extend `test_sync_e2e.py`, real API + Postgres): article URL → source `pending`/kind article and a `fetch_content` job; YouTube URL → `unsupported` + `fetch_title`; capture stored; each validation rejection; duplicate with `?utm_source=x` → merged deleted row + updated original (state queued → consumed); retry_source on a failed source enqueues the right steps and is rejected on a ready one; pull with > 500 changed rows across sources/artifacts/cards (insert artifacts and cards directly) returns each row exactly once over pages.
- [ ] **Step 3: Implement.** Keep `actions.py`'s batch/savepoint/duplicate-action structure; dispatch by `ActionType` to `capture.add_source` / `capture.retry_source`.
- [ ] **Step 4: Run** `make test-db && make lint`.
- [ ] **Step 5: Commit** "Sync: classify and merge shared URLs, Safari captures, retry_source, pull artifacts and cards".

### Task 6: `fetch_content` for articles and X

**Files:**
- Create: `services/worker/archie_worker/content/__init__.py`, `content/article.py`, `content/x.py`, `handlers/fetch_content.py`
- Create: `services/worker/tests/test_content.py`, `services/worker/tests/test_fetch_content_e2e.py`, cassettes in `services/worker/tests/cassettes/`
- Modify: `services/worker/archie_worker/handlers/__init__.py`, `services/worker/pyproject.toml` (add `trafilatura`)

**Interfaces:**
- Consumes: Task 1 (`urls.x_post_id`, `SourceCapture`), Task 2 (`pipeline.*`, `PermanentJobError`, `FailureReason.TEXT_MISSING`, `handlers.mark_source_failed`, the handler contract).
- Produces:
  - `content.article.clean_capture(text: str) -> str` — normalize whitespace per line, collapse 3+ blank lines to one, drop any line (≥ 20 chars) seen more than twice after its first two occurrences, cap at 200,000 chars.
  - `content.article.extract(*, html: str, url: str) -> content.ExtractedText | None` via `trafilatura.extract(..., output_format="txt", include_comments=False)` and `trafilatura.extract_metadata` for the title (fallback `fetch_title.extract_title`).
  - `@dataclass(frozen=True) class content.ExtractedText: title: str | None; text: str`
  - `content.x.fetch_thread(*, post_id: str) -> ExtractedText` — fxtwitter `/2/thread/{id}` with 3 tries 2 s apart on 404/5xx/timeout, then vxtwitter `https://api.vxtwitter.com/i/status/{id}`; raises on total failure.
  - `content.x.thread_text(*, data: dict[str, Any]) -> ExtractedText` — pure: posts by the shared post's author in thread order (`thread[]`, falling back to the single `tweet`), each post's text plus any `quote.text` (prefixed `Quoting @handle:`), an Article's `article.content.blocks[].text` joined with `article.title` first; title `@handle: <first 80 chars of first post>` or the Article title.
  - `handlers.fetch_content.handle(db, job) -> None`; registered as `HandlerSpec(run=fetch_content.handle, on_final_failure=handlers.mark_source_failed)`.
- Review: yes (state machine, outside input).

Handler steps: read source + capture (skip deleted) → lock, `set_processing(PROCESSING)`, commit → get text (capture → `clean_capture`; x → `fetch_thread`; article → GET 15 s/5 MB with the M1 streaming pattern then `extract`) → word check (article ≥ 50, x ≥ 1) else `PermanentJobError(FailureReason.TEXT_MISSING)` → lock, refresh (skip deleted), `write_artifact(TEXT, {"text": ...}, model=None, prompt_version=None)`, set the title if empty, `enqueue_steps([ANALYZE, PRIMER])`.

- [ ] **Step 1: Record** with `--record-mode=once -m postgres`: a real article (`https://www.paulgraham.com/greatwork.html`), a page with too little text (`https://example.com/`), fxtwitter threads from the spike (`sama/2107691261776052633` thread, `hwchase17/2116553654857867330` Article, `hwchase17/2116230499140251964` quote). Save one fxtwitter JSON body as a fixture file for the pure `thread_text` test (copy it out of the cassette).
- [ ] **Step 2: Unit tests** (`test_content.py`): `clean_capture` drops triple-repeated caption lines and keeps two; `thread_text` on the recorded JSON keeps the author's posts in order, includes the quote, builds the Article text and title.
- [ ] **Step 3: E2e tests** (`test_fetch_content_e2e.py`, real DB + recorded HTTP, `run_one` with real `HANDLERS`): article → text artifact v1 with > 50 words, title set, analyze + primer jobs queued, source `processing`; capture → no HTTP at all (empty cassette in `none` mode would fail on any request), text from the capture; example.com → job failed after one attempt, source `failed` with the TEXT_MISSING reason; X thread → all three sama posts in order.
- [ ] **Step 4: Implement**, run `make test-db && make lint`.
- [ ] **Step 5: Commit** "Worker: fetch_content for articles, Safari captures and X".

### Task 7: `analyze` and `primer`

**Files:**
- Create: `services/worker/archie_worker/prompts.py`, `handlers/analyze.py`, `handlers/primer.py`
- Create: `services/worker/tests/test_analyze_primer_e2e.py`, cassettes
- Modify: `services/worker/archie_worker/handlers/__init__.py`

**Interfaces:**
- Consumes: Task 2 (`pipeline.*`, `mark_source_failed`), Task 3 (`llm.*`, `recording`).
- Produces:
  - `prompts.ANALYZE_PROMPT_VERSION = "analyze-v1"`, `prompts.PRIMER_PROMPT_VERSION = "primer-v1"`, `prompts.DOMAINS`, `prompts.ANALYZE_SYSTEM`, `prompts.PRIMER_SYSTEM`, `prompts.ANALYSIS_SCHEMA`, `prompts.user_message(*, kind: models.SourceKind, title: str | None, url: str, text: str) -> str`
  - `handlers.analyze.handle`, `handlers.primer.handle`, both registered with `on_final_failure=mark_source_failed`.
- Review: yes (money, state machine).

Prompts: copy `spikes/llm_processing/process_sources.py`'s `READING_VOICE`, `ANALYZE_SYSTEM_PROMPT`, `PRIMER_SYSTEM_PROMPT`, `DOMAINS` and `ANALYSIS_SCHEMA`, generalized from "podcast episode/transcript" to "source (article, X post or thread, or episode)/text". Changes to the schema: `timestamp` becomes `{"type": ["string", "null"]}` (null for text sources; the prompt says to cite timestamps only when the text has them); add `"is_educational": {"type": "boolean"}` (required) with the prompt rule from the product scope: educational content gets cards; pure entertainment (banter, sports chat, gossip) gets `is_educational=false` and an empty `cards` list. Cards: 3–5, kinds concept/mechanism/number, single focused questions (not compound — the spike's finding), rough numbers. `user_message` wraps text in `<text>` tags with kind, title and URL above, text capped at 200,000 chars.

Handler steps (both): read source, user, current text artifact (missing → raise, the loop retries) → `api_key = llm.api_key_for(user)` → `db.commit()` → `llm.complete(db.get_bind(), ...)` (assert the bind is an `Engine`) → lock, refresh (skip deleted) → write.
- analyze: `json.loads` the text; `write_artifact(SUMMARY, analysis, model=completion.model, prompt_version=...)`; soft-delete (`deleted_at`, `updated_at`, `change_seq`) cards of this source whose `artifact_id` is not the new one; insert the new cards (only when `is_educational`) each with `change_seq`; `finish_step`.
- primer: `write_artifact(PRIMER, {"markdown": completion.text}, ...)`; `finish_step`.

- [ ] **Step 1: Record** real calls (`--record-mode=once -m postgres`) for: the Paul Graham essay text (the test inserts the text artifact from a fixture file `services/worker/tests/fixtures/greatwork.txt`: the essay's plain text, fetched once and stripped of tags with a throwaway script, not committed) → analyze and primer; an entertainment text (a short sports-banter transcript fixture) → analyze with `is_educational=false`; a real 529/overloaded is hard to provoke, so record a real 401 by setting a wrong key for one test (`ANTHROPIC_API_KEY=sk-ant-invalid` in record mode) to cover "API error → job retried, nothing written".
- [ ] **Step 2: Refusal cassette:** copy the primer's recorded interaction, change the first response's `stop_reason` to `"refusal"`, and put a comment at the top of the YAML saying it was edited from a real response because refusals can't be provoked on demand. The test asserts the primer is still written (from the fallback interaction, recorded for Opus) and `llm_calls` has two rows, the first `refusal`.
- [ ] **Step 3: E2e tests:** analyze writes a summary (gist non-empty, domain in `DOMAINS`) and 3–5 cards; after primer too, the source is `ready`; entertainment → summary, no cards; a second analyze run (enqueue again) → summary v2 current, v1 kept, old cards soft-deleted, new cards inserted; non-whitelisted user → job failed at once, source `failed` with NEEDS_API_KEY, zero `llm_calls`; 401 → job queued for retry, `last_error` set.
- [ ] **Step 4: Implement**, run `make test-db && make lint`; grep cassettes for keys.
- [ ] **Step 5: Commit** "Worker: analyze and primer with model fallback and versioned output".

### Task 8: App screens: Library status, source page, ＋ options, share deep link

**Files:**
- Modify: `app/src/app/(tabs)/library.tsx`, `app/src/app/(tabs)/add.tsx`, `app/src/app/_layout.tsx` (stack routes)
- Create: `app/src/app/source/[id].tsx`, `app/src/app/share.tsx`, `app/src/ui/Markdown.tsx`, `app/src/ui/Markdown.test.tsx` (or a pure `parseMarkdown` test)

**Interfaces:**
- Consumes: Task 4 (schema, `addSource`, `retrySource`, `CaptureOptions`, `CaptureChoice`).
- Produces: route `/source/[id]`; deep link `archie://share?url=…&intent=…&reaction=…&note=…&prep_me=1` handled by `share.tsx` (validates intent, calls `addSource`, then `router.replace("/(tabs)/library")`; with no session the root layout already shows sign-in).
- Review: no.

Library row adds a processing line under the state chip: `pending`/`processing` → "Processing…" (testID `source-processing-<id>`); `failed` → the `processingError` and a "Retry" link (testID `source-retry-<id>`, calls `retrySource`); `unsupported` → "Not processed yet". Tapping a row opens `/source/<id>` (testID `source-<id>` stays on the card).

Source page (`source/[id].tsx`, live queries): title, kind · host; gist; "Key ideas" numbered; "Rough numbers" in `monoLabel`/mono with timestamp chips when present; "Background you might need" collapsed (testID `primer-toggle`), expanding to `<Markdown>`; the reaction and note when set; "Cards from this" (question bold, answer below); processing line and Retry as in Library. testIDs `source-gist`, `source-primer`.

`Markdown.tsx`: `parseMarkdown(text) -> Block[]` (pure, tested: `#`/`##`/`###` headings, paragraphs, `-`/`*`/`1.` lists, `**bold**`, `*italic*`) and a renderer using `@/theme` `Text`. No new dependency.

＋ tab: URL field + `CaptureOptions` + Save (disabled until a URL and an intent are chosen; testIDs from M1 kept where flows use them — update `maestro/add_link.yaml` and the offline flows if a testID changes).

- [ ] **Step 1:** `parseMarkdown` tests; run them failing.
- [ ] **Step 2:** Implement the screens and renderer.
- [ ] **Step 3:** `npm run typecheck && npm test`; build and run on the simulator (`npx expo run:ios`) against `make start-local` and click through by hand with a source inserted via the API, or run the existing Maestro flows (`make maestro`).
- [ ] **Step 4: Commit** "App: processing status, Retry, source page, capture options in ＋, share deep link".

### Task 9: Share extension and the shared Keychain

**Files:**
- Modify: `app/package.json` (`expo-share-extension`), `app/app.config.ts`, `app/src/auth/session.ts`, `app/src/auth/session.test.ts`, `app/metro.config.js` (if `expo-share-extension` needs its metro wrapper)
- Create: `app/index.share.tsx`, `app/preprocessing.js`, `app/src/share/ShareSheet.tsx`, `app/src/share/submit.ts`, `app/src/share/submit.test.ts`, `app/plugins/withSharedKeychain.js`

**Interfaces:**
- Consumes: Task 4 (`CaptureOptions`, `extractFirstUrl`, types), the M1 `apiFetch` (`app/src/api/client.ts`).
- Produces:
  - `session.ts`: every secure-store call passes `{ keychainAccessGroup: SHARED_KEYCHAIN_GROUP }` (`SHARED_KEYCHAIN_GROUP = "3W3H65F89G.com.sampocs.archie.shared"`); `migrateSessionKeyToSharedGroup()` run once at startup before the session is read: if the group has no key and the old (no group) location has one, copy it and delete the old one.
  - `submit.ts`: `buildShareAction(input: { url: string; choice: CaptureChoice; capture: { title: string | null; text: string } | null }): OutboxEntry` (new UUIDs for action and source; capture text dropped if > 400,000 chars) and `submitShare(action, sessionKey): Promise<"saved" | "offline" | "signed-out">` (POST `/sync/push`; `applied`/`duplicate` → saved; 401 → signed-out; network error → offline; `rejected` → throws with the reason, shown in the sheet).
  - `shareDeepLink(input) -> string` building `share?url=…&intent=…` for `openHostApp`.
- Review: yes (auth).

Config:
- `app.config.ts` plugins: `["expo-share-extension", { activationRules: [{ type: "url" }, { type: "text" }], preprocessingFile: "./preprocessing.js", backgroundColor: <paper token as RGBA>, height: 560 }]`, then `"./plugins/withSharedKeychain.js"`.
- `withSharedKeychain.js`: for the main app use `withEntitlementsPlist` to set `keychain-access-groups: ["$(AppIdentifierPrefix)com.sampocs.archie.shared"]` and delete `com.apple.security.application-groups`; for the extension target, a `withDangerousMod` (ios) that edits the extension's `.entitlements` file written by `expo-share-extension` the same way. Read `node_modules/expo-share-extension` to find the file name and the order its mods run in; the plugin must run after it.
- `preprocessing.js`: the spike's file (`url`, `title`, `<article>` or body `innerText`).
- `index.share.tsx`: `AppRegistry`/`expo-share-extension` entry rendering `ShareSheet`.

`ShareSheet` (spec "Share extension"): URL from `props.url`, else `extractFirstUrl(props.text)`, else from `props.preprocessingResults.url`; title from the capture or the host; `CaptureOptions`; Save → `submitShare`; saved → check mark + `close()` after 1 s; offline/signed-out → "Couldn't reach Archie" + **Open Archie** (`openHostApp(shareDeepLink(...))`); rejected → the reason. No URL found → "Nothing to save here" + Close.

- [ ] **Step 1: Tests:** `submit.test.ts` (action shape: snake_case payload with `capture`, oversized capture dropped; result mapping for applied/duplicate/401/network/rejected with a fake fetch); `session.test.ts` (migration copies the old key once and only when the group is empty — extend the existing secure-store mock).
- [ ] **Step 2: Implement** and run `npm run typecheck && npm test`.
- [ ] **Step 3: Native build check:** `cd app && npx expo prebuild --platform ios --clean`, confirm `ios/` has the share extension target and both `.entitlements` files contain the keychain group and no application-groups key; then `xcodebuild -workspace ios/Archie.xcworkspace -scheme Archie -configuration Release -destination "generic/platform=iOS" -derivedDataPath ios/build -allowProvisioningUpdates DEVELOPMENT_TEAM=3W3H65F89G build | tail -20` succeeds (signing included). If signing fails for the extension's App ID, report the exact error (it may need the owner in the Apple portal) — do not work around it by disabling signing.
- [ ] **Step 4: Commit** "Share extension: Safari capture, capture options, direct save with the shared session key".

## Integration tasks (serial, after every parallel task)

### Task 10: Pipeline e2e, Maestro, deploy config and docs

**Files:**
- Create: `services/api/tests/e2e/test_pipeline_e2e.py` (+ cassette), `maestro/source_page.yaml`
- Modify: `.railway/railway.ts` (`ANTHROPIC_API_KEY: preserve()` on `archie`), `docs/deploy.md` (Not in code: the key), `AGENTS.md` (commands/recording note), `Makefile` (`make maestro` includes the new flow if it lists flows), the M2 spec's status line, `services/api/tests/e2e/cassettes/` (re-record `main_path` if Task 5 changed what it hits)
- Review: yes (whole flow)

- [ ] **Step 1: E2e over the live stack** (`@pytest.mark.worker`): `/test/session` user marked whitelisted → push `add_source` for the recorded article → poll pull until the source is `ready` (timeout 30 s) → pull has a summary artifact, a primer artifact and 3–5 cards; `llm_calls` has two rows with positive cost. Second case: X thread with intent queue. Record once (`--record-mode=once`), using `recording.use_recording_api_key`. The test-session route must be able to create a whitelisted user: if it can't, set `OWNER_EMAILS` to the test user's email in the fixture.
- [ ] **Step 2: Maestro** `source_page.yaml`: dev login → add a link in ＋ (Finished, Easy) → Library → wait for the gist (`extendedWaitUntil` `source-gist`, one wait only — see `maestro/README.md` on shared timeouts) → open the primer. Runs against `make start-local` with real keys only when the owner runs it; document that in `maestro/README.md` (replay mode for the local backend is not built yet).
- [ ] **Step 3: Full suite:** `make lint && make test-db && (cd app && npm run typecheck && npm test)`; `railway config plan` shows only the new preserved variable (run `npm install` at the root first).
- [ ] **Step 4: Commit** "M2: pipeline e2e, Maestro source page flow, deploy config".

### Task 11: Deploy and phone (needs the owner)

- [ ] Set `ANTHROPIC_API_KEY` on the Railway `archie` service from the owner's `.env` without printing it (`railway variable set --service archie ANTHROPIC_API_KEY="$(grep '^ANTHROPIC_API_KEY=' .env | cut -d= -f2-)"` — the value never reaches the terminal), `railway config apply`.
- [ ] Merge the PR after CI; Railway deploys `main`; `/health` ok.
- [ ] `scripts/install_ios.sh` with the phone plugged in.
- [ ] The owner: add Archie to the share sheet favorites; share a Safari article, a paywalled one, and an X thread; each shows summary, primer and cards within ~3 minutes. Check `llm_calls` cost in the prod DB.
