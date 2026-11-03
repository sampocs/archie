# Milestone 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the iPhone, the user can sign in with Apple, paste a link in ＋ (online or offline), and see it in Library with a title the backend worker fetched.

**Architecture:**
- A uv Python workspace at the repo root:
  - `packages/archie-shared` and `packages/archie-db`
  - `services/api` (FastAPI)
  - `services/worker`
- Postgres on Railway.
- An Expo app in `app/` with a local SQLite copy of the user's rows, kept in sync by an outbox of named actions (pushed) and a per-user change position (pulled).
- One Railway container runs migrations, then the API and the worker.

**Tech Stack:**
- **Backend:** Python 3.13, uv, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, PyJWT, httpx, pytest, pytest-recording (vcrpy), Docker Postgres 16 + pgvector.
- **App:** Expo (latest stable SDK), expo-router, expo-sqlite + drizzle-orm, expo-apple-authentication, expo-secure-store, jest.
- **Phone e2e:** Maestro.

**Spec:** `docs/superpowers/specs/2026-11-02-m1-foundation-design.md`. Read it before any task. It is the source of truth for behavior; this plan is the order and the shapes.

## Global Constraints

- **Python style:** the user's house style, which AGENTS.md (written in Task 1) condenses:
  - module-qualified imports
  - full typing with `X | None`
  - `StrEnum` instead of magic strings
  - dataclasses instead of tuples of more than two elements
  - named parameters when a call has more than one argument
  - guard clauses
  - blank-line paragraphs in any function longer than ~8 lines
  - why-comments only
- **Tests:** e2e first. A unit test only for logic that could plausibly be wrong. Never a test that restates a constant or checks wiring. Recorded real responses for outside calls, never hand-made mocks of their bodies.
- **Bundle id:** `com.sampocs.archie`. **URL scheme:** `archie`. **Apple audience:** `com.sampocs.archie`.
- **Sync limits:** at most 50 actions per push, at most 500 rows per pull page.
- **Jobs:** `max_attempts` = 3. Backoff of 10 s, 60 s and 300 s. A `running` job older than 600 s is stale. The worker polls every 2 s when idle.
- **`fetch_title`:** 10 s timeout, 1 MB body limit, `og:title` first, then `<title>`.
- **URLs:** http(s) only, 2,048 characters at most.
- **Sessions:** a 32-byte random key, sent as `Authorization: Bearer <key>`. Only its SHA-256 hex is stored. `last_used_at` is updated at most once per hour.
- **`ARCHIE_ENV`:** `prod`, `dev` or `test`. `POST /test/session` and the app's `archie://dev/login` exist only outside prod and release builds.
- **Env vars:** `DATABASE_URL`, `OWNER_EMAILS` (comma-separated), `APPLE_AUDIENCE`, `ARCHIE_ENV`, `TEST_DATABASE_URL` (tests only).
- **Secrets:** never print secrets or `.env` values. Check keys by variable name only.
- **Commits:** every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MN7nukQAsqfkk3GiAq6NkX
  ```
- **Branch:** all work happens on `m1-foundation`.

---

## File Structure

```
pyproject.toml  Makefile  docker-compose.yml  conftest.py  Dockerfile  .env.example  AGENTS.md  CLAUDE.md
.github/workflows/python.yaml
packages/archie-shared/archie_shared/{config.py, logging.py}
packages/archie-db/archie_db/
  session.py            engine creation + URL normalize
  models.py             User, Session, Source, AppliedAction, Job + StrEnums
  migrate.py            upgrade/downgrade CLI (archie-db)
  migrations/{env.py, script.py.mako, versions/0001_initial.py}
  changes.py            lock_user_writes(), next_change_seq()
  jobs.py               enqueue()
  tests/test_db_migrations.py
services/api/archie_api/
  main.py               create_app(), /health, router wiring
  deps.py               get_db(), current_user()
  auth/sessions.py      create_session(), resolve_session(), revoke_session()
  auth/apple.py         verify_identity_token()
  auth/routes.py        POST /auth/apple, POST /auth/logout
  sync/actions.py       apply_actions()
  sync/pull.py          pull_changes()
  sync/routes.py        POST /sync/push, GET /sync/pull
  sync/schemas.py
  test_routes.py        POST /test/session (non-prod only)
  launch.py             archie-launch: migrate, then run api + worker
services/api/tests/
  e2e/harness.py        LiveStack fixture: real uvicorn + real worker thread on test Postgres
  e2e/test_auth_e2e.py  e2e/test_sync_e2e.py  e2e/test_main_path_e2e.py
  test_apple.py
services/worker/archie_worker/
  main.py               archie-worker entry: run_forever()
  loop.py               claim_next(), run_one(), requeue_stale()
  handlers/fetch_title.py
