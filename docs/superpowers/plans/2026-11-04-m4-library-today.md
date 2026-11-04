# Milestone 4 Library, Today, Topics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The user lives in the app: Today (primers ready, up next, newsletters waiting), a searchable offline Library with a Domains view, item pages with every state action, a curated per-user topic list that Archie files into, topic primers, artwork, and podcast episode correction.

**Architecture:**
- DB (`0004_library`): new synced tables `topics` and `topic_primers`; new source columns (`domain`, `topic_id`, `image_url`, `queue_position`, `read_at`, `snoozed_until`, `primer_opened_at`, `newsletter_kind`, plus server-only `episode_guid`); `users.topics_chosen_at`. Domains and starter topics live in `archie_shared`; topic writes shared by API and worker live in `archie_db.user_topics`.
- API: 19 new push actions registered in one dispatch table (each validates fully, then writes under the user's lock); pull merges five tables; `/me` gains `topics_chosen` (and seeds the owner's topics); `GET /topics/starter`, `GET /sources/{id}/text`, `GET /sources/{id}/episodes`.
- Worker: `file_topic` (Haiku → Sonnet, JSON schema, server guard against near-duplicates and removed topics) after `analyze`; `topic_primer` (Sonnet → Opus); artwork `image_url` filled where each fetcher already reads the source; `fetch_content` honors a chosen podcast episode guid; `archie-refile-sources` one-off command.
- App: drizzle migration 0003 + sync of the new tables/columns; every action writes its row optimistically with its outbox entry; Today, Library (list/queue/snoozed/search/swipe + Domains), topic page, item page, finish/snooze sheets, topic picker, Removed topics.

**Tech Stack:** as M3, plus app packages `expo-image`, `expo-haptics`, `react-native-gesture-handler`, `@react-native-community/datetimepicker` (installed once in Task 3).

**Spec:** `docs/superpowers/specs/2026-11-04-m4-library-today-design.md` (source of truth for behavior; where it and the mocks `2026-11-04-m4-library-today-mocks.html` disagree, the spec wins). UX rules: `docs/superpowers/specs/2026-10-29-ux-and-brand-design.md`. The roadmap change (5 Pulse, 6 Cards, 7 Search + chat, 8 Notes import, 9 App Store) is already in `docs/superpowers/specs/2026-11-02-backend-architecture-design.md`; no task touches it.

## Global Constraints

