# Milestone 3 All Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The user shares a Spotify/Apple podcast episode or a YouTube video and gets its summary (with timestamps), primer and cards; newsletters mailed to their Archie address arrive in Library as Inbox items with a summary.

**Architecture:**
- Worker: `fetch_content` learns YouTube (captions → timed `text`) and podcasts (resolve the episode through Spotify's page / iTunes and the RSS feed; a published transcript → timed `text`, else a new `transcribe` job: download → ffmpeg chunks → Groq, OpenAI fallback → Haiku name corrections → timed `text`). Timed text reaches `analyze` (prompt `analyze-v2`) and `primer` with `[mm:ss]` markers, which fill the existing timestamp fields.
- API: `POST /ingest/email` (shared secret) turns a raw email into a `newsletter` source in state `inbox` with a capture, which runs `fetch_content` → `analyze` only (no cards, no primer). `/me` returns the user's newsletter address; sync adds `sender`.
- A Cloudflare Email Worker in `workers/newsletter/` forwards mail to that endpoint. The app shows Inbox items' sender, the newsletter address, and podcast timestamps.

**Tech Stack:** as M2, plus `defusedxml`, `youtube-transcript-api` 1.x (worker), `trafilatura` (now also in the API), `ffmpeg`/`ffprobe` (system), Groq and OpenAI transcription over plain `httpx` (no SDKs), Cloudflare Workers (`wrangler`).

**Spec:** `docs/superpowers/specs/2026-11-04-m3-all-sources-design.md`. Read it before any task: it is the source of truth for behavior; this plan is the order, the shapes and the names.

## Global Constraints

- **Python style:** the house style in `AGENTS.md` (module-qualified imports, full typing with `X | None`, `StrEnum`s, dataclasses over tuples of >2, named parameters, guard clauses, blank-line paragraphs past ~8 lines, why-comments only, docstrings on public functions/classes). Follow the patterns already in `services/worker/archie_worker/handlers/fetch_content.py` and `llm.py`.
- **Handler contract** (`loop.py` docstring): read into locals and `db.commit()` before any outside call (HTTP, model, ffmpeg); then `changes.lock_user_writes`, `db.refresh(source)`, skip if deleted, write. Rows written mid-handler that must survive a later failure (cost rows, transcript chunks) go through their **own** short `sqlalchemy.orm.Session(engine)` + commit, as `llm._record_call` does.
- **Tests:** e2e first; a unit test only for logic that could plausibly be wrong; outside calls replayed from recorded real responses (pytest-recording / vcrpy cassettes), never hand-written bodies. Constructing a library's own exception object or our own DB rows in a test is fine; inventing an outside service's response body is not.
- **Never print secrets** or `.env` values. Check keys by name only: `grep -o '^[A-Z_]*=' .env`. Cassettes must contain no `authorization`, `x-api-key`, `cookie`/`set-cookie` headers and no key material: before every commit that adds a cassette, `grep -rIl -e "x-api-key" -e "sk-ant-api" -e "gsk_" -e "sk-proj-" -e "Bearer " services/*/tests/cassettes services/api/tests/e2e/cassettes` prints nothing.
- **Cassette size (public repo):** no cassette over 5 MB; audio-bearing cassettes total ≤ 10 MB. Check with `du -h` before committing. Audio uploads to Groq/OpenAI are stripped from recorded requests (Task 4), so only the one download per cassette carries audio.
- **Models and prices:** analyze `claude-haiku-5-5` → `claude-sonnet-5-5`; primer `claude-sonnet-5-5` → `claude-opus-5-5`; corrections `claude-haiku-5-5` → `claude-sonnet-5-5`, max output 16000. Transcription: Groq `whisper-large-v3-turbo` $0.04 per audio hour; OpenAI `gpt-4o-mini-transcribe` $0.18 per audio hour.
- **Limits (verbatim from the spec):** Spotify page 15 s, 5 MB; RSS feed 30 s, 50 MB; episode match within ±3 days and `difflib.SequenceMatcher` ratio ≥ 0.6; published transcript ≥ 200 words; audio download 10 min total, 600 MB cap; chunks mono 16 kHz 32 kbps MP3, 600 s (`-f segment -segment_time 600`); OpenAI halves 300 s; fallback under 100 words per minute; `transcribe` stale after 3,600 s (others 900 s); model text cap 200,000 characters, 600,000 for timed sources; email body 10 MB (413); ingest token 10 lowercase letters/digits.
- **Prompt hint for Whisper** is exactly `f"{show}. {episode_title}."`.
- **Payload keys** on the wire are snake_case (`sender`, `ingest_address`).
- **Branch:** `m3-sources` (worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/m3-sources`). Foundation tasks run there, serially. Each parallel-safe task runs in its own worktree created with `git gtr new <branch> --from-current --yes` from the last foundation commit, then merges back into `m3-sources`.
- **Postgres from a worktree:** the local Postgres container (`second-brain-postgres-1`, `127.0.0.1:5434`) is already up from the main checkout; **never run `make db-up`, `make test-db`, `make migrate-local`, `make start-local` or `make reset-local-data` from a worktree** (each calls `docker compose`, which would try to start a second container on 5434). Run tests with:
  ```bash
  TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test uv run pytest -m "postgres or not postgres"
  ```
  **Parallel tasks each use their own test database**, because tests truncate every table and one test downgrades the schema: create it once with `docker exec second-brain-postgres-1 createdb -U archie archie_test_t<N>` (ignore "already exists") and use `.../archie_test_t<N>` in `TEST_DATABASE_URL`.
- **Recording a cassette:** delete it, then run the one test with `--record-mode=once` and `TEST_DATABASE_URL` set, e.g. `TEST_DATABASE_URL=... uv run pytest services/worker/tests/test_x.py::test_y --record-mode=once -m postgres`. Recording reads `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY` from the repo-root `.env` of the worktree (gtr copies it; if a name is missing there, copy that line from `/Users/sampocs/Documents/Personal/second-brain/.env` without printing it, e.g. `grep '^GROQ_API_KEY=' /Users/sampocs/Documents/Personal/second-brain/.env >> .env`). There is **no `SUPADATA_API_KEY`**: the Supadata path is built per its docs and its cassette is a follow-up.
- **ffmpeg:** check `which ffmpeg ffprobe`; if missing, `brew install ffmpeg`.
- **Checks before every commit:** `make lint` and the relevant tests (command above). App: `cd app && npm run typecheck && npx jest`.
- **Commits:** every message ends with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MN7nukQAsqfkk3GiAq6NkX
  ```
- **Out of scope for this plan:** deploying (merging to `main` deploys Railway), `railway config apply`, deploying the Cloudflare Worker. The plan ends at `m3-sources` ready for a PR.

## Decisions made while planning (owner asleep)

1. Groq and OpenAI are called with `httpx` directly (multipart POST), not their SDKs: one less dependency each, and `retry-after` is easy to read.
2. A `RetryLaterError` re-queues a job after the server's `retry-after`; it still counts as an attempt, so `transcribe` jobs get `max_attempts = 6` to absorb a few 429s.
3. The words-per-minute fallback check skips chunks shorter than 30 s (a trailing outro chunk would otherwise always "fail").
4. Groq errors that trigger the OpenAI fallback: any 4xx except 429. 5xx and timeouts propagate (the loop retries; finished chunks are kept).
5. Corrections are applied per segment: a `heard` match that would cross a segment boundary is skipped (logged). A correction whose `context` isn't found is not applied.
6. Apple episodes: when iTunes Lookup gives the episode's `episodeGuid`, the feed item is matched by guid first; title/date matching is the fallback.
7. The Spotify-exclusive e2e needs a real exclusive episode; if none is found in 15 minutes the test is dropped and listed as a follow-up (the reason mapping is still covered by the resolve unit tests).
8. The resume test replays the same cassette as the full transcribe test (chunk requests are matched by uploaded filename, Task 4) and proves chunk 0 was skipped by counting Groq cost rows, rather than recording a second audio-bearing cassette.
9. Tests use 60-second chunks (`transcription.CHUNK_SECONDS` monkeypatched) so a ~3-minute episode exercises several chunks, offsets and resume.
10. Newsletters: intent `queue` (the column is NOT NULL), `processing` starts `pending` (spec edited to match).
11. A YouTube link without a video id is `unsupported` with "Share a video, not the channel." (spec edited).

---

## File Structure

```
packages/archie-db/archie_db/models.py                    enums, new tables/columns, new_ingest_token      (T1)
packages/archie-db/archie_db/migrations/versions/0003_all_sources.py                                      (T1)
packages/archie-shared/archie_shared/config.py            Groq/OpenAI/Supadata/ingest settings             (T1)
packages/archie-shared/archie_shared/urls.py              podcast_link, youtube_video_id                   (T1)
conftest.py, .env.example, .railway/railway.ts, pyproject deps + uv.lock                                  (T1)
packages/archie-db/archie_db/jobs.py, pipeline.py         max_attempts, per-kind steps, unsupported error  (T2, T3)
services/worker/archie_worker/{loop,errors,llm}.py        stale_after, RetryLaterError, audio costs        (T2)
services/worker/archie_worker/content/__init__.py         Segment, timed_text_content, segments_of         (T3)
services/worker/archie_worker/content/episode.py          PodcastEpisode payload                           (T3)
services/worker/archie_worker/timestamps.py               format_timestamp, marked_text                    (T3)
services/worker/archie_worker/handlers/_text.py           store_text, enqueue_transcribe                   (T3)
services/worker/archie_worker/{prompts.py, handlers/analyze.py, handlers/_llm_step.py, handlers/fetch_content.py} (T3)
packages/archie-testing/archie_testing/{recording,media}.py  multi-key recording, audio stripping, test media (T4)
services/api/archie_api/sync/{capture,schemas}.py, auth/routes.py, archie_testing/harness.py              (T5)
services/worker/archie_worker/content/{podcast,transcripts}.py + fetch_content podcast branch             (T6)
services/worker/archie_worker/{transcription,corrections}.py, handlers/transcribe.py, Dockerfile, CI      (T7)
services/worker/archie_worker/content/youtube.py + fetch_content youtube branch                           (T8)
services/api/archie_api/ingest/*, scripts/scrub_newsletter_email.py, workers/newsletter/*                 (T9)
app/src/db/schema.ts, app/drizzle/0002_*, sync, Library, source page, Today sheet, maestro/add_podcast.yaml (T10)
services/api/tests/e2e/test_podcast_pipeline_e2e.py (Spotify case), docs, Makefile, maestro/README.md      (T11)
```

## Foundation tasks (run serially, in `m3-sources`)

### Task 1: Schema, settings, URL helpers and dependencies

**Files:**
- Create: `packages/archie-db/archie_db/migrations/versions/0003_all_sources.py`
- Modify: `packages/archie-db/archie_db/models.py`, `packages/archie-db/tests/test_db_migrations.py`, `packages/archie-shared/archie_shared/config.py`, `packages/archie-shared/archie_shared/urls.py`, `packages/archie-shared/tests/test_urls.py`, `conftest.py`, `.env.example`, `.railway/railway.ts`, `services/worker/pyproject.toml`, `services/api/pyproject.toml`, `pyproject.toml` (dev group, mypy overrides), `uv.lock`

**Interfaces:**
- Produces:
  - `models.SourceKind.NEWSLETTER = "newsletter"`; `models.JobKind.TRANSCRIBE = "transcribe"`; `models.TranscriptProvider(StrEnum)`: `GROQ = "groq"`, `OPENAI = "openai"`.
  - `models.INGEST_TOKEN_LENGTH = 10`; `models.new_ingest_token() -> str` (`secrets.choice` over `string.ascii_lowercase + string.digits`, 10 characters).
  - `models.User.ingest_token: Mapped[str]` — `String(16)`, unique, NOT NULL, Python `default=new_ingest_token` (so every `models.User(...)` in code and tests gets one).
  - `models.Source.sender: Mapped[str | None]` (`Text`), `models.Source.newsletter_message_id: Mapped[str | None]` (`String(998)`), unique index `uq_sources_user_id_newsletter_message_id` on `(user_id, newsletter_message_id)`.
  - `models.PodcastShow` (`podcast_shows`): `id BigInteger Identity PK`, `name_key String(512) unique NOT NULL`, `name Text NOT NULL`, `feed_url String(2048) NOT NULL`, `itunes_id BigInteger NULL`, `created_at`, `updated_at`.
  - `models.TranscriptChunk` (`transcript_chunks`): `id BigInteger Identity PK`, `source_id UUID FK sources.id ON DELETE CASCADE NOT NULL`, `chunk_index Integer NOT NULL`, `provider String(16) NOT NULL`, `model String(64) NOT NULL`, `segments JSONB NOT NULL` (absolute times: `[{"start": float, "text": str}]`), `created_at`. Unique constraint `uq_transcript_chunks_source_id_chunk_index` on `(source_id, chunk_index)`.
  - `models.LlmCall.audio_seconds: Mapped[Decimal | None]` (`Numeric(10, 3)`).
  - `config`: env-name constants `GROQ_API_KEY_ENV`, `OPENAI_API_KEY_ENV`, `SUPADATA_API_KEY_ENV`, `INGEST_SECRET_ENV`, `INGEST_EMAIL_DOMAIN_ENV`, `INGEST_ALIASES_ENV`; `Settings` fields `groq_api_key`, `openai_api_key`, `supadata_api_key`, `ingest_secret`, `ingest_email_domain`, `ingest_aliases` (all `str | None = None`); `Settings.ingest_alias_map() -> dict[str, str]` — `"news=a@x.com, test=a@x.com"` → `{"news": "a@x.com", "test": "a@x.com"}`, both sides stripped and lower-cased, entries without `=` or with an empty side skipped.
  - `urls.PodcastPlatform(StrEnum)`: `SPOTIFY = "spotify"`, `APPLE = "apple"`; `@dataclass(frozen=True) class urls.PodcastLink: platform: PodcastPlatform; episode_id: str; show_id: str | None`; `urls.podcast_link(url: str) -> PodcastLink | None` — `open.spotify.com/episode/<id>` → Spotify (show_id None); `podcasts.apple.com/<cc>/podcast/<slug>/id<digits>?i=<digits>` → Apple (show_id the digits after `id`); a show link, `?i=` missing, or any other URL → None.
  - `urls.youtube_video_id(url: str) -> str | None` — `youtube.com/watch?v=<id>`, `youtu.be/<id>`, `youtube.com/shorts/<id>`, `youtube.com/live/<id>`, with or without `www.`/`m.`; None otherwise (channels, playlists).
- Review: yes (migration).

**Migration `0003_all_sources`** (by hand, in `0002_capture_pipeline.py`'s style; `revision = "0003"`, `down_revision = "0002"`):
- `users.ingest_token`: add nullable `String(16)`; backfill `UPDATE users SET ingest_token = substr(md5(random()::text || id::text), 1, 10)` (hex digits are lowercase letters/digits); set NOT NULL; unique constraint. Name the constraint so `test_models_match_the_migrations` finds no difference (`unique=True` on the model column corresponds to Postgres's default `users_ingest_token_key`; adjust until the test is clean).
- `sources.sender Text NULL`, `sources.newsletter_message_id String(998) NULL`, the unique index above. `sources.kind` is a plain `String(16)` with no check constraint, so `newsletter` needs no schema change.
- `llm_calls.audio_seconds Numeric(10, 3) NULL`.
- Create `podcast_shows` and `transcript_chunks`.
- `downgrade()` drops all of it in reverse.

- [ ] **Step 1: Failing tests.**
  - `test_urls.py`: one test per case — Spotify episode (with `?si=` noise) → `PodcastLink(SPOTIFY, "abc", None)`; `https://open.spotify.com/show/4rOoJ6Egrf8K2IrywzwOMk` → None; `https://podcasts.apple.com/us/podcast/darknet-diaries/id1296350485?i=1000712345678` → `PodcastLink(APPLE, "1000712345678", "1296350485")`; the same without `?i=` → None; `youtube_video_id` for `watch?v=e0gVE3YxZs8&t=10`, `youtu.be/e0gVE3YxZs8`, `/shorts/e0gVE3YxZs8`, `/live/e0gVE3YxZs8`, `m.youtube.com/watch?v=e0gVE3YxZs8` → `"e0gVE3YxZs8"`; `youtube.com/@channel` → None.
  - `test_db_migrations.py`: `test_0003_gives_existing_users_an_ingest_token` (pattern of `test_0002_backfills_existing_m1_sources`: downgrade, upgrade to `"0002"`, insert two users with raw SQL, upgrade; each has a distinct 10-character `[a-z0-9]` token).
  - A config unit test for `ingest_alias_map` (malformed entries skipped, case folded) in `packages/archie-shared/tests/test_config.py` (create it).
- [ ] **Step 2: Run** `uv run pytest packages/archie-shared/tests` — fails (functions missing).
- [ ] **Step 3: Implement** urls, config, models, migration. Add `SUPADATA_API_KEY_ENV`, `INGEST_SECRET_ENV`, `INGEST_EMAIL_DOMAIN_ENV` and `INGEST_ALIASES_ENV` to root `conftest.py`'s `_SECRET_ENV_VARS` (and replace the `"OPENAI_API_KEY"`/`"GROQ_API_KEY"` literals with the new constants); add `"transcript_chunks", "podcast_shows"` to the front of `_TRUNCATE_TABLES`.
- [ ] **Step 4: Settings plumbing.** `.env.example`: one commented line each for `GROQ_API_KEY`, `OPENAI_API_KEY`, `SUPADATA_API_KEY`, `INGEST_SECRET`, `INGEST_EMAIL_DOMAIN` (e.g. `archiesecondbrain.com`), `INGEST_ALIASES` (`news=<owner email>,test=<owner email>`). `.railway/railway.ts`: add all six to the `archie` service's `env` as `preserve()`.
- [ ] **Step 5: Dependencies, once for every later task** (so parallel worktrees never conflict on `uv.lock`): `services/worker/pyproject.toml` add `"defusedxml>=0.7.1"`, `"youtube-transcript-api>=1.2"`; `services/api/pyproject.toml` add `"trafilatura>=2.3.1"`; root dev group add `"types-defusedxml"` (if it doesn't exist on PyPI, instead add a `[[tool.mypy.overrides]] module = "defusedxml.*" ignore_missing_imports = true`). Run `uv lock && uv sync`.
- [ ] **Step 6: Run** the full Python suite with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test uv run pytest -m "postgres or not postgres"` and `make lint` — all pass, including `test_models_match_the_migrations` and the downgrade round trip.
- [ ] **Step 7: Commit** "M3 schema: newsletters, transcript chunks, show registry, ingest tokens; podcast and YouTube URL parsing".

### Task 2: Worker contract: stale timeouts per kind, retry-after, audio costs

**Files:**
- Modify: `packages/archie-db/archie_db/jobs.py`, `packages/archie-db/archie_db/pipeline.py` (only `MAX_ATTEMPTS` and its use in `enqueue_steps`), `services/worker/archie_worker/loop.py`, `services/worker/archie_worker/errors.py`, `services/worker/archie_worker/llm.py`, `services/worker/tests/test_worker_e2e.py`, `services/worker/tests/test_llm.py`

**Interfaces:**
- Consumes: Task 1 (`JobKind.TRANSCRIBE`, `TranscriptProvider`, `LlmCall.audio_seconds`).
- Produces:
  - `jobs.enqueue(db, *, kind, user_id, payload, max_attempts: int | None = None) -> models.Job` (None keeps the column default 3).
  - `pipeline.MAX_ATTEMPTS: dict[models.JobKind, int] = {models.JobKind.TRANSCRIBE: 6}`; `enqueue_steps` passes `max_attempts=MAX_ATTEMPTS.get(step)`.
  - `errors.RetryLaterError(Exception)`: `__init__(self, *, reason: str, after_seconds: float)`, attributes `.reason`, `.after_seconds`.
  - `errors.FailureReason` adds (exact text): `SPOTIFY_ONLY = "This show is only on Spotify, so Archie can't get its audio."`, `EPISODE_NOT_FOUND = "Couldn't find this episode's audio. If the show is only on Spotify, Archie can't get it."`, `EPISODE_TOO_LONG = "This episode is too long to transcribe"`, `TRANSCRIPTION_NOT_SET_UP = "Transcription isn't set up on the server."`, `YOUTUBE_NEEDS_SETUP = "YouTube transcripts need setup on the server (a Supadata key)."`, `NO_CAPTIONS = "This video has no captions."`, `VIDEO_UNAVAILABLE = "This video isn't available."`
  - `loop.HandlerSpec` gains `stale_after: datetime.timedelta = STALE_AFTER` (field after `on_final_failure`).
  - `llm.CallContext.step: str` (was `models.JobKind`; a `JobKind` still passes since it is a `StrEnum`); `_record_call` stores `str(context.step)`.
  - `llm.CORRECTIONS_STEP = "corrections"`; `llm.CORRECTIONS_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)`.
  - `llm.GROQ_WHISPER = "whisper-large-v3-turbo"`, `llm.OPENAI_TRANSCRIBE = "gpt-4o-mini-transcribe"`.
  - `llm.audio_cost_usd(*, model: str, audio_seconds: Decimal) -> Decimal` — per-audio-hour table `{GROQ_WHISPER: Decimal("0.04"), OPENAI_TRANSCRIBE: Decimal("0.18")}`; `KeyError` for unknown models.
  - `llm.record_audio_call(engine: sqlalchemy.Engine, *, context: CallContext, provider: models.TranscriptProvider, model: str, audio_seconds: Decimal) -> None` — own session + commit; `input_tokens=0`, `output_tokens=0`, `stop_reason=None`, `audio_seconds` set, `cost_usd = audio_cost_usd(...)`.
- Review: yes (state machine, concurrency, money).

Loop behavior:
- `requeue_stale(db, *, now, handlers)`: a running job is stale when `started_at < now - handlers[kind].stale_after` (kinds missing from `handlers` use `STALE_AFTER`). Implement as one pass per kind in `handlers` (two `UPDATE ... RETURNING` per kind, as now, with `models.Job.kind == kind.value` added), then the hooks, then one commit. Keep the docstring accurate.
- `_record_failure`: a `RetryLaterError` with attempts left → `status=QUEUED`, `next_run_at = now() + max(after_seconds, 1)` seconds, `last_error = reason`. Out of attempts → failed with `GAVE_UP` as today. `PermanentJobError` unchanged.

- [ ] **Step 1: Tests** in `test_worker_e2e.py` (Postgres, small test-only handlers in a dict, as the existing hook tests do): a job of a kind with `stale_after=3600 s` that started 1,000 s ago is **not** requeued while one with the default is; the same job 4,000 s old is requeued; a handler raising `RetryLaterError(after_seconds=120)` leaves the job queued with `next_run_at` ~120 s ahead (assert within ±10 s of `now() + 120 s` read from Postgres) and `last_error` = the reason; on its last attempt it fails and calls the hook with `GAVE_UP`. `jobs.enqueue(..., max_attempts=6)` stores 6; `pipeline.enqueue_steps` for `TRANSCRIBE` stores 6.
- [ ] **Step 2: Tests** in `test_llm.py`: `audio_cost_usd(model=GROQ_WHISPER, audio_seconds=Decimal(3600)) == Decimal("0.04")`; `OPENAI_TRANSCRIBE` 1,800 s → `Decimal("0.09")`; unknown model → `KeyError`; `record_audio_call` (Postgres) inserts one row with tokens 0, `audio_seconds` 90.5, positive cost, provider `groq`, step `transcribe`.
- [ ] **Step 3: Run** them — fail. **Implement.** Run the whole worker suite — pass (existing HandlerSpec constructions still work since `stale_after` has a default).
- [ ] **Step 4: Commit** "Worker: per-kind stale timeouts, retry-after re-queueing, audio transcription costs".

### Task 3: Timed text, per-kind pipeline steps, analyze-v2

**Files:**
- Create: `services/worker/archie_worker/timestamps.py`, `services/worker/archie_worker/content/episode.py`, `services/worker/archie_worker/handlers/_text.py`, `services/worker/tests/test_timestamps.py`
- Modify: `services/worker/archie_worker/content/__init__.py`, `packages/archie-db/archie_db/pipeline.py`, `packages/archie-db/tests/test_pipeline.py`, `services/worker/archie_worker/prompts.py`, `services/worker/archie_worker/handlers/_llm_step.py`, `services/worker/archie_worker/handlers/analyze.py`, `services/worker/archie_worker/handlers/fetch_content.py`, `services/worker/tests/test_analyze_primer_e2e.py` (the cap test)

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `@dataclass(frozen=True) class content.Segment: start: float; text: str` (start in seconds from the beginning of the source).
  - `content.SEGMENTS_KEY = "segments"`, `content.TEXT_KEY = "text"`.
  - `content.timed_text_content(*, segments: Sequence[Segment], extra: Mapping[str, Any] | None = None) -> dict[str, Any]` → `{"text": " ".join(segment texts), "segments": [{"start": round(start, 2), "text": ...}], **extra}`; NUL characters stripped from every string.
  - `content.segments_of(text_content: Mapping[str, Any]) -> list[Segment]` (empty list when the key is absent).
  - `content.episode.EPISODE_KEY = "episode"`; `@dataclass(frozen=True) class content.episode.PodcastEpisode: show_name: str; title: str; description: str; feed_url: str; guid: str | None; audio_url: str; duration_s: int | None` with `to_payload() -> dict[str, Any]` and `@classmethod from_payload(cls, data: Mapping[str, Any]) -> PodcastEpisode`. This is the `transcribe` job payload's `episode` value and the `text` artifact's `episode` value.
  - `timestamps.format_timestamp(seconds: float) -> str` — under an hour `mm:ss` zero-padded (`0` → `"00:00"`, `59.9` → `"00:59"`, `734.2` → `"12:14"`); from an hour `h:mm:ss` (`3723` → `"1:02:03"`).
  - `timestamps.marked_text(segments: Sequence[content.Segment], *, every_seconds: float = 60.0) -> str` — segments joined by spaces; the first segment whose `start` is at or past the next boundary starts a new line with `[<format_timestamp(start)>] ` and moves the boundary to the next multiple of `every_seconds` after its start (the first segment always gets a marker).
  - `pipeline.required_artifacts(kind: models.SourceKind) -> tuple[models.ArtifactKind, ...]` — `(SUMMARY,)` for `NEWSLETTER`, else `(SUMMARY, PRIMER)`.
  - `pipeline.steps_after_text(kind: models.SourceKind) -> list[models.JobKind]` — `[ANALYZE]` for `NEWSLETTER`, else `[ANALYZE, PRIMER]`.
  - `pipeline.finish_step` uses `required_artifacts(models.SourceKind(source.kind))`; `pipeline.steps_to_retry` (signature unchanged; it reads the source's kind with `db.get`) only considers the steps of `steps_after_text(kind)`; with everything present it returns all of them.
  - `pipeline.set_processing` keeps `error` for `FAILED` **and** `UNSUPPORTED` (cleared otherwise).
  - `handlers._text.store_text(db, *, source: models.Source, text_content: dict[str, Any], title: str | None) -> None` — takes the user's lock, refreshes, returns if deleted; writes the `TEXT` artifact (`model=None, prompt_version=None`), sets the title if empty (the existing `_set_title_if_empty` rules move here), `pipeline.enqueue_steps(steps_after_text(kind))`.
  - `handlers._text.enqueue_transcribe(db, *, source: models.Source, episode: PodcastEpisode) -> None` — same lock/refresh/deleted guard; sets the title to `episode.title` if empty; `jobs.enqueue(kind=TRANSCRIBE, payload={pipeline.SOURCE_ID_KEY: str(source.id), EPISODE_KEY: episode.to_payload()}, max_attempts=pipeline.MAX_ATTEMPTS[TRANSCRIBE])`. The source stays `processing`.
  - `prompts.ANALYZE_PROMPT_VERSION = "analyze-v2"`; `prompts.MAX_TIMED_TEXT_CHARACTERS = 600_000`; `prompts.model_text(text_content: Mapping[str, Any]) -> str` — segments present → `marked_text(segments)[:600_000]`, else `text[:200_000]`; `prompts.user_message` no longer caps (its callers pass `model_text(...)`).
- Review: yes (state machine).

Prompt changes (`ANALYZE_SYSTEM`): **keep its first 60 characters unchanged** ("You process sources for a personal learning app. A source is") — the cassette matcher compares them, so the M2 analyze cassettes keep replaying. Replace the timestamp sentence with: the text of an episode may carry markers like `[12:14]` or `[1:02:03]` at roughly one-minute intervals; give each key idea and number the marker nearest before where it comes up, copied exactly; null when the text has no markers. Add to the cards rule: cards come only from the educational stretches of a source; a mostly entertaining show with one educational segment gets cards for that segment; still 3–5. Newsletter: add "A newsletter is an email digest; summarize its main stories." to the source-kind list. Primer prompt unchanged (`primer-v1`); it receives the same `model_text`.

`analyze.handle`: insert cards only when `analysis["is_educational"]` **and** the source kind is not `NEWSLETTER` (read the kind in `prepare_run`; add `kind: models.SourceKind` to `StepRun`).

`fetch_content.handle`: replace its inline write with `_text.store_text(db, source=source, text_content={"text": ...}, title=extracted.title)`. A newsletter source has a capture, so it already takes the capture branch; its minimum is the article minimum (50 words).

- [ ] **Step 1: Unit tests** `test_timestamps.py`: `format_timestamp` cases above; `marked_text` on segments at 0, 20, 61, 62, 130, 3700 s → markers on 0, 61, 130 and 3700 only (`[00:00]`, `[01:01]`, `[02:10]`, `[1:01:40]`), and a 4-segment list all inside the first minute → one marker. `model_text` caps: untimed 200,000; timed 600,000.
- [ ] **Step 2: DB tests** in `test_pipeline.py`: a newsletter source is READY after only a summary; `steps_to_retry` for a newsletter with text is `[ANALYZE]` and never includes `PRIMER`; `set_processing(UNSUPPORTED, error="x")` keeps `"x"`, `PROCESSING` clears it.
- [ ] **Step 3: Implement** everything above. Update `test_analyze_primer_e2e.py`'s cap test to `prompts.model_text`.
- [ ] **Step 4: Run** the full Python suite and `make lint` — pass with the existing cassettes (if an M2 analyze cassette stops matching, the 60-character prefix changed: restore it rather than re-recording).
- [ ] **Step 5: Commit** "Timed text with minute markers for analyze-v2; newsletters need only a summary".

### Task 4: Recording for Groq/OpenAI, audio-free cassettes, and the test media

**Files:**
- Modify: `packages/archie-testing/archie_testing/recording.py`
- Create: `packages/archie-testing/archie_testing/media.py`, `packages/archie-testing/tests/test_recording.py`

**Interfaces:**
- Consumes: Task 1 (`config.GROQ_API_KEY_ENV`, `OPENAI_API_KEY_ENV`).
- Produces:
  - `recording.use_recording_api_key(request, monkeypatch, *, env_names: Sequence[str] = (config.ANTHROPIC_API_KEY_ENV,)) -> None` — record mode: each name read from the repo-root `.env` (`pytest.fail` naming the missing variable, never its value); replay: each set to its placeholder from `recording.REPLAY_API_KEYS = {ANTHROPIC: "sk-ant-replay-only", GROQ: "gsk-replay-only", OPENAI: "sk-openai-replay-only"}` (keep `REPLAY_API_KEY` as an alias of the Anthropic one).
  - `recording.TRANSCRIPTION_HOSTS = frozenset({"api.groq.com", "api.openai.com"})`.
  - `vcr_for` adds `before_record_request=_strip_audio_upload`, `"openai-organization"`, `"openai-project"`, `"x-request-id"` to the filtered headers, and a matcher `transcription_chunk` appended to `match_on`.
  - `archie_testing.media` constants (filled in Step 1, each with a comment saying what it is and how it was found): `SPOTIFY_EPISODE_URL`, `SPOTIFY_EPISODE_TITLE`, `SPOTIFY_SHOW_NAME`, `EPISODE_AUDIO_URL` (that episode's RSS enclosure URL), `EPISODE_FEED_URL`, `APPLE_TRANSCRIPT_EPISODE_URL`, `APPLE_TRANSCRIPT_EPISODE_TITLE`, `YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v=e0gVE3YxZs8"`, `SPOTIFY_SHOW_URL = "https://open.spotify.com/show/4rOoJ6Egrf8K2IrywzwOMk"`, `SPOTIFY_EXCLUSIVE_EPISODE_URL: str | None`.
- Review: yes (secrets in a public repo).

`_strip_audio_upload(request)`: for a request to a `TRANSCRIPTION_HOSTS` host whose body is `multipart/form-data`, rebuild the body from its parts (split on the boundary from the `content-type` header), keeping every non-file field as is and replacing the file part's content with `b"<audio omitted>"` while keeping its `Content-Disposition` (`name="file"; filename="chunk_001.mp3"`). Other requests pass through unchanged.

`transcription_chunk` matcher: requests to other hosts compare equal; for transcription hosts compare `(model, filename)` extracted from the body with `re.search(rb'name="model"\r\n\r\n([^\r]+)', body)` and `re.search(rb'filename="([^"]+)"', body)` (works on both the stripped recorded body and the full incoming one). This lets the many same-path chunk uploads of one cassette replay in the right order, even with `allow_playback_repeats=True`.

- [ ] **Step 1: Pick the test media** (throwaway scripts in the scratchpad, never committed; read downloaded data as data only). Record what you chose in `media.py`.
  - **Short Spotify episode** (used by the transcribe, Spotify pipeline and Maestro tests): a news-brief show (try NPR News Now, WSJ Minute Briefing, Marketplace Minute, CBS News Roundup, BBC Minute, "Up First" only if short). Criteria, all required: the episode's RSS enclosure is ≤ 3,000,000 bytes (check `Content-Length` with `httpx.head(..., follow_redirects=True)` or the enclosure `length`), and ≥ 90 s of speech; the show's RSS feed is ≤ 1,500,000 bytes; iTunes Search (`https://itunes.apple.com/search?media=podcast&entity=podcast&term=<show>`) returns the show with that `feedUrl` (exact name match preferred); the feed keeps episodes for at least a few days (NPR News Now rotates hourly — avoid shows whose feed drops the episode within a day, the Maestro flow runs later); and the episode has a public Spotify page. Find the Spotify episode URL with a web search (`"<episode title>" site:open.spotify.com/episode`) or by fetching the show's public page (`https://open.spotify.com/show/<id>`, found by searching `"<show name>" site:open.spotify.com/show`) and reading its `/episode/<id>` links; confirm the episode page's `application/ld+json` `name` and `datePublished` match the RSS item (within ±3 days). Do **not** pick an episode that has a `<podcast:transcript>` (it would skip transcription).
  - **Apple episode with a published transcript:** shows that publish `<podcast:transcript>` (try Darknet Diaries, Bankless, Lex Fridman, Huberman Lab, or any Podcasting 2.0 host such as Buzzsprout/Transistor shows). Criteria: feed ≤ 2,000,000 bytes; the transcript file (prefer `text/vtt`) ≤ 300,000 bytes and ≥ 200 words; the episode is among the 200 newest in `https://itunes.apple.com/lookup?id=<collectionId>&entity=podcastEpisode&limit=200`. Build the link as `https://podcasts.apple.com/us/podcast/<any-slug>/id<collectionId>?i=<trackId>` from the lookup and open it once to check it resolves.
  - **YouTube:** `e0gVE3YxZs8` (Powell and the Fed in 60 s, auto captions, from the YouTube spike). Check it still has English captions with a one-off `uv run --with youtube-transcript-api python -I -c ...`; if gone, pick another public ≤ 2-minute captioned video and say so in the comment.
  - **Spotify-exclusive episode:** search for a current Spotify-exclusive show (no RSS: iTunes Search finds no show of that name, or its top hit's feed lacks the episode). Spend at most 15 minutes; if none, set `SPOTIFY_EXCLUSIVE_EPISODE_URL = None` with a comment, and Task 6 skips that test.
- [ ] **Step 2: Unit test** `test_recording.py` (no network): build a real multipart request locally with `httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions", data={"model": "whisper-large-v3-turbo", "language": "en"}, files={"file": ("chunk_001.mp3", b"\xff\xfb" * 5000, "audio/mpeg")})`, convert it to a `vcr.request.Request(method, uri, body=request.read(), headers=dict(request.headers))`; `_strip_audio_upload` drops the audio bytes (body under 1 KB, contains `<audio omitted>`, `chunk_001.mp3` and `whisper-large-v3-turbo`); the matcher says stripped-vs-full of the same chunk match, chunk_001 vs chunk_002 don't, and two requests to `api.anthropic.com` are left to the other matcher (equal). A non-transcription request is returned unchanged.
- [ ] **Step 3: Implement**; run the whole suite (existing cassettes still replay) and `make lint`.
- [ ] **Step 4: Commit** "Recording: Groq and OpenAI keys, audio stripped from cassettes, chunk-aware matching; test media".

### Task 5: Capture classification and the wire shapes

**Files:**
- Modify: `services/api/archie_api/sync/capture.py`, `services/api/archie_api/sync/schemas.py`, `services/api/archie_api/auth/routes.py`, `services/api/archie_api/test_routes.py` (nothing if `email` already passes through), `packages/archie-testing/archie_testing/harness.py`, `services/api/tests/e2e/test_sync_e2e.py`, `services/api/tests/e2e/test_auth_e2e.py`

**Interfaces:**
- Consumes: Task 1 (`urls.podcast_link`, `urls.youtube_video_id`, `User.ingest_token`, `Settings.ingest_email_domain`), Task 3 (`set_processing` keeps the unsupported error).
- Produces:
  - `SourceOut.sender: str | None` (after `merged_into_id`).
  - `MeView.ingest_address: str | None` — `f"{user.ingest_token}@{domain}"` when `INGEST_EMAIL_DOMAIN` is set, else None.
  - `LiveStack.sign_in(*, apple_sub="test-user", is_whitelisted=False, email: str | None = None) -> str` (passes `email` to `/test/session`).
  - capture: `_SHOW_LINK_REASON = "Share an episode, not the show."`, `_CHANNEL_LINK_REASON = "Share a video, not the channel."`; one private `_start_for(url: str) -> _Start` (`@dataclass(frozen=True) class _Start: processing: models.ProcessingStatus; error: str | None; first_job: models.JobKind`):
    - article, x → `PENDING`, None, `FETCH_CONTENT`
    - podcast with `podcast_link(url)` → `PENDING`, `FETCH_CONTENT`; without → `UNSUPPORTED`, `_SHOW_LINK_REASON`, `FETCH_TITLE`
    - youtube with `youtube_video_id(url)` → `PENDING`, `FETCH_CONTENT`; without → `UNSUPPORTED`, `_CHANNEL_LINK_REASON`, `FETCH_TITLE`
    Used by `_insert_source` (sets `processing_error` too) and `_reclassify_m1_source` (an M1 link whose URL now starts the pipeline gets `PENDING` + `FETCH_CONTENT`; otherwise only its kind changes, as now).
- Review: yes (sync, state machine).

- [ ] **Step 1: Update e2e tests** in `test_sync_e2e.py`: replace `test_a_youtube_or_podcast_url_is_unsupported_and_only_gets_a_title` with (a) YouTube video and Spotify episode → `pending` + one `fetch_content` job; (b) Spotify show link, Apple show link (no `?i=`), YouTube channel → `unsupported`, the matching `processing_error`, one `fetch_title` job. Change `test_sharing_an_m1_youtube_link_classifies_it_but_leaves_it_unsupported` to expect `pending` and a `fetch_content` job for `watch?v=abc123`, and add the same test for an M1 Spotify show link (stays unsupported, no fetch). Pulled sources carry `sender: None`. In `test_auth_e2e.py`: `/me` has `ingest_address` None without the domain and `<10 chars>@archiesecondbrain.com` with `INGEST_EMAIL_DOMAIN` set by `monkeypatch.setenv`.
- [ ] **Step 2: Run** — fails. **Implement.** Run the full suite (`test_main_path_e2e.py` still passes: its Spotify show link stays `unsupported` with `fetch_title`) and `make lint`.
- [ ] **Step 3: Commit** "Capture: podcast episodes and YouTube videos start the pipeline; sender and newsletter address on the wire".

## Parallel-safe tasks

Every task below depends only on Tasks 1–5. Each runs in its own `git gtr` worktree branched from the last foundation commit, with its own test database (`archie_test_t<N>`), and merges back into `m3-sources`. Overlaps are textual only: Tasks 6 and 8 each add one branch to `fetch_content.py`; Task 7 adds one entry to `handlers/__init__.py`.

### Task 6: Podcast episodes: resolve, show registry, published transcripts

**Files:**
- Create: `services/worker/archie_worker/content/podcast.py`, `services/worker/archie_worker/content/transcripts.py`, `services/worker/tests/test_podcast.py`, `services/worker/tests/test_podcast_e2e.py`, `services/api/tests/e2e/test_podcast_pipeline_e2e.py`, cassettes, `services/worker/tests/fixtures/podcast/` (one real feed and transcript file each copied out of a recorded cassette, for the pure parser tests)
- Modify: `services/worker/archie_worker/handlers/fetch_content.py`

**Interfaces:**
- Consumes: Task 1 (`urls.podcast_link`, `models.PodcastShow`), Task 2 (reasons), Task 3 (`Segment`, `timed_text_content`, `PodcastEpisode`, `EPISODE_KEY`, `_text.store_text`, `_text.enqueue_transcribe`), Task 4 (`media`, recording).
- Produces:
  - `@dataclass(frozen=True) class podcast.TranscriptLink: url: str; mime_type: str`
  - `@dataclass(frozen=True) class podcast.ResolvedEpisode: episode: PodcastEpisode; transcripts: list[TranscriptLink]`
  - `podcast.resolve(engine: sqlalchemy.Engine, *, link: urls.PodcastLink) -> ResolvedEpisode` — raises `PermanentJobError(SPOTIFY_ONLY)` when iTunes Search finds no show, `PermanentJobError(EPISODE_NOT_FOUND)` when no feed item matches (or Apple's lookup lacks the episode).
  - Pure helpers (unit-tested): `podcast.spotify_episode_from_page(page: str) -> SpotifyEpisode` (`@dataclass(frozen=True) SpotifyEpisode: title: str; show_name: str; published: datetime.date`; `ValueError` when the ld+json or the "Listen to this episode from {show} on Spotify." prefix is missing → the caller maps it to `EPISODE_NOT_FOUND`); `podcast.parse_feed(feed: bytes) -> list[FeedItem]` (`defusedxml.ElementTree.fromstring`; `FeedItem`: `title, published: datetime.date | None, guid: str | None, audio_url: str | None, duration_s: int | None, description: str, transcripts: list[TranscriptLink]`; `itunes:duration` as seconds or `[h:]mm:ss`; description with tags stripped and whitespace collapsed, capped at 2,000 characters); `podcast.best_match(*, title: str, published: datetime.date, items: Sequence[FeedItem]) -> FeedItem | None` (items within ±3 days, highest `SequenceMatcher` ratio of the spike's `_normalize`d titles, ≥ 0.6, and only items with an `audio_url`); `podcast.name_key(name: str) -> str` (lower-cased, whitespace collapsed).
  - `transcripts.fetch_best(links: Sequence[TranscriptLink]) -> transcripts.PublishedTranscript | None` (`@dataclass(frozen=True) PublishedTranscript: text: str; segments: list[Segment]`) — tries links in preference order `text/vtt`, then `application/x-subrip`/`application/srt`, then `application/json`, then `text/html`/`text/plain`; 30 s, 10 MB each; a fetch or parse failure moves to the next; None when nothing yields ≥ 200 words.
  - Pure parsers: `transcripts.parse_vtt(text: str) -> list[Segment]`, `parse_srt(text: str) -> list[Segment]`, `parse_json(text: str) -> list[Segment]` (Podcasting 2.0: `segments[].startTime`, `segments[].body`), `html_to_text(text: str) -> str`. Cue text has tags (`<v Name>`, `<c>`) removed; consecutive cues are kept as separate segments.
- Review: yes (outside input parsing).

Resolution (spec "Podcasts: resolving the episode", following `spikes/podcast_resolve/resolve_episodes.py`): httpx with the spike's browser `User-Agent`, `follow_redirects=True`, size-capped reads via `fetch_title.fetch_page` (Spotify 15 s / 5 MB) and a bytes variant for feeds (30 s / 50 MB; add `fetch_title.fetch_bytes(*, url, timeout_seconds, max_bytes) -> bytes` next to `fetch_page` and make `fetch_page` decode its result).
- Spotify: page → `SpotifyEpisode` → registry lookup by `name_key(show_name)` in a short `Session(engine)`; miss → iTunes Search `https://itunes.apple.com/search?media=podcast&entity=podcast&term=<show>&limit=5`, exact case-insensitive `collectionName` match else the top hit; no results → `SPOTIFY_ONLY`. Feed → `best_match`; none → `EPISODE_NOT_FOUND`. Only after a match, upsert the registry row (`INSERT ... ON CONFLICT (name_key) DO UPDATE SET feed_url, itunes_id, updated_at`) in its own short session.
- Apple: `https://itunes.apple.com/lookup?id=<show_id>&entity=podcastEpisode&limit=200`; the result with `wrapperType == "track"` has `feedUrl`; the `podcastEpisode` result with `trackId == int(episode_id)` gives `trackName`, `releaseDate`, `episodeGuid`; match the feed item by guid first, else `best_match`. Apple doesn't touch the registry.
- `PodcastEpisode` from the match: `show_name` (Spotify's name, or Apple's `collectionName`), `title` (the feed item's), `description`, `feed_url`, `guid`, `audio_url`, `duration_s`.

`fetch_content` podcast branch (after `_start_processing`, which already committed): `link = urls.podcast_link(url)` (None → `PermanentJobError(EPISODE_NOT_FOUND)`); `resolved = podcast.resolve(engine, link=link)`; `published = transcripts.fetch_best(resolved.transcripts)`; published → `_text.store_text(text_content=content.timed_text_content(segments=published.segments, extra={EPISODE_KEY: resolved.episode.to_payload()}) if published.segments else {"text": published.text, EPISODE_KEY: ...}, title=resolved.episode.title)`; else `_text.enqueue_transcribe(source=source, episode=resolved.episode)`. Get the engine with `db.get_bind()` + `assert isinstance(engine, sqlalchemy.Engine)` as `_llm_step.call_model` does.

- [ ] **Step 1: Record** (`--record-mode=once`, the test DB set) in `test_podcast_e2e.py` (worker level, `run_one` with real `HANDLERS`, `recording.vcr_for`, `allow_playback_repeats=True`):
  - `podcast_apple_transcript`: `media.APPLE_TRANSCRIPT_EPISODE_URL` → lookup, feed, transcript; **no audio request** (assert no recorded request path ends in `.mp3`/`.m4a`).
  - `podcast_spotify_resolve`: `media.SPOTIFY_EPISODE_URL` → page, iTunes Search, feed (no transcript, so a `transcribe` job is queued, no download).
  - `podcast_spotify_registry_hit`: the same link with a `podcast_shows` row for that show inserted first → page and feed only (no `itunes.apple.com` request).
  - `podcast_spotify_exclusive` (only if `media.SPOTIFY_EXCLUSIVE_EPISODE_URL`; else `pytest.skip` with the reason).
  Copy the Apple feed's bytes and the transcript file out of their cassette into `fixtures/podcast/` for the parser tests (the feed trimmed to its first 5 items by an XML-aware script, so the fixture stays small).
- [ ] **Step 2: Unit tests** `test_podcast.py`: `parse_vtt` on the fixture transcript (first segment start 0-ish, starts non-decreasing, tags stripped, ≥ 200 words), `parse_srt`/`parse_json` on small real files: download one real SRT and one real Podcasting 2.0 JSON transcript from any public feed that offers them (note the source URL in a comment); if none turns up in 10 minutes, convert the real VTT fixture to SRT and to JSON with a throwaway script, commit the converted files, and say in the test docstring that they were converted from the real VTT; `parse_feed` on the fixture (titles, dates, enclosures, durations, transcript links); `best_match`: exact title 2 days apart wins; a 0.59-ratio title → None; a matching title 4 days apart → None; an item without audio is skipped; `spotify_episode_from_page` on the Spotify page copied out of `podcast_spotify_resolve` (title, show name, date); `name_key("  The  Daily ")=="the daily"`.
- [ ] **Step 3: E2e assertions:** Apple → text artifact v1 with `segments` (≥ 200 words, starts non-decreasing) and `episode` (feed_url, audio_url set), title = the episode title, analyze + primer jobs queued, no `transcribe` job. Spotify → no text artifact, one `transcribe` job whose payload `episode` round-trips through `PodcastEpisode.from_payload` with `audio_url == media.EPISODE_AUDIO_URL`, title set, source `processing`, one `podcast_shows` row with `name_key(media.SPOTIFY_SHOW_NAME)`. Registry hit → same result; its cassette has no `itunes.apple.com` request, so a replay that tried iTunes would fail. Exclusive → job failed after one attempt, source `failed` with `SPOTIFY_ONLY` or `EPISODE_NOT_FOUND` (whichever the real data produces; assert it's one of the two and that no `podcast_shows` row was written).
- [ ] **Step 4: API e2e** `services/api/tests/e2e/test_podcast_pipeline_e2e.py` (copy the helpers of `test_pipeline_e2e.py`; `pytestmark = [postgres, worker]`): whitelisted user pushes `add_source` for `media.APPLE_TRANSCRIPT_EPISODE_URL` (intent finished) → poll until `ready` → summary and primer present; at least one key idea or number has a timestamp matching `^\d{1,2}:\d{2}(:\d{2})?$`; `llm_calls` steps `["analyze", "primer"]` with positive costs. Record `pipeline_podcast_apple.yaml` once (Anthropic key via `use_recording_api_key`). Also `test_a_spotify_show_link_is_unsupported` (no cassette needed: it only queues `fetch_title`; assert the pulled `processing_error`).
- [ ] **Step 5: Implement**, run the suite against `archie_test_t6` and `make lint`; cassette key grep and `du -h` checks.
- [ ] **Step 6: Commit** "Worker: resolve podcast episodes through Spotify, iTunes and RSS; published transcripts; show registry".

### Task 7: `transcribe`: download, chunk, Groq with OpenAI fallback, name corrections, resume

**Files:**
- Create: `services/worker/archie_worker/transcription.py`, `services/worker/archie_worker/corrections.py`, `services/worker/archie_worker/handlers/transcribe.py`, `services/worker/tests/test_transcription.py` (unit), `services/worker/tests/test_transcribe_e2e.py`, cassettes, `services/worker/tests/fixtures/audio/short_chunk.mp3`
- Modify: `services/worker/archie_worker/handlers/__init__.py`, `Dockerfile`, `.github/workflows/python.yaml`

**Interfaces:**
- Consumes: Task 1 (`TranscriptChunk`, `TranscriptProvider`, settings), Task 2 (`RetryLaterError`, reasons, `llm.record_audio_call`, `llm.CORRECTIONS_*`, `HandlerSpec.stale_after`), Task 3 (`Segment`, `timed_text_content`, `PodcastEpisode`, `EPISODE_KEY`, `_text.store_text`), Task 4 (recording, `media.EPISODE_AUDIO_URL`).
- Produces:
  - `transcription.CHUNK_SECONDS = 600`, `OPENAI_PART_SECONDS = 300`, `DOWNLOAD_TIMEOUT_SECONDS = 600`, `MAX_AUDIO_BYTES = 600_000_000`, `MIN_WORDS_PER_MINUTE = 100`, `MIN_CHECKED_CHUNK_SECONDS = 30`, `GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"`, `OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"`.
  - `@dataclass(frozen=True) class transcription.TranscriptionKeys: groq: str | None; openai: str | None`; `transcription.keys_for(user: models.User) -> TranscriptionKeys` — not whitelisted → `PermanentJobError(NEEDS_API_KEY)`; neither key set → `PermanentJobError(TRANSCRIPTION_NOT_SET_UP)`.
  - `transcription.download(*, url: str, directory: pathlib.Path) -> pathlib.Path` — streamed with httpx (`follow_redirects=True`), total-deadline check per chunk as `fetch_title.fetch_page` does, over `MAX_AUDIO_BYTES` → `PermanentJobError(EPISODE_TOO_LONG)`.
  - `@dataclass(frozen=True) class transcription.AudioChunk: index: int; path: pathlib.Path; start_seconds: float; duration_seconds: float`; `transcription.split(*, audio: pathlib.Path, directory: pathlib.Path, chunk_seconds: float) -> list[AudioChunk]` — `ffmpeg -loglevel error -i <audio> -ac 1 -ar 16000 -b:a 32k -f segment -segment_time <chunk_seconds> <dir>/chunk_%03d.mp3` (`subprocess.run(..., check=True)`), durations from `ffprobe -v error -show_entries format=duration -of csv=p=0`, `start_seconds` = sum of the previous durations.
  - `transcription.needs_fallback(*, segments: Sequence[Segment], duration_seconds: float) -> bool` — False under `MIN_CHECKED_CHUNK_SECONDS`; else words / (duration / 60) < `MIN_WORDS_PER_MINUTE`.
  - `transcription.GroqRejectedError(Exception)` — Groq answered 4xx other than 429.
  - `transcription.transcribe_groq(*, chunk: AudioChunk, api_key: str, prompt: str) -> list[Segment]` — multipart `file`, `model=whisper-large-v3-turbo`, `response_format=verbose_json`, `language=en`, `temperature=0`, `prompt`; `segments[].start + chunk.start_seconds`, text stripped; 429 → `RetryLaterError(reason="Groq rate limit", after_seconds=float(retry-after or 60))`; other 4xx → `GroqRejectedError`; 5xx → `raise_for_status()`. Timeout 300 s.
  - `transcription.transcribe_openai(*, chunk: AudioChunk, api_key: str, prompt: str, directory: pathlib.Path) -> list[Segment]` — `split` the chunk again into `OPENAI_PART_SECONDS` parts (named `<chunk stem>_part_%03d.mp3`), each sent with `model=gpt-4o-mini-transcribe`, `response_format=json`, `language=en`, `prompt`; one `Segment(start=chunk.start_seconds + part.start_seconds, text=json["text"])` per part.
  - `transcription.transcribe_chunk(engine, *, chunk: AudioChunk, keys: TranscriptionKeys, prompt: str, context: llm.CallContext, directory: pathlib.Path) -> ChunkTranscript` (`@dataclass(frozen=True) ChunkTranscript: provider: models.TranscriptProvider; model: str; segments: list[Segment]`) — Groq when a Groq key exists (record an audio call after each successful response); on `GroqRejectedError` or `needs_fallback` → OpenAI if an OpenAI key exists (record its call), else keep Groq's segments (or re-raise the Groq rejection if there are none); no Groq key → OpenAI directly.
  - `corrections.SYSTEM` (the `correct_names` spike's `SYSTEM_PROMPT` with the web-search sentence removed and a rule added: `context` is 4–12 words copied exactly from the transcript around the mishearing and containing `heard`), `corrections.SCHEMA` (the spike's schema with `evidence` replaced by `"context": {"type": "string"}`), `@dataclass(frozen=True) class corrections.Correction: heard: str; correct: str; context: str`, `corrections.MAX_OUTPUT_TOKENS = 16000`.
  - `corrections.request(engine, *, api_key: str, context: llm.CallContext, episode: PodcastEpisode, text: str) -> list[Correction]` — `llm.complete(models=llm.CORRECTIONS_MODELS, system=SYSTEM, user_message=f"Show: {show}\nEpisode title: {title}\nEpisode description: {description}\n\n<transcript>\n{text}\n</transcript>", json_schema=SCHEMA, max_tokens=MAX_OUTPUT_TOKENS)` with `context.step == llm.CORRECTIONS_STEP`; drops entries with empty `heard` or `heard == correct`.
  - `corrections.apply(segments: Sequence[Segment], corrections: Sequence[Correction]) -> list[Segment]` (pure).
  - `handlers.transcribe.handle(db, job) -> None`; registered `HandlerSpec(run=transcribe.handle, on_final_failure=mark_source_failed, stale_after=datetime.timedelta(seconds=3600))`.
- Review: yes (resume logic, money, concurrency).

`corrections.apply` algorithm: join the segment texts with single spaces into one string, remembering each segment's `[start, end)` character span. For each correction, find every case-insensitive occurrence of its `context`; inside each occurrence, find whole-word (`(?<!\w)…(?!\w)`, `re.IGNORECASE`) matches of `heard`; skip a match that crosses a segment span boundary (log it); collect `(begin, end, correct)` replacements, dropping overlaps. Apply replacements from the end backwards to each segment's own text (translating offsets into that segment). Corrections whose context is never found change nothing. Never replace outside a context occurrence.

`transcribe.handle`:
1. Read the source (skip deleted), `keys = transcription.keys_for(user)`, `anthropic_key = llm.api_key_for(user)`, `episode = PodcastEpisode.from_payload(job.payload[EPISODE_KEY])`, the finished chunk indexes (`SELECT chunk_index FROM transcript_chunks WHERE source_id = ...`); `db.commit()`.
2. In a `tempfile.TemporaryDirectory()`: `download`, `split(chunk_seconds=CHUNK_SECONDS)`; for each chunk not finished: `transcribe_chunk(...)` (prompt `f"{episode.show_name}. {episode.title}."`, `CallContext(step=models.JobKind.TRANSCRIBE)`), then store it at once in its own session with `postgresql.insert(models.TranscriptChunk).values(...).on_conflict_do_nothing(index_elements=["source_id", "chunk_index"])` + commit, so a later failure keeps it. Log before each chunk (`"Transcribing chunk %d/%d of source %s"`).
3. Read every chunk's segments in `chunk_index` order (short session) → one segment list.
4. Corrections: `corrections.request(...)`; on `llm.ModelOutputError`, `anthropic.APIError` or `json.JSONDecodeError` log a warning and use no corrections (the transcript is not failed). `corrections.apply`.
5. `_text.store_text(db, source=source, text_content=content.timed_text_content(segments=corrected, extra={EPISODE_KEY: episode.to_payload()}), title=episode.title)`.

- [ ] **Step 1: Unit tests** `test_transcription.py` (no network): `needs_fallback` — 600 s with 1,500 words → False; 600 s with 900 words → True; 20 s with 3 words → False (exempt); `corrections.apply` — the "Gary" case (three "Gary"s in different segments, one correction `{heard: "Gary", correct: "Gabby", context: "and then Gary said the Fed"}` changes only the one inside that context), a context that isn't in the text changes nothing, whole-word only ("Ty" doesn't touch "Tyler"), case-insensitive match keeps other text intact, a match spanning two segments is skipped, two corrections in one context both apply.
- [ ] **Step 2: Fixture audio:** after Step 3's first recording, make `fixtures/audio/short_chunk.mp3` from the downloaded episode (take it out of the cassette's response body with a small script, or download `media.EPISODE_AUDIO_URL` once): `ffmpeg -i <episode> -t 60 -ac 1 -ar 16000 -b:a 32k short_chunk.mp3` (≈ 240 KB).
- [ ] **Step 3: Record and assert** in `test_transcribe_e2e.py` (Postgres; `recording.use_recording_api_key(env_names=(ANTHROPIC, GROQ, OPENAI))`; monkeypatch `transcription.CHUNK_SECONDS = 60`; a whitelisted user, a podcast source in `processing`, and a `transcribe` job enqueued with `_text.enqueue_transcribe` and a `PodcastEpisode` built from `media` constants):
  - `transcribe_short_episode` (the only audio-bearing cassette in this task): run `run_one` until idle for the transcribe job only (assert the next queued jobs are analyze + primer and don't run them). Text artifact has `segments` with non-decreasing starts spanning > 60 s (so offsets were applied), `episode` present; `transcript_chunks` has one row per chunk; `llm_calls` has one `groq` row per chunk (`audio_seconds` > 0, `cost_usd` > 0, tokens 0) and one `corrections` row (Haiku, cost > 0).
  - Resume: insert a `transcript_chunks` row for chunk 0 with provider `groq` and our own segments `[{"start": 0.0, "text": "RESUMED CHUNK ZERO"}]`, then replay **the same cassette** (`allow_playback_repeats=True`): groq `llm_calls` rows = chunks − 1, and the text starts with "RESUMED CHUNK ZERO" (each Groq call writes one cost row, so the count proves chunk 0 was never sent).
  - Too long: monkeypatch `transcription.MAX_AUDIO_BYTES = 1000` and replay the same cassette → job failed after one attempt, source `failed` with `EPISODE_TOO_LONG`, no `llm_calls`.
  - Keys: non-whitelisted user → failed at once with `NEEDS_API_KEY`, zero `llm_calls`, no HTTP (empty cassette in `none` mode); whitelisted with neither Groq nor OpenAI key (delete both env vars) → `TRANSCRIPTION_NOT_SET_UP`.
  - `transcribe_openai_chunk`: `transcription.transcribe_openai` on `short_chunk.mp3` (as `AudioChunk(index=3, start_seconds=180.0, ...)`) → segments start at 180.0 and contain ≥ 50 words; one recorded OpenAI call.
  - `transcribe_groq_rejected`: `transcribe_chunk` on `short_chunk.mp3` with `TranscriptionKeys(groq="gsk-invalid", openai=<real>)` — record with that literal invalid Groq key so Groq answers a real 401 → result provider `openai`, one `openai` cost row and no `groq` row.
  Check the cassettes: no audio bytes in any Groq/OpenAI request body (`grep -c "audio omitted"` > 0), key grep clean, `du -h` within limits.
- [ ] **Step 4: Implement** `transcription.py`, `corrections.py`, the handler and its registration.
- [ ] **Step 5: ffmpeg in the image and CI.** `Dockerfile`: before `uv sync`, `RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*`. `.github/workflows/python.yaml` `Test` job: a step `sudo apt-get update && sudo apt-get install -y ffmpeg` before "Run tests". Run `docker build -t archie-m3-check .` locally if Docker can build (it is up for Postgres); then `docker run --rm archie-m3-check ffmpeg -version | head -1`.
- [ ] **Step 6: Run** the suite against `archie_test_t7` and `make lint`.
- [ ] **Step 7: Commit** "Worker: transcribe podcasts with Groq, OpenAI fallback and name corrections, resuming finished chunks".

### Task 8: YouTube captions

**Files:**
- Create: `services/worker/archie_worker/content/youtube.py`, `services/worker/tests/test_youtube.py`, `services/worker/tests/test_youtube_e2e.py`, cassettes; add a YouTube case to `services/api/tests/e2e/test_youtube_pipeline_e2e.py` (create)
- Modify: `services/worker/archie_worker/handlers/fetch_content.py`

**Interfaces:**
- Consumes: Task 1 (`urls.youtube_video_id`, `Settings.supadata_api_key`), Task 2 (reasons), Task 3 (`Segment`, `timed_text_content`, `_text.store_text`), Task 4 (`media.YOUTUBE_VIDEO_URL`, recording).
- Produces:
  - `youtube.SUPADATA_URL = "https://api.supadata.ai/v1/youtube/transcript"`
  - `youtube.fetch_segments(*, video_id: str, supadata_api_key: str | None) -> list[Segment]` — Supadata when a key is given (`GET SUPADATA_URL?videoId=<id>&lang=en`, header `x-api-key`, 30 s; `content[].offset` is milliseconds → seconds; read its docs at https://supadata.ai/documentation first and follow them where they differ — never request the AI-generated mode; a 404/"transcript-unavailable" answer → `NO_CAPTIONS`), else `youtube_transcript_api.YouTubeTranscriptApi().fetch(video_id, languages=["en"])` → one `Segment(start=snippet.start, text=snippet.text)` per snippet (newlines collapsed to spaces, empty snippets and `[Music]`-only snippets dropped).
  - `youtube.permanent_error_for(error: Exception, *, has_supadata_key: bool) -> errors.PermanentJobError | None` — `RequestBlocked`/`IpBlocked` without a Supadata key → `YOUTUBE_NEEDS_SETUP`; `TranscriptsDisabled`/`NoTranscriptFound` → `NO_CAPTIONS`; `VideoUnavailable` → `VIDEO_UNAVAILABLE`; anything else → None (the caller re-raises, the loop retries).
  - `youtube.fetch_title(*, video_id: str) -> str | None` — `fetch_title.fetch_page("https://www.youtube.com/watch?v=<id>", 15 s, 5 MB)` → `fetch_title.extract_title`; `httpx.HTTPError`/`TimeoutError` → None (title stays the URL).
- Review: no.

`fetch_content` youtube branch: `video_id = urls.youtube_video_id(url)` (None → `PermanentJobError(VIDEO_UNAVAILABLE)`; capture already filters it); segments via `fetch_segments` with `permanent_error_for` mapping (`except youtube_transcript_api.CouldNotRetrieveTranscript as error`); word count < 50 → `NO_CAPTIONS`; title via `youtube.fetch_title` when the source has none; `_text.store_text(text_content=content.timed_text_content(segments=...), title=...)`.

- [ ] **Step 1: Unit test** `test_youtube.py`: `permanent_error_for` with real exception instances built from the library's classes (e.g. `youtube_transcript_api.RequestBlocked("e0gVE3YxZs8")`; check each class's constructor in the installed package) for every row of the mapping, including blocked-with-Supadata-key → None.
- [ ] **Step 2: Record** (from this Mac, direct path, no Supadata key) `youtube_powell.yaml` in `test_youtube_e2e.py`: fetch_content for `media.YOUTUBE_VIDEO_URL` → text artifact with ≥ 100 words and segments with non-decreasing starts, title set from `og:title`, analyze + primer queued. If YouTube rate-limits the recording (`429`), wait a few minutes and retry; don't loop.
- [ ] **Step 3: API e2e** `test_youtube_pipeline_e2e.py` (`postgres`, `worker`): whitelisted user adds `media.YOUTUBE_VIDEO_URL` → `ready`; summary present; at least one key idea or number timestamp matches `^\d{1,2}:\d{2}(:\d{2})?$`; `llm_calls` analyze + primer. Record `pipeline_youtube.yaml`.
- [ ] **Step 4: Implement**; run the suite against `archie_test_t8` and `make lint`; cassette checks.
- [ ] **Step 5: Follow-up note:** add to the M3 spec's end a "Follow-ups" line: "Record a Supadata cassette (`youtube_supadata.yaml`, same video) once `SUPADATA_API_KEY` exists; until then the Supadata branch is untested." (If Task 11 also edits the spec, the merge is textual.)
- [ ] **Step 6: Commit** "Worker: YouTube captions (Supadata when configured, else direct) with timestamps".

### Task 9: Newsletter ingest: fixtures, `POST /ingest/email`, Email Worker

**Files:**
- Create: `scripts/scrub_newsletter_email.py`, `services/api/tests/fixtures/newsletters/{morning_brew.eml,substack_bytebytego.eml}`, `services/api/archie_api/ingest/__init__.py`, `services/api/archie_api/ingest/email_message.py`, `services/api/archie_api/ingest/routes.py`, `services/api/tests/test_email_message.py`, `services/api/tests/e2e/test_ingest_e2e.py`, cassettes, `workers/newsletter/{worker.js,wrangler.toml,README.md}`
- Modify: `services/api/archie_api/main.py`

**Interfaces:**
- Consumes: Task 1 (`SourceKind.NEWSLETTER`, `Source.sender`, `Source.newsletter_message_id`, `User.ingest_token`, ingest settings, `ingest_alias_map`), Task 3 (newsletter → analyze only, no cards), Task 5 (`LiveStack.sign_in(email=...)`, `/me.ingest_address`).
- Produces:
  - Route `POST /ingest/email`: headers `x-ingest-secret`, `x-ingest-to`, `x-ingest-from`; body the raw RFC 822 bytes. 401 missing/wrong secret (also when `INGEST_SECRET` is unset); 413 over `INGEST_MAX_BYTES = 10 * 1024 * 1024` (check `content-length` first, then count while reading); 202 `{"status": "accepted"}` for created, duplicate and unknown-recipient alike.
  - `@dataclass(frozen=True) class email_message.ParsedEmail: subject: str | None; sender: str | None; message_id: str; web_url: str | None; text: str`
  - `email_message.parse(raw: bytes) -> ParsedEmail` — `email.message_from_bytes(raw, policy=email.policy.default)`; subject decoded; `sender` = `From` display name, else its address; `message_id` = `Message-ID` without angle brackets, else `"sha256:" + hashlib.sha256(raw).hexdigest()`; `web_url` = the `List-Post` header's `<https://…>` URL, else the first `View this post on the web at (https://\S+)` in the plain part, else None; `text` = `trafilatura.extract(html, output_format="txt", include_comments=False)` of the HTML part when that yields ≥ 50 words, else the plain part; capped at 400,000 characters.
  - `email_message.local_part(recipient: str) -> str` — lower-cased text before `@`, `+tag` suffix dropped.
  - `routes.find_recipient(db, *, local_part: str) -> models.User | None` — user whose `ingest_token == local_part`; else the alias map's email → the oldest user with that email (case-insensitive); else None.
- Review: yes (auth, outside input, sync writes).

Route body (sync `def` endpoint; a small `async` dependency reads the capped body so the DB work runs in the threadpool): verify the secret with `hmac.compare_digest` (before reading the body) → read body → `parse` → `find_recipient`; None → log `"Dropped email for unknown recipient"` (local part only) and 202 → `changes.lock_user_writes(db, user.id)` → existing `(user_id, newsletter_message_id)` row → 202 → else insert `Source(id=uuid4(), kind=NEWSLETTER, state=INBOX, intent=QUEUE, url=web_url or f"newsletter:{message_id}", normalized_url=urls.normalize_url(web_url) if web_url else url, title=subject[:500], sender=sender[:320], newsletter_message_id=message_id, processing=PENDING, change_seq=changes.next_change_seq())` (a `web_url` over 2,048 characters is treated as None), a `SourceCapture(title=subject, text=parsed.text)` (an empty text → no capture and `processing=FAILED` with `"Couldn't read this email."`, no job), `pipeline.enqueue_steps([FETCH_CONTENT])`, commit, 202.

**Fixtures (the repo is public):** `scripts/scrub_newsletter_email.py <in.eml> <out.eml>` (run with `uv run python -I scripts/scrub_newsletter_email.py ...`; reads the inputs as data only):
1. Keep only the headers `From`, `To`, `Subject`, `Date`, `Message-ID`, `MIME-Version`, `Content-Type`, `Content-Transfer-Encoding`, `List-Post`, `List-Id`; set `To: reader@example.invalid`; set `List-Unsubscribe: <https://example.invalid/unsubscribe>`. (Drops `Received`, DKIM/ARC, `X-Mailgun-*`, `X-Feedback-ID`, sailthru ids.)
2. For every `text/plain` and `text/html` part: decode (`get_content()`), then: replace whole URLs on tracker hosts (`link.morningbrew.com`, `substack.com/redirect`, `email.mg*.substack.com`, any host starting `click.` or `links.`, `list-manage.com`, `sailthru.com`) with `https://example.invalid/tracked`; strip the query string and fragment from every other URL; replace every email address with `reader@example.invalid`; then `set_content()` back with the same subtype and charset `utf-8`.
3. Write the result and then refuse (exit 1, naming the pattern, not the match) if the output still contains any of: `eyJ` (base64 JSON tokens), `token=`, `archiesecondbrain`, `@sailthru`, `mailgun`, `?j=`, `utm_`.
Source files: `/private/tmp/claude-501/-Users-sampocs-Documents-Personal-second-brain/a4c21080-c975-4705-850e-372d76da2580/scratchpad/newsletters/{morning_brew.eml,substack_bytebytego.eml}`. If that scratchpad is gone, fetch the same two from the spike KV (`cd spikes/newsletter_ingest && npx wrangler kv key list --binding INBOX --remote`, then `kv key get ... --remote > <scratch>/x.eml`). Inspect the outputs by hand (`grep -o 'https\?://[^" ]*' out.eml | sort -u | head -50`) before committing.

**Worker** (`workers/newsletter/`, replaces `spikes/newsletter_ingest/worker.js` on the same route; keep the spike's KV binding):
```js
// Forwards every email to Archie's API, and keeps the raw message in KV as a debugging record.
export default {
  async email(message, env) {
    const raw = await new Response(message.raw).arrayBuffer();
    await env.INBOX.put(`${new Date().toISOString()}_${message.to}`, raw, {
      metadata: { from: message.from, to: message.to, subject: message.headers.get("subject") ?? "" },
    });

    const response = await fetch(`${env.API_URL}/ingest/email`, {
      method: "POST",
      headers: {
        "content-type": "message/rfc822",
        "x-ingest-secret": env.INGEST_SECRET,
        "x-ingest-to": message.to,
        "x-ingest-from": message.from,
      },
      body: raw,
    });
    // Throwing makes Cloudflare retry or bounce, so a failed delivery is never silently lost.
    if (!response.ok) throw new Error(`Archie ingest answered ${response.status}`);
  },
};
```
`wrangler.toml`: `name = "archie-newsletter"`, `main = "worker.js"`, `compatibility_date = "2026-10-01"`, the spike's `[[kv_namespaces]]` block, `[vars] API_URL = "https://archie-production-4856.up.railway.app"`. `README.md`: deploy steps for the owner (`npx wrangler secret put INGEST_SECRET` with the same value as Railway's; `npx wrangler deploy`; Cloudflare dashboard → Email Routing → catch-all → Send to Worker `archie-newsletter`; send a test mail; then delete the spike worker with `npx wrangler delete` in `spikes/newsletter_ingest`), and a local check (`npx wrangler dev`, then `curl -X POST 'http://localhost:8787/cdn-cgi/handler/email?from=a@example.com&to=<token>@archiesecondbrain.com' --data-binary @services/api/tests/fixtures/newsletters/substack_bytebytego.eml`). Not deployed in this plan.

- [ ] **Step 1: Scrub** the two emails into `services/api/tests/fixtures/newsletters/`; the script's own checks pass; read the URL list by hand.
- [ ] **Step 2: Unit tests** `test_email_message.py` on the fixtures: Substack → subject "How Netflix Uses AI Agents for Performance Engineering", sender "ByteByteGo", `web_url` "https://blog.bytebytego.com/p/how-netflix-uses-ai-agents-for-performance", ≥ 300 words, text contains a sentence you pick from the post; Morning Brew → sender "Morning Brew", subject "☕ Putting it to a vote", `web_url` None, ≥ 300 words; a raw message with no `Message-ID` (build one with `email.message.EmailMessage` in the test — our own input, not an outside body) → `sha256:` id stable across two parses; `local_part("AbC123+x@archiesecondbrain.com") == "abc123"`.
- [ ] **Step 3: E2e** `test_ingest_e2e.py` (`postgres`; `worker` only on the processing tests; `INGEST_SECRET`, `INGEST_EMAIL_DOMAIN=archiesecondbrain.com` via `monkeypatch.setenv` before requests): wrong/missing secret → 401, no row; 11 MB body → 413; unknown token → 202, no source; the token address from `/me` → newsletter source (kind, state `inbox`, intent `queue`, sender, title, `url` as parsed) → worker runs fetch_content + analyze → pull shows `ready`, a summary, **no primer artifact, no cards**, `llm_calls` = one `analyze` row; delivering the same bytes again → still one source; `INGEST_ALIASES=news=owner@example.com` with a user signed in with `email="Owner@Example.com"` → `news@archiesecondbrain.com` lands on that user. Record `ingest_substack.yaml` and `ingest_morning_brew.yaml` (analyze only).
- [ ] **Step 4: Implement**; mount the router in `main.create_app`; run the suite against `archie_test_t9` and `make lint`.
- [ ] **Step 5: Commit** "Newsletters: ingest endpoint, scrubbed fixtures, Email Worker".

### Task 10: App: sender, Inbox label, newsletter address, unsupported reason, timestamps; Maestro flow

**Files:**
- Modify: `app/src/db/schema.ts`, `app/src/sync/engine.ts`, `app/src/sync/transport.ts`, `app/src/sync/engine.test.ts`, `app/src/app/(tabs)/library.tsx`, `app/src/app/source/[id].tsx`, `app/src/app/(tabs)/today.tsx`, `app/src/ui/ProcessingLine.tsx`, `maestro/README.md`, `Makefile` (`maestro` target)
- Create: `app/drizzle/0002_*.sql` + snapshot/journal/`migrations.js` (via `npm run db:generate`), `app/src/ui/sourceLabels.ts`, `app/src/ui/sourceLabels.test.ts`, `app/src/account/newsletterAddress.ts`, `app/src/account/newsletterAddress.test.ts`, `maestro/add_podcast.yaml`

**Interfaces:**
- Consumes: Task 5 wire shapes (`sender`, `ingest_address`), Task 4 (`media.SPOTIFY_EPISODE_URL`, copied literally into the flow).
- Produces:
  - `schema.sources.sender: text("sender")` (nullable); `PulledSource.sender: string | null`; transport maps it.
  - `sourceLabels.ts`: `sourceByline(source: { kind: string; url: string; sender: string | null }): string` — newsletter → sender ?? "Newsletter"; else the URL's hostname without `www.` (falls back to the URL); `stateLabel(state: string): string` — `inbox` → "Inbox", `queued` → "Queued", `consumed` → "Done", others capitalized.
  - `newsletterAddress.ts`: `newsletterAddressFrom(me: unknown): string | null` — the `ingest_address` string when present and containing `@`, else null.
- Review: no.

UI: Library row's state chip shows `stateLabel(source.state)`; the secondary text next to it shows `sourceByline(source)` for newsletters (testID `source-sender-<id>`) and `source.kind` otherwise. Source page header: `{kind} · {byline}`. `ProcessingLine`: `unsupported` shows `processingError ?? "Not processed yet"`. `TimestampChip` gets `testID="timestamp"`. Today account sheet (`sheetOpen`): on open, `apiFetch("/me", ...)` with the session key (from the same place `_layout.tsx` gets it), and when `newsletterAddressFrom(...)` is non-null show a "Newsletter address" label, the address (testID `newsletter-address`, selectable) and a "Copy" button (testID `newsletter-address-copy`, `Clipboard.setStringAsync` from `expo-clipboard`); errors hide the row.

`maestro/add_podcast.yaml` (pattern of `source_page.yaml`; header comment: needs real keys, costs a few cents, run only against the local backend): `runFlow: login.yaml` → `openLink: archie://dev/login?whitelisted=1` (+ the optional "Open" tap) → wait "Library" → `tab-add` (with the swallowed-tap guard) → tap `add-url` → `inputText: <media.SPOTIFY_EPISODE_URL>` → `intent-queue` → `add-save` → `tapOn: ".*(open.spotify.com|<first word of the episode title>).*"` → one `extendedWaitUntil` `id: primer-toggle` with `timeout: 300000` → `assertVisible: { id: "source-gist" }` → `assertVisible: { id: "timestamp" }`. Add it to the README table and to `make maestro`'s list.

- [ ] **Step 1: Jest tests** for `sourceByline`, `stateLabel`, `newsletterAddressFrom`, and in `engine.test.ts` a pulled source with `sender` is stored (and updated on re-pull).
- [ ] **Step 2: Implement**; `npm run db:generate` and commit the generated files.
- [ ] **Step 3: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 4: Commit** "App: Inbox newsletters with sender, newsletter address in the account sheet, timestamps testID; Maestro podcast flow".

## Integration tasks (serial, in `m3-sources`, after every parallel task is merged)

### Task 11: Spotify → transcription pipeline e2e, docs and deploy config

**Files:**
- Modify: `services/api/tests/e2e/test_podcast_pipeline_e2e.py` (add the Spotify case) + cassette `pipeline_podcast_spotify.yaml`, `docs/deploy.md`, `AGENTS.md` (recording note), `docs/superpowers/specs/2026-11-04-m3-all-sources-design.md` (status line + follow-ups)
- Review: yes (whole flow)

- [ ] **Step 1: Merge check.** `git log --oneline` shows Tasks 6–10 merged; run the full suite against `archie_test` and `make lint` once before adding anything.
- [ ] **Step 2: E2e over the live stack** (`postgres`, `worker`; `use_recording_api_key(env_names=(ANTHROPIC, GROQ, OPENAI))`; `transcription.CHUNK_SECONDS` monkeypatched to 60 so the run matches Task 7's): whitelisted user pushes `add_source` for `media.SPOTIFY_EPISODE_URL` (intent queue) → poll (replay 60 s, recording 600 s) until `ready` → summary with ≥ 1 timestamped key idea or number, primer present; `llm_calls` steps include `transcribe` (provider `groq`, `audio_seconds` > 0), `corrections`, `analyze`, `primer`, each with `cost_usd` > 0; `transcript_chunks` rows exist. Record once; check size (≤ 5 MB) and keys.
- [ ] **Step 3: Docs.** `docs/deploy.md` "Not in code": `GROQ_API_KEY`, `OPENAI_API_KEY`, `SUPADATA_API_KEY` (optional; YouTube fails with "needs setup" on Railway without it), `INGEST_SECRET` (same value as the Worker's secret), `INGEST_EMAIL_DOMAIN`, `INGEST_ALIASES`, set with `railway variable set` without echoing values; the image now carries ffmpeg; the newsletter Worker deploys from `workers/newsletter/README.md` after the API is live. `AGENTS.md` Commands: recording also reads `GROQ_API_KEY`/`OPENAI_API_KEY` for transcription cassettes. Spec: add a status line ("Implemented on `m3-sources`; not deployed") and the follow-ups: Supadata cassette; deploy steps (Railway vars, `railway config apply`, Worker deploy + Email Routing switch); the Spotify-exclusive e2e if it was skipped.
- [ ] **Step 4: Commit** "M3: Spotify-to-transcript pipeline e2e; deploy docs".

### Task 12: Full verification, including the Maestro flows

- Review: no

- [ ] **Step 1: Python:** `make lint` and `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test uv run pytest -m "postgres or not postgres"` — all pass with no network (replay). `make scaffold` output unchanged or smaller.
- [ ] **Step 2: App:** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 3: Local backend from the worktree** (not `make start-local`, which would call `docker compose` here): `DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie uv run archie-db upgrade`, then empty synced data with `docker exec -i second-brain-postgres-1 psql -q -U archie archie -c "TRUNCATE applied_actions, jobs, sources, sessions, users RESTART IDENTITY CASCADE"`, then in the background `DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie ARCHIE_ENV=dev uv run archie-launch`. The worker reads `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY` from the worktree's `.env` (check the names exist, never the values). `curl -s localhost:8000/health` → ok.
- [ ] **Step 4: Simulator:** iPhone 17 Pro (`4CD896B6-813A-41B7-A193-F1AD87AE1113`), booted (`xcrun simctl boot 4CD896B6-813A-41B7-A193-F1AD87AE1113` if not). Debug build from the worktree per `maestro/README.md`: `cd app && npx expo run:ios --device 4CD896B6-813A-41B7-A193-F1AD87AE1113`, Metro left running in the background.
- [ ] **Step 5: Flows** (from the worktree root, `PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH"`): `maestro test maestro/add_link.yaml maestro/sign_out.yaml maestro/source_page.yaml maestro/add_podcast.yaml` — all pass (the podcast and source-page flows spend a few cents). If `add_podcast` times out, read the worker log and the source's `processing_error` before retrying; a failure caused by the episode leaving the feed means re-picking `media` constants (Task 4 Step 1) and re-recording the cassettes that use them, which is a reportable problem, not something to paper over. `share_sheet.yaml` needs a Release build: run it only if time allows, and report if skipped.
- [ ] **Step 6:** Stop the backend and Metro. `git status` clean apart from intended changes; branch `m3-sources` ready for a PR (do not push or merge unless asked).