services/worker/tests/{test_worker_e2e.py, cassettes/}
app/                    Expo project
  app.config.ts  package.json  drizzle.config.ts  babel.config.js  metro.config.js  jest.config.js
  src/app/_layout.tsx  sign-in.tsx  dev/login.tsx  (tabs)/{_layout,today,library,add,review,ask}.tsx
  src/theme/{tokens.ts, type.ts, components/*.tsx}
  src/db/{schema.ts, client.ts, actions.ts}  drizzle/ (generated migrations)
  src/api/client.ts
  src/auth/session.ts
  src/sync/{engine.ts, engine.test.ts, transport.ts, useSync.ts}
maestro/{add_link.yaml, sign_out.yaml, offline.yaml, run_offline.sh}
```

---

## Foundation tasks (run serially)

### Task 1: Scaffold the workspace with `/scaffold`

**Files:**
- Create: everything the scaffold skill writes. Root config files, `packages/archie-shared`, `packages/archie-db`, `services/api`, `services/worker`, `AGENTS.md`, `CLAUDE.md`.

**Interfaces:**
- Produces:
  - `archie_shared.config.get_settings() -> Settings`, with fields `database_url: str | None`, `owner_emails: str | None`, `apple_audience: str | None`, `archie_env: str | None`, plus the methods:
    - `require_database_url() -> str`
    - `owner_email_set() -> frozenset[str]`, lower-cased and trimmed
    - `env() -> ArchieEnv`, a `StrEnum` of `prod`, `dev` and `test`, defaulting to `dev`
  - `archie_shared.logging.configure()`
  - `archie_db.session.engine_for(url) -> sqlalchemy.Engine` and `normalize_url(url) -> str`
  - `archie_db.migrate.upgrade(url)` and `downgrade(url)`, with console script `archie-db`
  - root `conftest.py` with the `postgres` marker, `test_database_url` and `migrated_database_url` fixtures, and network/credential isolation
  - `archie_api.main.create_app() -> fastapi.FastAPI`, plus `app = create_app()`, with `GET /health`
  - Makefile targets: `install`, `lint`, `format`, `tidy`, `test`, `db-up`, `db-down`, `test-db`, `scaffold`, `start-api-local`, `start-worker-local`
- Review: no.

**This task is run by the controller, not a subagent.** The scaffold skill needs the user's approval of the tree.

- [ ] **Step 1: Invoke the skill.** Skill tool, `skill: "scaffold"`. For its context step, answer from the spec without asking again:
  - **Services:** Postgres, HTTP API, background worker. The web frontend is not Python; the Expo app lives in `app/` and is excluded from ruff and mypy.
  - **Domain:** "Archie turns podcasts, articles, videos and newsletters a user shares into summaries, primers and spaced-repetition cards."
  - **Nouns:** sources, sync actions, jobs.
  - **Prefix:** `archie_`.
- [ ] **Step 2: Propose the tree** with `[keep]`/`[exemplar]` tags, plus the worktree-policy question the skill asks, in one message. Recommend **no worktree policy**: the user's default branch-in-place rule already applies, and we're on `m1-foundation`. Wait for the user's answer.
- [ ] **Step 3: Write the foundation and exemplars** per the skill. Required deviations from the steamroller references:
  - **Python version:** `requires-python = ">=3.13"`, and ruff `target-version = "py313"`.
  - **Exclusions:** ruff, mypy and pytest exclude `app`, `spikes` and `maestro`.
  - **`docker-compose.yml`** uses image `pgvector/pgvector:pg16`, user/password/db `archie`, port `127.0.0.1:5434:5432`, and creates an `archie_test` database through an init script in `docker/postgres-init/`. Port 5434 avoids steamroller's 5433.
  - **Makefile `LOCAL_TEST_DATABASE_URL`:** `postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test`.
  - **`conftest.py` table list:** `_TRUNCATE_TABLES = ("applied_actions", "jobs", "sources", "sessions", "users")`. Task 2 creates these tables. Until then, keep the exemplar table names and leave a `# SCAFFOLD:` marker on the constant.
  - **Settings** include the fields and methods listed under Produces.
  - **`.env.example`** lists `DATABASE_URL`, `OWNER_EMAILS`, `APPLE_AUDIENCE`, `ARCHIE_ENV` and `TEST_DATABASE_URL`.
- [ ] **Step 4: Verify:** `uv sync && make lint && make db-up && make test && make test-db && make scaffold`. All pass, and `make scaffold` lists only the exemplar markers.
- [ ] **Step 5: Commit** as one commit, "Scaffold uv-workspace monorepo with exemplar code", whose body lists foundation vs exemplar and the verification.

### Task 2: Real schema, change positions and job enqueue

**Files:**
- Modify: `packages/archie-db/archie_db/models.py` (replace the exemplar tables)
- Modify: `packages/archie-db/archie_db/migrations/versions/0001_initial.py` (replace it)
- Create: `packages/archie-db/archie_db/changes.py`, `packages/archie-db/archie_db/jobs.py`
- Modify: `conftest.py` (`_TRUNCATE_TABLES`, and remove its marker)
- Delete: any exemplar files these supersede
- Test: `packages/archie-db/tests/test_db_migrations.py` (kept from the scaffold), `packages/archie-db/tests/test_changes.py`

**Interfaces:**
- Produces, in `archie_db.models`:
  - StrEnums:
    - `SourceKind` (`LINK = "link"`)
    - `SourceState` (`QUEUED`, `INBOX`, `BRIEFED`, `CONSUMED`, `PROCESSING`, `FAILED`)
    - `SourceIntent` (`FINISHED`, `QUEUE`)
    - `JobKind` (`FETCH_TITLE = "fetch_title"`)
    - `JobStatus` (`QUEUED`, `RUNNING`, `DONE`, `FAILED`)
    - `ActionResult` (`APPLIED`, `DUPLICATE`, `REJECTED`)
  - Models:
    - `User(id: int, apple_sub: str, email: str | None, is_whitelisted: bool, created_at)`
    - `Session(id: int, user_id: int, key_hash: str, created_at, last_used_at, revoked_at: datetime | None)`
    - `Source(id: uuid.UUID, user_id: int, url: str, title: str | None, kind: str, state: str, intent: str, created_at, updated_at, deleted_at: datetime | None, change_seq: int)`
    - `AppliedAction(action_id: uuid.UUID, user_id: int, applied_at, result: str, reason: str | None)`
    - `Job(id: int, kind: str, payload: dict[str, Any], user_id: int, status: str, attempts: int, max_attempts: int, next_run_at, last_error: str | None, started_at: datetime | None, created_at)`
- Produces, in `archie_db.changes`:
  - `lock_user_writes(db: sqlalchemy.orm.Session, user_id: int) -> None`
  - `next_change_seq() -> sqlalchemy.ColumnElement[int]`
- Produces, in `archie_db.jobs`:
  - `enqueue(db: sqlalchemy.orm.Session, *, kind: JobKind, user_id: int, payload: dict[str, Any]) -> Job`
- Review: yes (migration, concurrency).

- [ ] **Step 1: Write `models.py`.** Follow the steamroller style: `TIMESTAMP = sqlalchemy.DateTime(timezone=True)`, and a docstring on every table. Key columns:

```python
CHANGE_SEQ_NAME = "change_seq"
CHANGE_SEQ = sqlalchemy.Sequence(CHANGE_SEQ_NAME, metadata=...)  # declared on Base.metadata so autogenerate sees it

class User(Base):
    """A person who signed in with Apple; `is_whitelisted` means the owner's API keys pay for their processing."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.Identity(), primary_key=True)
    apple_sub: Mapped[str] = mapped_column(sqlalchemy.String(255), unique=True)
    email: Mapped[str | None] = mapped_column(sqlalchemy.String(320))
    is_whitelisted: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())


class Source(Base):
    """One captured item. The id is generated on the phone so an offline-created row keeps its identity."""

    __tablename__ = "sources"
    __table_args__ = (sqlalchemy.Index("ix_sources_user_id_change_seq", "user_id", "change_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(sqlalchemy.String(2048))
    title: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    state: Mapped[str] = mapped_column(sqlalchemy.String(16))
    intent: Mapped[str] = mapped_column(sqlalchemy.String(16))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    # Always assigned via changes.next_change_seq() under changes.lock_user_writes(); see changes.py for why.
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)
```

  - `Session` has `key_hash` `String(64)`, unique, indexed.
  - `AppliedAction` has primary key `action_id` (UUID) and a `user_id` FK.
  - `Job` has an index `ix_jobs_status_next_run_at` on `(status, next_run_at)`, `payload` JSONB, `max_attempts` with server default `3`, and `attempts` with server default `0`.

- [ ] **Step 2: Hand-write `0001_initial.py`.** It runs `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` (enabled now for milestone 6), then `CREATE SEQUENCE change_seq`, then the five tables in FK order. `downgrade` drops them in reverse order, then the sequence. It leaves the extension in place.

- [ ] **Step 3: Write `changes.py`:**

```python
"""Change positions that phones pull from.

Every insert or update of a synced row takes the next value of one Postgres sequence. A phone pulls
rows with a position above its last one. The trap is that two transactions can take positions 5 and 6
and commit as 6 then 5: a phone pulling in between would advance past 5 and never see it. Serializing
each user's writes with a transaction-scoped advisory lock makes one user's positions commit in order.
Write volume per user is tiny, so the lock costs nothing.
"""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm

from archie_db import models


def lock_user_writes(db: sqlalchemy.orm.Session, user_id: int) -> None:
    """Block until this transaction is the only one writing synced rows for `user_id`; released at commit."""
    db.execute(sqlalchemy.select(sqlalchemy.func.pg_advisory_xact_lock(user_id)))


def next_change_seq() -> sqlalchemy.ColumnElement[int]:
    """The next change position. Call only after `lock_user_writes` in the same transaction."""
    return sqlalchemy.func.nextval(models.CHANGE_SEQ_NAME)
```

- [ ] **Step 4: Write `jobs.py`:**

```python
"""The job queue's write side: callers enqueue inside their own transaction, so work is never lost or orphaned."""

from __future__ import annotations

from typing import Any

import sqlalchemy.orm

from archie_db import models


def enqueue(
    db: sqlalchemy.orm.Session, *, kind: models.JobKind, user_id: int, payload: dict[str, Any]
) -> models.Job:
    """Add a job that is due now; it commits (or rolls back) with the caller's transaction."""
    job = models.Job(kind=kind.value, user_id=user_id, payload=payload, status=models.JobStatus.QUEUED.value)
    db.add(job)
    db.flush()
    return job
```

  `next_run_at` uses server default `now()`.

- [ ] **Step 5: Write the failing ordering test**, `packages/archie-db/tests/test_changes.py`. This is meaningful logic: if the lock is missing, commit order breaks.

```python
"""The per-user lock makes change positions commit in increasing order, so a pull can never skip a row."""

import threading
import uuid

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session

pytestmark = pytest.mark.postgres


def test_second_writer_waits_for_first_so_positions_commit_in_order(migrated_database_url: str) -> None:
    """While writer A holds the lock uncommitted, writer B cannot take a position, so B's position is larger."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as setup:
        user = models.User(apple_sub="sub-1")
        setup.add(user)
        setup.commit()
        user_id = user.id

    first = sqlalchemy.orm.Session(engine)
    changes.lock_user_writes(first, user_id)
    first_seq = first.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one()

    second_seq: list[int] = []

    def write_second() -> None:
        with sqlalchemy.orm.Session(engine) as second:
            changes.lock_user_writes(second, user_id)
            second_seq.append(second.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one())
            second.commit()

    thread = threading.Thread(target=write_second)
    thread.start()
    thread.join(timeout=0.5)
    assert thread.is_alive(), "second writer should be blocked by the first writer's lock"

    first.commit()
    thread.join(timeout=5)
    assert second_seq and second_seq[0] > first_seq
```

  Run: `make test-db`. It FAILS until `changes.py` exists, and passes after.

- [ ] **Step 6: Run** `make lint && make test-db`. The scaffold's models-match-migrations test must pass; that check is what catches drift between the models and the migration.
- [ ] **Step 7: Remove the superseded exemplar files** (exemplar tables and their tests), then run `make scaffold` to confirm.
- [ ] **Step 8: Commit** "DB: users, sessions, sources, applied actions, jobs; per-user change positions".

### Task 3: Sessions, the auth dependency, the test session route, and the e2e harness

**Files:**
- Create: `services/api/archie_api/deps.py`, `services/api/archie_api/auth/__init__.py`, `services/api/archie_api/auth/sessions.py`, `services/api/archie_api/auth/routes.py` (logout only here; Task 5 adds `/auth/apple`), `services/api/archie_api/test_routes.py`
- Create: `services/api/tests/e2e/harness.py`, `services/api/tests/e2e/conftest.py`, `services/api/tests/e2e/test_auth_e2e.py`
- Modify: `services/api/archie_api/main.py` (wire the routers; include `test_routes` only when `env() is not PROD`)
- Delete: the exemplar routes and schemas these supersede

**Interfaces:**
- Consumes: Task 2 models and `archie_shared.config`.
- Produces:
  - `archie_api.auth.sessions.create_session(db, *, user_id: int) -> str`, which returns the raw key
  - `resolve_session(db, *, raw_key: str) -> models.User | None`
  - `revoke_session(db, *, raw_key: str) -> None`
  - `archie_api.deps.get_db() -> Iterator[sqlalchemy.orm.Session]`, from a module-level engine built from `require_database_url()`
  - `current_user(...) -> models.User`, a FastAPI dependency that raises 401
  - `current_session_key(...) -> str`
  - `POST /test/session` with body `{"apple_sub": str = "test-user", "email": str | None = None}`, returning `{"session_key": str}`
  - **The harness**, for every later e2e task:
    - fixture `live_stack(migrated_database_url) -> LiveStack`
    - `@dataclass class LiveStack: base_url: str; database_url: str; client: httpx.Client; def sign_in(self, *, apple_sub: str = "test-user") -> str; def authed(self, session_key: str) -> httpx.Client`
    - `start_worker: bool` is controlled by marker `@pytest.mark.worker`. The worker loop it uses is Task 6's, imported lazily so this task doesn't depend on it; without the marker, no worker starts.
- Review: yes (auth).

- [ ] **Step 1: Write the harness.**
  - It runs the real app with `uvicorn.Server(uvicorn.Config(archie_api.main.app, host="127.0.0.1", port=<free port>, log_level="warning"))` in a daemon thread, and waits until `server.started`.
  - It sets `DATABASE_URL` to the migrated test URL and `ARCHIE_ENV=test` before importing `archie_api.main`. `deps` builds its engine lazily on the first request, so env set in the fixture applies.
  - On teardown it sets `server.should_exit = True` and joins the thread.
  - It lives under the root conftest's isolation. e2e tests carry `@pytest.mark.postgres`, which keeps real sockets: localhost for the server, and vcrpy intercepting outside HTTP.

- [ ] **Step 2: Write the failing e2e tests**, `test_auth_e2e.py`:

```python
"""Auth through the real API: a session key works until logout, and nothing works without one."""

import pytest
from tests.e2e.harness import LiveStack

pytestmark = pytest.mark.postgres


def test_requests_without_a_session_key_are_rejected(live_stack: LiveStack) -> None:
    """A protected route returns 401 with no Authorization header and with an unknown key."""
    assert live_stack.client.get("/sync/pull", params={"since": 0}).status_code == 401
    assert live_stack.authed("not-a-real-key").get("/sync/pull", params={"since": 0}).status_code == 401


def test_logout_revokes_the_session_key(live_stack: LiveStack) -> None:
    """After logout, the same key is rejected."""
    session_key = live_stack.sign_in()
    authed = live_stack.authed(session_key)

    assert authed.post("/auth/logout").status_code == 204
    assert authed.get("/sync/pull", params={"since": 0}).status_code == 401
```

  Until Task 4 lands, `/sync/pull` doesn't exist. In this task, mount a minimal protected `GET /me` that returns `{"user_id": int}` under `current_user`, and have both tests use `/me`. Task 4 keeps `/me`; the app uses it on launch to check the session.

- [ ] **Step 3: Implement `sessions.py`.**
  - `secrets.token_urlsafe(32)` makes the key, and `hashlib.sha256(key.encode()).hexdigest()` is what's stored.
  - `resolve_session` selects by hash with `revoked_at IS NULL`. It updates `last_used_at` only when it is older than one hour (`SESSION_TOUCH_INTERVAL = datetime.timedelta(hours=1)`), so reads don't become writes.
  - `deps.current_user` parses `Authorization: Bearer <key>` with a guard clause; anything else is a 401 `HTTPException`.
- [ ] **Step 4: Implement `test_routes.py`.** It upserts the user by `apple_sub` and returns `create_session(...)`. `main.create_app()` mounts it only when `config.get_settings().env() is not ArchieEnv.PROD`.
- [ ] **Step 5: Run** `make test-db`; the auth e2e tests pass. Run `make lint`.
- [ ] **Step 6: Commit** "API: session keys, auth dependency, test session route, live-stack e2e harness".

### Task 4: Expo app shell, theme, local database and API client

**Files:**
- Create: the `app/` Expo project, plus `app/app.config.ts`, `app/src/app/_layout.tsx`, `app/src/app/(tabs)/{_layout,today,library,add,review,ask}.tsx` (placeholders here, filled in by Task 8)
- Create: `app/src/theme/tokens.ts`, `app/src/theme/type.ts`, `app/src/theme/components/{Screen,Text,Button,Card,TextField}.tsx`
- Create: `app/src/db/schema.ts`, `app/src/db/client.ts`, `app/src/db/actions.ts`, `app/drizzle.config.ts`, and the generated `app/drizzle/`
- Create: `app/src/api/client.ts`
- Create: `app/jest.config.js`, `app/src/db/actions.test.ts`

**Interfaces:**
- Produces, local schema (`schema.ts`, Drizzle `sqliteTable`):
  - `sources { id text pk, url text, title text null, kind text, state text, intent text, createdAt text, updatedAt text, deletedAt text null, syncError text null }`
  - `outbox { id text pk, type text, payload text (JSON), createdAt text, status text ('pending' | 'rejected'), error text null }`
  - `syncState { id integer pk (always 1), position integer, lastPushFailed integer (0 | 1) }`
- Produces, `actions.ts`:
  - `export async function addSource(db: AppDb, input: { url: string; intent: "finished" | "queue" }): Promise<string>`
  - It returns the new source id, and writes the source row (state `consumed` for finished and `queued` for queue, kind `link`) and an outbox row `{type: "add_source", payload: {id, url, intent}}` in one `db.transaction`.
  - Ids come from `expo-crypto` `randomUUID()`.
- Produces, `client.ts`:
  - `export const API_URL: string`, from `process.env.EXPO_PUBLIC_API_URL`
  - `export class UnauthorizedError extends Error {}` and `export class NetworkError extends Error {}`
  - `export async function apiFetch(path: string, init: { method?: string; body?: unknown; sessionKey: string | null }): Promise<unknown>`, which throws `NetworkError` on fetch failure or 5xx, and `UnauthorizedError` on 401
- Produces, `db/client.ts`: `export type AppDb` and `export const db: AppDb` (`drizzle(openDatabaseSync("archie.db"))`), and `useDbMigrations()`, which wraps Drizzle's `useMigrations`.
- Produces, theme: tokens and components named as in the UX spec, chunk 1.
- Review: no.

- [ ] **Step 1: Create the project.**
  - Run `npx create-expo-app@latest app --template tabs`, then move routes under `app/src/app`. expo-router supports `src/app`.
  - Delete the template's sample screens.
  - Install: `npx expo install expo-sqlite expo-secure-store expo-apple-authentication expo-crypto expo-network expo-clipboard expo-font drizzle-orm`, then `npm i -D drizzle-kit babel-plugin-inline-import jest jest-expo @types/jest`.
  - Configure `babel.config.js` with inline-import for `.sql`, and `metro.config.js` with `sourceExts.push("sql")`, per Drizzle's Expo SQLite guide (https://orm.drizzle.team/docs/connect-expo-sqlite). Read that page; don't guess.
- [ ] **Step 2: Write `app.config.ts`.**
  - `name: "Archie"`, `slug: "archie"`, `scheme: "archie"`, `ios: { bundleIdentifier: "com.sampocs.archie", usesAppleSignIn: true, supportsTablet: false }`.
  - Plugins: `expo-router`, `expo-sqlite`, `expo-secure-store`, `expo-apple-authentication`, `expo-font`.
  - The Geist font files are loaded with `expo-font`.
- [ ] **Step 3: Theme chunk 1.** Read `docs/superpowers/specs/2026-10-29-ux-and-brand-design.md` → "Visual system", plus its Build plan Chunk 1. Implement `tokens.ts` (light/dark colors exactly as listed, domain and signal colors, radii, spacing), `type.ts` (Geist scale) and the listed components. Components read the color scheme through `useColorScheme()`.
- [ ] **Step 4: Tabs layout.** Today · Library · ＋ · Review · Ask, in that order. Labels as in the UX spec; the chat tab is labeled "Ask". The active tab uses chrome. Each screen renders `<Screen>` with its title for now.
- [ ] **Step 5: Schema and migrations.** Write `schema.ts`, run `npx drizzle-kit generate`, and commit `app/drizzle/`. `_layout.tsx` calls `useDbMigrations()` and renders nothing until migrations succeed. Seed `syncState` with row `{id: 1, position: 0, lastPushFailed: 0}` with `onConflictDoNothing`.
- [ ] **Step 6: Write the failing test** `actions.test.ts`. The atomicity of `addSource` is real logic: a source without its outbox row would never sync.
  - Run against `better-sqlite3` with Drizzle's `better-sqlite3` driver and the same schema. Add `better-sqlite3` as a dev dependency, and make `AppDb` the shared `BaseSQLiteDatabase` type so both drivers fit.
  - Test 1: after `addSource`, exactly one source and one pending outbox row exist, with the same id in the payload.
  - Test 2: if the outbox insert throws (simulated by a `CHECK` that rejects the type, added only in the test DB), no source row remains.
- [ ] **Step 7:** Run `npx jest src/db` and it passes. Run `npx tsc --noEmit` and it's clean.
- [ ] **Step 8:** Run `npx expo prebuild --platform ios --clean`, then `npx expo run:ios` (simulator). The app launches showing five tabs styled per the spec. Take a simulator screenshot (`xcrun simctl io booted screenshot /tmp/...` in the scratchpad) and look at it.
- [ ] **Step 9: Commit** "App: Expo shell, theme chunk 1, local database, outbox write, API client".

## Parallel-safe tasks

Every task below depends only on Tasks 1–4.

### Task 5: Sign in with Apple, on the backend and in the app

**Files:**
- Create: `services/api/archie_api/auth/apple.py`, `services/api/tests/test_apple.py`
- Modify: `services/api/archie_api/auth/routes.py` (add `POST /auth/apple`)
- Create: `app/src/auth/session.ts`, `app/src/app/sign-in.tsx`, `app/src/app/dev/login.tsx`
- Modify: `app/src/app/_layout.tsx` (auth gate)

**Interfaces:**
- Consumes: Task 3 `create_session`, `current_user` and `/me`; Task 4 `apiFetch`, theme components and `db`.
- Produces:
  - `archie_api.auth.apple.verify_identity_token(token: str, *, audience: str, jwks_client: jwt.PyJWKClient) -> AppleIdentity`, where `@dataclass(frozen=True) class AppleIdentity: sub: str; email: str | None`
  - It raises `InvalidAppleToken`.
  - `POST /auth/apple` takes body `{"identity_token": str}` and returns `{"session_key": str}`, or 401.
  - App `session.ts`:
    - `getSessionKey(): Promise<string | null>`, `setSessionKey(key: string): Promise<void>`, `clearSession(): Promise<void>`. Keychain key `archie.session`; `clearSession` also deletes all rows from `sources`, `outbox` and `syncState` and re-seeds `syncState`.
    - `signInWithApple(): Promise<void>`
    - `useSession(): { status: "loading" | "signedOut" | "signedIn"; sessionKey: string | null }`, backed by a tiny module-level store so `clearSession` updates every subscriber.
- Depends on: Tasks 1–4.
- Review: yes (auth).

- [ ] **Step 1: Write failing unit tests** `test_apple.py`. Token checking is logic that could be wrong.
  - Generate an RSA key pair in the test with `cryptography`.
  - Build a `jwt.PyJWKClient` subclass that returns that key from `get_signing_key_from_jwt`. This is a real PyJWT type with the network fetch swapped out, not a mock of Apple's response body.
  - Mint tokens with `iss="https://appleid.apple.com"`, `aud="com.sampocs.archie"`, `sub`, `email`, `exp`.
  - Cases:
    - a good token returns sub and email
    - a token signed with another key raises
    - the wrong `aud` raises
    - an expired token raises
    - the wrong `iss` raises
- [ ] **Step 2: Run** `uv run pytest services/api/tests/test_apple.py`. They FAIL because the module doesn't exist yet.
- [ ] **Step 3: Implement.**

```python
APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


def verify_identity_token(token: str, *, audience: str, jwks_client: jwt.PyJWKClient) -> AppleIdentity:
    """Check an Apple identity token's signature, issuer, audience and expiry; return who signed in."""
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key=signing_key.key, algorithms=["RS256"], audience=audience, issuer=APPLE_ISSUER)
    except jwt.PyJWTError as error:
        # One narrow boundary: every PyJWT failure means "not a valid sign-in", which the route maps to 401.
        raise InvalidAppleToken(str(error)) from error
    return AppleIdentity(sub=claims["sub"], email=claims.get("email"))
```

  - The module-level `_JWKS_CLIENT = jwt.PyJWKClient(APPLE_JWKS_URL, cache_keys=True, lifespan=86400)`.
  - The route then:
    - upserts the user by `apple_sub`
    - sets `email` when the token has one
    - sets `is_whitelisted = email.lower() in settings.owner_email_set()`
    - returns `create_session`
  - Add `pyjwt[crypto]` to the api package.
- [ ] **Step 4: Run** the tests; they pass. Run `make lint`.
- [ ] **Step 5: App.**
  - `sign-in.tsx` shows the wordmark and an `AppleAuthentication.AppleAuthenticationButton`. It calls `signInAsync({ requestedScopes: [FULL_NAME, EMAIL] })`, then `POST /auth/apple` with `identityToken`, then `setSessionKey`.
  - When the user cancels (`ERR_REQUEST_CANCELED`), nothing happens; any other error shows an inline message.
  - `_layout.tsx` redirects to `/sign-in` when `signedOut`. On launch, when `signedIn`, it calls `GET /me`, and an `UnauthorizedError` → `clearSession()`.
  - `dev/login.tsx`: if `!__DEV__`, it renders `<Redirect href="/" />` and nothing else. Otherwise it calls `POST /test/session` and then `setSessionKey`, then replaces the route with `/(tabs)/library`.
- [ ] **Step 6: Verify on the simulator.** Open `xcrun simctl openurl booted archie://dev/login` against `make start-api-local`, and the Library tab appears. The real Apple sign-in is checked on the phone in Task 10.
- [ ] **Step 7: Commit** "Auth: Sign in with Apple on the API and in the app; dev login link".

### Task 6: Sync push and pull on the backend

**Files:**
- Create: `services/api/archie_api/sync/{__init__,schemas,actions,pull,routes}.py`, `services/api/tests/e2e/test_sync_e2e.py`
- Modify: `services/api/archie_api/main.py` (include the sync router)

**Interfaces:**
- Consumes: Task 2 `lock_user_writes`, `next_change_seq` and `enqueue`; Task 3 `current_user`, `get_db` and the harness.
- Produces:
  - Schemas:
    - `PushRequest{actions: list[ActionIn]}` with `max_length=50`
    - `ActionIn{id: uuid.UUID, type: ActionType, payload: dict[str, Any]}`, where `ActionType` is a StrEnum with `ADD_SOURCE = "add_source"`
    - `PushResponse{results: list[ActionOut]}`, with `ActionOut{id: uuid.UUID, result: ActionResult, reason: str | None}`
    - `PullResponse{rows: PulledRows, position: int, more: bool}`, with `PulledRows{sources: list[SourceOut]}`
    - `SourceOut` fields are snake_case, matching the model's synced columns, with ISO timestamps
  - `apply_actions(db, *, user: models.User, actions: list[ActionIn]) -> list[ActionOut]`
  - `pull_changes(db, *, user_id: int, since: int, limit: int = 500) -> PullResponse`
- Depends on: Tasks 1–4.
- Review: yes (state, concurrency).

- [ ] **Step 1: Write the failing e2e tests**, `test_sync_e2e.py`:

```python
"""Sync through the real API: actions apply once and in order, and pulls never skip a row."""

import threading
import uuid

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, session
from tests.e2e.harness import LiveStack

pytestmark = pytest.mark.postgres


def _add_source(url: str, *, action_id: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "id": str(action_id or uuid.uuid4()),
        "type": "add_source",
        "payload": {"id": str(uuid.uuid4()), "url": url, "intent": "queue"},
    }


def test_added_source_comes_back_in_a_pull(live_stack: LiveStack) -> None:
    """A pushed add_source appears in the next pull as a queued link, with a higher position."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")

    pushed = authed.post("/sync/push", json={"actions": [action]}).json()
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    assert pushed["results"] == [{"id": action["id"], "result": "applied", "reason": None}]
    assert [row["id"] for row in pulled["rows"]["sources"]] == [action["payload"]["id"]]
    assert pulled["rows"]["sources"][0]["state"] == "queued"
    assert pulled["position"] > 0


def test_a_retried_action_is_applied_once(live_stack: LiveStack) -> None:
    """Pushing the same action id twice returns duplicate and leaves one source."""
    authed = live_stack.authed(live_stack.sign_in())
    action = _add_source("https://example.com/a")

    authed.post("/sync/push", json={"actions": [action]})
    second = authed.post("/sync/push", json={"actions": [action]}).json()
    pulled = authed.get("/sync/pull", params={"since": 0}).json()

    assert second["results"][0]["result"] == "duplicate"
    assert len(pulled["rows"]["sources"]) == 1


def test_a_rejected_action_does_not_block_later_ones(live_stack: LiveStack) -> None:
    """A non-http URL is rejected with a reason; the next action in the batch still applies."""
    authed = live_stack.authed(live_stack.sign_in())
    bad, good = _add_source("ftp://example.com"), _add_source("https://example.com/ok")

    results = authed.post("/sync/push", json={"actions": [bad, good]}).json()["results"]

    assert results[0]["result"] == "rejected" and results[0]["reason"]
    assert results[1]["result"] == "applied"


def test_a_source_id_owned_by_another_user_is_rejected(live_stack: LiveStack) -> None:
    """Reusing someone else's source id is rejected instead of overwriting their row."""
    first = live_stack.authed(live_stack.sign_in(apple_sub="user-a"))
    second = live_stack.authed(live_stack.sign_in(apple_sub="user-b"))
    action = _add_source("https://example.com/a")
    first.post("/sync/push", json={"actions": [action]})

    stolen = {**action, "id": str(uuid.uuid4())}
    result = second.post("/sync/push", json={"actions": [stolen]}).json()["results"][0]

    assert result["result"] == "rejected"


def test_pull_does_not_skip_a_row_committed_after_a_later_one(live_stack: LiveStack) -> None:
    """A write holding the user's lock blocks a push, so the pull position can never jump past it."""
    session_key = live_stack.sign_in()
    authed = live_stack.authed(session_key)
    engine = session.engine_for(live_stack.database_url)
    user_id = authed.get("/me").json()["user_id"]

    # Writer A: takes the lock and a position, and stays uncommitted.
    slow_writer = sqlalchemy.orm.Session(engine)
    changes.lock_user_writes(slow_writer, user_id)
    slow_source_id = uuid.uuid4()
    slow_writer.add(models.Source(
        id=slow_source_id, user_id=user_id, url="https://example.com/slow", kind="link",
        state="queued", intent="queue", change_seq=slow_writer.execute(sqlalchemy.select(changes.next_change_seq())).scalar_one(),
    ))
    slow_writer.flush()

    # Writer B: a push through the API, which must wait for A.
    push_thread = threading.Thread(
        target=lambda: authed.post("/sync/push", json={"actions": [_add_source("https://example.com/fast")]})
    )
    push_thread.start()
    push_thread.join(timeout=0.5)
    assert push_thread.is_alive()

    mid = authed.get("/sync/pull", params={"since": 0}).json()
    assert mid["rows"]["sources"] == []

    slow_writer.commit()
    push_thread.join(timeout=5)
    final = authed.get("/sync/pull", params={"since": mid["position"]}).json()
    assert {row["id"] for row in final["rows"]["sources"]} == {str(slow_source_id), final["rows"]["sources"][1]["id"]}


def test_pull_pages_until_more_is_false(live_stack: LiveStack) -> None:
    """With more rows than one page, following positions returns every row exactly once."""
    authed = live_stack.authed(live_stack.sign_in())
    for batch in range(11):
        authed.post("/sync/push", json={"actions": [_add_source(f"https://example.com/{batch}-{index}") for index in range(50)]})

    seen: list[str] = []
    position, more = 0, True
    while more:
        page = authed.get("/sync/pull", params={"since": position}).json()
        seen += [row["id"] for row in page["rows"]["sources"]]
        position, more = page["position"], page["more"]

    assert len(seen) == 550 and len(set(seen)) == 550
```

  - The `httpx.Client` used from the thread needs `timeout=10`.
  - In the ordering test, assert on the set of both ids. The fast row's id is unknown to the test, so assert `len(final) == 2` and that `slow_source_id` is in it. Implementers: simplify the last assert to exactly that.
- [ ] **Step 2: Run** `make test-db`. The tests FAIL with 404s.
- [ ] **Step 3: Implement `actions.py`.**
  - `apply_actions` opens one transaction per push and calls `changes.lock_user_writes(db, user.id)` first.
  - For each action, in order:
    - Skip it if its id is already in `applied_actions` for this user. Return `duplicate` without re-applying, and don't insert a new `applied_actions` row.
    - Validate the payload with a guard per rule. The URL must parse as http(s) and be at most 2,048 characters; intent must be in `SourceIntent`; and the source id must not already exist. The same user re-adding the same id is also rejected: their own retry with a new action id is still a bug.
    - On failure, insert `AppliedAction(result=rejected, reason=...)` and continue.
    - Otherwise insert the `Source` with `change_seq=next_change_seq()`, `state` = consumed if finished else queued, and `kind` = link. Then call `jobs.enqueue(kind=FETCH_TITLE, payload={"source_id": str(id)})` and insert `AppliedAction(result=applied)`.
  - Commit once at the end. Each rule lives in a `_validate_add_source(...) -> str | None` helper, which returns the reason or None.
- [ ] **Step 4: Implement `pull.py`.**
  - Select `Source` where `user_id == user_id` and `change_seq > since`, ordered by `change_seq`, with a limit.
  - The position is the last row's `change_seq`, or `since` when there are no rows; `more = len(rows) == limit`.
  - Deleted rows are included (with `deleted_at` set).
- [ ] **Step 5: Routes.** `POST /sync/push` → `apply_actions`. `GET /sync/pull?since=` (`since: int = Query(ge=0)`) → `pull_changes`. Both use `current_user`.
- [ ] **Step 6: Run** `make test-db` and every test passes. Run `make lint`.
- [ ] **Step 7: Commit** "Sync: push actions with per-user ordering and dedupe; paged pull by change position".

### Task 7: The worker, `fetch_title`, the launcher and the deploy config

**Files:**
- Create: `services/worker/archie_worker/{main,loop}.py`, `services/worker/archie_worker/handlers/{__init__,fetch_title}.py`
- Create: `services/worker/tests/test_worker_e2e.py`, `services/worker/tests/cassettes/` (recorded)
- Create: `services/api/archie_api/launch.py` (console script `archie-launch`), `Dockerfile`, `railway.json`
- Modify: `Makefile` (`start-worker-local`, `start-local` running both)

**Interfaces:**
- Consumes: Task 2 models, `changes` and `jobs`; the Task 3 harness (marker `worker`).
- Produces:
  - `archie_worker.loop.claim_next(db) -> models.Job | None`
  - `run_one(engine: sqlalchemy.Engine, *, handlers: Mapping[models.JobKind, Handler]) -> bool`, which returns whether a job ran
  - `requeue_stale(db, *, now: datetime) -> int`
  - `run_forever(engine, *, stop: threading.Event) -> None`
  - `Handler = Callable[[sqlalchemy.orm.Session, models.Job], None]`
  - `HANDLERS: dict[JobKind, Handler]`
  - `archie_worker.handlers.fetch_title.handle(db, job) -> None`
- Depends on: Tasks 1–4.
- Review: yes (state machine, concurrency).

- [ ] **Step 1: Record a real page.**
  - Pick a stable page with an `og:title` (e.g. `https://www.paulgraham.com/greatwork.html`, which has a `<title>`) and one with `og:title` (e.g. a GitHub repo page).
  - Write the tests with `@pytest.mark.vcr`, and record with `uv run pytest services/worker/tests --record-mode=once -m postgres` (the network is allowed for postgres-marked tests).
  - Commit the cassettes. For the failure case, record a real 500 from `https://httpbin.org/status/500`.
- [ ] **Step 2: Write the failing e2e tests**, `test_worker_e2e.py`. Each test:
  - inserts a user and a source directly
  - enqueues `fetch_title` through `jobs.enqueue`
  - calls `run_one` (or several) with real handlers, against the recorded HTTP
  - asserts on the DB

  Cases:
  1. **og:title wins:** `title` equals the page's og:title, the job is `done`, and the source's `change_seq` is higher than before.
  2. **The `<title>` fallback** is used when there's no og:title.
  3. **A recorded 500 is retried:** after the first `run_one`, `attempts == 1`, status `queued`, and `next_run_at` ≈ now + 10 s. Move `next_run_at` to now and run twice more. Then status is `failed`, `last_error` is set, and the title is still null.
  4. **Recovery after a failure:** a job whose first attempt hit the 500 cassette and whose second attempt hits the good page ends `done`. Use two cassettes in sequence via `vcr.use_cassette` contexts.
  5. **Stale jobs:** a job `running` with `started_at` 11 minutes ago is put back to `queued` by `requeue_stale`. One 5 minutes old is untouched.
  6. **No title on the page:** the job is still `done`, and the title stays null.
- [ ] **Step 3: Implement `loop.py`.**

```python
BACKOFF_SECONDS = (10, 60, 300)
STALE_AFTER = datetime.timedelta(seconds=600)
IDLE_POLL_SECONDS = 2.0


def claim_next(db: sqlalchemy.orm.Session) -> models.Job | None:
    """Lock one due job so no other worker takes it, and mark it running."""
    job = db.execute(
        sqlalchemy.select(models.Job)
        .where(models.Job.status == models.JobStatus.QUEUED.value, models.Job.next_run_at <= sqlalchemy.func.now())
        .order_by(models.Job.next_run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = models.JobStatus.RUNNING.value
    job.started_at = sqlalchemy.func.now()
    job.attempts += 1
    return job
```

  `run_one`:
  - **Claim** in one short transaction and commit, so the job is visibly `running`.
  - **Run** the handler in a second transaction.
  - **On success** it marks the job `done`.
  - **On any exception from the handler** it rolls back, then in a third transaction:
    - sets `last_error`
    - if `attempts >= max_attempts`, marks the job `failed`
    - otherwise sets it back to `queued`, with `next_run_at = now + BACKOFF_SECONDS[min(attempts - 1, 2)]`
  - Catching `Exception` here is the job runner's error boundary. Comment that this is the one place it's intended.

  `run_forever` calls `requeue_stale` once a minute and `run_one` in a loop, sleeping `IDLE_POLL_SECONDS` (via `stop.wait`) when no job ran.
- [ ] **Step 4: Implement `fetch_title.py`.**
  - It uses `httpx.Client(timeout=10, follow_redirects=True)` and streams the body, stopping at 1 MB.
  - `raise_for_status()` makes 4xx/5xx raise, so the job retries.
  - It parses with `html.parser` from the stdlib (a small `HTMLParser` subclass that collects `og:title` and the first `<title>`).
  - Then it calls `changes.lock_user_writes(db, job.user_id)`, sets `source.title`, `updated_at = now()` and `change_seq = next_change_seq()`.
  - If the source no longer exists or is deleted, it returns without doing anything.
- [ ] **Step 5: Launcher, `launch.py`.**
  - `archie-launch`:
    1. Runs `migrate.upgrade(settings.require_database_url())`.
    2. Starts two child processes with `subprocess.Popen`: `uvicorn archie_api.main:app --host 0.0.0.0 --port $PORT`, and `archie-worker`.
    3. Waits on both. When either exits, it terminates the other and exits with that child's code, so Railway restarts the whole container.
    4. On SIGTERM, it forwards the signal to both children.
  - `archie-worker` (`archie_worker.main:main`) calls `logging.configure()`, then `run_forever(engine_for(url), stop=Event)`, with SIGTERM setting `stop`.
- [ ] **Step 6: `Dockerfile`.** Base `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`. Copy the workspace, then `uv sync --frozen --no-dev`. Then `CMD ["uv", "run", "--no-sync", "archie-launch"]`. `railway.json` sets `{"build": {"builder": "DOCKERFILE"}, "deploy": {"healthcheckPath": "/health", "restartPolicyType": "ON_FAILURE"}}`.
- [ ] **Step 7: Verify.** `make test-db` passes. `docker build -t archie .` succeeds. Then run `docker run --rm -e DATABASE_URL=<local docker url via host.docker.internal:5434> -e ARCHIE_ENV=dev -e PORT=8000 -p 8000:8000 archie`, and `curl localhost:8000/health` returns ok. Stop the container.
- [ ] **Step 8: Commit** "Worker: Postgres job loop with retries and stale recovery; fetch_title; launcher and Dockerfile".

### Task 8: The app's sync engine, screens and sync status

**Files:**
- Create: `app/src/sync/engine.ts`, `app/src/sync/engine.test.ts`, `app/src/sync/transport.ts`, `app/src/sync/useSync.ts`
- Modify: `app/src/app/(tabs)/{add,library,today}.tsx`, `app/src/app/(tabs)/_layout.tsx` (sync status line)

**Interfaces:**
- Consumes: Task 4 `db`, schema, `addSource`, `apiFetch`, `NetworkError`, `UnauthorizedError` and the theme. The session is read through a `getSessionKey` parameter, so this task doesn't import Task 5's module. `useSync` takes `sessionKey` and `onUnauthorized` as arguments, which the root layout passes in.
- Produces:
  - `engine.ts`:

```ts
export type OutboxEntry = { id: string; type: string; payload: unknown };
export type PushResult = { id: string; result: "applied" | "duplicate" | "rejected"; reason: string | null };
export type PulledSource = { id: string; url: string; title: string | null; kind: string; state: string; intent: string;
  created_at: string; updated_at: string; deleted_at: string | null };
export type PullPage = { rows: { sources: PulledSource[] }; position: number; more: boolean };

export interface SyncStore {
  pendingActions(limit: number): Promise<OutboxEntry[]>;
  removeActions(ids: string[]): Promise<void>;
  rejectAction(id: string, reason: string): Promise<void>;    // also sets sources.syncError for that action's source
  getPosition(): Promise<number>;
  applyPage(page: PullPage): Promise<void>;                   // upsert rows + save position in one transaction
  setLastPushFailed(failed: boolean): Promise<void>;
}
export interface SyncTransport {
  push(actions: OutboxEntry[]): Promise<PushResult[]>;
  pull(since: number): Promise<PullPage>;
}
export type SyncOutcome = "synced" | "offline" | "unauthorized";
export async function runSync(store: SyncStore, transport: SyncTransport): Promise<SyncOutcome>;
```

  - `useSync.ts`: `useSync({ sessionKey, onUnauthorized }): void`. It wires the triggers and never runs two syncs at once. `useSyncStatus(): { waiting: number; offline: boolean }` is a live query on the outbox count and `syncState.lastPushFailed`.
- Depends on: Tasks 1–4.
- Review: yes (sync state).

- [ ] **Step 1: Write failing tests** `engine.test.ts`. Use an in-memory `SyncStore` (a plain object over arrays) and a scripted `SyncTransport`. These are the sync rules, which is real logic.
  1. **Order and batches:** pending actions are pushed in creation order, in batches of 50 (120 pending → pushes of 50, 50 and 20). `applied` and `duplicate` entries are removed.
  2. **Rejections:** a `rejected` result calls `rejectAction` with the reason, and the rest of the batch is still removed.
  3. **Network errors:** a `NetworkError` on push returns `"offline"`, sets `lastPushFailed=true`, does not pull, and keeps every action.
  4. **Push before pull:** a successful push then pulls from the stored position, following `more` across pages until `more` is false. Each page is applied in order, and the final position is saved.
  5. **Unauthorized:** an `UnauthorizedError` from push or pull returns `"unauthorized"`.
  6. **Clearing the failed flag:** after a successful push, `lastPushFailed` is false.
- [ ] **Step 2: Run** `npx jest src/sync`. The tests FAIL.
- [ ] **Step 3: Implement `runSync`:**

```ts
const PUSH_BATCH = 50;

export async function runSync(store: SyncStore, transport: SyncTransport): Promise<SyncOutcome> {
  try {
    await pushAll(store, transport);
    await pullAll(store, transport);
    return "synced";
  } catch (error) {
    if (error instanceof UnauthorizedError) return "unauthorized";
    if (error instanceof NetworkError) {
      await store.setLastPushFailed(true);
      return "offline";
    }
    throw error;
  }
}

async function pushAll(store: SyncStore, transport: SyncTransport): Promise<void> {
  // Push before pulling: a pull must never overwrite a local change the server hasn't seen yet.
  for (let batch = await store.pendingActions(PUSH_BATCH); batch.length > 0; batch = await store.pendingActions(PUSH_BATCH)) {
    const results = await transport.push(batch);
    for (const rejected of results.filter((result) => result.result === "rejected")) {
      await store.rejectAction(rejected.id, rejected.reason ?? "rejected");
    }
    await store.removeActions(results.filter((result) => result.result !== "rejected").map((result) => result.id));
  }
  await store.setLastPushFailed(false);
}

async function pullAll(store: SyncStore, transport: SyncTransport): Promise<void> {
  for (let more = true; more; ) {
    const page = await transport.pull(await store.getPosition());
    await store.applyPage(page);
    more = page.more;
  }
}
```

  `pendingActions` returns only `status = 'pending'`. Rejected entries keep `status = 'rejected'`, so they leave the queue.
- [ ] **Step 4: Run** the tests; they pass.
- [ ] **Step 5: Implement the real `SyncStore`** (Drizzle over `db`) and the `SyncTransport` (`apiFetch` to `/sync/push` and `/sync/pull`) in `transport.ts`.
  - `applyPage` upserts by id with `onConflictDoUpdate`. It overwrites every server column and leaves `syncError` alone: the server copy is the latest, because a push always happens first.
  - It saves the position in the same transaction.
- [ ] **Step 6: Implement `useSync`.**
  - It holds a `running` ref. A trigger that arrives during a run sets a `rerun` flag, which runs once more at the end.
  - **Triggers:**
    - when the hook mounts
    - `AppState` changing to `active`
    - `expo-network` `addNetworkStateListener` when it becomes connected
    - a 60 s `setInterval` while active
    - `requestSync()`, exported and called after `addSource`
  - When the outcome is `unauthorized`, it calls `onUnauthorized`.
- [ ] **Step 7: Screens.**
  - **`add.tsx`:** a `TextField` for the URL with a Paste button (`Clipboard.getStringAsync()` runs only when the button is tapped) and two buttons, Finished and Queue it.
    - Both buttons are disabled until the text parses as an http(s) URL.
    - On tap, it runs `addSource`, then `requestSync()`, clears the field, and navigates to Library.
  - **`library.tsx`:** a `useLiveQuery` over `sources` where `deletedAt IS NULL`, ordered by `createdAt` descending.
    - Each row shows the title (or the URL, muted), a state pill and the kind.
    - A row with `syncError` shows the error mark, and tapping it shows the reason in a simple alert-free inline expansion. Don't use `Alert` (see Maestro).
    - The empty state reads "Nothing here yet. Paste a link in ＋."
  - **Sync status:** in the tabs layout, `useSyncStatus` renders "Offline · N changes waiting" above the tab bar when `offline && waiting > 0`.
  - **`today.tsx`:** the header has an account button. Tapping it opens a small sheet with "Sign out" (testID `sign-out`). This task renders the button and takes an `onSignOut` from context; Task 9 wires `clearSession`.
- [ ] **Step 8: Run** `npx tsc --noEmit` and `npx jest`; both pass.
- [ ] **Step 9: Commit** "App: sync engine with outbox push and paged pull; ＋ and Library screens; sync status".

## Integration tasks (serial, after every parallel task)

### Task 9: Wire it together, the backend main-path e2e, and Maestro

**Files:**
- Modify: `app/src/app/_layout.tsx` (pass `sessionKey` and `onUnauthorized` into `useSync`; give `onSignOut` → `clearSession`)
- Create: `services/api/tests/e2e/test_main_path_e2e.py` (marker `worker`, with a recorded cassette)
- Create: `maestro/add_link.yaml`, `maestro/sign_out.yaml`, `maestro/offline.yaml`, `maestro/run_offline.sh`, `maestro/README.md`
- Modify: `Makefile` (`maestro` and `maestro-offline` targets)

**Interfaces:**
- Consumes: everything above.
- Depends on: Tasks 1–8.
- Review: yes.

- [ ] **Step 1: Main-path e2e.** `live_stack` with the worker running:
  - sign in
  - push `add_source` for the recorded page
  - poll `/sync/pull` every 0.2 s for up to 10 s until the source has a title
  - assert the title equals the recorded og:title, and the position rose between the first pull and the titled pull

  Record the cassette once, then run `make test-db`.
- [ ] **Step 2: Wire the app layout** as listed under Files. Check by hand on the simulator: open the dev login, add a link, and the title appears within a few seconds while `make start-local` runs.
- [ ] **Step 3: Install Maestro.** Run `curl -fsSL "https://get.maestro.mobile.dev" | bash`. It needs Java 17+; check `java -version`, and if it's missing, `brew install openjdk@17` and follow brew's PATH note. Then `maestro --version`.
- [ ] **Step 4: Flows.** Each one starts with `- openLink: archie://dev/login`, then `- assertVisible: "Library"`. Every interactive element in the app needs a `testID` (add the missing ones):
  - `add_link.yaml`: tap the ＋ tab, input `https://www.paulgraham.com/greatwork.html`, tap "Queue it", then `extendedWaitUntil` the page's title is visible (timeout 15000).
  - `sign_out.yaml`: on the Today tab, tap the account button, tap `sign-out`, and assert the Apple sign-in button is visible.
  - `offline.yaml` + `run_offline.sh`:
    1. The script starts the backend (`make start-local` in the background) and runs the first half of the flow: log in, then assert Library.
    2. It kills the backend and runs the second half: add `https://example.com/offline-test`, then assert "1 change waiting" is visible.
    3. It restarts the backend and runs the third half: wait until "changes waiting" is not visible, then wait until "Example Domain" is visible.

    Three small flow files (`offline_1_login.yaml`, `offline_2_add.yaml`, `offline_3_synced.yaml`), driven by the script, keep this deterministic.
- [ ] **Step 5: Run** `make maestro` and `make maestro-offline` against a simulator debug build, and all pass. Add `maestro/README.md` covering how to run them (simulator booted, `npx expo run:ios`, backend local).
- [ ] **Step 6: Commit** "Main-path e2e, app wiring, and Maestro flows (add link, sign out, offline sync)".

### Task 10: Deploy to Railway, install on the phone, live check

**Files:**
- Modify: `app/app.config.ts` (the production `EXPO_PUBLIC_API_URL` for release builds)
- Create: `scripts/install_ios.sh` (adapted from `spikes/share_extension/install.sh`)
- Modify: `AGENTS.md` (Commands: deploy, install, maestro)

**Interfaces:**
- Depends on: Tasks 1–9.
- Review: no (ops). The controller runs it with the user.

- [ ] **Step 1: Railway.** The controller uses the `use-railway` skill.
  1. Create the project `archie` in the user's workspace.
  2. Add Postgres. Check that the image supports `vector` (Railway's pgvector template or image `pgvector/pgvector:pg16`). If the default Postgres lacks the extension, deploy the pgvector template instead.
  3. Add an app service from this repo (Dockerfile).
  4. Set the variables: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `OWNER_EMAILS=<the user's Apple email, which the user provides>`, `APPLE_AUDIENCE=com.sampocs.archie`, `ARCHIE_ENV=prod`.
  5. Generate a domain.
  6. Check that `curl https://<domain>/health` returns ok, and that `POST /test/session` returns 404 in prod.
- [ ] **Step 2: Release build.** Run `EXPO_PUBLIC_API_URL=https://<domain> npx expo prebuild --platform ios --clean`, then an `xcodebuild` Release build signed with team `3W3H65F89G`, then `scripts/install_ios.sh` (the phone must be plugged in and unlocked). If signing complains about the Sign in with Apple capability, ask the user to enable it for `com.sampocs.archie` in the developer portal.
- [ ] **Step 3: Live check with the user.**
  1. Sign in with Apple and choose "Share My Email".
  2. Check in Railway's Postgres that the user row has `is_whitelisted = true`.
  3. Add a link while online, and the title appears.
  4. Turn on airplane mode, add a link, and "1 change waiting" shows.
  5. Turn off airplane mode, and it syncs and gets a title.
  6. Kill and reopen the app, and you're still signed in.
- [ ] **Step 4: Commit** "Deploy: Railway service, release install script, live check". Then update the spec's status line to "Built 2026-11-xx".