- **Python style:** `AGENTS.md` house style (module-qualified imports as the repo does them, e.g. `from archie_db import changes, models` then `changes.touch(...)`; classes/`typing` by name; full typing with `X | None`; `StrEnum`s for compared strings; dataclasses over tuples of >2; named parameters; guard clauses; blank-line paragraphs past ~8 lines; why-comments; docstrings on public functions/classes).
- **Handler contract** (`services/worker/archie_worker/loop.py` docstring): read into locals and `db.commit()` before any outside call; then `changes.lock_user_writes`, `db.refresh(row)`, skip if deleted/removed, write.
- **Action contract:** every push action handler has the signature `(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None` (rejection reason or None) and runs under the batch's user lock inside a savepoint. **A handler validates everything before its first write**: returning a reason does *not* roll back earlier writes (`_apply_action` records the rejection inside the same savepoint). Every changed synced row gets a fresh `change_seq` (sources/topics via `changes.touch`, artifacts/topic primers/cards by setting `change_seq = changes.next_change_seq()`).
- **Wire payloads** (snake_case; `id` is always the row the action changes, which the phone's "keep the local copy while an action is unsent" rule relies on):

  | type | payload |
  |---|---|
  | `finish_source` | `{id, reaction?: "easy"\|"mostly"\|"lost", note?: str}` |
  | `set_prep_me` | `{id, prep_me: bool}` |
  | `set_read` | `{id, read: bool}` |
  | `set_primer_opened` | `{target: "source"\|"topic_primer", id, opened: bool}` (`id` = source id or topic primer row id) |
  | `snooze` | `{target: "source"\|"topic_primer", id, until: ISO-8601 with offset \| null}` |
  | `set_queue_position` | `{id, position: float}` |
  | `go_deeper`, `read_later`, `delete_source` | `{id}` |
  | `add_topic` | `{id, domain, name}` |
  | `rename_topic` | `{id, name}` |
  | `merge_topic` | `{id, into_id}` |
  | `remove_topic`, `restore_topic`, `request_topic_primer` | `{id}` (topic id) |
  | `set_source_topic` | `{id, topic_id}` (`id` = source id) |
  | `choose_topics` | `{topics: [{id, domain, name}]}` (1–200 entries) |
  | `choose_episode` | `{id, guid}` |
- **Pulled rows:** `sources` gain `domain, topic_id, image_url, queue_position, read_at, snoozed_until, primer_opened_at, newsletter_kind`; `topics`: `id, domain, name, origin, removed_at, merged_into_id, created_at, updated_at, change_seq`; `topic_primers`: `id, topic_id, version, is_current, content, opened_at, snoozed_until, created_at, change_seq`. `PullResponse.rows` keys: `sources, artifacts, cards, topics, topic_primers`.
- **HTTP shapes:** `GET /me` → `{user_id, ingest_address, topics_chosen: bool}`. `GET /topics/starter` → `{domains: [{domain: str, topics: [str]}]}` (domain order of `Domain`). `GET /sources/{id}/text` → `{text}` (newsletters only, else 404). `GET /sources/{id}/episodes` → `{episodes: [{guid, title, published: "YYYY-MM-DD" | null, duration_s: int | null, is_current: bool}]}` newest first; 404 when not a resolved podcast of the caller; 502 when the feed can't be read.
- **Domains (fixed, in this order; value = display name, stored as is):** Macro, Finance, Trading, Crypto, Startups, AI, Politics, Geopolitics, Sports, Geography, History, Software engineering, Other. Colors light/dark: existing Macro `#3F7262`/`#79B39E`, Finance `#8A7533`/`#CDB46A`, Crypto `#A8613A`/`#DC9867`, Startups `#3D6690`/`#7FA7D9`, AI `#6A5A9C`/`#A898DE`, History `#8E5468`/`#C98BA0`; new Trading `#4F6F8A`/`#8FB0CC`, Politics `#8A4F4F`/`#D58E8E`, Geopolitics `#5E6B3A`/`#A9B77A`, Sports `#3A7A7A`/`#7CC2C2`, Geography `#7A6248`/`#C7A783`, Software engineering `#5A5F6E`/`#A3A8B8`, Other `#77736A`/`#A9A59B`.
- **Models and prompts:** `llm.FILE_TOPIC_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)`; topic primers use `llm.PRIMER_MODELS`, prompt version `"topic-primer-v1"`. `file_topic` cost must stay under $0.001 per source (asserted in its test).
- **Snooze choices** (phone time zone, sent as UTC): Tonight 18:00 (hidden from 17:00), Tomorrow 09:00, This weekend (next Saturday 09:00), Next week (next Monday 09:00), a picked date at 09:00.
- **Queue:** lower `queue_position` is higher. New queued sources, Read later and snooze set `min − 1` (0 when the queue is empty); reorder sends the midpoint of the new neighbours (computed on the phone); Up next = first 3 visible queued items.
- **Topic names:** 1–80 characters after whitespace collapse; compared with `normalize_topic_name` (case-folded, `&` → `and`, every run of non-letters/digits → one space). Unique per user among non-merged topics (live **and** removed).
- **Tests:** e2e first; unit tests only for real logic; outside calls replayed from recorded cassettes, never hand-written bodies (constructing our own rows or our own dataclasses is fine). App logic tests are `*.test.ts` (jest matches only `.ts`).
- **Never print secrets** or `.env` values; check keys by name only (`grep -o '^[A-Z_]*=' .env`). Before committing a cassette: `grep -rIl -e "x-api-key" -e "sk-ant-api" -e "gsk_" -e "sk-proj-" -e "Bearer " services/*/tests/cassettes services/api/tests/e2e/cassettes` prints nothing, and no cassette is over 5 MB (`du -h`).
- **Recording a cassette:** delete it, then run that one test with `TEST_DATABASE_URL` set and `--record-mode=once -m postgres`, e.g. `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t<N> uv run pytest services/worker/tests/test_file_topic_e2e.py::test_x --record-mode=once -m postgres`. Anthropic recordings read `ANTHROPIC_API_KEY` from the worktree's repo-root `.env` through `archie_testing.recording.use_recording_api_key` (record mode only). If the worktree's `.env` lacks it, copy the line without printing it: `grep '^ANTHROPIC_API_KEY=' /Users/sampocs/Documents/Personal/second-brain/.env >> .env`.
- **Branch and worktrees:** branch `m4-library`, worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/m4-library`. Foundation tasks run there serially. Each parallel-safe task runs in its own worktree from the last foundation commit (`git gtr new m4-t<N> --from-current --yes` run inside the `m4-library` worktree), then merges back into `m4-library`.
- **Postgres from a worktree:** the container `second-brain-postgres-1` (`127.0.0.1:5434`) is already up from the main checkout. **Never run `make db-up`, `make test-db`, `make migrate-local`, `make start-local`, `make reset-local-data` or any `make maestro*` target from a worktree.** Run tests with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test uv run pytest -m "postgres or not postgres"`. **Parallel tasks each use their own database** (tests truncate tables and one downgrades the schema): `docker exec second-brain-postgres-1 createdb -U archie archie_test_t<N>` (ignore "already exists"), then `.../archie_test_t<N>`.
- **Maestro:** implementers write the flow YAML and the testIDs it needs, and check the YAML parses (`PATH="/opt/homebrew/opt/openjdk@17/bin:$HOME/.maestro/bin:$PATH" maestro check-syntax maestro/<flow>.yaml` if that subcommand exists, else skip). **Flows are run only by the coordinator, from the main checkout, against the local backend** (Task 16). Every flow keeps the existing testIDs `tab-*`, `account-button`, `sign-out`, `add-*`, `intent-*`, `reaction-*`, `prep-me`, `source-gist`, `primer-toggle`, `timestamp`, and the text "Processing…" while a source processes and "▾ Background you might need" when its primer is open.
- **Checks before every commit:** Python: `make lint` and the relevant tests (command above). App: `cd app && npm run typecheck && npx jest`.
- **Commits:** every message ends with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MN7nukQAsqfkk3GiAq6NkX
  ```
- **Out of scope:** deploying, `railway config apply`, pushing or merging to `main`. The plan ends with `m4-library` ready for a PR.

## Decisions made while planning

1. **Owner seeding also runs on `GET /me`**, not only at Apple sign-in: the owner's phone keeps its session across the deploy and never signs in again, but calls `/me` on every launch. Seeding is idempotent (no-op once the user has any topic).
2. **The picker's starter list comes from `GET /topics/starter`** (one source of truth in `archie_shared.topics`); the picker is only shown online anyway, since it is gated on `/me`.
3. **Picker gating:** the app shows the picker when `/me` says `topics_chosen: false` **and** the local `topics` table is empty; Continue needs at least one topic, so a submitted picker always leaves local rows and the gate opens offline at once.
4. **`/test/session` gains `seed_topics: bool = False`** (seeds the owner's topics for that test user); the dev login link sends `seed_topics: true` unless `?picker=1`, and takes `?sub=<apple_sub>` so the picker flow uses a fresh user. Existing flows therefore never meet the picker.
5. **`file_topic` is enqueued by `analyze` only when the source was never filed (`domain IS NULL`) and the user has chosen topics.** A later re-analyze (Go deeper, a new episode) never overrides a topic the user set by hand; removing a topic re-files explicitly.
6. **Removing a topic nulls `topic_id` on its sources at once** (domain kept) before enqueuing their `file_topic` jobs, so the phone never shows a removed topic's chip.
7. **`add_topic`/`rename_topic` colliding with a removed topic is refused** ("a removed topic has this name; restore it instead"), matching the unique index (removed topics keep their name).
8. **Topic primers of removed or merged topics are hidden** on the phone (Primers ready, Library). Every topic primer is "pushed" (only added topics and explicit requests make them), so no extra flag is stored.
9. **"Writing a primer…" state** uses a phone-only column `topics.primer_requested_at` (set by `add_topic`/`request_topic_primer`, never overwritten by a pull, like `sync_error`); after 10 minutes without a primer the page offers "Write a primer" again.
10. **Chosen podcast episode** is kept in a server-only column `sources.episode_guid` (not pulled), so a later Retry still resolves the episode the user picked. `choose_episode` also clears `title` and `image_url` so the new episode's title and artwork replace them.
11. **Go deeper is allowed only on a READY source**; it also sets `read_at` if unset. Newsletter cards come from the re-run `analyze`, which now gives cards to a newsletter only when `state == consumed`.
12. **Library filters:** All = every source + live current topic primers; Inbox = `inbox` and `briefed`; Primers = live current topic primers + sources with `prep_me` and a primer. Every filter ends with a "Snoozed · N" section (the spec requires it for Queued). A domain card shows when it has items **or** user-added topics, so a freshly added topic is visible.
13. **Analyze keeps its own domain enum** (`prompts.DOMAINS`) as a hint; it is not changed to the new list, so the M2/M3 analyze cassettes keep replaying. Filing owns the real domain.
14. **"This weekend" on a Saturday or Sunday means the next Saturday.** "This week" in Library = created in the last 7 days.
15. **Podcast feed parsing moves to `archie_shared.podcast_feed`** (in Task 1, unchanged behavior) so the API's episode list and the worker share it.
16. **Rejected `add_topic`** deletes the phone's optimistic topic row (it would otherwise linger forever); other rejected actions keep the existing "Not synced" marker on the source.

---

## File Structure

```
packages/archie-shared/archie_shared/domains.py            Domain StrEnum, parse_domain                        (T1)
packages/archie-shared/archie_shared/topics.py             OWNER_TOPICS, STARTER_EXTRAS, STARTER_TOPICS, normalize_topic_name (T1)
packages/archie-shared/archie_shared/podcast_feed.py       FeedItem, TranscriptLink, parse_feed, fetch_feed, item_by_guid (T1, T10 adds artwork)
packages/archie-db/archie_db/models.py                     Topic, TopicPrimer, TopicOrigin, NewsletterKind, new columns, JobKinds (T1)
packages/archie-db/archie_db/migrations/versions/0004_library.py                                              (T1)
packages/archie-db/archie_db/changes.py                    touch()                                             (T1)
packages/archie-db/archie_db/user_topics.py                named_topic, create_topic, seed_owner_topics, enqueue helpers, analyzed_sources (T1)
services/worker/archie_worker/{content/__init__,content/episode,handlers/_text,content/podcast}.py  image_url plumbing, feed move (T1)
services/api/archie_api/sync/{schemas,pull,actions,capture,rows}.py   pull of 5 tables, dispatch table, queue position (T2)
services/api/archie_api/auth/{routes,apple}.py, test_routes.py        topics_chosen, owner seeding               (T2)
services/api/archie_api/sources/routes.py                  GET /sources/{id}/text (T2), /episodes (T10)
app/src/db/{schema,actions,testDb}.ts, app/drizzle/0003_*, app/src/sync/{engine,transport}.ts           (T3)
app/src/topics/{domains,topicName}.ts, app/src/library/{data,visibility,snooze}.ts, app/src/theme/tokens.ts (T3)
app/src/ui/{haptics,ArtworkTile,ItemRow,SourceRow,StatusTagView,Kicker,GroupedList,BottomSheet,MenuSheet,FinishSheet,SnoozeSheet,TopicChooserSheet}.tsx (T4)
app/src/app/(tabs)/library.tsx shell, app/src/library/{LibraryList,DomainsView}.tsx minimal, Screen onBack  (T4)
services/api/archie_api/sync/source_actions.py + analyze card rule                                         (T5)
services/api/archie_api/sync/topic_actions.py, services/api/archie_api/topics/routes.py                    (T6)
services/worker/archie_worker/handlers/file_topic.py, prompts, refile.py                                   (T7)
services/worker/archie_worker/handlers/topic_primer.py, prompts                                             (T8)
services/worker/archie_worker/{handlers/fetch_title,content/article,content/x,content/youtube}.py artwork  (T9)
podcast artwork, /sources/{id}/episodes, sync/episodes.py (choose_episode), fetch_content guid             (T10)
app/src/app/(tabs)/today.tsx                                                                                (T11)
app/src/library/{LibraryList,ReorderableQueue,SwipeRow,queue,search}.ts(x)                                  (T12)
app/src/library/DomainsView.tsx, app/src/app/topic/[id].tsx, app/src/app/settings/removed-topics.tsx       (T13)
app/src/app/source/[id].tsx, app/src/item/*                                                                 (T14)
app/src/app/topic-picker.tsx, app/src/app/_layout.tsx gating, app/src/app/dev/login.tsx                    (T15)
maestro/*.yaml, maestro/run_newsletter.sh, maestro/README.md, Makefile, docs/deploy.md                     (T11–T16)
```

## Foundation tasks (run serially, in `m4-library`)

### Task 1: Schema 0004, domains and topics, shared backend plumbing  (tier: most capable)

**Files:**
- Create: `packages/archie-db/archie_db/migrations/versions/0004_library.py`, `packages/archie-shared/archie_shared/domains.py`, `packages/archie-shared/archie_shared/topics.py`, `packages/archie-shared/archie_shared/podcast_feed.py`, `packages/archie-db/archie_db/user_topics.py`, `packages/archie-shared/tests/test_topics.py`, `packages/archie-db/tests/test_user_topics.py`
- Modify: `packages/archie-db/archie_db/models.py`, `packages/archie-db/archie_db/changes.py`, `packages/archie-db/tests/test_db_migrations.py`, `conftest.py` (`_TRUNCATE_TABLES`), `packages/archie-shared/pyproject.toml` (+ `uv.lock`), `services/worker/archie_worker/content/__init__.py`, `services/worker/archie_worker/content/episode.py`, `services/worker/archie_worker/content/podcast.py`, `services/worker/archie_worker/handlers/_text.py`, `services/worker/tests/test_text_step.py`, `services/worker/tests/test_podcast.py` (imports of moved names)

**Interfaces:**
- Produces:
  - `archie_shared.domains.Domain(StrEnum)` with members `MACRO="Macro"`, `FINANCE="Finance"`, `TRADING="Trading"`, `CRYPTO="Crypto"`, `STARTUPS="Startups"`, `AI="AI"`, `POLITICS="Politics"`, `GEOPOLITICS="Geopolitics"`, `SPORTS="Sports"`, `GEOGRAPHY="Geography"`, `HISTORY="History"`, `SOFTWARE_ENGINEERING="Software engineering"`, `OTHER="Other"`; `domains.parse_domain(raw: str) -> Domain` (case-insensitive, unknown → `OTHER`).
  - `archie_shared.topics.OWNER_TOPICS`, `STARTER_EXTRAS`, `STARTER_TOPICS: dict[Domain, tuple[str, ...]]`; `topics.normalize_topic_name(name: str) -> str`; `topics.is_starter_topic(*, domain: Domain, name: str) -> bool`.
  - `archie_shared.podcast_feed`: `TranscriptLink`, `FeedItem` (moved unchanged from `content/podcast.py`), `parse_feed(feed: bytes) -> list[FeedItem]`, `item_by_guid(*, items: Sequence[FeedItem], guid: str | None) -> FeedItem | None`, `fetch_feed(feed_url: str) -> bytes` (httpx stream, 30 s total, 50 MB cap, the worker's browser User-Agent), `EPISODE_KEY = "episode"`.
  - `models.TopicOrigin(StrEnum)`: `STARTER`, `ARCHIE`, `USER`; `models.NewsletterKind(StrEnum)`: `NEWS="news"`, `ESSAY="essay"`; `models.JobKind.FILE_TOPIC="file_topic"`, `TOPIC_PRIMER="topic_primer"`.
  - `models.Topic`, `models.TopicPrimer` (columns below); `Source.domain/topic_id/image_url/queue_position/read_at/snoozed_until/primer_opened_at/newsletter_kind/episode_guid`; `User.topics_chosen_at`.
  - `changes.touch(row: models.Source | models.Topic) -> None` (fresh `updated_at` and `change_seq`).
  - `archie_db.user_topics`: `TOPIC_ID_KEY = "topic_id"`, `MAX_TOPIC_NAME_LENGTH = 80`, `clean_name(name: str) -> str`, `named_topic(db, *, user_id: int, name: str) -> models.Topic | None`, `create_topic(db, *, user_id: int, domain: Domain, name: str, origin: models.TopicOrigin, topic_id: uuid.UUID | None = None, removed: bool = False) -> models.Topic`, `seed_owner_topics(db, *, user: models.User) -> None`, `live_topics(db, *, user_id: int) -> list[models.Topic]`, `removed_topics(db, *, user_id: int) -> list[models.Topic]`, `analyzed_sources(db, *, user_id: int) -> list[models.Source]`, `enqueue_file_topic(db, *, source: models.Source) -> None`, `enqueue_topic_primer(db, *, topic: models.Topic) -> None`.
  - Worker: `content.ExtractedText.image_url: str | None = None`; `episode.PodcastEpisode.image_url: str | None = None` (last field; `from_payload` reads `data.get("image_url")` so queued M3 payloads still load); `_text.store_text(db, *, source, text_content, title, image_url: str | None = None)` and `_text.enqueue_transcribe` both set `source.image_url` when the source has none.
- Review: yes (migration, backfills).

**Models** (add to `models.py`; keep the existing style):

```python
class TopicOrigin(StrEnum):
    """Who put a topic on the user's list: the starter list, Archie's filing, or the user."""

    STARTER = "starter"
    ARCHIE = "archie"
    USER = "user"


class NewsletterKind(StrEnum):
    """What a newsletter is: a digest of short items, or one piece of writing worth reading whole."""

    NEWS = "news"
    ESSAY = "essay"


class Topic(Base):
    """One topic on a user's curated list. Removed topics stay (blocked, restorable); merged ones point at the winner."""

    __tablename__ = "topics"
    __table_args__ = (
        sqlalchemy.Index("ix_topics_user_id_change_seq", "user_id", "change_seq"),
        # Live and removed topics keep their names unique; a merged topic gives its name up.
        sqlalchemy.Index(
            "uq_topics_user_id_lower_name",
            "user_id",
            sqlalchemy.text("lower(name)"),
            unique=True,
            postgresql_where=sqlalchemy.text("merged_into_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    domain: Mapped[str] = mapped_column(sqlalchemy.String(32))
    name: Mapped[str] = mapped_column(sqlalchemy.String(200))
    origin: Mapped[str] = mapped_column(sqlalchemy.String(16))
    removed_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topics.id")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class TopicPrimer(Base):
    """One version of a topic's general-background primer; exactly one version per topic is current."""

    __tablename__ = "topic_primers"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("topic_id", "version", name="uq_topic_primers_version"),
        sqlalchemy.Index(
            "uq_topic_primers_current", "topic_id", unique=True, postgresql_where=sqlalchemy.text("is_current")
        ),
        sqlalchemy.Index("ix_topic_primers_user_id_change_seq", "user_id", "change_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    topic_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topics.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    is_current: Mapped[bool] = mapped_column(sqlalchemy.Boolean)
    # Markdown under "markdown", the same shape as a source primer artifact.
    content: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    model: Mapped[str | None] = mapped_column(sqlalchemy.String(64))
    prompt_version: Mapped[str | None] = mapped_column(sqlalchemy.String(32))
    opened_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    snoozed_until: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)
```

`Source` additions (before `change_seq`; `Topic` must be declared before `Source` or the FK given as a string, which it is):

```python
    # Filing: null until `file_topic` ran; `topic_id` stays null when the only fit was a removed topic.
    domain: Mapped[str | None] = mapped_column(sqlalchemy.String(32))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topics.id", ondelete="SET NULL")
    )
    image_url: Mapped[str | None] = mapped_column(sqlalchemy.String(2048))
    # Queued sources only; lower is higher in the queue.
    queue_position: Mapped[float | None] = mapped_column(sqlalchemy.Double)
    read_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    snoozed_until: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    primer_opened_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    newsletter_kind: Mapped[str | None] = mapped_column(sqlalchemy.String(16))
    # Server only (never pulled): the feed guid the user chose with "Wrong episode?".
    episode_guid: Mapped[str | None] = mapped_column(sqlalchemy.String(1024))
```

`User`: `topics_chosen_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)` with comment "Set once the user finished the topic picker (or was seeded as the owner)."

`JobKind`: add `FILE_TOPIC = "file_topic"` and `TOPIC_PRIMER = "topic_primer"`.

**Migration `0004_library`** (by hand, in `0003_all_sources.py`'s style; `revision = "0004"`, `down_revision = "0003"`):
- `users.topics_chosen_at` nullable timestamp.
- Create `topics` (all columns; FK `merged_into_id → topics.id`; index `ix_topics_user_id_change_seq`; the unique functional index with `op.create_index("uq_topics_user_id_lower_name", "topics", ["user_id", sqlalchemy.text("lower(name)")], unique=True, postgresql_where=sqlalchemy.text("merged_into_id IS NULL"))`), then `topic_primers` (constraint/indexes as the model).
- `sources`: add the nine columns (`queue_position` as `sqlalchemy.Double()`); FK `sources.topic_id → topics.id ON DELETE SET NULL` named `sources_topic_id_fkey`.
- Backfill, in this order (the phone pulls only rows whose position moved, so every source gets a new `change_seq`):
  ```python
  op.execute(
      "UPDATE sources SET queue_position = ranked.position FROM ("
      " SELECT id, -row_number() OVER (PARTITION BY user_id ORDER BY created_at, change_seq) AS position"
      " FROM sources WHERE state = 'queued' AND deleted_at IS NULL"
      ") AS ranked WHERE sources.id = ranked.id"
  )
  op.execute(
      "UPDATE sources SET primer_opened_at = now(),"
      " read_at = CASE WHEN kind = 'newsletter' THEN now() END,"
      " change_seq = nextval('change_seq')"
  )
  ```
- `downgrade()` drops everything in reverse (FK and columns on `sources`, then `topic_primers`, `topics`, then `users.topics_chosen_at`).
- `test_models_match_the_migrations` must stay clean. Alembic skips expression indexes when comparing (it logs a warning); if it reports the FK name, name the model's FK the same way (`sqlalchemy.ForeignKey("topics.id", ondelete="SET NULL", name="sources_topic_id_fkey")`).

**`archie_shared/domains.py`:**

```python
"""The fixed list of domains every source and topic belongs to; the app mirrors it in `app/src/topics/domains.ts`."""

from __future__ import annotations

from enum import StrEnum


class Domain(StrEnum):
    """A broad area of knowledge. The value is the display name: it is stored as is and shown by the app."""

    MACRO = "Macro"
    FINANCE = "Finance"
    TRADING = "Trading"
    CRYPTO = "Crypto"
    STARTUPS = "Startups"
    AI = "AI"
    POLITICS = "Politics"
    GEOPOLITICS = "Geopolitics"
    SPORTS = "Sports"
    GEOGRAPHY = "Geography"
    HISTORY = "History"
    SOFTWARE_ENGINEERING = "Software engineering"
    OTHER = "Other"


def parse_domain(raw: str) -> Domain:
    """`raw` as a Domain, matched case-insensitively; anything else (a model's invention) is Other."""
    wanted = raw.strip().casefold()
    return next((domain for domain in Domain if domain.value.casefold() == wanted), Domain.OTHER)
```

**`archie_shared/topics.py`** (names verbatim from the spec; note the en dash in "US–China"):

```python
"""Starting topics: the starter list the picker offers and the owner's own picks (topic names aren't private)."""

from __future__ import annotations

import re

from archie_shared.domains import Domain

OWNER_TOPICS: dict[Domain, tuple[str, ...]] = {
    Domain.MACRO: (
        "Fed & monetary policy", "Interest rates & bonds", "Inflation", "Liquidity & the Fed's balance sheet",
        "Dollar & currencies", "Jobs & the labor market", "Government debt & deficits",
        "Recessions & the business cycle", "Macro & risk assets", "Tariffs & trade",
    ),
    Domain.FINANCE: (
        "Investing fundamentals", "Stocks & public markets", "Venture capital", "Private equity", "Banking",
        "Valuing companies", "IPOs & M&A",
    ),
    Domain.TRADING: (
        "Market structure", "Market making", "Derivatives & options", "Perpetual futures", "Liquidity & volume",
        "Risk management", "Trading strategies", "Quant trading",
    ),
    Domain.CRYPTO: (
        "Bitcoin", "Ethereum", "Rollups & L2s", "Cosmos & IBC", "Solana", "DeFi", "Stablecoins",
        "Staking & restaking", "Tokenomics", "Data availability & modular chains", "Zero knowledge",
        "Crypto regulation", "Crypto investing",
    ),
    Domain.STARTUPS: ("Startup ideas", "Product-market fit", "Growth & marketing", "Fundraising", "Founder lessons"),
    Domain.AI: (
        "AI products & agents", "Models & AI labs", "Chips & Nvidia", "Data centers & hyperscalers",
        "Energy & power", "AI business & economics", "AI policy & safety",
    ),
    Domain.POLITICS: (
        "US politics & elections", "The Trump administration", "Congress & legislation", "Regulation",
        "Courts & the law", "Political economy",
    ),
    Domain.GEOPOLITICS: (
        "US–China", "Taiwan & chips", "Russia & Ukraine", "Middle East", "Europe", "Trade wars & sanctions",
        "Defense & military", "Global institutions",
    ),
    Domain.SPORTS: (
        "NFL play schemes", "NFL contracts & the salary cap", "NFL draft & team building", "Quarterbacks",
        "Sports business",
    ),
    Domain.GEOGRAPHY: (
        "Countries & capitals", "Physical geography", "Population & cities", "Natural resources",
        "Borders & regions", "Climate",
    ),
    Domain.HISTORY: (
        "US history", "The world wars", "The Cold War", "Ancient history", "Economic & financial history",
        "History of technology", "Empires",
    ),
    Domain.SOFTWARE_ENGINEERING: (
        "Frontend & mobile", "Backend & APIs", "Data engineering & databases", "DevOps & cloud",
        "AI/ML engineering", "Languages & tools",
    ),
}

# Starter topics the owner didn't pick; the owner gets them as removed, so they can be restored.
STARTER_EXTRAS: dict[Domain, tuple[str, ...]] = {
    Domain.FINANCE: ("Personal finance & taxes", "Insurance"),
    Domain.SPORTS: ("College football",),
}

# What the picker offers, in domain order; Other has no starter topics.
STARTER_TOPICS: dict[Domain, tuple[str, ...]] = {
    domain: OWNER_TOPICS.get(domain, ()) + STARTER_EXTRAS.get(domain, ())
    for domain in Domain
    if domain in OWNER_TOPICS or domain in STARTER_EXTRAS
}

_NOT_LETTER_OR_DIGIT = re.compile(r"[\W_]+")


def normalize_topic_name(name: str) -> str:
    """The form topic names are compared in: case-folded, `&` read as "and", punctuation and spacing ignored."""
    return " ".join(_NOT_LETTER_OR_DIGIT.sub(" ", name.casefold().replace("&", " and ")).split())


def is_starter_topic(*, domain: Domain, name: str) -> bool:
    """Whether `name` is one of the starter topics of `domain` (compared normalized)."""
    wanted = normalize_topic_name(name)
    return any(normalize_topic_name(starter) == wanted for starter in STARTER_TOPICS.get(domain, ()))
```

(Ruff format will reflow the tuples one name per line; that's fine.)

**`archie_db/user_topics.py`:**

```python
"""A user's topics: lookups and writes shared by the API's actions and the worker's filing.

Every function that writes expects the caller to hold `changes.lock_user_writes` for the user.
"""

from __future__ import annotations

import uuid

import sqlalchemy
import sqlalchemy.orm
from archie_shared import topics
from archie_shared.domains import Domain

from archie_db import changes, jobs, models, pipeline

# The job payload key naming the topic a `topic_primer` job writes for.
TOPIC_ID_KEY = "topic_id"
MAX_TOPIC_NAME_LENGTH = 80


def clean_name(name: str) -> str:
    """The name as stored: whitespace runs collapsed, ends trimmed."""
    return " ".join(name.split())


def named_topic(db: sqlalchemy.orm.Session, *, user_id: int, name: str) -> models.Topic | None:
    """The user's live or removed topic whose name normalizes like `name`; merged topics never match."""
    wanted = topics.normalize_topic_name(name)
    candidates = db.scalars(
        sqlalchemy.select(models.Topic).where(models.Topic.user_id == user_id, models.Topic.merged_into_id.is_(None))
    )
    return next((topic for topic in candidates if topics.normalize_topic_name(topic.name) == wanted), None)


def create_topic(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    domain: Domain,
    name: str,
    origin: models.TopicOrigin,
    topic_id: uuid.UUID | None = None,
    removed: bool = False,
) -> models.Topic:
    """Insert a topic (a removed one when `removed`); the phone supplies the id for topics the user adds."""
    topic = models.Topic(
        id=topic_id or uuid.uuid4(),
        user_id=user_id,
        domain=domain.value,
        name=clean_name(name),
        origin=origin.value,
        removed_at=sqlalchemy.func.now() if removed else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(topic)
    db.flush()
    return topic


def seed_owner_topics(db: sqlalchemy.orm.Session, *, user: models.User) -> None:
    """Give the owner their picks as live starter topics and the other starter topics as removed; mark them chosen.

    A no-op once the user has any topic, so it is safe on every sign-in and `/me`.
    """
    has_topics = db.scalar(sqlalchemy.select(sqlalchemy.exists().where(models.Topic.user_id == user.id)))
    if has_topics:
        return

    for domain, names in topics.OWNER_TOPICS.items():
        for name in names:
            create_topic(db, user_id=user.id, domain=domain, name=name, origin=models.TopicOrigin.STARTER)
    for domain, names in topics.STARTER_EXTRAS.items():
        for name in names:
            create_topic(
                db, user_id=user.id, domain=domain, name=name, origin=models.TopicOrigin.STARTER, removed=True
            )
    user.topics_chosen_at = sqlalchemy.func.now()
    db.flush()


def live_topics(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Topic]:
    """The user's topics that are neither removed nor merged, by domain then name."""
    return list(
        db.scalars(
            sqlalchemy.select(models.Topic)
            .where(
                models.Topic.user_id == user_id,
                models.Topic.removed_at.is_(None),
                models.Topic.merged_into_id.is_(None),
            )
            .order_by(models.Topic.domain, models.Topic.name)
        )
    )


def removed_topics(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Topic]:
    """The user's removed (blocked) topics that weren't merged away."""
    return list(
        db.scalars(
            sqlalchemy.select(models.Topic).where(
                models.Topic.user_id == user_id,
                models.Topic.removed_at.is_not(None),
                models.Topic.merged_into_id.is_(None),
            )
        )
    )


def analyzed_sources(db: sqlalchemy.orm.Session, *, user_id: int) -> list[models.Source]:
    """The user's live sources that have a current summary, which is what filing reads."""
    return list(
        db.scalars(
            sqlalchemy.select(models.Source)
            .join(
                models.SourceArtifact,
                sqlalchemy.and_(
                    models.SourceArtifact.source_id == models.Source.id,
                    models.SourceArtifact.kind == models.ArtifactKind.SUMMARY.value,
                    models.SourceArtifact.is_current,
                ),
            )
            .where(models.Source.user_id == user_id, models.Source.deleted_at.is_(None))
            .order_by(models.Source.created_at)
        )
    )


def enqueue_file_topic(db: sqlalchemy.orm.Session, *, source: models.Source) -> None:
    """Queue filing for one source in the caller's transaction."""
    jobs.enqueue(
        db, kind=models.JobKind.FILE_TOPIC, user_id=source.user_id, payload={pipeline.SOURCE_ID_KEY: str(source.id)}
    )


def enqueue_topic_primer(db: sqlalchemy.orm.Session, *, topic: models.Topic) -> None:
    """Queue a topic primer for one topic in the caller's transaction."""
    jobs.enqueue(db, kind=models.JobKind.TOPIC_PRIMER, user_id=topic.user_id, payload={TOPIC_ID_KEY: str(topic.id)})
```

**`changes.touch`:**

```python
def touch(row: models.Source | models.Topic) -> None:
    """Mark a changed row so phones pull it again. Call only after `lock_user_writes` in the same transaction."""
    row.updated_at = sqlalchemy.func.now()
    row.change_seq = next_change_seq()
```

**`archie_shared/podcast_feed.py`:** move `TranscriptLink`, `FeedItem`, `parse_feed`, `_feed_item`, `_item_date`, `_duration_seconds`, `_description` and their constants (`_PODCAST_NAMESPACES`, `_ITUNES_NAMESPACE`, `_CONTENT_NAMESPACE`, `_TAG_PATTERN`, `_MAX_DESCRIPTION_LENGTH`) out of `services/worker/archie_worker/content/podcast.py` unchanged; rename `_item_by_guid` to public `item_by_guid` (same body). Add:

```python
EPISODE_KEY = "episode"  # Where the worker keeps a resolved `PodcastEpisode` on the `text` artifact.

FEED_TIMEOUT_SECONDS = 30
FEED_MAX_BYTES = 50_000_000
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"


def fetch_feed(feed_url: str) -> bytes:
    """Download a feed (at most 50 MB within 30 s in total); raises httpx errors on 4xx/5xx and TimeoutError past it."""
    deadline = time.monotonic() + FEED_TIMEOUT_SECONDS
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=FEED_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
        with client.stream("GET", feed_url) as response:
            response.raise_for_status()

            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Fetching {feed_url} took longer than {FEED_TIMEOUT_SECONDS}s")
                body.extend(chunk)
                if len(body) >= FEED_MAX_BYTES:
                    break
            return bytes(body[:FEED_MAX_BYTES])
```

The worker keeps fetching feeds through `fetch_title.fetch_bytes` (the recorded cassettes stay identical); `content/podcast.py` imports `from archie_shared import podcast_feed` and uses `podcast_feed.FeedItem`, `podcast_feed.parse_feed`, `podcast_feed.item_by_guid`, `podcast_feed.TranscriptLink`; `content/episode.py` sets `EPISODE_KEY = podcast_feed.EPISODE_KEY`. `packages/archie-shared/pyproject.toml` dependencies add `"httpx>=0.28.1"` and `"defusedxml>=0.7.1"`; run `uv lock && uv sync`.

**Worker image plumbing** (`handlers/_text.py`):

```python
def _set_image_if_empty(source: models.Source, *, image_url: str | None) -> None:
    if source.image_url or not image_url:
        return

    source.image_url = image_url[:_MAX_IMAGE_URL_LENGTH]
    changes.touch(source)
```

with `_MAX_IMAGE_URL_LENGTH = 2048`, called in `store_text` (new keyword `image_url: str | None = None`) after `_set_title_if_empty`, and in `enqueue_transcribe` with `episode.image_url`.

**`conftest.py`:** `_TRUNCATE_TABLES` starts with `"topic_primers", "topics",`.

- [ ] **Step 1: Unit tests** `packages/archie-shared/tests/test_topics.py`:
  - `normalize_topic_name`: `"Fed & Monetary Policy"` and `"fed and monetary  policy"` normalize equal; `"US–China"` → `"us china"`; `"AI/ML engineering"` → `"ai ml engineering"`; `"  Rollups & L2s!"` → `"rollups and l2s"`.
  - `STARTER_TOPICS` is every `OWNER_TOPICS` name plus exactly `"Personal finance & taxes"`, `"Insurance"` (Finance) and `"College football"` (Sports); no two starter names normalize equal; `Domain.OTHER not in STARTER_TOPICS`.
  - `parse_domain("software engineering") is Domain.SOFTWARE_ENGINEERING`; `parse_domain("Tech") is Domain.OTHER`.
  - `is_starter_topic(domain=Domain.FINANCE, name="insurance")` is True; `(domain=Domain.MACRO, name="Insurance")` is False.
- [ ] **Step 2: DB tests** (`@pytest.mark.postgres`):
  - `test_db_migrations.py::test_0004_backfills_queue_positions_and_read_markers`: pattern of `test_0003_...` — downgrade, upgrade to `"0003"`, insert a user and three sources with raw SQL (queued at `now() - interval '2 days'`, queued at `now() - interval '1 day'`, a `newsletter` in `inbox`), record their `change_seq`, upgrade; the older queued gets `-1`, the newer `-2`, the newsletter `NULL` queue position; all three have `primer_opened_at` set and a higher `change_seq`; only the newsletter has `read_at`. Truncate users at the end as the other migration tests do.
  - `packages/archie-db/tests/test_user_topics.py` (fixture `db` as in `test_pipeline.py`, user created and locked): `seed_owner_topics` creates `sum(len(names) for names in OWNER_TOPICS.values())` live `starter` topics and 3 removed ones, sets `topics_chosen_at`, and a second call adds nothing; `named_topic(name="fed and monetary policy")` finds "Fed & monetary policy" and `named_topic` finds a removed topic too, but not a merged one; `create_topic` with a name differing only in case from a live topic raises `sqlalchemy.exc.IntegrityError` (use `db.begin_nested()` around it), while the same name after the first topic gets `merged_into_id` succeeds; `analyzed_sources` returns only live sources with a current summary.
  - `services/worker/tests/test_text_step.py`: `store_text(..., image_url="https://img.example/a.jpg")` sets the image on an image-less source and keeps an existing one; `PodcastEpisode.from_payload` of a payload without `image_url` gives `image_url=None`.
- [ ] **Step 3: Run** `uv run pytest packages/archie-shared/tests` — fails (modules missing).
- [ ] **Step 4: Implement** everything above; update `services/worker/tests/test_podcast.py` imports to `archie_shared.podcast_feed` where it used the moved names.
- [ ] **Step 5: Run** the full Python suite against `archie_test` (command in Global Constraints) and `make lint` — all pass, including `test_models_match_the_migrations`, the downgrade round trip, and every podcast cassette test unchanged.
- [ ] **Step 6: Commit** "M4 schema: topics, topic primers, library columns; domains and starter topics; shared feed parsing".

### Task 2: API sync plumbing: pull of five tables, action dispatch table, `/me`, owner seeding  (tier: standard)

**Files:**
- Create: `services/api/archie_api/sync/rows.py`, `services/api/archie_api/sources/__init__.py`, `services/api/archie_api/sources/routes.py`, `services/api/tests/e2e/test_library_sync_e2e.py`
- Modify: `services/api/archie_api/sync/schemas.py`, `services/api/archie_api/sync/pull.py`, `services/api/archie_api/sync/actions.py`, `services/api/archie_api/sync/capture.py`, `services/api/archie_api/auth/routes.py`, `services/api/archie_api/auth/apple.py`, `services/api/archie_api/test_routes.py`, `services/api/archie_api/main.py`, `packages/archie-testing/archie_testing/harness.py`, `services/api/tests/test_capture.py` (merge_page tests), `services/api/tests/test_apple.py`, `services/api/tests/e2e/test_sync_e2e.py` (only if an assertion on the exact pulled key set breaks)

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `schemas.ActionType` gains every type in the Global Constraints table (values exactly as listed).
  - `actions.ActionHandler` (Protocol, `__call__(self, db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None`) and `actions.HANDLERS: dict[schemas.ActionType, ActionHandler]` holding `ADD_SOURCE` and `RETRY_SOURCE`; a type with no entry is rejected with `actions.NOT_SUPPORTED = "action not supported yet"`. Parallel tasks register by adding entries to `HANDLERS`.
  - `rows.parse(model: type[PayloadT], payload: Mapping[str, object]) -> PayloadT | None`; `rows.owned_source(db, *, user, source_id: uuid.UUID) -> models.Source | None` (None when missing, another user's, or deleted); `rows.owned_topic(db, *, user, topic_id: uuid.UUID) -> models.Topic | None` (None when missing, another user's, or merged; removed topics are returned); `rows.owned_topic_primer(db, *, user, primer_id: uuid.UUID) -> models.TopicPrimer | None`; `rows.top_queue_position(db, *, user_id: int) -> float`; `rows.MALFORMED = "payload is malformed"`, `rows.NO_SOURCE = "source not found"`, `rows.NO_TOPIC = "topic not found"`.
  - `schemas.SourceOut` gains the eight pulled columns; `schemas.TopicOut`, `schemas.TopicPrimerOut`; `PulledRows.topics`, `PulledRows.topic_primers`.
  - `pull.PulledTable(StrEnum)`: `SOURCES`, `ARTIFACTS`, `CARDS`, `TOPICS`, `TOPIC_PRIMERS`; `pull.merge_page(*, tables: Mapping[str, Sequence[RowT]], since: int, limit: int) -> MergedPage[RowT]` with `MergedPage.rows: dict[str, list[RowT]]`, `.position`, `.more`.
  - `MeView.topics_chosen: bool`. `GET /me` seeds the owner's topics first (Decision 1).
  - `TestSessionRequest.seed_topics: bool = False`; `LiveStack.sign_in(..., seed_topics: bool = False)`.
  - `sources.routes.router` (prefix `/sources`) with `GET /{source_id}/text`, mounted in `main.create_app`.
  - New queued sources from `add_source` get `queue_position = rows.top_queue_position(...)`.
- Review: yes (sync, auth).

`rows.py`:

```python
"""The caller's own rows for sync actions, payload parsing, and the top of the queue."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import pydantic
import sqlalchemy
from archie_db import models
from sqlalchemy import orm

MALFORMED = "payload is malformed"
NO_SOURCE = "source not found"
NO_TOPIC = "topic not found"


def parse[PayloadT: pydantic.BaseModel](model: type[PayloadT], payload: Mapping[str, object]) -> PayloadT | None:
    """The payload as `model`, or None when it doesn't fit (the action is then rejected as malformed)."""
    try:
        return model.model_validate(payload)
    except pydantic.ValidationError:
        return None


def owned_source(db: orm.Session, *, user: models.User, source_id: uuid.UUID) -> models.Source | None:
    """The user's live source with this id; another user's or a deleted one is treated as missing."""
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user.id or source.deleted_at is not None:
        return None
    return source


def owned_topic(db: orm.Session, *, user: models.User, topic_id: uuid.UUID) -> models.Topic | None:
    """The user's topic with this id unless it was merged away; removed topics are returned (restore needs them)."""
    topic = db.get(models.Topic, topic_id)
    if topic is None or topic.user_id != user.id or topic.merged_into_id is not None:
        return None
    return topic


def owned_topic_primer(db: orm.Session, *, user: models.User, primer_id: uuid.UUID) -> models.TopicPrimer | None:
    """The user's topic primer row with this id."""
    primer = db.get(models.TopicPrimer, primer_id)
    return primer if primer is not None and primer.user_id == user.id else None


def top_queue_position(db: orm.Session, *, user_id: int) -> float:
    """A position above every queued source of the user: one less than the lowest, or 0 for an empty queue."""
    lowest = db.scalar(
        sqlalchemy.select(sqlalchemy.func.min(models.Source.queue_position)).where(
            models.Source.user_id == user_id,
            models.Source.state == models.SourceState.QUEUED.value,
            models.Source.deleted_at.is_(None),
        )
    )
    return 0.0 if lowest is None else lowest - 1
```

`actions.py` changes:

```python
class ActionHandler(Protocol):
    """One action type's handler: returns the rejection reason, or None when applied (validate before writing)."""

    def __call__(self, db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None: ...


NOT_SUPPORTED = "action not supported yet"

# Each action type's handler; later work registers its types here.
HANDLERS: dict[schemas.ActionType, ActionHandler] = {
    schemas.ActionType.ADD_SOURCE: capture.add_source,
    schemas.ActionType.RETRY_SOURCE: capture.retry_source,
}


def _dispatch(db: orm.Session, *, user: models.User, action: schemas.ActionIn) -> str | None:
    """Run the action's handler; returns the rejection reason, or None when applied."""
    handler = HANDLERS.get(action.type)
    if handler is None:
        return NOT_SUPPORTED
    return handler(db, user=user, payload=action.payload)
```

In the `IntegrityError` branch, the reason becomes `"source id already exists" if action.type == schemas.ActionType.ADD_SOURCE else "id already exists"` (a phone-made topic id can collide too). Fix the docstring of `apply_actions` to say handlers must validate before writing.

`pull.py`: replace the three-table merge with:

```python
class PulledTable(StrEnum):
    """The synced tables a pull page carries, keyed as on the wire."""

    SOURCES = "sources"
    ARTIFACTS = "artifacts"
    CARDS = "cards"
    TOPICS = "topics"
    TOPIC_PRIMERS = "topic_primers"


@dataclasses.dataclass(frozen=True)
class MergedPage[RowT: _Positioned]:
    """The rows one pull page keeps from each table, and where the phone should resume."""

    rows: dict[str, list[RowT]]
    position: int
    more: bool


def merge_page[RowT: _Positioned](
    *, tables: Mapping[str, Sequence[RowT]], since: int, limit: int
) -> MergedPage[RowT]:
    """Keep the `limit` lowest positions across the tables' rows (each table already holds its own lowest).

    (Keep the rest of the existing docstring.)
    """
    all_rows = [row for rows in tables.values() for row in rows]
    kept_positions = sorted(row.change_seq for row in all_rows)[:limit]
    position = kept_positions[-1] if kept_positions else since

    return MergedPage(
        rows={name: [row for row in rows if row.change_seq <= position] for name, rows in tables.items()},
        position=position,
        more=len(all_rows) > limit or any(len(rows) == limit for rows in tables.values()),
    )
```

`pull_changes` builds `tables` from `_changed_rows` for all five models (widen `_changed_rows`'s type constraint to include `models.Topic` and `models.TopicPrimer`) and validates `page.rows[PulledTable.X]` into the matching `*Out` model. `TopicOut`/`TopicPrimerOut` follow `CardOut` (`from_attributes=True`) with exactly the Global Constraints fields.

`capture._insert_source`: after building the source, `if source.state == models.SourceState.QUEUED.value: source.queue_position = rows.top_queue_position(db, user_id=user.id)` (before `db.add`).

`/me` (`auth/routes.py`):

```python
class MeView(pydantic.BaseModel):
    """The signed-in user, as the app sees it."""

    user_id: int
    ingest_address: str | None
    # False until the user finished the topic picker; the app shows the picker while it is false.
    topics_chosen: bool


@router.get("/me")
def me(
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> MeView:
    """Return the signed-in user (seeding the owner's topics on first sight); 401 means sign in again."""
    settings = config.get_settings()
    if user.email is not None and user.email.lower() in settings.owner_email_set():
        changes.lock_user_writes(db, user.id)
        user_topics.seed_owner_topics(db, user=user)
        db.commit()

    domain = settings.ingest_email_domain
    ingest_address = f"{user.ingest_token}@{domain}" if domain else None
    return MeView(user_id=user.id, ingest_address=ingest_address, topics_chosen=user.topics_chosen_at is not None)
```

`apple.upsert_apple_user`: after the existing flush, `if user.is_whitelisted: changes.lock_user_writes(db, user.id); user_topics.seed_owner_topics(db, user=user)` (whitelisting is exactly "email in OWNER_EMAILS"). `test_routes.create_test_session`: after whitelisting, `if request.seed_topics: changes.lock_user_writes(db, user.id); user_topics.seed_owner_topics(db, user=user)`.

`sources/routes.py`:

```python
"""Per-source reads the phone makes online: a newsletter's full text (and, later, a podcast's nearby episodes)."""

router = fastapi.APIRouter(prefix="/sources", tags=["sources"])

_TEXT_KEY = "text"  # The `text` artifact's content key (the worker's `content.TEXT_KEY`).


class SourceTextView(pydantic.BaseModel):
    """A newsletter's stored text, for "Open the full email"."""

    text: str


@router.get("/{source_id}/text")
def source_text(
    source_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> SourceTextView:
    """The caller's newsletter text; 404 for any other source, someone else's, or one without text yet."""
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user.id or source.deleted_at is not None:
        raise _not_found()
    if source.kind != models.SourceKind.NEWSLETTER:
        raise _not_found()

    artifact = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.TEXT)
    if artifact is None:
        raise _not_found()
    return SourceTextView(text=artifact.content[_TEXT_KEY])


def _not_found() -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail="no such source text")
```

- [ ] **Step 1: Update** `services/api/tests/test_capture.py`'s merge tests to the `tables` mapping, and add one with five tables where two tables fill their own limit (`more` is True).
- [ ] **Step 2: E2e** `test_library_sync_e2e.py` (`postgres`): 
  - two queued `add_source`s → the later one's pulled `queue_position` is lower; a finished one has `None`.
  - a pulled source carries exactly the old keys plus the eight new ones (`episode_guid` absent).
  - rows inserted directly (own session, `changes.lock_user_writes`, `user_topics.create_topic`, a `TopicPrimer` with `content={"markdown": "# x"}`) interleaved with sources come back across pages in position order (use a `limit`-sized load like `test_pull_pages_across_sources_artifacts_and_cards` but with topics; 260 topics + 260 sources → pages of 500 and 20, every id once).
  - `/me` → `topics_chosen` False for a new user; `sign_in(seed_topics=True)` → True and a pull holds the owner's topics (live count = owner list size, 3 with `removed_at`).
  - with `monkeypatch.setenv("OWNER_EMAILS", "owner@example.com")` and `sign_in(email="owner@example.com")`, the first `/me` seeds (topics_chosen True); a second `/me` adds no rows.
  - `GET /sources/{id}/text`: a newsletter source inserted with a `text` artifact → 200 with its text; another user → 404; an article → 404.
  - `test_apple.py` DB class: a first sign-in of an owner email seeds the owner's topics; another email seeds nothing.
- [ ] **Step 3: Run** — fails. **Implement.** Run the whole Python suite and `make lint` — pass.
- [ ] **Step 4: Commit** "Sync: pull topics and topic primers, action dispatch table, queue positions, topics_chosen and owner seeding".

### Task 3: App data layer: schema, migration, sync of the new tables, optimistic actions, shared logic  (tier: most capable)

**Files:**
- Create: `app/drizzle/0003_*.sql` + snapshot/journal/`migrations.js` (via `npm run db:generate`), `app/src/db/testDb.ts`, `app/src/topics/domains.ts`, `app/src/topics/topicName.ts`, `app/src/topics/topicName.test.ts`, `app/src/library/join.ts`, `app/src/library/join.test.ts`, `app/src/library/useLibraryData.ts`, `app/src/library/visibility.ts`, `app/src/library/visibility.test.ts`, `app/src/library/snooze.ts`, `app/src/library/snooze.test.ts`, `packages/archie-shared/tests/test_domains.py`
- Modify: `app/package.json` + `app/package-lock.json` (new packages), `app/jest.config.js`, `app/src/db/schema.ts`, `app/src/db/actions.ts`, `app/src/db/actions.test.ts`, `app/src/sync/engine.ts`, `app/src/sync/transport.ts`, `app/src/sync/engine.test.ts`, `app/src/theme/tokens.ts`

**Interfaces:**
- Consumes: the wire shapes in Global Constraints (Tasks 1–2).
- Produces (every later app task relies on these names):
  - `schema.sources` new columns `domain`, `topicId`, `imageUrl`, `queuePosition` (`real`), `readAt`, `snoozedUntil`, `primerOpenedAt`, `newsletterKind`; `schema.topics` (`id, domain, name, origin, removedAt, mergedIntoId, createdAt, updatedAt, primerRequestedAt`); `schema.topicPrimers` (`id, topicId, version, isCurrent, content, openedAt, snoozedUntil, createdAt`).
  - `engine.ts`: `PulledTopic`, `PulledTopicPrimer`; `PullPage.rows.topics`, `.topic_primers`; `PulledSource` gains the eight snake_case fields.
  - `actions.ts`: `ActionType` union; `PrimerTarget = "source" | "topic_primer"`; functions (all synchronous, each one `db.transaction` writing the optimistic row(s) and one outbox entry): `finishSource(db, input: { sourceId: string; reaction: Reaction | null; note: string | null }): void`, `setPrepMe(db, sourceId: string, prepMe: boolean): void`, `setRead(db, sourceId: string, read: boolean): void`, `setPrimerOpened(db, target: PrimerTarget, id: string, opened: boolean): void`, `snooze(db, target: PrimerTarget, id: string, until: Date | null): void`, `setQueuePosition(db, sourceId: string, position: number): void`, `goDeeper(db, sourceId: string): void`, `readLater(db, sourceId: string): void`, `deleteSource(db, sourceId: string): void`, `addTopic(db, input: { domain: DomainName; name: string }): string`, `renameTopic(db, topicId: string, name: string): void`, `mergeTopic(db, topicId: string, intoId: string): void`, `removeTopic(db, topicId: string): void`, `restoreTopic(db, topicId: string): void`, `setSourceTopic(db, sourceId: string, topicId: string): void`, `requestTopicPrimer(db, topicId: string): void`, `chooseTopics(db, topics: ChosenTopic[]): void` with `ChosenTopic = { domain: DomainName; name: string; origin: "starter" | "user" }`, `chooseEpisode(db, sourceId: string, guid: string): void`. `addSource` also sets a queued source's `queuePosition` to the local top.
  - `topics/domains.ts`: `DOMAINS` (13 names, spec order), `DomainName`, `asDomain(value: string | null): DomainName` (unknown/null → `"Other"`). `tokens.ts`: `Domain = DomainName`; `domainColors` keyed by every `DomainName`.
  - `topics/topicName.ts`: `normalizeTopicName(name: string): string`, `slugify(text: string): string`, `MAX_TOPIC_NAME_LENGTH = 80`, `topicNameError(name: string, topics: TopicRow[], ignoreId?: string): string | null`.
  - `library/join.ts`: `SourceRow`, `TopicRow`, `TopicPrimerRow`, `LibrarySource` (`SourceRow & { topic: TopicRow | null; summary: SummaryContent | null; primerCreatedAt: string | null }`), `LibraryData` (`{ sources: LibrarySource[]; topics: TopicRow[]; topicPrimers: TopicPrimerRow[] }`), `joinLibrary(...)`, `isLiveTopic(topic: TopicRow): boolean`. `library/useLibraryData.ts`: `useLibraryData(): LibraryData` (non-deleted sources newest first, current artifacts, all topics, current topic primers).
  - `library/visibility.ts`: `StatusTag` (`"Queued" | "Done" | "Unread" | "Read" | "Briefed" | "Primer" | "Processing" | "Failed"`), `isSnoozed`, `statusTag`, `queueOrder`, `upNext`, `PrimerReadyItem`, `primersReady`, `waitingNewsletters` (signatures below).
  - `library/snooze.ts`: `SnoozeChoiceKey`, `SnoozeChoice`, `snoozeChoices(now: Date): SnoozeChoice[]`, `pickedDateUntil(day: Date): Date`, `formatReturnTime(until: Date, now: Date): string`.
  - `db/testDb.ts`: `makeTestDb(): AppDb` (in-memory better-sqlite3 with every drizzle migration applied and the `sync_state` row seeded).
- Review: yes (sync, optimistic state).

- [ ] **Step 1: Packages, once for every later app task** (so parallel worktrees never conflict on `package-lock.json`): if `app/node_modules` is missing in the worktree, `cd app && npm ci` first; then `cd app && npx expo install expo-image expo-haptics react-native-gesture-handler @react-native-community/datetimepicker`. Add `process.env.TZ = "America/New_York";` as the first line of `app/jest.config.js` with a comment ("snooze tests rely on a fixed zone with a DST change").

- [ ] **Step 2: Schema + migration.** In `schema.ts` (import `real` too):

```ts
  // Filing, artwork and reading state (M4). `queuePosition`: lower is higher in the queue.
  domain: text("domain"),
  topicId: text("topic_id"),
  imageUrl: text("image_url"),
  queuePosition: real("queue_position"),
  readAt: text("read_at"),
  snoozedUntil: text("snoozed_until"),
  primerOpenedAt: text("primer_opened_at"),
  newsletterKind: text("newsletter_kind"),
```

```ts
export const topics = sqliteTable("topics", {
  id: text("id").primaryKey(),
  domain: text("domain").notNull(),
  name: text("name").notNull(),
  // starter | archie | user
  origin: text("origin").notNull(),
  removedAt: text("removed_at"),
  mergedIntoId: text("merged_into_id"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  // Phone only (a pull never writes it): when this phone asked for a primer, so the topic page can say it's coming.
  primerRequestedAt: text("primer_requested_at"),
});

export const topicPrimers = sqliteTable("topic_primers", {
  id: text("id").primaryKey(),
  topicId: text("topic_id").notNull(),
  version: integer("version").notNull(),
  isCurrent: integer("is_current").notNull(),
  // JSON-encoded { markdown }.
  content: text("content").notNull(),
  openedAt: text("opened_at"),
  snoozedUntil: text("snoozed_until"),
  createdAt: text("created_at").notNull(),
});
```

Run `cd app && npm run db:generate`; commit the generated SQL, snapshot, journal and `migrations.js`.

`db/testDb.ts`:

```ts
import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";

import migrations from "../../drizzle/migrations";
import type { AppDb } from "./client";
import * as schema from "./schema";

// Tests run against the app's real schema: every generated migration, in journal order.
export function makeTestDb(): AppDb {
  const sqlite = new Database(":memory:");
  const sqlByKey = migrations.migrations as Record<string, string>;
  for (const entry of migrations.journal.entries) {
    const sql = sqlByKey[`m${String(entry.idx).padStart(4, "0")}`];
    for (const statement of sql.split("--> statement-breakpoint")) {
      if (statement.trim()) sqlite.exec(statement);
    }
  }
  sqlite.prepare("INSERT INTO sync_state (id, position, last_push_failed) VALUES (1, 0, 0)").run();
  return drizzle(sqlite, { schema }) as unknown as AppDb;
}
```

- [ ] **Step 3: Domains, tokens and topic names.**

`topics/domains.ts`:

```ts
/** The fixed domain list, in the same order as `archie_shared.domains.Domain` (a Python test checks they match). */
export const DOMAINS = [
  "Macro",
  "Finance",
  "Trading",
  "Crypto",
  "Startups",
  "AI",
  "Politics",
  "Geopolitics",
  "Sports",
  "Geography",
  "History",
  "Software engineering",
  "Other",
] as const;

export type DomainName = (typeof DOMAINS)[number];

export function asDomain(value: string | null): DomainName {
  return (DOMAINS as readonly string[]).includes(value ?? "") ? (value as DomainName) : "Other";
}
```

`tokens.ts`: `import type { DomainName } from "@/topics/domains"; export type Domain = DomainName;` and replace `domainColors` with the 13 light/dark pairs from Global Constraints, keyed by name (`Macro: "#3F7262"`, …, `"Software engineering": "#5A5F6E"`, `Other: "#77736A"`; dark likewise).

`packages/archie-shared/tests/test_domains.py` (not Postgres): read `app/src/topics/domains.ts` (`pathlib.Path(__file__).resolve().parents[3] / "app" / "src" / "topics" / "domains.ts"`), take the quoted strings between `DOMAINS = [` and `] as const` with `re.findall(r'"([^"]+)"', block)`, assert equal to `[domain.value for domain in Domain]`.

`topics/topicName.ts`:

```ts
import type { TopicRow } from "@/library/join";

export const MAX_TOPIC_NAME_LENGTH = 80;

/** The form names are compared in, matching the server's `normalize_topic_name`. */
export function normalizeTopicName(name: string): string {
  return name.toLowerCase().replace(/&/g, " and ").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

/** A testID-safe form of a domain or topic name: "Fed & monetary policy" → "fed-monetary-policy". */
export function slugify(text: string): string {
  return text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
}

/** Why `name` can't be used for a new or renamed topic, or null; mirrors the server's checks. */
export function topicNameError(name: string, topics: TopicRow[], ignoreId?: string): string | null {
  const cleaned = name.split(/\s+/).filter(Boolean).join(" ");
  if (!cleaned) return "Give the topic a name.";
  if (cleaned.length > MAX_TOPIC_NAME_LENGTH) return `Keep it under ${MAX_TOPIC_NAME_LENGTH} characters.`;

  const wanted = normalizeTopicName(cleaned);
  const clash = topics.find(
    (topic) => topic.id !== ignoreId && !topic.mergedIntoId && normalizeTopicName(topic.name) === wanted,
  );
  if (!clash) return null;
  return clash.removedAt ? "You removed a topic with this name. Restore it in Settings." : "You already have this topic.";
}
```

- [ ] **Step 4: Join, visibility and snooze logic.**

`library/join.ts`:

```ts
import * as schema from "@/db/schema";
import { parseSummary, type SummaryContent } from "@/ui/summaryContent";

export type SourceRow = typeof schema.sources.$inferSelect;
export type TopicRow = typeof schema.topics.$inferSelect;
export type TopicPrimerRow = typeof schema.topicPrimers.$inferSelect;
type ArtifactRow = typeof schema.artifacts.$inferSelect;

export type LibrarySource = SourceRow & {
  topic: TopicRow | null;
  summary: SummaryContent | null;
  // When the current primer artifact was written; null when the source has no primer.
  primerCreatedAt: string | null;
};

export type LibraryData = { sources: LibrarySource[]; topics: TopicRow[]; topicPrimers: TopicPrimerRow[] };

export function isLiveTopic(topic: TopicRow): boolean {
  return !topic.removedAt && !topic.mergedIntoId;
}

/** Attaches each source's topic, current summary and primer time; `artifacts` must be current ones only. */
export function joinLibrary(input: {
  sources: SourceRow[];
  artifacts: ArtifactRow[];
  topics: TopicRow[];
  topicPrimers: TopicPrimerRow[];
}): LibraryData {
  const topicsById = new Map(input.topics.map((topic) => [topic.id, topic]));
  const summaries = new Map<string, SummaryContent>();
  const primerTimes = new Map<string, string>();
  for (const artifact of input.artifacts) {
    if (artifact.kind === "summary") summaries.set(artifact.sourceId, parseSummary(artifact.content));
    if (artifact.kind === "primer") primerTimes.set(artifact.sourceId, artifact.createdAt);
  }

  return {
    sources: input.sources.map((source) => ({
      ...source,
      topic: source.topicId ? (topicsById.get(source.topicId) ?? null) : null,
      summary: summaries.get(source.id) ?? null,
      primerCreatedAt: primerTimes.get(source.id) ?? null,
    })),
    topics: input.topics,
    topicPrimers: input.topicPrimers,
  };
}
```

`library/useLibraryData.ts`: four `useLiveQuery`s (`sources` where `deletedAt` is null ordered by `createdAt` desc; `artifacts` where `isCurrent = 1`; all `topics`; `topicPrimers` where `isCurrent = 1`) and `useMemo(() => joinLibrary({...}), [...])`.

`library/visibility.ts`:

```ts
import { isLiveTopic, type LibraryData, type LibrarySource, type TopicPrimerRow, type TopicRow } from "./join";

export type StatusTag = "Queued" | "Done" | "Unread" | "Read" | "Briefed" | "Primer" | "Processing" | "Failed";

export function isSnoozed(item: { snoozedUntil: string | null }, now: Date): boolean {
  return item.snoozedUntil !== null && new Date(item.snoozedUntil) > now;
}

/** The Library row's tag: the pipeline's state wins while it is working or failed, then the reading state. */
export function statusTag(source: { state: string; processing: string; readAt: string | null }): StatusTag {
  if (source.processing === "pending" || source.processing === "processing") return "Processing";
  if (source.processing === "failed") return "Failed";
  if (source.state === "queued") return "Queued";
  if (source.state === "consumed") return "Done";
  if (source.state === "briefed") return "Briefed";
  return source.readAt ? "Read" : "Unread";
}

/** Queued sources in queue order: lowest position first; unpositioned ones last, newest first. */
export function queueOrder(sources: LibrarySource[]): LibrarySource[] {
  return sources
    .filter((source) => source.state === "queued")
    .sort((first, second) => {
      const a = first.queuePosition ?? Number.POSITIVE_INFINITY;
      const b = second.queuePosition ?? Number.POSITIVE_INFINITY;
      return a !== b ? a - b : second.createdAt.localeCompare(first.createdAt);
    });
}

export function upNext(sources: LibrarySource[], now: Date): LibrarySource[] {
  return queueOrder(sources).filter((source) => !isSnoozed(source, now));
}

export type PrimerReadyItem =
  | { kind: "source"; key: string; createdAt: string; source: LibrarySource }
  | { kind: "topic"; key: string; createdAt: string; primer: TopicPrimerRow; topic: TopicRow };

/** Pushed primers nobody has opened yet, newest first: prepped sources' primers and live topics' primers. */
export function primersReady(data: LibraryData, now: Date): PrimerReadyItem[] {
  const sourceItems: PrimerReadyItem[] = data.sources
    .filter((source) => source.prepMe === 1 && source.primerCreatedAt && !source.primerOpenedAt && !isSnoozed(source, now))
    .map((source) => ({ kind: "source", key: `source-${source.id}`, createdAt: source.primerCreatedAt!, source }));

  const topicsById = new Map(data.topics.map((topic) => [topic.id, topic]));
  const topicItems: PrimerReadyItem[] = data.topicPrimers.flatMap((primer) => {
    const topic = topicsById.get(primer.topicId);
    if (!topic || !isLiveTopic(topic) || primer.openedAt || isSnoozed(primer, now)) return [];
    return [{ kind: "topic" as const, key: `topic-${primer.id}`, createdAt: primer.createdAt, primer, topic }];
  });

  return [...sourceItems, ...topicItems].sort((first, second) => second.createdAt.localeCompare(first.createdAt));
}

export type WaitingNewsletters = { count: number; senders: string[]; since: string | null };

/** Newsletters in the inbox (not briefed, not snoozed): how many, the two newest distinct senders, the oldest time. */
export function waitingNewsletters(sources: LibrarySource[], now: Date): WaitingNewsletters {
  const waiting = sources
    .filter((source) => source.kind === "newsletter" && source.state === "inbox" && !isSnoozed(source, now))
    .sort((first, second) => second.createdAt.localeCompare(first.createdAt));
  const senders = [...new Set(waiting.map((source) => source.sender ?? "Newsletter"))].slice(0, 2);
  return { count: waiting.length, senders, since: waiting.at(-1)?.createdAt ?? null };
}
```

`library/snooze.ts`:

```ts
export type SnoozeChoiceKey = "tonight" | "tomorrow" | "weekend" | "nextWeek";
export type SnoozeChoice = { key: SnoozeChoiceKey; label: string; until: Date };

const TONIGHT_HOUR = 18;
// From 17:00 "Tonight" would be under an hour away, so it isn't offered.
const TONIGHT_CUTOFF_HOUR = 17;
const MORNING_HOUR = 9;
const SATURDAY = 6;
const MONDAY = 1;

function atHour(day: Date, hour: number): Date {
  // Built from local date parts, so DST changes land on the wall-clock hour.
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), hour, 0, 0, 0);
}

function daysUntil(now: Date, weekday: number): number {
  // Strictly after today: on a Saturday, "this weekend" is next Saturday.
  return (weekday - now.getDay() + 7) % 7 || 7;
}

function plusDays(day: Date, days: number): Date {
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() + days);
}

/** The preset snooze times, in the phone's time zone. */
export function snoozeChoices(now: Date): SnoozeChoice[] {
  const tonight: SnoozeChoice[] =
    now.getHours() < TONIGHT_CUTOFF_HOUR ? [{ key: "tonight", label: "Tonight", until: atHour(now, TONIGHT_HOUR) }] : [];
  return [
    ...tonight,
    { key: "tomorrow", label: "Tomorrow", until: atHour(plusDays(now, 1), MORNING_HOUR) },
    { key: "weekend", label: "This weekend", until: atHour(plusDays(now, daysUntil(now, SATURDAY)), MORNING_HOUR) },
    { key: "nextWeek", label: "Next week", until: atHour(plusDays(now, daysUntil(now, MONDAY)), MORNING_HOUR) },
  ];
}

export function pickedDateUntil(day: Date): Date {
  return atHour(day, MORNING_HOUR);
}

/** "6 PM" today, "Sat 9 AM" within a week, else "Nov 20, 9 AM". */
export function formatReturnTime(until: Date, now: Date): string {
  const hour = until.getHours();
  const time = `${hour % 12 === 0 ? 12 : hour % 12}${until.getMinutes() ? `:${String(until.getMinutes()).padStart(2, "0")}` : ""} ${hour < 12 ? "AM" : "PM"}`;
  const days = Math.round((atHour(until, 0).getTime() - atHour(now, 0).getTime()) / 86_400_000);
  if (days === 0) return time;
  if (days > 0 && days < 7) return `${until.toLocaleDateString("en-US", { weekday: "short" })} ${time}`;
  return `${until.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
}
```

- [ ] **Step 5: Engine types and the sync store.** `engine.ts`:

```ts
export type PulledSource = {
  // …existing fields…
  domain: string | null;
  topic_id: string | null;
  image_url: string | null;
  queue_position: number | null;
  read_at: string | null;
  snoozed_until: string | null;
  primer_opened_at: string | null;
  newsletter_kind: string | null;
};
export type PulledTopic = {
  id: string;
  domain: string;
  name: string;
  origin: string;
  removed_at: string | null;
  merged_into_id: string | null;
  created_at: string;
  updated_at: string;
};
export type PulledTopicPrimer = {
  id: string;
  topic_id: string;
  version: number;
  is_current: boolean;
  content: unknown;
  opened_at: string | null;
  snoozed_until: string | null;
  created_at: string;
};
export type PullPage = {
  rows: {
    sources: PulledSource[];
    artifacts: PulledArtifact[];
    cards: PulledCard[];
    topics: PulledTopic[];
    topic_primers: PulledTopicPrimer[];
  };
  position: number;
  more: boolean;
};
```

`transport.ts` `applyPage`: the source `values` gain `domain`, `topicId`, `imageUrl`, `queuePosition`, `readAt`, `snoozedUntil`, `primerOpenedAt`, `newsletterKind`; then, inside the same transaction after cards (the `unsent` set already holds every pending payload's `id`, which is the topic or primer an action changes):

```ts
        for (const topic of page.rows.topics) {
          if (unsent.has(topic.id)) continue;
          // primerRequestedAt is phone-only and deliberately left out.
          const values = {
            domain: topic.domain,
            name: topic.name,
            origin: topic.origin,
            removedAt: topic.removed_at,
            mergedIntoId: topic.merged_into_id,
            createdAt: topic.created_at,
            updatedAt: topic.updated_at,
          };
          tx.insert(schema.topics)
            .values({ id: topic.id, ...values })
            .onConflictDoUpdate({ target: schema.topics.id, set: values })
            .run();
        }

        for (const primer of page.rows.topic_primers) {
          if (unsent.has(primer.id)) continue;
          const values = {
            topicId: primer.topic_id,
            version: primer.version,
            isCurrent: primer.is_current ? 1 : 0,
            content: JSON.stringify(primer.content),
            openedAt: primer.opened_at,
            snoozedUntil: primer.snoozed_until,
            createdAt: primer.created_at,
          };
          tx.insert(schema.topicPrimers)
            .values({ id: primer.id, ...values })
            .onConflictDoUpdate({ target: schema.topicPrimers.id, set: values })
            .run();
        }
```

`rejectAction`: right after reading the payload's `id` (the existing `sourceId` line), `if (entry.type === "add_topic") { tx.delete(schema.topics).where(eq(schema.topics.id, sourceId)).run(); return; }` (Decision 16), before the existing source update; rename that local to `rowId` since it is no longer always a source.

- [ ] **Step 6: Optimistic actions** (`db/actions.ts`; keep `addSource`/`retrySource`, add the rest):

```ts
import { and, eq, isNull, min, sql } from "drizzle-orm";

import type { DomainName } from "@/topics/domains";

export type ActionType =
  | "add_source" | "retry_source" | "finish_source" | "set_prep_me" | "set_read" | "set_primer_opened" | "snooze"
  | "set_queue_position" | "go_deeper" | "read_later" | "delete_source" | "add_topic" | "rename_topic"
  | "merge_topic" | "remove_topic" | "restore_topic" | "set_source_topic" | "request_topic_primer"
  | "choose_topics" | "choose_episode";
export type PrimerTarget = "source" | "topic_primer";
export type ChosenTopic = { domain: DomainName; name: string; origin: "starter" | "user" };

type Tx = Parameters<Parameters<AppDb["transaction"]>[0]>[0];

function enqueue(tx: Tx, type: ActionType, payload: Record<string, unknown>): void {
  tx.insert(schema.outbox)
    .values({ id: randomUUID(), type, payload: JSON.stringify(payload), createdAt: new Date().toISOString(), status: "pending" })
    .run();
}

function updateSource(tx: Tx, sourceId: string, values: Partial<typeof schema.sources.$inferInsert>): void {
  tx.update(schema.sources)
    .set({ ...values, updatedAt: new Date().toISOString() })
    .where(eq(schema.sources.id, sourceId))
    .run();
}

// Mirrors the server's rule: one above the current top, or 0 for an empty queue.
function topQueuePosition(tx: Tx): number {
  const row = tx
    .select({ lowest: min(schema.sources.queuePosition) })
    .from(schema.sources)
    .where(and(eq(schema.sources.state, "queued"), isNull(schema.sources.deletedAt)))
    .get();
  return row?.lowest == null ? 0 : row.lowest - 1;
}

function topicDomain(tx: Tx, topicId: string): string | null {
  return tx.select().from(schema.topics).where(eq(schema.topics.id, topicId)).get()?.domain ?? null;
}

export function finishSource(
  db: AppDb,
  input: { sourceId: string; reaction: Reaction | null; note: string | null },
): void {
  db.transaction((tx) => {
    updateSource(tx, input.sourceId, {
      state: "consumed",
      snoozedUntil: null,
      ...(input.reaction ? { reaction: input.reaction } : {}),
      ...(input.note ? { note: input.note } : {}),
      // "Parts lost me" pushes the primer to Today, as the server does.
      ...(input.reaction === "lost" ? { prepMe: 1 } : {}),
    });
    enqueue(tx, "finish_source", {
      id: input.sourceId,
      ...(input.reaction ? { reaction: input.reaction } : {}),
      ...(input.note ? { note: input.note } : {}),
    });
  });
}

export function setPrepMe(db: AppDb, sourceId: string, prepMe: boolean): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { prepMe: prepMe ? 1 : 0 });
    enqueue(tx, "set_prep_me", { id: sourceId, prep_me: prepMe });
  });
}

export function setRead(db: AppDb, sourceId: string, read: boolean): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { readAt: read ? new Date().toISOString() : null });
    enqueue(tx, "set_read", { id: sourceId, read });
  });
}

export function setPrimerOpened(db: AppDb, target: PrimerTarget, id: string, opened: boolean): void {
  const openedAt = opened ? new Date().toISOString() : null;
  db.transaction((tx) => {
    if (target === "source") updateSource(tx, id, { primerOpenedAt: openedAt });
    else tx.update(schema.topicPrimers).set({ openedAt }).where(eq(schema.topicPrimers.id, id)).run();
    enqueue(tx, "set_primer_opened", { target, id, opened });
  });
}

export function snooze(db: AppDb, target: PrimerTarget, id: string, until: Date | null): void {
  const snoozedUntil = until ? until.toISOString() : null;
  db.transaction((tx) => {
    if (target === "topic_primer") {
      tx.update(schema.topicPrimers).set({ snoozedUntil }).where(eq(schema.topicPrimers.id, id)).run();
    } else {
      const source = tx.select().from(schema.sources).where(eq(schema.sources.id, id)).get();
      // A snoozed queued item comes back at the top of the queue.
      const position = until && source?.state === "queued" ? { queuePosition: topQueuePosition(tx) } : {};
      updateSource(tx, id, { snoozedUntil, ...position });
    }
    enqueue(tx, "snooze", { target, id, until: snoozedUntil });
  });
}

export function setQueuePosition(db: AppDb, sourceId: string, position: number): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { queuePosition: position });
    enqueue(tx, "set_queue_position", { id: sourceId, position });
  });
}

export function goDeeper(db: AppDb, sourceId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    updateSource(tx, sourceId, {
      state: "consumed",
      processing: "processing",
      readAt: sql`coalesce(${schema.sources.readAt}, ${now})`,
    });
    enqueue(tx, "go_deeper", { id: sourceId });
  });
}

export function readLater(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { state: "queued", snoozedUntil: null, queuePosition: topQueuePosition(tx) });
    enqueue(tx, "read_later", { id: sourceId });
  });
}

export function deleteSource(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { deletedAt: new Date().toISOString() });
    enqueue(tx, "delete_source", { id: sourceId });
  });
}

export function addTopic(db: AppDb, input: { domain: DomainName; name: string }): string {
  const id = randomUUID();
  const now = new Date().toISOString();
  const name = input.name.split(/\s+/).filter(Boolean).join(" ");
  db.transaction((tx) => {
    // The server writes a primer for every added topic, so the page can say it's coming right away.
    tx.insert(schema.topics)
      .values({ id, domain: input.domain, name, origin: "user", createdAt: now, updatedAt: now, primerRequestedAt: now })
      .run();
    enqueue(tx, "add_topic", { id, domain: input.domain, name });
  });
  return id;
}

export function renameTopic(db: AppDb, topicId: string, name: string): void {
  const cleaned = name.split(/\s+/).filter(Boolean).join(" ");
  db.transaction((tx) => {
    tx.update(schema.topics).set({ name: cleaned, updatedAt: new Date().toISOString() }).where(eq(schema.topics.id, topicId)).run();
    enqueue(tx, "rename_topic", { id: topicId, name: cleaned });
  });
}

export function mergeTopic(db: AppDb, topicId: string, intoId: string): void {
  db.transaction((tx) => {
    const domain = topicDomain(tx, intoId);
    tx.update(schema.sources).set({ topicId: intoId, domain }).where(eq(schema.sources.topicId, topicId)).run();
    tx.update(schema.topics).set({ mergedIntoId: intoId }).where(eq(schema.topics.id, topicId)).run();
    enqueue(tx, "merge_topic", { id: topicId, into_id: intoId });
  });
}

export function removeTopic(db: AppDb, topicId: string): void {
  db.transaction((tx) => {
    tx.update(schema.topics).set({ removedAt: new Date().toISOString() }).where(eq(schema.topics.id, topicId)).run();
    // The server re-files these; until then they show without a topic, never under the removed one.
    tx.update(schema.sources).set({ topicId: null }).where(eq(schema.sources.topicId, topicId)).run();
    enqueue(tx, "remove_topic", { id: topicId });
  });
}

export function restoreTopic(db: AppDb, topicId: string): void {
  db.transaction((tx) => {
    tx.update(schema.topics).set({ removedAt: null }).where(eq(schema.topics.id, topicId)).run();
    enqueue(tx, "restore_topic", { id: topicId });
  });
}

export function setSourceTopic(db: AppDb, sourceId: string, topicId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { topicId, domain: topicDomain(tx, topicId) });
    enqueue(tx, "set_source_topic", { id: sourceId, topic_id: topicId });
  });
}

export function requestTopicPrimer(db: AppDb, topicId: string): void {
  db.transaction((tx) => {
    tx.update(schema.topics).set({ primerRequestedAt: new Date().toISOString() }).where(eq(schema.topics.id, topicId)).run();
    enqueue(tx, "request_topic_primer", { id: topicId });
  });
}

export function chooseTopics(db: AppDb, topics: ChosenTopic[]): void {
  const now = new Date().toISOString();
  const rows = topics.map((topic) => ({ ...topic, id: randomUUID() }));
  db.transaction((tx) => {
    for (const row of rows) {
      tx.insert(schema.topics)
        .values({
          id: row.id,
          domain: row.domain,
          name: row.name,
          origin: row.origin,
          createdAt: now,
          updatedAt: now,
          primerRequestedAt: row.origin === "user" ? now : null,
        })
        .run();
    }
    enqueue(tx, "choose_topics", { topics: rows.map((row) => ({ id: row.id, domain: row.domain, name: row.name })) });
  });
}

export function chooseEpisode(db: AppDb, sourceId: string, guid: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { processing: "processing", processingError: null });
    enqueue(tx, "choose_episode", { id: sourceId, guid });
  });
}
```

`addSource`: the inserted row gets `queuePosition: input.intent === "queue" ? topQueuePosition(tx) : null`. Refactor `addSource`/`retrySource` onto `enqueue` while here. (If `Tx` doesn't type-check with this drizzle version, use `import type { SQLiteTransaction } from "drizzle-orm/sqlite-core"` with the same generic parameters as `AppDb`.)

- [ ] **Step 7: Tests** (jest):
  - `topicName.test.ts`: the four normalization cases from Task 1 give the same strings as Python (`"us china"`, `"ai ml engineering"`, `"rollups and l2s"`, `"fed and monetary policy"`); `slugify("Fed & monetary policy") === "fed-monetary-policy"`; `topicNameError` → empty, 81 characters, a live clash, a removed clash (Settings message), the same name with `ignoreId` of itself → null, a merged topic's name → null.
  - `join.test.ts`: a source gets its topic, parsed summary and primer time; a source without artifacts gets nulls.
  - `visibility.test.ts`: `statusTag` for every row of the table (processing beats state); `isSnoozed` past/future/null; `upNext` hides snoozed and orders by position then newest; `primersReady` includes a prepped unread source primer and an unread live topic primer, newest first, and excludes opened, snoozed, un-prepped, no-primer, removed-topic and merged-topic cases; `waitingNewsletters` counts inbox newsletters only (not briefed, not snoozed), two newest distinct senders, `since` = the oldest.
  - `snooze.test.ts` (TZ is America/New_York): at Wed 2026-11-04 16:59 local the first choice is Tonight 18:00 (`until.toISOString() === "2026-11-04T23:00:00.000Z"`); at 17:00 Tonight is absent; Tomorrow is Thu 09:00; This weekend is Sat 2026-11-07 09:00; Next week is Mon 2026-11-09 09:00; on Sat 2026-10-31 20:00 Tomorrow is `"2026-11-01T14:00:00.000Z"` (EST after the DST change, not 13:00Z); on a Saturday "This weekend" is the next Saturday; `pickedDateUntil` is 09:00 local; `formatReturnTime` gives "6 PM", "Sat 9 AM", "Nov 20, 9 AM".
  - `actions.test.ts` (use `makeTestDb()` for the new cases; keep the existing CHECK-based rollback test as is): `finishSource` with `lost` sets `prepMe` and the payload omits empty note; `snooze` on a queued source moves it above the top (−1 below the current minimum) and the payload `until` is an ISO string; `snooze(..., null)` sends `until: null`; `readLater` puts an inbox source at the top as `queued`; `addSource` queued twice → the second is lower; `mergeTopic` moves sources and their domain; `removeTopic` clears `topicId` on its sources; `chooseTopics` payload has `topics: [{id, domain, name}]` and inserts rows; `addTopic` returns the id used in the payload.
  - `engine.test.ts` (with `makeTestDb()`): a page with topics and topic primers is stored; a topic with a pending outbox action keeps its local name; a later pull doesn't clear `primerRequestedAt`; a rejected `add_topic` deletes the local topic; a pulled source's new fields are stored.
  - `uv run pytest packages/archie-shared/tests/test_domains.py` passes.
- [ ] **Step 8: Run** `cd app && npm run typecheck && npx jest` — pass. (Screens still compile: `Text`'s `domain` prop now takes `DomainName`.)
- [ ] **Step 9: Commit** "App data: topics and topic primers synced, library columns, optimistic actions, visibility and snooze rules".

### Task 4: App UI primitives, sheets and the Library shell  (tier: standard)

**Files:**
- Create: `app/src/ui/haptics.ts`, `app/src/ui/monogram.ts`, `app/src/ui/monogram.test.ts`, `app/src/ui/ArtworkTile.tsx`, `app/src/ui/Kicker.tsx`, `app/src/ui/StatusTagView.tsx`, `app/src/ui/ItemRow.tsx`, `app/src/ui/SourceRow.tsx`, `app/src/ui/GroupedList.tsx`, `app/src/ui/BottomSheet.tsx`, `app/src/ui/MenuSheet.tsx`, `app/src/ui/FinishSheet.tsx`, `app/src/ui/SnoozeSheet.tsx`, `app/src/ui/TopicChooserSheet.tsx`, `app/src/ui/useNow.ts`, `app/src/library/LibraryList.tsx`, `app/src/library/DomainsView.tsx`
- Modify: `app/src/app/_layout.tsx` (`GestureHandlerRootView`), `app/src/theme/components/Screen.tsx` (`onBack`), `app/src/ui/sourceLabels.ts` (+ test), `app/src/app/(tabs)/library.tsx` (shell)

**Interfaces:**
- Consumes: Task 3.
- Produces:
  - `haptics.haptic(event: "selection" | "light" | "success"): void` (selection → `Haptics.selectionAsync()`, light → `impactAsync(ImpactFeedbackStyle.Light)`, success → `notificationAsync(NotificationFeedbackType.Success)`; each `void`-ed, never awaited).
  - `monogram.monogramFor(item: { kind: string; title: string | null; sender: string | null; url: string }): string` (first letter or digit, upper-cased, of sender → title → URL hostname; `"▶"` for youtube; `"?"` when none); `monogram.PRIMER_MONOGRAM = "◆"`.
  - `ArtworkTile` props `{ imageUrl: string | null; domain: string | null; monogram: string; size: number; circle?: boolean; unread?: boolean; testID?: string }` — `expo-image` `Image` with `cachePolicy="disk"`; on `onError` (or no URL) renders the monogram tile in `theme.domains[asDomain(domain)]` with white text; `unread` draws an 8 px blue dot (`#3D7BF2` light / `#6EA1FF` dark) at the top-left corner, testID `${testID}-unread`.
  - `Kicker` props `{ domain: string | null; suffix?: string; label?: string }` — uppercase kicker text `"<label ?? Domain> · <suffix>"` in the domain color (`variant="kicker"`, `domain={asDomain(domain)}`); `label` replaces the domain name (Today's "Inbox" row).
  - `StatusTagView` props `{ tag: StatusTag; testID?: string }` (Unread in `ink` semibold, Processing `ink3`, Failed `signals.missed`, others `ink2` on `press`).
  - `ItemRow` props `{ artwork: ArtworkTile props; kicker: Kicker props; title: string; meta: string; end?: ReactNode; onPress?: () => void; onLongPress?: () => void; testID?: string }` — 44 px artwork (its testID is `${testID}-art`, so an unread dot is `${testID}-art-unread`), kicker, two-line title (`headline`), one-line meta (`secondary`, `ink3`), `end` on the right; press → `haptic("light")` then `onPress`.
  - `SourceRow` props `{ source: LibrarySource; end?: ReactNode; meta?: string; testID?: string; onPress?: () => void }` — `ItemRow` for a source: artwork `imageUrl`/`domain`/`monogramFor`/`circle = kind === "x"`/`unread = statusTag(source) === "Unread"`; kicker domain; title `title ?? url`; meta default `sourceMeta(source)`; default `onPress` pushes `/source/[id]`.
  - `sourceLabels.kindLabel(kind: string): string` (podcast "Podcast", youtube "YouTube", article "Article", x "X post", newsletter "Newsletter", else "Link"); `sourceLabels.sourceMeta(source: { kind: string; url: string; sender: string | null }): string` = `` `${kindLabel(kind)} · ${sourceByline(source)}` ``.
  - `GroupedList` props `{ title?: string; right?: ReactNode; children: ReactNode; testID?: string }` — section label row + a `Card` group with hairline separators between children.
  - `BottomSheet` props `{ visible: boolean; onClose: () => void; children: ReactNode; testID?: string }` — RN `Modal` (`transparent`, `animationType="slide"`), dim backdrop (`press` 60% black) closing on tap, sheet with grabber on `surface`, rounded top corners `radii.card`, bottom safe-area padding.
  - `MenuSheet` props `{ visible; onClose; items: { label: string; onPress: () => void; destructive?: boolean; testID: string }[] }` — each item a full-width row; tapping closes the sheet first.
  - `FinishSheet` props `{ sourceId: string; visible: boolean; onClose: () => void }`.
  - `SnoozeSheet` props `{ target: PrimerTarget; id: string; visible: boolean; onClose: () => void }`.
  - `TopicChooserSheet` props `{ visible: boolean; onClose: () => void; title: string; excludeTopicId?: string; onChoose: (topic: TopicRow) => void }`.
  - `useNow(intervalMs = 60_000): Date` (state refreshed on an interval, so snoozes expire on screen).
  - `Screen` gains `onBack?: () => void`, rendering a `‹` button (testID `screen-back`, `hitSlop` 12) before the title.
  - Library shell: `library.tsx` calls `const data = useLibraryData();` and owns `mode: "list" | "domains"` (segmented toggle `library-mode-list` / `library-mode-domains`, `haptic("selection")`), the search field (`TextField` testID `library-search`, placeholder "Search your library"), reads `filter` from `useLocalSearchParams<{ filter?: string }>()`, and renders `<LibraryList data={...} query={query} initialFilter={filter} />` when in list mode **or the query is non-empty**, else `<DomainsView data={...} />`. `LibraryList` props `{ data: LibraryData; query: string; initialFilter?: string }`; `DomainsView` props `{ data: LibraryData }`. This task ships them as working minimal versions: `LibraryList` = every source newest first as `SourceRow`s with `StatusTagView` ends (the "⚠ Not synced" marker and `ProcessingLine` stay from today's row); `DomainsView` = one `GroupedList` row per domain with items (name, count). Tasks 12 and 13 grow them.
- Review: no.

Key code:

```tsx
// ui/FinishSheet.tsx
const VERDICTS: { reaction: Reaction; label: string; signal: Signal }[] = [
  { reaction: "easy", label: "Easy", signal: "gotIt" },
  { reaction: "mostly", label: "Mostly followed", signal: "partly" },
  { reaction: "lost", label: "Parts lost me", signal: "missed" },
];

export function FinishSheet({ sourceId, visible, onClose }: FinishSheetProps) {
  const theme = useTheme();
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [note, setNote] = useState("");

  function save(): void {
    finishSource(db, { sourceId, reaction, note: note.trim() || null });
    haptic("success");
    requestSync();
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="finish-sheet">
      <Text variant="headline">How'd it go?</Text>
      <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
        {VERDICTS.map((verdict) => (
          <Pressable
            key={verdict.reaction}
            testID={`finish-${verdict.reaction}`}
            onPress={() => {
              haptic("selection");
              setReaction((current) => (current === verdict.reaction ? null : verdict.reaction));
            }}
            style={{
              flex: 1,
              borderRadius: theme.radii.chip,
              paddingVertical: theme.spacing.md,
              alignItems: "center",
              borderWidth: 1.5,
              borderColor: reaction === verdict.reaction ? theme.signals[verdict.signal] : theme.colors.line,
            }}
          >
            <Text variant="secondary">{verdict.label}</Text>
          </Pressable>
        ))}
      </View>
      {/* The mic waits for voice input (a follow-up); typing works now. */}
      <TextField testID="finish-note" placeholder="Anything confusing? (optional)" value={note} onChangeText={setNote} multiline />
      <Button testID="finish-save" label="Save" onPress={save} />
      <Text variant="secondary" tone="ink3">Both are optional: Save alone marks it done.</Text>
    </BottomSheet>
  );
}
```

```tsx
// ui/SnoozeSheet.tsx (structure)
export function SnoozeSheet({ target, id, visible, onClose }: SnoozeSheetProps) {
  const now = useNow();
  const [picking, setPicking] = useState(false);
  const [pickedDay, setPickedDay] = useState(() => new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));

  function choose(until: Date): void {
    snooze(db, target, id, until);
    haptic("success");
    requestSync();
    setPicking(false);
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="snooze-sheet">
      <Text variant="headline">Snooze until</Text>
      {snoozeChoices(now).map((choice) => (
        <Pressable key={choice.key} testID={`snooze-${choice.key}`} onPress={() => choose(choice.until)}>
          {/* label left, resolved time right (mono): "Tonight · 6 PM", "Tomorrow · Thu 9 AM" */}
          <Text>{choice.label}</Text>
          <Text variant="monoLabel" tone="ink3">{formatReturnTime(choice.until, now)}</Text>
        </Pressable>
      ))}
      <Pressable testID="snooze-pick" onPress={() => setPicking(true)}><Text>Pick a date…</Text></Pressable>
      {picking ? (
        <>
          <DateTimePicker
            value={pickedDay}
            mode="date"
            display="inline"
            minimumDate={new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)}
            onChange={(_, day) => day && setPickedDay(day)}
          />
          <Button testID="snooze-pick-confirm" label={`Snooze until ${formatReturnTime(pickedDateUntil(pickedDay), now)}`} onPress={() => choose(pickedDateUntil(pickedDay))} />
        </>
      ) : null}
    </BottomSheet>
  );
}
```

`TopicChooserSheet`: `useLiveQuery` of live topics (`removedAt` null, `mergedIntoId` null) minus `excludeTopicId`; a filter `TextField` (`topic-chooser-search`, filters with `normalizeTopicName(...).includes(normalizeTopicName(query))`); rows grouped by domain in `DOMAINS` order (kicker header per domain), each `Pressable` testID `topic-choice-${slugify(topic.name)}` → `haptic("selection")`, `onChoose(topic)`, `onClose()`.

`ArtworkTile` fallback logic: `const [failed, setFailed] = useState(false); const showImage = imageUrl !== null && !failed;` reset `failed` when `imageUrl` changes (`useEffect`).

- [ ] **Step 1: Unit test** `monogram.test.ts`: newsletter with sender "Morning Brew" → "M"; article titled "  how to" → "H"; untitled link → hostname's first letter; youtube → "▶"; a title starting with an emoji falls through to the next letter/digit. `sourceLabels.test.ts`: `kindLabel` table and `sourceMeta` for a newsletter ("Newsletter · Morning Brew").
- [ ] **Step 2: Implement** all primitives and the Library shell. Wrap the root `<Stack>`'s parent in `<GestureHandlerRootView style={{ flex: 1 }}>` in `_layout.tsx`.
- [ ] **Step 3: Run** `cd app && npm run typecheck && npx jest` — pass. Start Metro is not needed; a typecheck is the bar here.
- [ ] **Step 4: Commit** "App: artwork tiles, rows, sheets (finish, snooze, menu, topic chooser), haptics, Library shell".

## Parallel-safe tasks

Every task below depends only on Tasks 1–4 and can run at the same time as the others in its own worktree (`git gtr new m4-t<N> --from-current --yes`) with its own test database `archie_test_t<N>`. Several touch the same files (`sync/actions.py`'s `HANDLERS`, `handlers/__init__.py`'s `HANDLERS`, `analyze.py`, `_layout.tsx`, `main.py`) only additively; the merges are textual.

### Task 5: API reading-state actions, and newsletter cards after Go deeper  (tier: standard)

**Files:**
- Create: `services/api/archie_api/sync/source_actions.py`, `services/api/tests/e2e/test_source_actions_e2e.py`
- Modify: `services/api/archie_api/sync/actions.py` (`HANDLERS` entries), `services/worker/archie_worker/handlers/analyze.py` (card rule), `services/worker/tests/test_analyze_primer_e2e.py`

**Interfaces:**
- Consumes: Task 1 (`changes.touch`, models), Task 2 (`rows.*`, `HANDLERS`).
- Produces: `source_actions.finish_source`, `set_prep_me`, `set_read`, `set_primer_opened`, `snooze`, `set_queue_position`, `go_deeper`, `read_later`, `delete_source` (all `ActionHandler`s) registered under their `ActionType`s; `source_actions.PrimerTarget(StrEnum)`: `SOURCE="source"`, `TOPIC_PRIMER="topic_primer"`.
- Depends on: Tasks 1–4.
- Review: yes (state machine).

Rules (reject with the quoted reason; validate before writing):

| Action | Allowed when | Writes |
|---|---|---|
| `finish_source` | owned source, `state == queued` ("source is not queued") | `state=consumed`, `snoozed_until=None`; `reaction` if given; `note` if given (≤ 2,000 chars, `capture.MAX_NOTE_LENGTH`); `prep_me=True` when reaction is `lost` |
| `set_prep_me` | queued | `prep_me` |
| `set_read` | `kind == newsletter` ("source is not a newsletter") and `state in (inbox, briefed)` ("source is not in the inbox") | `read_at = now()` or None |
| `set_primer_opened` | owned source, or owned topic primer ("topic primer not found") | `primer_opened_at` / `opened_at` = `now()` or None |
| `snooze` | owned source or topic primer | `snoozed_until = until`; a queued source snoozed to a time also gets `queue_position = top` |
| `set_queue_position` | queued; `position` finite | `queue_position` |
| `go_deeper` | `state in (inbox, briefed)` and `processing == ready` ("source is not ready") | `state=consumed`, `read_at` if unset, processing `processing`, enqueue `[ANALYZE, PRIMER]` |
| `read_later` | `state in (inbox, briefed)` | `state=queued`, `queue_position=top`, `snoozed_until=None` |
| `delete_source` | owned source | `deleted_at=now()`; its live cards soft-deleted with fresh positions |

```python
"""Reading-state actions on a source (and on topic primers for opened/snoozed): each returns the rejection reason or None.

The caller holds the user's write lock; every check runs before the first write (see `actions.apply_actions`).
"""

from __future__ import annotations

import uuid
from enum import StrEnum

import pydantic
import sqlalchemy
from archie_db import changes, models, pipeline
from sqlalchemy import orm

from archie_api.sync import capture, rows

_NOT_QUEUED = "source is not queued"
_NOT_IN_INBOX = "source is not in the inbox"
_NOT_NEWSLETTER = "source is not a newsletter"
_NOT_READY = "source is not ready"
_NO_PRIMER = "topic primer not found"
_INBOX_STATES = frozenset({models.SourceState.INBOX, models.SourceState.BRIEFED})


class PrimerTarget(StrEnum):
    """What a primer-opened or snooze action points at."""

    SOURCE = "source"
    TOPIC_PRIMER = "topic_primer"


class _SourcePayload(pydantic.BaseModel):
    id: uuid.UUID


class _FinishPayload(_SourcePayload):
    reaction: models.Reaction | None = None
    note: str | None = pydantic.Field(default=None, max_length=capture.MAX_NOTE_LENGTH)


class _PrepMePayload(_SourcePayload):
    prep_me: bool


class _ReadPayload(_SourcePayload):
    read: bool


class _PrimerOpenedPayload(_SourcePayload):
    target: PrimerTarget
    opened: bool


class _SnoozePayload(_SourcePayload):
    target: PrimerTarget
    until: pydantic.AwareDatetime | None


class _QueuePositionPayload(_SourcePayload):
    position: float = pydantic.Field(allow_inf_nan=False)


def finish_source(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Mark a queued source consumed, with the optional reaction and note; "Parts lost me" also pushes its primer."""
    parsed = rows.parse(_FinishPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.state != models.SourceState.QUEUED:
        return _NOT_QUEUED

    source.state = models.SourceState.CONSUMED.value
    source.snoozed_until = None
    if parsed.reaction is not None:
        source.reaction = parsed.reaction.value
    if parsed.note:
        source.note = parsed.note
    if parsed.reaction == models.Reaction.LOST:
        source.prep_me = True
    changes.touch(source)
    return None


def snooze(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Hide a source or topic primer until `until` (None unsnoozes); a snoozed queued source returns at the top."""
    parsed = rows.parse(_SnoozePayload, payload)
    if parsed is None:
        return rows.MALFORMED

    if parsed.target == PrimerTarget.TOPIC_PRIMER:
        primer = rows.owned_topic_primer(db, user=user, primer_id=parsed.id)
        if primer is None:
            return _NO_PRIMER
        primer.snoozed_until = parsed.until
        primer.change_seq = changes.next_change_seq()
        return None

    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if parsed.until is not None and source.state == models.SourceState.QUEUED:
        source.queue_position = rows.top_queue_position(db, user_id=user.id)
    source.snoozed_until = parsed.until
    changes.touch(source)
    return None


def go_deeper(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Consume an inbox item for real: write its primer and re-analyze it, which now gives it cards."""
    parsed = rows.parse(_SourcePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.state not in _INBOX_STATES:
        return _NOT_IN_INBOX
    if source.processing != models.ProcessingStatus.READY:
        return _NOT_READY

    source.state = models.SourceState.CONSUMED.value
    source.read_at = source.read_at or sqlalchemy.func.now()
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.ANALYZE, models.JobKind.PRIMER])
    return None


def delete_source(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Soft-delete a source and its cards, so phones drop both."""
    parsed = rows.parse(_SourcePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE

    source.deleted_at = sqlalchemy.func.now()
    changes.touch(source)
    db.execute(
        sqlalchemy.update(models.Card)
        .where(models.Card.source_id == source.id, models.Card.deleted_at.is_(None))
        .values(deleted_at=sqlalchemy.func.now(), updated_at=sqlalchemy.func.now(), change_seq=changes.next_change_seq())
    )
    return None
```

`set_prep_me`, `set_read`, `set_primer_opened`, `set_queue_position`, `read_later` follow the same shape (parse → owned row → state guard from the table → write → `changes.touch` / primer `change_seq`). Register all nine in `actions.HANDLERS`.

Analyze card rule (`analyze.py`), replacing the newsletter line:

```python
    # A newsletter gets cards only once the user went deeper (it is then consumed); other sources always may.
    wants_cards = run.kind != models.SourceKind.NEWSLETTER or source.state == models.SourceState.CONSUMED
    if analysis["is_educational"] and wants_cards:
        _insert_cards(db, source=source, artifact_id=summary.id, cards=analysis["cards"])
```

- [ ] **Step 1: E2e** `test_source_actions_e2e.py` (`postgres`; helpers `_push`, `_pull_sources` like `test_sync_e2e.py`; rows the API can't reach — a READY newsletter in `inbox`, a topic primer — are inserted with their own session under `changes.lock_user_writes`): for each action, the applied case (pulled row shows the change, `change_seq` grew), a repeated action id → `duplicate` and no second change, another user's id → rejected `source not found`, and the state-guard rejection from the table. Also: finish with `lost` → `prep_me` True; snooze of a queued source → its `queue_position` is below every other queued source's; `snooze` with `until: null` clears it; `snooze` with a naive datetime → `payload is malformed`; `set_queue_position` with `"Infinity"` → malformed; `go_deeper` on a READY inbox newsletter → state consumed, processing `processing`, jobs `analyze` then `primer` queued; on a `processing` one → `source is not ready`; `read_later` → queued at the top; `delete_source` → pulled with `deleted_at`, its card pulled with `deleted_at`; topic-primer `set_primer_opened`/`snooze` apply to the primer row and pull back.
- [ ] **Step 2: Worker test** in `test_analyze_primer_e2e.py`: `test_a_newsletter_analyzed_after_going_deeper_gets_cards` — a newsletter source in state `consumed` replays `analyze_greatwork` → 3–5 cards. The existing inbox-newsletter test still gets none.
- [ ] **Step 3: Run** — fail. **Implement.** Run the suite against `archie_test_t5` and `make lint` — pass.
- [ ] **Step 4: Commit** "Sync: finish, prep, read, primer opened, snooze, queue order, go deeper, read later, delete".

### Task 6: API topic actions, the picker's submit and `GET /topics/starter`  (tier: standard)

**Files:**
- Create: `services/api/archie_api/sync/topic_actions.py`, `services/api/archie_api/topics/__init__.py`, `services/api/archie_api/topics/routes.py`, `services/api/tests/e2e/test_topic_actions_e2e.py`
- Modify: `services/api/archie_api/sync/actions.py` (`HANDLERS`), `services/api/archie_api/main.py` (mount the router)

**Interfaces:**
- Consumes: Task 1 (`user_topics.*`, `topics.is_starter_topic`, `Domain`), Task 2 (`rows.*`).
- Produces: `topic_actions.add_topic`, `rename_topic`, `merge_topic`, `remove_topic`, `restore_topic`, `set_source_topic`, `request_topic_primer`, `choose_topics` registered in `HANDLERS`; `GET /topics/starter`; `topic_actions.MAX_CHOSEN_TOPICS = 200`.
- Depends on: Tasks 1–4.
- Review: yes (state machine, uniqueness).

| Action | Rejected when (reason) | Writes |
|---|---|---|
| `add_topic` | domain not a `Domain` value ("domain is not one of Archie's domains"); name empty ("topic name is empty") or > 80 ("topic name is longer than 80 characters"); a live topic normalizes the same ("a topic with this name already exists"); a removed one does ("a removed topic has this name; restore it instead"); the id exists ("id already exists") | `user` topic with the phone's id; `enqueue_topic_primer` |
| `rename_topic` | topic missing/merged/removed ("topic not found"); the name checks above, ignoring the topic itself | `name`, `touch` |
| `merge_topic` | either missing/removed/merged, or the same topic ("can't merge a topic into itself") | sources of A → `topic_id=B`, `domain=B.domain`, each touched; A `merged_into_id=B`, touched |
| `remove_topic` | missing/removed ("topic not found") | `removed_at=now()`; its live sources `topic_id=None` (domain kept), touched, and one `file_topic` each |
| `restore_topic` | missing, or not removed ("topic is not removed") | `removed_at=None`, touched |
| `set_source_topic` | source missing; topic missing/removed | `topic_id`, `domain = topic.domain`, touched |
| `request_topic_primer` | topic missing/removed; a current primer exists ("topic already has a primer"); a queued or running `topic_primer` job for it ("a primer is already being written") | `enqueue_topic_primer` |
| `choose_topics` | `topics_chosen_at` set ("topics already chosen"); empty list ("choose at least one topic"); any entry failing the `add_topic` checks, including two entries that normalize the same | each topic created (`origin = starter` when `is_starter_topic`, else `user`, which also gets `enqueue_topic_primer`); `topics_chosen_at = now()`; `enqueue_file_topic` for every `analyzed_sources` row |

```python
"""Topic actions: add, rename, merge, remove (which re-files), restore, file a source by hand, ask for a primer, and
submit the picker. Each returns the rejection reason or None; the caller holds the user's write lock and every check
runs before the first write."""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import changes, models, user_topics
from archie_shared import topics
from archie_shared.domains import Domain
from sqlalchemy import orm

from archie_api.sync import rows

MAX_CHOSEN_TOPICS = 200

_BAD_DOMAIN = "domain is not one of Archie's domains"
_EMPTY_NAME = "topic name is empty"
_LONG_NAME = f"topic name is longer than {user_topics.MAX_TOPIC_NAME_LENGTH} characters"
_NAME_TAKEN = "a topic with this name already exists"
_NAME_REMOVED = "a removed topic has this name; restore it instead"
_ID_EXISTS = "id already exists"


class _TopicPayload(pydantic.BaseModel):
    id: uuid.UUID


class _AddTopicPayload(_TopicPayload):
    domain: str
    name: str


class _RenameTopicPayload(_TopicPayload):
    name: str


class _MergeTopicPayload(_TopicPayload):
    into_id: uuid.UUID


class _SetSourceTopicPayload(pydantic.BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID


class _ChooseTopicsPayload(pydantic.BaseModel):
    topics: list[_AddTopicPayload] = pydantic.Field(max_length=MAX_CHOSEN_TOPICS)


def add_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Add a topic the user wants to understand, and queue its primer."""
    parsed = rows.parse(_AddTopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    reason = _new_topic_reason(db, user=user, domain=parsed.domain, name=parsed.name)
    if reason is not None:
        return reason
    if db.get(models.Topic, parsed.id) is not None:
        return _ID_EXISTS

    topic = user_topics.create_topic(
        db,
        user_id=user.id,
        domain=Domain(parsed.domain),
        name=parsed.name,
        origin=models.TopicOrigin.USER,
        topic_id=parsed.id,
    )
    user_topics.enqueue_topic_primer(db, topic=topic)
    return None


def remove_topic(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Block a topic: its sources lose it now and are filed again, with this topic among the removed."""
    parsed = rows.parse(_TopicPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    topic = rows.owned_topic(db, user=user, topic_id=parsed.id)
    if topic is None or topic.removed_at is not None:
        return rows.NO_TOPIC

    topic.removed_at = sqlalchemy.func.now()
    changes.touch(topic)
    for source in _sources_of(db, topic=topic):
        source.topic_id = None
        changes.touch(source)
        user_topics.enqueue_file_topic(db, source=source)
    return None


def choose_topics(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Submit the picker: create the chosen topics, mark topics chosen, and file every analyzed source."""
    parsed = rows.parse(_ChooseTopicsPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    if user.topics_chosen_at is not None:
        return "topics already chosen"
    if not parsed.topics:
        return "choose at least one topic"
    reason = _chosen_topics_reason(db, user=user, chosen=parsed.topics)
    if reason is not None:
        return reason

    for chosen in parsed.topics:
        domain = Domain(chosen.domain)
        is_starter = topics.is_starter_topic(domain=domain, name=chosen.name)
        topic = user_topics.create_topic(
            db,
            user_id=user.id,
            domain=domain,
            name=chosen.name,
            origin=models.TopicOrigin.STARTER if is_starter else models.TopicOrigin.USER,
            topic_id=chosen.id,
        )
        if not is_starter:
            user_topics.enqueue_topic_primer(db, topic=topic)

    user.topics_chosen_at = sqlalchemy.func.now()
    for source in user_topics.analyzed_sources(db, user_id=user.id):
        user_topics.enqueue_file_topic(db, source=source)
    return None


def _new_topic_reason(
    db: orm.Session, *, user: models.User, domain: str, name: str, ignore_id: uuid.UUID | None = None
) -> str | None:
    """Why a topic with this domain and name can't be added (or a topic renamed to it), or None."""
    if domain not in set(Domain):
        return _BAD_DOMAIN
    return _name_reason(db, user=user, name=name, ignore_id=ignore_id)


def _name_reason(db: orm.Session, *, user: models.User, name: str, ignore_id: uuid.UUID | None) -> str | None:
    cleaned = user_topics.clean_name(name)
    if not cleaned:
        return _EMPTY_NAME
    if len(cleaned) > user_topics.MAX_TOPIC_NAME_LENGTH:
        return _LONG_NAME

    existing = user_topics.named_topic(db, user_id=user.id, name=cleaned)
    if existing is None or existing.id == ignore_id:
        return None
    return _NAME_REMOVED if existing.removed_at is not None else _NAME_TAKEN


def _chosen_topics_reason(db: orm.Session, *, user: models.User, chosen: list[_AddTopicPayload]) -> str | None:
    """The first reason any chosen topic can't be created, counting clashes among the chosen ones themselves."""
    seen: set[str] = set()
    for entry in chosen:
        reason = _new_topic_reason(db, user=user, domain=entry.domain, name=entry.name)
        if reason is not None:
            return reason
        if db.get(models.Topic, entry.id) is not None:
            return _ID_EXISTS

        key = topics.normalize_topic_name(entry.name)
        if key in seen:
            return _NAME_TAKEN
        seen.add(key)
    return None


def _sources_of(db: orm.Session, *, topic: models.Topic) -> list[models.Source]:
    return list(
        db.scalars(
            sqlalchemy.select(models.Source).where(
                models.Source.topic_id == topic.id, models.Source.deleted_at.is_(None)
            )
        )
    )
```

`rename_topic`, `merge_topic`, `restore_topic`, `set_source_topic`, `request_topic_primer` follow the table in the same shape. `request_topic_primer`'s job check:

```python
    writing = db.scalar(
        sqlalchemy.select(sqlalchemy.exists().where(
            models.Job.kind == models.JobKind.TOPIC_PRIMER.value,
            models.Job.status.in_([models.JobStatus.QUEUED.value, models.JobStatus.RUNNING.value]),
            models.Job.payload[user_topics.TOPIC_ID_KEY].astext == str(topic.id),
        ))
    )
```

and the current-primer check is `db.scalar(sqlalchemy.select(sqlalchemy.exists().where(models.TopicPrimer.topic_id == topic.id, models.TopicPrimer.is_current)))`.

`topics/routes.py`:

```python
"""The starter topic list the picker offers."""

router = fastapi.APIRouter(prefix="/topics", tags=["topics"])


class StarterDomainView(pydantic.BaseModel):
    """One domain's starter topics, in display order."""

    domain: str
    topics: list[str]


class StarterTopicsView(pydantic.BaseModel):
    """Every domain with starter topics, in domain order."""

    domains: list[StarterDomainView]


@router.get("/starter")
def starter_topics(_user: Annotated[models.User, fastapi.Depends(deps.current_user)]) -> StarterTopicsView:
    """The picker's list; signed-in users only."""
    return StarterTopicsView(
        domains=[
            StarterDomainView(domain=domain.value, topics=list(names))
            for domain, names in topics.STARTER_TOPICS.items()
        ]
    )
```

- [ ] **Step 1: E2e** `test_topic_actions_e2e.py` (`postgres`; insert sources/topics/summaries directly where the API can't reach; pull to check what phones see; `_queued_jobs` helper): every row of the table, applied and rejected; idempotent repeat (same action id → duplicate, one row); another user's topic → `topic not found`; `add_topic` with "FED and monetary-policy" when "Fed & monetary policy" is live → taken, and when it's removed → the restore reason; `add_topic` enqueues one `topic_primer` job with `{"topic_id": ...}`; `merge_topic` moves two sources (domain follows) and the merged name can be re-added afterwards; `remove_topic` clears `topic_id` on its sources (domain kept) and enqueues one `file_topic` per live source (none for a deleted one); `restore_topic` then works and re-files nothing; `request_topic_primer` twice → the second is rejected as being written; with a current primer → rejected; `choose_topics` with one starter name ("Inflation", origin `starter`, no primer job) and one own name ("Robotics", origin `user`, a primer job) → `/me` says `topics_chosen` True, two analyzed sources get `file_topic` jobs and an unanalyzed one doesn't; a second `choose_topics` → "topics already chosen"; a list with "Inflation" twice → taken and nothing created; `GET /topics/starter` lists 12 domains, Finance ending with "Personal finance & taxes", "Insurance", and 401 without a session.
- [ ] **Step 2: Run** — fail. **Implement**, mount the router in `main.create_app`. Run the suite against `archie_test_t6` and `make lint` — pass.
- [ ] **Step 3: Commit** "Sync: topic actions (add, rename, merge, remove with re-filing, restore, set, primer request) and the picker".

### Task 7: Worker `file_topic`, its prompt, and `archie-refile-sources`  (tier: most capable)

**Files:**
- Create: `services/worker/archie_worker/handlers/file_topic.py`, `services/worker/archie_worker/refile.py`, `services/worker/tests/test_file_topic_e2e.py`, cassettes `services/worker/tests/cassettes/file_topic_{reuse,new,removed,newsletter}.yaml`
- Modify: `services/worker/archie_worker/prompts.py`, `services/worker/archie_worker/llm.py`, `services/worker/archie_worker/handlers/__init__.py`, `services/worker/archie_worker/handlers/analyze.py`, `services/worker/pyproject.toml` (script), `services/worker/tests/test_analyze_primer_e2e.py`

**Interfaces:**
- Consumes: Task 1 (`user_topics.*`, `Domain`, `parse_domain`, `JobKind.FILE_TOPIC`, `NewsletterKind`).
- Produces: `llm.FILE_TOPIC_MODELS`; `prompts.FILE_TOPIC_SYSTEM`, `prompts.FILE_TOPIC_SCHEMA`, `prompts.file_topic_message(...)`; `file_topic.FilingDecision`, `file_topic.parse_decision(raw: Mapping[str, Any], *, is_newsletter: bool) -> FilingDecision`, `file_topic.apply_filing(db, *, source: models.Source, decision: FilingDecision) -> None`, `file_topic.handle`; `HANDLERS[JobKind.FILE_TOPIC] = HandlerSpec(run=file_topic.handle)` (no failure hook: filing never fails a source); `refile.refile_all(db) -> int`, `refile.main()`, script `archie-refile-sources = "archie_worker.refile:main"`.
- Depends on: Tasks 1–4.
- Review: yes (the guard is what keeps the topic list clean).

`prompts.py` additions:

```python
FILE_TOPIC_SYSTEM = """You file sources for a personal learning app into the user's own list of topics. Each topic \
sits under one domain.

Rules:
- Reuse one of the user's topics whenever one fits, even loosely. Copy its name exactly and set is_new to false.
- Only when none of them fits, propose a new topic and set is_new to true. Make it short (2-5 words) and reusable for \
many future sources, in the style of the user's topics. Never propose a near-duplicate of an existing or removed topic \
(no rewording, plural, abbreviation or synonym of one).
- Never propose a removed topic or anything close to one: the user removed those on purpose. If the only fit is a \
removed topic, reuse a broader existing topic or propose a different one.
- domain: the domain of the topic you chose (an existing topic's own domain when you reuse one).
- newsletter_kind: for a newsletter only, otherwise null. "news" is a digest of several short items; "essay" is one \
piece of writing worth reading whole.

The analysis hints (domain, topic, tags) come from an earlier step with a different domain list; treat them as hints."""

FILE_TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "enum": [domain.value for domain in Domain]},
        "topic": {"type": "string"},
        "is_new": {"type": "boolean"},
        "newsletter_kind": {
            "anyOf": [{"type": "string", "enum": [kind.value for kind in models.NewsletterKind]}, {"type": "null"}]
        },
    },
    "required": ["domain", "topic", "is_new", "newsletter_kind"],
    "additionalProperties": False,
}

_MAX_FILING_KEY_IDEAS = 8


def file_topic_message(
    *,
    kind: models.SourceKind,
    title: str | None,
    analysis: Mapping[str, Any],
    live_topics: Sequence[str],
    removed_topics: Sequence[str],
) -> str:
    """The source's summary and hints, then the user's topics as `domain › name` lines and the removed names."""
    summary = analysis["summary"]
    key_ideas = "\n".join(f"- {item['idea']}" for item in summary["key_ideas"][:_MAX_FILING_KEY_IDEAS])
    hints = f"domain {analysis['domain']}, topic {analysis['topic']}, tags {', '.join(analysis['tags'])}"
    live = "\n".join(f"- {line}" for line in live_topics) or "- (none yet)"
    removed = "\n".join(f"- {name}" for name in removed_topics) or "- (none)"
    return (
        f"Source kind: {kind.value}\nTitle: {title or '(none)'}\nAnalysis hints: {hints}\n\n"
        f"Gist: {summary['gist']}\nKey ideas:\n{key_ideas}\n\n"
        f"The user's topics (domain › name):\n{live}\n\nRemoved topics (never propose these or anything close):\n{removed}"
    )
```

`llm.py`: `FILE_TOPIC_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)`.

`handlers/file_topic.py`:

```python
"""`file_topic`: decide a source's domain and topic from its summary, reusing the user's topics wherever one fits.

The model proposes; the server guard decides. A name matching a live topic (case and punctuation aside) files the
source there; one matching a removed topic leaves it without a topic (domain kept); anything else becomes a new
`archie` topic. Filing never blocks a source from being ready, so this step has no failure hook.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, user_topics
from archie_shared import domains
from archie_shared.domains import Domain

from archie_worker import llm, prompts

MAX_OUTPUT_TOKENS = 400


@dataclass(frozen=True)
class FilingDecision:
    """What the model proposed for one source, already cleaned."""

    domain: Domain
    topic: str
    newsletter_kind: models.NewsletterKind | None


@dataclass(frozen=True)
class _FilingRun:
    """What the model call needs, copied out so no ORM object is held across it."""

    source_id: uuid.UUID
    user_id: int
    is_newsletter: bool
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """File the job's source under a domain and topic, creating an `archie` topic only when nothing fits."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.FILE_TOPIC_MODELS,
        system=prompts.FILE_TOPIC_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.FILE_TOPIC_SCHEMA,
    )
    decision = parse_decision(json.loads(completion.text), is_newsletter=run.is_newsletter)

    changes.lock_user_writes(db, run.user_id)
    source = db.get_one(models.Source, run.source_id)
    db.refresh(source)
    if source.deleted_at is not None:
        return
    apply_filing(db, source=source, decision=decision)


def parse_decision(raw: Mapping[str, Any], *, is_newsletter: bool) -> FilingDecision:
    """The model's answer, cleaned: an unknown domain becomes Other, the name is trimmed to the topic length cap."""
    kind = raw.get("newsletter_kind")
    return FilingDecision(
        domain=domains.parse_domain(str(raw["domain"])),
        topic=user_topics.clean_name(str(raw["topic"]))[: user_topics.MAX_TOPIC_NAME_LENGTH],
        newsletter_kind=models.NewsletterKind(kind) if is_newsletter and kind in set(models.NewsletterKind) else None,
    )


def apply_filing(db: sqlalchemy.orm.Session, *, source: models.Source, decision: FilingDecision) -> None:
    """Write the decision through the server guard; the caller holds the user's write lock."""
    existing = user_topics.named_topic(db, user_id=source.user_id, name=decision.topic) if decision.topic else None
    if existing is not None and existing.removed_at is None:
        source.topic_id = existing.id
        source.domain = existing.domain
    elif existing is not None or not decision.topic:
        # A removed topic is the user's "not this": keep the domain, file under no topic.
        source.topic_id = None
        source.domain = decision.domain.value
    else:
        created = user_topics.create_topic(
            db,
            user_id=source.user_id,
            domain=decision.domain,
            name=decision.topic,
            origin=models.TopicOrigin.ARCHIE,
        )
        source.topic_id = created.id
        source.domain = created.domain

    if decision.newsletter_kind is not None:
        source.newsletter_kind = decision.newsletter_kind.value
    changes.touch(source)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _FilingRun | None:
    """Read the source, its summary and the user's topics, then commit; None when there is nothing to file."""
    source = db.get(models.Source, uuid.UUID(job.payload[pipeline.SOURCE_ID_KEY]))
    if source is None or source.deleted_at is not None:
        return None
    user = db.get_one(models.User, source.user_id)
    if user.topics_chosen_at is None:
        return None
    summary = pipeline.current_artifact(db, source_id=source.id, kind=models.ArtifactKind.SUMMARY)
    if summary is None:
        return None

    # Checked before reading topics so a user without a key fails at once (PermanentJobError, no hook).
    api_key = llm.api_key_for(user)
    kind = models.SourceKind(source.kind)
    run = _FilingRun(
        source_id=source.id,
        user_id=source.user_id,
        is_newsletter=kind == models.SourceKind.NEWSLETTER,
        context=llm.CallContext(
            user_id=source.user_id, source_id=source.id, job_id=job.id, step=models.JobKind.FILE_TOPIC
        ),
        api_key=api_key,
        user_message=prompts.file_topic_message(
            kind=kind,
            title=source.title,
            analysis=summary.content,
            live_topics=[f"{topic.domain} › {topic.name}" for topic in user_topics.live_topics(db, user_id=user.id)],
            removed_topics=[topic.name for topic in user_topics.removed_topics(db, user_id=user.id)],
        ),
    )
    db.commit()
    return run
```

`analyze.handle`, after `pipeline.finish_step(...)`:

```python
    # File each source once, after its first summary; a re-analysis never overrides a topic the user chose.
    user = db.get_one(models.User, source.user_id)
    if source.domain is None and user.topics_chosen_at is not None:
        user_topics.enqueue_file_topic(db, source=source)
```

`refile.py`:

```python
"""`archie-refile-sources`: queue `file_topic` for every live, analyzed source of every user who has chosen topics.

Run once after deploying M4, after the owner opened the app (which seeds their topics); see docs/deploy.md.
Re-running only files sources again.
"""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session, user_topics
from archie_shared import config, logging

_logger = logging.get_logger(logging.LoggerName.WORKER, "refile")


def main() -> None:
    """Queue the filing jobs against `DATABASE_URL` and report how many."""
    logging.configure()
    engine = session.engine_for(config.get_settings().require_database_url())
    with sqlalchemy.orm.Session(engine) as db:
        count = refile_all(db)
        db.commit()
    _logger.info("Queued file_topic for %d sources", count)


def refile_all(db: sqlalchemy.orm.Session) -> int:
    """Queue one `file_topic` per analyzed live source of each user with topics, in the caller's transaction."""
    user_ids = db.scalars(sqlalchemy.select(models.User.id).where(models.User.topics_chosen_at.is_not(None))).all()
    queued = 0
    for user_id in user_ids:
        changes.lock_user_writes(db, user_id)
        for source in user_topics.analyzed_sources(db, user_id=user_id):
            user_topics.enqueue_file_topic(db, source=source)
            queued += 1
    return queued
```

Tests build their own rows (a user with `topics_chosen_at` set, topics via `user_topics.create_topic`, a source with a `summary` artifact whose content is a full analysis dict — `{"summary": {"gist", "key_ideas": [{"timestamp": None, "idea": ...}], "numbers": []}, "domain", "topic", "tags", "concepts", "is_educational", "cards": []}` written by the test, not a model response).

- [ ] **Step 1: Deterministic DB tests** in `test_file_topic_e2e.py` (`postgres`, no cassette) on `apply_filing` with hand-made `FilingDecision`s: "fed and monetary-policy" → the live "Fed & monetary policy" topic, and the source's domain becomes that topic's; a name normalizing to a removed topic → `topic_id` None, domain = the decision's; a new name → one new `archie` topic in the decision's domain; an empty name → no topic; `newsletter_kind` written for a newsletter decision. `parse_decision`: domain `"Tech"` → `Other`; `newsletter_kind` ignored for a non-newsletter; an 120-character name is cut to 80.
- [ ] **Step 2: Recorded e2e** (`replay` fixture as in `test_analyze_primer_e2e.py`, `recording.use_recording_api_key` autouse), each running one `file_topic` job through `loop.run_one`:
  - `file_topic_reuse`: the summary of "How to Do Great Work" (gist and 3 key ideas you write from `fixtures/greatwork.txt`); live topics = `OWNER_TOPICS` plus a user topic "Careers & doing great work" (Startups) → the source's `topic_id` is one of the user's existing topics (assert no topic was created) and the `llm_calls` row is step `file_topic`, model Haiku, `cost_usd < Decimal("0.001")`.
  - `file_topic_new`: the same summary; the user's only topics are Sports ones ("NFL play schemes", "Quarterbacks") → a new `archie` topic exists and the source points at it.
  - `file_topic_removed`: the same summary; live topics Sports only; removed "Careers & doing great work" and "Founder lessons" → the source's topic, if any, does not normalize to either removed name (the guard holds whatever the model said).
  - `file_topic_newsletter`: a `newsletter` source whose summary you write from the Morning Brew fixture's subject and three stories (`services/api/tests/fixtures/newsletters/morning_brew.eml`) with the owner's topics → `newsletter_kind == "news"`.
  - Plus (no cassette): a non-whitelisted user's job fails with `NEEDS_API_KEY` and the source's `processing` is unchanged; a user without `topics_chosen_at` → the job is done with no `llm_calls`; analyze for a user with chosen topics queues `file_topic` after its own job, and analyze of an already-filed source does not (extend `test_analyze_primer_e2e.py` with two tests replaying `analyze_greatwork`).
  - `refile_all`: two users (one with topics, one without), three sources (analyzed, analyzed but deleted, unanalyzed) → returns 1 and queues one job.
- [ ] **Step 3: Record** the four cassettes (`--record-mode=once`; about a tenth of a cent each), run the cassette checks.
- [ ] **Step 4: Implement**; register the handler; add the script; `uv sync`. Run the suite against `archie_test_t7` and `make lint` — pass.
- [ ] **Step 5: Commit** "Worker: file_topic with a server guard against near-duplicate and removed topics; archie-refile-sources".

### Task 8: Worker `topic_primer`  (tier: standard)

**Files:**
- Create: `services/worker/archie_worker/handlers/topic_primer.py`, `services/worker/tests/test_topic_primer_e2e.py`, cassette `services/worker/tests/cassettes/topic_primer_fed.yaml`
- Modify: `services/worker/archie_worker/prompts.py`, `services/worker/archie_worker/llm.py` (`CallContext.source_id: uuid.UUID | None`), `services/worker/archie_worker/handlers/__init__.py`

**Interfaces:**
- Consumes: Task 1 (`models.TopicPrimer`, `user_topics.TOPIC_ID_KEY`, `JobKind.TOPIC_PRIMER`).
- Produces: `prompts.TOPIC_PRIMER_PROMPT_VERSION = "topic-primer-v1"`, `prompts.TOPIC_PRIMER_SYSTEM`, `prompts.topic_primer_message(*, domain: str, topic: str, source_titles: Sequence[str]) -> str`; `topic_primer.handle`, `topic_primer.write_topic_primer(db, *, topic: models.Topic, markdown: str, model: str) -> models.TopicPrimer`; `HANDLERS[JobKind.TOPIC_PRIMER] = HandlerSpec(run=topic_primer.handle)`.
- Depends on: Tasks 1–4.
- Review: no.

```python
TOPIC_PRIMER_PROMPT_VERSION = "topic-primer-v1"

TOPIC_PRIMER_SYSTEM = f"""You write topic primers for a personal learning app. A topic primer gives the general \
background on one topic (for example "How the Fed works" for the topic "Fed & monetary policy"): the core concepts, \
how the machinery works, the key players, a little history, the rough numbers worth knowing, and the live debates. \
It is about the topic, not about any one source.

The user lists the titles of their own sources on the topic. Use them only to decide what to emphasize, never as \
material to summarize. Write for a smart beginner: friendly, no assumed jargon, a 5-8 minute read (roughly 900-1400 \
words). Use markdown with short sections and a title.

{READING_VOICE}"""


def topic_primer_message(*, domain: str, topic: str, source_titles: Sequence[str]) -> str:
    """The topic and its domain, then the user's source titles on it (for emphasis only)."""
    titles = "\n".join(f"- {title}" for title in source_titles) or "- (none yet)"
    return f"Domain: {domain}\nTopic: {topic}\n\nThe user's sources on this topic (for emphasis only):\n{titles}"
```

```python
"""`topic_primer`: write the general background for one of the user's topics, as markdown.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
A removed or merged topic, or one that already has a primer, gets nothing.
"""

MAX_OUTPUT_TOKENS = 6000
MAX_SOURCE_TITLES = 30


@dataclass(frozen=True)
class _PrimerRun:
    """What the model call needs, copied out of the session."""

    topic_id: uuid.UUID
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Write the topic's primer with the primer models and store it as its current version."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.PRIMER_MODELS,
        system=prompts.TOPIC_PRIMER_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
    )

    changes.lock_user_writes(db, run.user_id)
    topic = db.get_one(models.Topic, run.topic_id)
    db.refresh(topic)
    if topic.removed_at is not None or topic.merged_into_id is not None:
        return
    write_topic_primer(db, topic=topic, markdown=completion.text, model=completion.model)


def write_topic_primer(
    db: sqlalchemy.orm.Session, *, topic: models.Topic, markdown: str, model: str
) -> models.TopicPrimer:
    """Add the next version as current; the previous current one stays, no longer current. Caller holds the lock."""
    previous = db.scalars(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == topic.id, models.TopicPrimer.is_current
        )
    ).one_or_none()
    if previous is not None:
        # Flushed first so the partial unique index never sees two current rows.
        previous.is_current = False
        previous.change_seq = changes.next_change_seq()
        db.flush()

    latest_version = db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(models.TopicPrimer.version)).where(
            models.TopicPrimer.topic_id == topic.id
        )
    )
    primer = models.TopicPrimer(
        id=uuid.uuid4(),
        user_id=topic.user_id,
        topic_id=topic.id,
        version=(latest_version or 0) + 1,
        is_current=True,
        content={"markdown": markdown},
        model=model,
        prompt_version=prompts.TOPIC_PRIMER_PROMPT_VERSION,
        change_seq=changes.next_change_seq(),
    )
    db.add(primer)
    db.flush()
    return primer
```

`_prepare`: load the topic from `job.payload[user_topics.TOPIC_ID_KEY]`; None if missing, removed, merged, or it already has a current primer; `api_key = llm.api_key_for(user)`; titles = the user's live sources in that topic with a title, newest first, at most `MAX_SOURCE_TITLES`; `CallContext(user_id=..., source_id=None, job_id=job.id, step=models.JobKind.TOPIC_PRIMER)`; commit; return the run.

- [ ] **Step 1: Tests** `test_topic_primer_e2e.py` (`postgres`): record `topic_primer_fed` — a whitelisted user, a `user` topic "Fed & monetary policy" (Macro) with two titled sources in it → one current primer v1, markdown non-empty and starting with `#`, model Sonnet, `prompt_version == "topic-primer-v1"`, one `llm_calls` row with step `topic_primer` and `source_id` NULL. No cassette: a removed topic → job done, no primer, no call; a topic with a current primer → nothing written; `write_topic_primer` twice → v2 current, v1 not current, both with new positions.
- [ ] **Step 2: Run** — fail. **Implement**, record (a couple of cents), cassette checks. Run the suite against `archie_test_t8` and `make lint` — pass.
- [ ] **Step 3: Commit** "Worker: topic primers".

### Task 9: Artwork for YouTube, articles, links and X  (tier: cheap)

**Files:**
- Modify: `services/worker/archie_worker/handlers/fetch_title.py`, `services/worker/archie_worker/content/article.py`, `services/worker/archie_worker/content/x.py`, `services/worker/archie_worker/content/youtube.py`, `services/worker/archie_worker/handlers/fetch_content.py`, `services/worker/tests/test_fetch_title.py`, `services/worker/tests/test_worker_e2e.py`, `services/worker/tests/test_fetch_content_e2e.py`, `services/worker/tests/test_youtube_e2e.py`
- Create: cassette `services/worker/tests/cassettes/article_og_image.yaml`

**Interfaces:**
- Consumes: Task 1 (`ExtractedText.image_url`, `_text.store_text(image_url=...)`, `Source.image_url`).
- Produces: `fetch_title.extract_image(*, page: str, base_url: str) -> str | None`; `youtube.thumbnail_url(video_id: str) -> str`.
- Depends on: Tasks 1–4.
- Review: no.

- `_TitleParser` also records the first `og:image` meta `content`. `extract_image` returns it made absolute with `urllib.parse.urljoin(base_url, raw.strip())`, only when the result's scheme is `http`/`https`, NUL stripped, ≤ 2,048 characters; else None.
- `fetch_title.handle`: compute title and image from the page; return when both are None; under the lock write the title (as now) and the image when the source has none; one `change_seq` bump.
- `article.extract`: `ExtractedText(title=..., text=..., image_url=fetch_title.extract_image(page=html, base_url=url))`.
- `x.thread_text`: `image_url=shared_post["author"].get("avatar_url")` (the app draws X artwork as a circle).
- `youtube.thumbnail_url(video_id) = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"`; `fetch_content._fetch_youtube` passes `image_url=youtube.thumbnail_url(video_id)` to `store_text`.
- `fetch_content.handle`'s capture/article/X branch passes `image_url=extracted.image_url`.

- [ ] **Step 1: Unit tests** (`test_fetch_title.py`): relative `og:image` `/img/a.png` on `https://site.example/post/1` → `https://site.example/img/a.png`; protocol-relative `//cdn.example/a.png` → `https://cdn.example/a.png`; `javascript:alert(1)` → None; no og:image → None.
- [ ] **Step 2: E2e on existing cassettes:** `og_page` → `image_url == "https://ogp.me/logo.png"` (`test_worker_e2e.py`); `x_thread_sama` → the avatar URL from `fixtures/fxtwitter_thread_sama.json`; `youtube_powell` → `https://i.ytimg.com/vi/e0gVE3YxZs8/hqdefault.jpg`; `article_greatwork` (no og:image) → `image_url` None.
- [ ] **Step 3: Record** `article_og_image.yaml` in `test_fetch_content_e2e.py`: an article whose page has an `og:image` and ≥ 50 words of text; use `https://blog.bytebytego.com/p/how-netflix-uses-ai-agents-for-performance` after checking its HTML has `og:image` (`curl -s <url> | grep -o 'og:image" content="[^"]*'`; pick another public article if not) → `image_url` is that absolute URL. No API keys involved; cassette check.
- [ ] **Step 4: Implement.** Run the suite against `archie_test_t9` and `make lint` — pass.
- [ ] **Step 5: Commit** "Worker: artwork from og:image, YouTube thumbnails and X avatars".

### Task 10: Podcasts: artwork, the episode list, and `choose_episode`  (tier: standard)

**Files:**
- Create: `services/api/archie_api/sync/episodes.py`, `services/api/tests/e2e/test_episodes_e2e.py`, cassettes `services/api/tests/e2e/cassettes/episodes_darknet.yaml`, `services/worker/tests/cassettes/podcast_apple_chosen_episode.yaml`
- Modify: `packages/archie-shared/archie_shared/podcast_feed.py`, `services/worker/archie_worker/content/podcast.py`, `services/worker/archie_worker/handlers/fetch_content.py`, `services/api/archie_api/sources/routes.py`, `services/api/archie_api/sync/actions.py` (`HANDLERS`), `services/worker/tests/test_podcast.py`, `services/worker/tests/test_podcast_e2e.py`

**Interfaces:**
- Consumes: Task 1 (`podcast_feed`, `PodcastEpisode.image_url`, `Source.episode_guid`), Task 2 (`sources.routes.router`, `rows.*`).
- Produces:
  - `podcast_feed.FeedItem.image_url: str | None` (the item's `itunes:image@href`, else the channel's `itunes:image@href`, else the channel's `<image><url>`).
  - `podcast.resolve(engine, *, link: urls.PodcastLink, episode_guid: str | None = None) -> ResolvedEpisode` — with a guid, the item is chosen by `podcast_feed.item_by_guid` (Spotify: in the registered/searched feed; Apple: instead of Lookup's `episodeGuid`); not found → `EPISODE_NOT_FOUND`.
  - `ResolvedEpisode.episode.image_url` = item image, else iTunes `artworkUrl600` (from the Search hit or the Lookup show result).
  - `GET /sources/{source_id}/episodes` (shape in Global Constraints); `sources.routes.EPISODE_WINDOW_DAYS = 30`; `sources.routes.episodes_near(*, items: Sequence[podcast_feed.FeedItem], current_guid: str | None, fallback_date: datetime.date) -> list[EpisodeView]`.
  - `episodes.choose_episode` registered under `ActionType.CHOOSE_EPISODE`.
- Depends on: Tasks 1–4.
- Review: yes (destructive re-run of a source's outputs).

`choose_episode` (rejections: `rows.NO_SOURCE`; "source is not a podcast"; processing `pending`/`processing` → "source is still processing"; `guid` 1–1,024 characters else malformed):

```python
def choose_episode(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Replace the matched episode: retire the source's text, summary, primer and cards, drop its transcript chunks,
    and fetch again with the chosen feed guid."""
    parsed = rows.parse(_ChooseEpisodePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if source.kind != models.SourceKind.PODCAST:
        return _NOT_PODCAST
    if source.processing in _BUSY:
        return _STILL_PROCESSING

    _retire_outputs(db, source=source)
    db.execute(sqlalchemy.delete(models.TranscriptChunk).where(models.TranscriptChunk.source_id == source.id))
    # Cleared so the new episode's title and artwork replace them (the pipeline only fills empty ones).
    source.episode_guid = parsed.guid
    source.title = None
    source.image_url = None
    pipeline.set_processing(db, source=source, status=models.ProcessingStatus.PROCESSING)
    pipeline.enqueue_steps(db, source=source, steps=[models.JobKind.FETCH_CONTENT])
    return None


def _retire_outputs(db: orm.Session, *, source: models.Source) -> None:
    """Make the current text, summary and primer non-current and soft-delete the cards, each with a new position."""
    for kind in (models.ArtifactKind.TEXT, models.ArtifactKind.SUMMARY, models.ArtifactKind.PRIMER):
        artifact = pipeline.current_artifact(db, source_id=source.id, kind=kind)
        if artifact is not None:
            artifact.is_current = False
            artifact.change_seq = changes.next_change_seq()
    db.execute(
        sqlalchemy.update(models.Card)
        .where(models.Card.source_id == source.id, models.Card.deleted_at.is_(None))
        .values(deleted_at=sqlalchemy.func.now(), updated_at=sqlalchemy.func.now(), change_seq=changes.next_change_seq())
    )
```

`fetch_content`: `_SourceInput.episode_guid: str | None` read in `_start_processing`; `_fetch_podcast` calls `podcast.resolve(engine, link=link, episode_guid=source_input.episode_guid)` and passes `image_url=resolved.episode.image_url` to `store_text`.

Episode list route (sync `def`; read, commit, then fetch):

```python
@router.get("/{source_id}/episodes")
def episodes(
    source_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> EpisodesView:
    """The show's episodes within 30 days of the matched one, newest first, for "Wrong episode?"."""
    resolved = _resolved_episode(db, user=user, source_id=source_id)
    # Nothing is held open while the feed downloads.
    db.commit()
    try:
        items = podcast_feed.parse_feed(podcast_feed.fetch_feed(resolved.feed_url))
    except (httpx.HTTPError, TimeoutError, xml.etree.ElementTree.ParseError, ValueError) as error:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_502_BAD_GATEWAY, detail="couldn't read the feed") from error
    return EpisodesView(
        episodes=episodes_near(items=items, current_guid=resolved.guid, fallback_date=resolved.saved_on)
    )
```

`_resolved_episode` returns a frozen dataclass `(feed_url: str, guid: str | None, saved_on: datetime.date)` from the source's current `text` artifact's `content[podcast_feed.EPISODE_KEY]`; 404 when the source is missing/another user's/deleted/not a podcast or has no resolved episode. `episodes_near`: centre = the current item's `published` (by guid), else `fallback_date` (the source's `created_at` date); keep items with a guid and a `published` within ±30 days; newest first; `is_current = item.guid == current_guid`.

- [ ] **Step 1: Unit tests** (`test_podcast.py`, fixture feed `darknet_diaries_feed.xml`): every parsed item has an `image_url`; an item without its own `itunes:image` falls back to the channel's (build a small feed string in the test from a copy of the fixture's channel with one item's `itunes:image` removed — our own input). `episodes_near` on the fixture's items: centred on a middle item's guid, every result within 30 days, newest first, exactly one `is_current`; unknown guid → centred on `fallback_date`.
- [ ] **Step 2: Worker e2e** (`test_podcast_e2e.py`): the existing `podcast_apple_transcript` and `podcast_spotify_resolve` tests also assert `image_url` is an `https://` URL on the source (transcript path) and on the queued `transcribe` payload's episode (Spotify path). Record `podcast_apple_chosen_episode`: the same Apple link as `podcast_apple_transcript`, source `episode_guid` = the guid of the item right after the matched one in that cassette's recorded feed body → the stored text artifact's `episode.guid` is the chosen guid. A chosen guid that isn't in the feed → `EPISODE_NOT_FOUND`, no request beyond the feed (replay the same cassette).
- [ ] **Step 3: API e2e** `test_episodes_e2e.py` (`postgres`): rows inserted directly — a podcast source with a `text` artifact whose content has `episode: {feed_url: "https://podcast.darknetdiaries.com", guid: <a guid from the live feed at record time>, …}`; record `episodes_darknet.yaml` (one feed download; check `du -h` < 5 MB) → 200, the chosen guid present with `is_current`, all within ±30 days, newest first. Another user → 404; an article → 404; a podcast without text → 404. `choose_episode`: applied → current text/summary/primer pulled with `is_current` False, cards pulled deleted, `transcript_chunks` gone, processing `processing`, title None, one `fetch_content` job, `episode_guid` stored; rejected for an article, for a `processing` source, for another user's; a repeat action id → duplicate.
- [ ] **Step 4: Implement.** Run the suite against `archie_test_t10` and `make lint` — pass; cassette checks.
- [ ] **Step 5: Commit** "Podcasts: artwork, nearby-episode list and choose_episode".

### Task 11: App Today  (tier: standard)

**Files:**
- Modify: `app/src/app/(tabs)/today.tsx`
- Create: `app/src/today/todayLabels.ts`, `app/src/today/todayLabels.test.ts`, `maestro/today_primer.yaml`

**Interfaces:**
- Consumes: Task 3 (`useLibraryData`, `primersReady`, `upNext`, `waitingNewsletters`, `setPrepMe`), Task 4 (`GroupedList`, `ItemRow`, `SourceRow`, `ArtworkTile`, `haptic`, `useNow`).
- Produces: `todayLabels.todayDate(now: Date): string` ("Wed · Nov 4"); `todayLabels.sinceLabel(since: string, now: Date): string` ("since Mon" within 6 days, else "since Nov 1"); `todayLabels.newslettersLine(count: number): string` ("1 newsletter waiting for your brief" / "6 newsletters waiting for your brief"). Routes it links to: `/source/[id]?primer=1`, `/topic/[id]?primer=1` (Tasks 13–14 read `primer=1`), `/(tabs)/library?filter=queued|inbox` (Task 4 shell reads `filter`), `/settings/removed-topics` (Task 13).
- Depends on: Tasks 1–4.
- Review: no.

Screen (`Screen title="Today"`, `headerRight` = a row of the mono date `todayDate(now)` (testID `today-date`) and the existing `account-button`):
- **Primers ready** (`GroupedList title="Primers ready" testID="today-primers"`, hidden when empty): one `ItemRow` per `primersReady(data, now)` item, testID `primer-ready-<index>`, artwork monogram `PRIMER_MONOGRAM` in the domain colour with `unread` true; source item: kicker `{domain: source.domain, suffix: "Background"}`, title `source.title ?? source.url`, meta "You asked to prep this" (or "You said parts lost you" when `reaction === "lost"`), press → `router.push({ pathname: "/source/[id]", params: { id, primer: "1" } })`; topic item: kicker `{domain: topic.domain, suffix: "Topic primer"}`, title `topic.name`, meta "You added this topic", press → `/topic/[id]` with `primer: "1"`.
- **Up next** (`GroupedList title="Up next" right=<"See all N ›" testID="today-see-all">`, hidden when empty): first 3 of `upNext(data.sources, now)` as `SourceRow`s, testID `up-next-<index>`, `end` = a chip `prep-<index>` labelled "Prep me" / "Prepping" (filled when on) → `setPrepMe(db, id, !on)`, `haptic("selection")`, `requestSync()`. "See all" → `router.push("/(tabs)/library?filter=queued")`.
- **Newsletters** (hidden when `count === 0`): one `ItemRow` testID `today-newsletters`, monogram "✉", kicker `{domain: "Finance", label: "Inbox"}` (the mock's colour), title `newslettersLine(count)`, meta `` `${senders.join(", ")} · ${sinceLabel(since, now)}` ``, `end` "›", press → `/(tabs)/library?filter=inbox`.
- **Empty Today** (all three hidden): one line, testID `today-empty`: "Nothing waiting. Tap ＋ to add a link, or share one to Archie."
- **Account sheet** keeps its newsletter address and Sign out, and adds a secondary Button "Removed topics" (testID `removed-topics-link`) → `router.push("/settings/removed-topics")`.

- [ ] **Step 1: Unit tests** `todayLabels.test.ts` (TZ America/New_York): `todayDate(new Date(2026, 10, 4, 9))` → "Wed · Nov 4"; `sinceLabel` two days back → "since Mon", ten days back → "since Oct 25"; `newslettersLine(1)` and `(6)`.
- [ ] **Step 2: Implement** the screen.
- [ ] **Step 3: Maestro flow** `maestro/today_primer.yaml` (header comment: needs the owner's keys, costs a few cents, local backend only): `runFlow: login.yaml` → `openLink: archie://dev/login?whitelisted=1` (+ the optional "Open" tap, as `source_page.yaml`) → wait "Library" → `tab-add` (with the swallowed-tap guard) → `add-url` → `inputText: "https://paulgraham.com/hwh.html"` → tap "Paste a link to save it." (dismiss keyboard) → `intent-queue` → `prep-me` → `add-save` → `tapOn: id: "tab-today"` → one `extendedWaitUntil: visible: id: "primer-ready-0"`, `timeout: 240000` → `assertVisible: id: "primer-ready-0-art-unread"` → `tapOn: id: "primer-ready-0"` → `assertVisible: "▾ Background you might need"` → `tapOn: id: "screen-back"` → `assertNotVisible: id: "primer-ready-0"` (opened primers leave Primers ready, so the dot is gone) → `assertVisible: id: "up-next-0"`.
- [ ] **Step 4: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 5: Commit** "App: Today with primers ready, up next and waiting newsletters".

### Task 12: App Library list: filters, queue reordering, snoozed, search, swipe actions  (tier: most capable)

**Files:**
- Modify: `app/src/library/LibraryList.tsx`
- Create: `app/src/library/queue.ts`, `app/src/library/queue.test.ts`, `app/src/library/search.ts`, `app/src/library/search.test.ts`, `app/src/library/sections.ts`, `app/src/library/sections.test.ts`, `app/src/library/ReorderableQueue.tsx`, `app/src/library/SwipeRow.tsx`, `maestro/library_queue.yaml`, `maestro/library_search.yaml`

**Interfaces:**
- Consumes: Task 3 (`LibraryData`, `queueOrder`, `isSnoozed`, `statusTag`, `setQueuePosition`, `setRead`, `setPrimerOpened`, `deleteSource`, `formatReturnTime`), Task 4 (`SourceRow`, `ItemRow`, `StatusTagView`, `GroupedList`, `FinishSheet`, `SnoozeSheet`, `haptic`, `useNow`, the `LibraryList` props `{ data, query, initialFilter? }`).
- Produces:
  - `queue.positionBetween(above: number | null, below: number | null): number` (both null → 0; no above → `below − 1`; no below → `above + 1`; else the midpoint); `queue.positionAfterMove(positions: number[], from: number, to: number): number` (the moved item's new position given the list's positions in order).
  - `search.searchText(source: LibrarySource): string` (lower-cased title, sender, domain, topic name, gist, key ideas joined by newlines); `search.matchesQuery(text: string, query: string): boolean` (every whitespace-separated term of the lower-cased query appears; empty query → true).
  - `sections.LibraryFilter = "all" | "queued" | "done" | "inbox" | "primers"`; `sections.LibraryEntry = { kind: "source"; source: LibrarySource } | { kind: "topicPrimer"; primer: TopicPrimerRow; topic: TopicRow }`; `sections.filterEntries(data: LibraryData, filter: LibraryFilter): LibraryEntry[]` (Decision 12); `sections.filterCounts(data, now): Record<LibraryFilter, number>` (visible, i.e. not snoozed); `sections.byWeek(entries: LibraryEntry[], now: Date): { thisWeek: LibraryEntry[]; earlier: LibraryEntry[]; snoozed: LibraryEntry[] }` (created in the last 7 days / older / snoozed, newest first within each).
- Depends on: Tasks 1–4.
- Review: no.

Layout (`LibraryList`):
- Filter chips row (horizontal `ScrollView`): `filter-all`, `filter-queued`, `filter-done`, `filter-inbox`, `filter-primers`, each label + count (`filter-count-<filter>`, not shown for All); selected chip is chrome-filled; `haptic("selection")`. Initial filter from `initialFilter` when it is a `LibraryFilter`.
- With a non-empty `query`: no chips; entries = all non-deleted sources where `matchesQuery(searchText(source), query)`, newest first, as `SourceRow`s; none → text "No matches for “<query>”" (testID `library-search-empty`).
- **Queued**: `GroupedList title="Your queue · drag to reorder"` with `ReorderableQueue` over the visible queued sources in `queueOrder`, then `GroupedList title={`Snoozed · ${n}`}` (testID `library-snoozed`) whose rows end with the mono return time `formatReturnTime(new Date(snoozedUntil), now)`.
- **Other filters**: `byWeek` → "This week", "Earlier", "Snoozed · N" sections (each hidden when empty). Topic primer entries render as `ItemRow` (monogram ◆, kicker `{domain: topic.domain, suffix: "Topic primer"}`, title `topic.name`, meta "Primer", end `StatusTagView tag="Primer"`, press → `/topic/[id]`). Source rows end with `StatusTagView tag={statusTag(source)}` (testID `status-<id>`) and keep the "⚠ Not synced" marker (`source-error-<id>`) and `ProcessingLine`.
- Empty filter: "Nothing here yet. Paste a link in ＋." (testID `library-empty`).

`SwipeRow` (`ReanimatedSwipeable` from `react-native-gesture-handler/ReanimatedSwipeable`, `renderRightActions` returning 1–2 72-px buttons; closes after an action; `haptic("light")` on open): actions per entry —
- queued source: "Snooze" (opens `SnoozeSheet target="source"`), "Finished" (opens `FinishSheet`);
- newsletter in inbox/briefed: "Snooze", "Mark read" / "Mark unread" (`setRead(db, id, !readAt)`);
- a primer entry (topic primer, or a source shown under the Primers filter): "Snooze" (`target` "topic_primer" or "source"), "Mark read"/"Mark unread" (`setPrimerOpened(db, target, id, !opened)`);
- consumed source (Done): "Delete" (`deleteSource`, `haptic("success")`);
- anything else: no swipe.
Button testIDs `swipe-snooze-<id>`, `swipe-finish-<id>`, `swipe-read-<id>`, `swipe-delete-<id>`; every action ends with `requestSync()`.

`ReorderableQueue` props `{ sources: LibrarySource[]; renderRow: (source: LibrarySource, index: number) => ReactNode }`: each row is `SwipeRow`-wrapped and has a `≡` handle (testID `queue-handle-<index>`; the row itself `queue-row-<index>`). Rows have a fixed height (`QUEUE_ROW_HEIGHT = 76`). A `Gesture.Pan()` on the handle drives a reanimated `translateY` for the dragged row (raised with a shadow, `zIndex` 1) and, on `onEnd`, computes `to = clamp(from + Math.round(translationY / QUEUE_ROW_HEIGHT), 0, n − 1)`; when `to !== from` it calls (via `runOnJS`) `onMove(from, to)`:

```ts
function onMove(from: number, to: number): void {
  const positions = sources.map((source, index) => source.queuePosition ?? index);
  setQueuePosition(db, sources[from].id, positionAfterMove(positions, from, to));
  haptic("light");
  requestSync();
}
```

`queue.ts`:

```ts
export function positionBetween(above: number | null, below: number | null): number {
  if (above === null && below === null) return 0;
  if (above === null) return below! - 1;
  if (below === null) return above + 1;
  return (above + below) / 2;
}

/** The moved item's new position: the midpoint of its new neighbours once it is taken out of the list. */
export function positionAfterMove(positions: number[], from: number, to: number): number {
  const rest = positions.filter((_, index) => index !== from);
  return positionBetween(to > 0 ? rest[to - 1] : null, to < rest.length ? rest[to] : null);
}
```

- [ ] **Step 1: Unit tests**: `queue.test.ts` (move first to last, last to first, middle down by one, the two-item swap, a single item, equal neighbours stay ordered); `search.test.ts` (matches title, sender, domain, topic name, gist and a key idea; case-insensitive; all terms required; empty query matches; URL alone doesn't match); `sections.test.ts` (each filter's membership per Decision 12, counts exclude snoozed, removed/merged topics' primers excluded, `byWeek` boundaries at exactly 7 days).
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Maestro flows** (free: the test user isn't whitelisted, so sources fail at analyze but keep their titles; header comment says so):
  - `maestro/library_queue.yaml`: `runFlow: login.yaml` → add `https://example.com/` (queue) then `https://example.org/` (queue) through `tab-add` (as `add_link.yaml`) → `tab-library` → `filter-queued` → `assertVisible: { text: ".*example\\.org.*", above: { text: ".*example\\.com.*" } }` (newest on top) → `swipe: { from: { id: "queue-handle-0" }, direction: DOWN, duration: 1500 }` → `assertVisible: { text: ".*example\\.com.*", above: { text: ".*example\\.org.*" } }` → `swipe: { from: { id: "queue-row-0" }, direction: LEFT }` → `tapOn: "Snooze"` → `tapOn: { id: "snooze-tomorrow" }` → `assertVisible: { id: "library-snoozed" }` → `assertVisible: "Snoozed · 1"`.
  - `maestro/library_search.yaml`: `runFlow: login.yaml` → add `https://example.com/` (queue) → wait for the title "Example Domain" in Library (`extendedWaitUntil`, 60 s) → `tapOn: { id: "library-search" }` → `inputText: "example domain"` → `assertVisible: ".*Example Domain.*"` → `eraseText` → `inputText: "zzqx nothing"` → `assertVisible: { id: "library-search-empty" }`.
- [ ] **Step 4: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 5: Commit** "App: Library filters, queue drag-to-reorder, snoozed, local search, swipe actions".

### Task 13: App Domains view, topic page, topic actions, Removed topics  (tier: standard)

**Files:**
- Modify: `app/src/library/DomainsView.tsx`, `app/src/app/_layout.tsx` (two `Stack.Screen`s inside the signed-in guard)
- Create: `app/src/library/domainStats.ts`, `app/src/library/domainStats.test.ts`, `app/src/topics/TopicMenu.tsx`, `app/src/topics/RenameTopicSheet.tsx`, `app/src/topics/AddTopicSheet.tsx`, `app/src/app/topic/[id].tsx`, `app/src/app/settings/removed-topics.tsx`, `maestro/topics.yaml`

**Interfaces:**
- Consumes: Task 3 (`addTopic`, `renameTopic`, `mergeTopic`, `removeTopic`, `restoreTopic`, `requestTopicPrimer`, `setPrimerOpened`, `topicNameError`, `slugify`, `DOMAINS`, `isLiveTopic`, `statusTag`), Task 4 (`MenuSheet`, `BottomSheet`, `TopicChooserSheet`, `SourceRow`, `GroupedList`, `Kicker`, `Screen onBack`, `haptic`, `Markdown`).
- Produces:
  - `domainStats.DomainCard = { domain: DomainName; count: number; done: number; queued: number; inbox: number; chips: { topic: TopicRow; count: number; own: boolean }[] }`; `domainStats.domainCards(data: LibraryData): DomainCard[]` — a card per domain with items or user-added live topics (Decision 12), by count desc then `DOMAINS` order; chips = live topics with items (count desc) then the user's own (`origin === "user"`) with none (`own: true`).
  - `TopicMenu` props `{ topic: TopicRow; visible: boolean; onClose: () => void; onRemoved?: () => void }` — `MenuSheet` with Rename (`topic-menu-rename` → `RenameTopicSheet`), Merge into… (`topic-menu-merge` → `TopicChooserSheet` excluding itself → `mergeTopic` then navigate to the target when on the topic page), Remove (`topic-menu-remove` → `removeTopic`, `haptic("success")`, `onRemoved?.()`); each ends with `requestSync()`.
  - Routes `/topic/[id]` (reads `primer=1`) and `/settings/removed-topics`.
- Depends on: Tasks 1–4.
- Review: no.

`DomainsView` (`testID="domains-view"`): a `Card` per `domainCards(data)` entry (testID `domain-<slugify(domain)>`): colour dot, name, count; a 6-px bar of three segments (done, queued, inbox widths as % of count; colours: domain colour at 100%, 60%, 30% opacity); chips (testID `topic-chip-<slugify(name)>`, label + count, outlined when `own`); tap → `router.push({ pathname: "/topic/[id]", params: { id } })` with `haptic("light")`; long press → `haptic("selection")` and `TopicMenu`. Below the cards: "＋ Add a topic you want to understand" (testID `add-topic`) → `AddTopicSheet`.

`AddTopicSheet`: domain chips (`add-topic-domain-<slug>`, `DOMAINS` minus Other first, Other last; one selected, default the first), `TextField` `add-topic-name`, inline error `topicNameError(name, topics)` under it (testID `add-topic-error`), Add `add-topic-save` (disabled while there's an error or no domain) → `addTopic(db, { domain, name })`, `haptic("success")`, `requestSync()`, close. `RenameTopicSheet`: `TextField` `topic-rename-input` prefilled, error via `topicNameError(name, topics, topic.id)`, Save `topic-rename-save` → `renameTopic`.

Topic page (`/topic/[id]`, `Screen onBack={router.back}` with `headerRight` ••• testID `topic-more` → `TopicMenu`):
- A merged topic (`mergedIntoId`) → `router.replace` to the winner.
- `Kicker {domain, suffix: "Topic"}`, the name (`articleTitle`, testID `topic-name`), counts "N items · D done · Q queued" (testID `topic-counts`).
- A removed topic shows "You removed this topic." and a Button "Restore" (`topic-restore`) instead of the primer section.
- Primer section: current topic primer → a toggle "Primer" (testID `topic-primer-toggle`) opening `Markdown`; opening (or `primer=1` on arrival) calls `setPrimerOpened(db, "topic_primer", primer.id, true)` once when `openedAt` is null, then `requestSync()`. No primer and `primerRequestedAt` within 10 minutes → "Writing a primer… ready in a minute or two." (testID `topic-primer-writing`); otherwise a card "Write a primer on this topic / The general background, about 6 minutes to read." (testID `topic-write-primer`) → `requestTopicPrimer`, `haptic("success")`, `requestSync()`.
- Items: the topic's non-deleted sources newest first as `SourceRow`s (meta `` `${kindLabel(kind)} · ${statusTag(source)}` ``).

Removed topics (`/settings/removed-topics`, `Screen title="Removed topics" onBack`): every topic with `removedAt` and no `mergedIntoId`, by name; row = name + domain kicker + Button "Restore" (testID `restore-<slugify(name)>`) → `restoreTopic`, `haptic("success")`, `requestSync()`. Empty → "No removed topics." (testID `removed-topics-empty`).

- [ ] **Step 1: Unit tests** `domainStats.test.ts`: counts and done/queued/inbox split; a domain with only a user topic appears with count 0 and that chip `own`; chips exclude removed and merged topics; ordering by count then domain order.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Maestro flow** `maestro/topics.yaml` (free; the topic's primer job fails without the owner's key, which is fine): `runFlow: login.yaml` → `tab-library` → `library-mode-domains` → `tapOn: { id: "add-topic" }` → `tapOn: { id: "add-topic-domain-macro" }` → `tapOn: { id: "add-topic-name" }` → `inputText: "Monetary plumbing"` → `tapOn: { id: "add-topic-save" }` → `assertVisible: { id: "topic-chip-monetary-plumbing" }` → `longPressOn: { id: "topic-chip-monetary-plumbing" }` → `tapOn: { id: "topic-menu-remove" }` → `assertNotVisible: { id: "topic-chip-monetary-plumbing" }` → `tapOn: { id: "tab-today" }` → `tapOn: { id: "account-button" }` → `tapOn: { id: "removed-topics-link" }` → `tapOn: { id: "restore-monetary-plumbing" }` → `assertNotVisible: { id: "restore-monetary-plumbing" }` (the owner's three removed starter topics stay listed, so the screen is never empty here) → `tapOn: { id: "screen-back" }` → `tapOn: { id: "tab-library" }` → `assertVisible: { id: "topic-chip-monetary-plumbing" }`.
- [ ] **Step 4: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 5: Commit** "App: Domains view, topic page and topic actions, Removed topics".

### Task 14: App item page, finish flow, full email, wrong episode  (tier: standard)

**Files:**
- Modify: `app/src/app/source/[id].tsx`
- Create: `app/src/item/ItemHeader.tsx`, `app/src/item/ItemActions.tsx`, `app/src/item/ItemMenu.tsx`, `app/src/item/FullEmailSheet.tsx`, `app/src/item/EpisodesSheet.tsx`, `app/src/item/timestampLink.ts`, `app/src/item/timestampLink.test.ts`, `maestro/finish_item.yaml`, `maestro/newsletter_1_login.yaml`, `maestro/newsletter_2_go_deeper.yaml`, `maestro/run_newsletter.sh`

**Interfaces:**
- Consumes: Task 3 (`setPrepMe`, `goDeeper`, `readLater`, `setRead`, `setPrimerOpened`, `setSourceTopic`, `deleteSource`, `chooseEpisode`, `asDomain`), Task 4 (`ArtworkTile`, `Kicker`, `FinishSheet`, `SnoozeSheet`, `MenuSheet`, `BottomSheet`, `TopicChooserSheet`, `Screen onBack`, `haptic`, `kindLabel`, `sourceByline`), the HTTP shapes of `GET /sources/{id}/text` and `/episodes` (Global Constraints).
- Produces: `timestampLink.timestampSeconds(timestamp: string): number | null` (`"12:14"` → 734, `"1:02:03"` → 3723, junk → null); `timestampLink.timestampUrl(source: { kind: string; url: string }, timestamp: string): string` (YouTube: the URL with `t=<seconds>` set via `URL.searchParams`; Spotify `open.spotify.com/episode/...`: with `t=<seconds>`; anything else: the URL unchanged).
- Depends on: Tasks 1–4.
- Review: no.

Page (keeps testIDs `source-gist`, `primer-toggle`, `timestamp`, the "Processing…" `ProcessingLine` and the "▾ Background you might need" text):
- `Screen title="" onBack={router.back}` with `headerRight` ••• (testID `item-more`). Merged tombstones still redirect as today.
- `ItemHeader`: `ArtworkTile size={92}` (circle for X); `Kicker {domain, suffix: kindLabel(kind)}`; by-line `sourceByline(source)`; a line "Saved <weekday> · <stateLabel>"; reaction chip (Easy/Mostly followed/Parts lost me) when set; topic chip (testID `item-topic-chip`) → `/topic/[id]`; `ProcessingLine`.
- Title (`articleTitle`, testID `item-title`).
- `ItemActions` by state: queued → Button "I finished it" (`item-finish`, opens `FinishSheet`) + chip "Prep me"/"✓ Prepping" (`item-prep`, `setPrepMe`, `haptic("selection")`); inbox/briefed → Button "Go deeper" (`item-go-deeper`, `goDeeper`, `haptic("success")`) + "Read later" (`item-read-later`, `readLater`); consumed → nothing. Each ends with `requestSync()`.
- Gist, Key ideas, Rough numbers as today; `TimestampChip` becomes a `Pressable` (testID stays `timestamp`) → `Linking.openURL(timestampUrl(source, timestamp))`, `haptic("light")`.
- "Background you might need" collapsed; opening it (or `primer=1` on arrival) calls `setPrimerOpened(db, "source", id, true)` once when `primerOpenedAt` is null, then `requestSync()`.
- "Your note": reaction + note (as today's `ReactionSection`).
- "Cards from this": only when `state === "consumed"`; otherwise the section is absent (the spec wins over the mock's "Cards are written when you finish it.").
- Newsletters: a row "Open the full email ›" (testID `item-full-email`) → `FullEmailSheet`: `apiFetch(`/sources/${id}/text`, { sessionKey })` → `Markdown` of the text inside a `ScrollView`; failure → "Needs a connection." (testID `full-email-offline`).
- `ItemMenu` (`MenuSheet`): Change topic (`menu-change-topic` → `TopicChooserSheet` → `setSourceTopic`), Snooze (`menu-snooze` → `SnoozeSheet target="source"`), for newsletters in inbox/briefed "Mark unread"/"Mark read" (`menu-read` → `setRead`), for podcasts "Wrong episode?" (`menu-episode` → `EpisodesSheet`), Delete (`menu-delete`, destructive → `deleteSource`, `haptic("success")`, `router.back()`).
- `EpisodesSheet`: on open `apiFetch(`/sources/${id}/episodes`, { sessionKey })`; rows `episode-<index>` with title, date, duration (`h:mm`), current one marked "Matched"; tap a non-current one → `chooseEpisode(db, id, guid)`, `haptic("success")`, `requestSync()`, close; loading spinner; failure → "Needs a connection." (testID `episodes-offline`).

- [ ] **Step 1: Unit tests** `timestampLink.test.ts`: the seconds cases; YouTube `https://www.youtube.com/watch?v=abc&t=5` + "1:02:03" → `t=3723` (replaced, `v` kept); `https://youtu.be/abc` + "00:10" → `t=10`; Spotify episode + "12:14" → `t=734`; Apple → unchanged; an unparseable timestamp → the URL unchanged.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Maestro flows:**
  - `maestro/finish_item.yaml` (free): `runFlow: login.yaml` → add `https://example.net/` (queue) → in Library `tapOn: ".*example\\.net.*"` → `tapOn: { id: "item-finish" }` → `tapOn: { id: "finish-mostly" }` → `tapOn: { id: "finish-save" }` → `assertNotVisible: { id: "item-finish" }` → `assertVisible: "Mostly followed"` → `tapOn: { id: "screen-back" }` → `tapOn: { id: "filter-done" }` → `assertVisible: ".*example\\.net.*"`.
  - Newsletter Go deeper (needs the owner's keys and `INGEST_SECRET` in the repo-root `.env`; a few cents): `maestro/newsletter_1_login.yaml` = `runFlow: login.yaml` → `openLink: archie://dev/login?whitelisted=1` (+ "Open") → wait "Library". `maestro/newsletter_2_go_deeper.yaml` = `tapOn: { id: "tab-library" }` → `tapOn: { id: "filter-inbox" }` → `extendedWaitUntil: { visible: ".*Putting it to a vote.*", timeout: 180000 }` → `tapOn: ".*Putting it to a vote.*"` → `extendedWaitUntil: { visible: { id: "item-go-deeper" }, timeout: 120000 }` (the summary must be ready first) → `tapOn: { id: "item-go-deeper" }` → `extendedWaitUntil: { visible: "Cards from this", timeout: 300000 }`. `maestro/run_newsletter.sh` (pattern of `run_offline.sh`, `set -euo pipefail`, run from the repo root with the backend already up via `make start-local`): fail with a message naming `INGEST_SECRET` if `grep -q '^INGEST_SECRET=' .env` fails; `maestro test maestro/newsletter_1_login.yaml`; `TOKEN=$(docker compose exec -T postgres psql -q -U archie archie -tAc "SELECT ingest_token FROM users WHERE apple_sub = 'test-user'" | tr -d '[:space:]')`; `SECRET=$(grep '^INGEST_SECRET=' .env | cut -d= -f2-)` (never echoed); `curl -fsS -X POST http://localhost:8000/ingest/email -H "content-type: message/rfc822" -H "x-ingest-secret: $SECRET" -H "x-ingest-to: $TOKEN@local.test" -H "x-ingest-from: crew@morningbrew.com" --data-binary @services/api/tests/fixtures/newsletters/morning_brew.eml >/dev/null`; `maestro test maestro/newsletter_2_go_deeper.yaml`. `chmod +x` it.
- [ ] **Step 4: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 5: Commit** "App: item page with state actions, finish sheet, full email and wrong-episode picker".

### Task 15: App topic picker and its gate  (tier: standard)

**Files:**
- Create: `app/src/app/topic-picker.tsx`, `app/src/topics/pickerState.ts`, `app/src/topics/pickerState.test.ts`, `maestro/topic_picker.yaml`
- Modify: `app/src/app/_layout.tsx`, `app/src/app/dev/login.tsx`

**Interfaces:**
- Consumes: Task 3 (`chooseTopics`, `ChosenTopic`, `slugify`, `topicNameError`, `DOMAINS`), Task 4 (`haptic`, `Screen`), `GET /topics/starter` and `/me.topics_chosen` (Global Constraints).
- Produces: `pickerState.togglePick(picked: ChosenTopic[], topic: ChosenTopic): ChosenTopic[]`; `pickerState.addOwn(picked: ChosenTopic[], domain: DomainName, name: string): { picked: ChosenTopic[]; error: string | null }` (rejects empty, > 80, or a name normalizing like an already picked one: "Already picked."); route `/topic-picker`.
- Depends on: Tasks 1–4.
- Review: no.

Gate (`_layout.tsx`). `RootLayout`'s hooks run before the local migrations finish, and the new `topics` table only exists after them, so move the `<SignOutContext.Provider>`/`<Stack>` part into a child component `AppStack` that `RootLayout` renders only once `migrations.success` (and fonts/session) are ready; the gate lives in `AppStack`:

```tsx
  const [topicsChosen, setTopicsChosen] = useState<boolean | null>(null);
  const { data: localTopics } = useLiveQuery(db.select({ id: schema.topics.id }).from(schema.topics).limit(1));

  // On launch (and after any sign-in), learn whether the picker is still owed; offline it simply isn't shown.
  useEffect(() => {
    if (session.status !== "signedIn") return;
    apiFetch("/me", { sessionKey: session.sessionKey })
      .then((me) => setTopicsChosen((me as { topics_chosen?: boolean }).topics_chosen !== false))
      .catch((error) => {
        if (error instanceof UnauthorizedError) void clearSession();
      });
  }, [session.status, session.sessionKey]);

  const needsPicker = session.status === "signedIn" && topicsChosen === false && localTopics.length === 0;
```

and the signed-in `Stack.Protected` splits into `guard={session.status === "signedIn" && !needsPicker}` (existing screens plus `topic/[id]` and `settings/removed-topics` if Task 13's lines are present — the merge is textual) and `guard={needsPicker}` holding `<Stack.Screen name="topic-picker" />`. Reset `topicsChosen` to null on sign-out.

Picker screen (`Screen title="Pick your topics"`): one line of copy ("Archie files what you save under these. Pick the ones you want to understand; you can change them any time."), then `fetch` `GET /topics/starter` (loading text; failure → "Needs a connection." + Button "Try again" `picker-retry`). Per domain: `Kicker`-styled domain name, chips for its starter topics (testID `pick-<slugify(domain)>-<slugify(name)>`, nothing selected initially; tap → `togglePick`, `haptic("selection")`), the user's own picks for that domain as filled chips, and "＋ Add your own" (`pick-add-<slug(domain)>`) revealing a `TextField` (`pick-add-<slug(domain)>-input`) + "Add" (`pick-add-<slug(domain)>-save`) with the `addOwn` error inline. Footer Button "Continue" (`picker-continue`, label "Continue · N", disabled at 0) → `chooseTopics(db, picked)`, `haptic("success")`, `requestSync()`; the gate opens because local topics now exist.

Dev login (`dev/login.tsx`): read `picker` and `sub` params; POST `/test/session` with `{ is_whitelisted: whitelisted === "1", seed_topics: picker !== "1", ...(sub ? { apple_sub: sub } : {}) }`.

- [ ] **Step 1: Unit tests** `pickerState.test.ts`: toggling adds then removes; `addOwn` adds an own topic with `origin: "user"`, rejects empty/too long/"inflation" when "Inflation" is picked.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Maestro flow** `maestro/topic_picker.yaml` (free): `launchApp: { clearState: true, clearKeychain: true }` → wait `apple-sign-in` → `openLink: archie://dev/login?picker=1&sub=picker-user` (+ "Open") → `extendedWaitUntil: { visible: { id: "pick-macro-inflation" }, timeout: 30000 }` → `assertVisible: "Continue · 0"` → `tapOn: { id: "pick-macro-inflation" }` → `scrollUntilVisible: { element: { id: "pick-crypto-bitcoin" } }` → `tapOn: { id: "pick-crypto-bitcoin" }` → `scrollUntilVisible: { element: { id: "pick-add-ai" } }` → `tapOn: { id: "pick-add-ai" }` → `tapOn: { id: "pick-add-ai-input" }` → `inputText: "Robotics"` → `tapOn: { id: "pick-add-ai-save" }` → `tapOn: { id: "picker-continue" }` → `extendedWaitUntil: { visible: { id: "tab-library" }, timeout: 15000 }` → `tapOn: { id: "tab-library" }` → `tapOn: { id: "library-mode-domains" }` → `assertVisible: { id: "topic-chip-robotics" }`.
- [ ] **Step 4: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 5: Commit** "App: topic picker on first sign-in".

## Integration task (serial, in `m4-library`, after Tasks 5–15 are merged)

### Task 16: Merge check, docs, full verification and the Maestro run  (tier: standard; Maestro steps by the coordinator)

**Files:**
- Modify: `Makefile` (`reset-local-data` truncation, Maestro targets), `maestro/README.md`, `docs/deploy.md`, `AGENTS.md` (commands), `docs/superpowers/specs/2026-11-04-m4-library-today-design.md` (status line)
- Review: no.

- [ ] **Step 1: Merge check.** `git log --oneline` shows Tasks 5–15 merged. `rg -n "NOT_SUPPORTED" services/api` shows only its definition and use (every `ActionType` has a handler: add a test in `test_library_sync_e2e.py` asserting `set(actions.HANDLERS) == set(schemas.ActionType)`). Resolve any leftover duplicate imports from the textual merges (`make lint`).
- [ ] **Step 2: Python and app suites:** `make lint`; `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test uv run pytest -m "postgres or not postgres"` — all pass with no network; `cd app && npm run typecheck && npx jest` — pass. `make scaffold` output unchanged or smaller.
- [ ] **Step 3: Makefile.** `reset-local-data` truncates `applied_actions, jobs, topic_primers, topics, sources, sessions, users`. `maestro` runs `add_link sign_out source_page library_queue library_search topics finish_item topic_picker today_primer` (the last spends a few cents like `source_page`); new target `maestro-newsletter: reset-local-data` runs `maestro/run_newsletter.sh`; add it to `.PHONY`.
- [ ] **Step 4: Docs.** `maestro/README.md`: a table row per new flow (what it proves), the `run_newsletter.sh` note (needs `INGEST_SECRET` and the owner's keys in `.env`, the backend up, a few cents), and that the picker flow signs in as `picker-user`. `docs/deploy.md` "Not in code" gains **M4 re-filing**: after the M4 deploy, open the app once as the owner (its `/me` seeds the owner's topics), then run `railway ssh --service archie -- uv run --no-sync archie-refile-sources` once; it queues `file_topic` for every analyzed source of users with topics (a fraction of a cent each). `AGENTS.md` Commands: `make maestro-newsletter`. Spec: add "**Status:** Implemented on `m4-library` (plan `docs/superpowers/plans/2026-11-04-m4-library-today.md`)."
- [ ] **Step 5: Commit** "M4: Maestro targets, deploy and flow docs".
- [ ] **Step 6 (coordinator, main checkout):** with `m4-library` checked out in the main checkout (or its changes pulled there), `make db-up`, `make migrate-local`, `make start-local` in one terminal; boot the iPhone 17 Pro simulator and `cd app && npx expo run:ios`; then `make maestro` and `make maestro-newsletter`. All flows pass. A failure caused by a real outside change (a page or feed moved) is reported, not papered over.
- [ ] **Step 7:** Stop the backend and Metro. `git status` clean apart from intended changes; `m4-library` ready for a PR (do not push or merge unless asked).

---

## Self-review notes

- Spec coverage: states/actions (T5), queue position (T2 add_source, T3 local, T5 snooze/read later, T12 reorder), snooze (T3 rules, T4 sheet, T5 server), read and primer opened (T5, T11, T13, T14), domains list and colours (T1, T3), topics table, starter/owner lists, picker and owner seeding (T1, T2, T6, T15), `file_topic` with guard and `newsletter_kind` (T7), topic actions incl. remove → re-file (T6), topic primers (T8, T13), artwork per kind (T9, T10), episode correction endpoint and `choose_episode` (T10, T14), pull of the new tables (T2, T3), `/me` `topics_chosen` (T2), migration 0004 + backfills + `archie-refile-sources` (T1, T7, T16), every screen (T11–T15), Maestro flows listed in the spec (finish T14, reorder/snooze T12, search T12, add/remove/restore topic T13, Today primer dot T11, newsletter Go deeper T14, picker T15), roadmap already updated.
- Haptics: selection on chips/toggles (T4, T11–T15), light on push/pop and swipe open (T4 rows, T12), success on Save/Finish and saves (T4 sheets, T13–T15).
