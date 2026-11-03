# Milestone 1: Foundation (2026-11-02)

The first milestone of the roadmap in `2026-11-02-backend-architecture-design.md`. Product behavior is defined in `2026-10-26-product-scope.md` and the visual design in `2026-10-29-ux-and-brand-design.md`.

## Goal

On the phone, the user can:

1. Sign in with Apple once and stay signed in.
2. See the tab bar, styled per the UX spec.
3. Paste a link in ＋ and choose Finished or Queue it.
4. See the link in Library, with its page title filled in a few seconds later by the backend worker.
5. Do all of this offline, with the change syncing once the phone is back online.

This proves the whole loop: phone action → outbox → API → Postgres → worker job → change position → pull → phone.

## Out of scope

- The share extension (milestone 2).
- Processing beyond fetching the title.
- Every screen beyond the shell, ＋ and a plain Library list.
- Motion, haptics and brand assets (UX chunks 2–3, milestone 4).
- Deleting your account, and bringing your own API keys (milestone 9).
- Google sign-in.

## Repo layout

```
pyproject.toml, Makefile, docker-compose.yml, conftest.py, Dockerfile   uv workspace root
packages/archie-shared/   config, logging
packages/archie-db/       models, session, migrations, change positions, job enqueue
services/api/             FastAPI app (archie_api): auth, sync, test routes, launcher
services/worker/          job loop and handlers (archie_worker)
app/                      Expo app (latest stable SDK), expo-router under app/src/app
maestro/                  Maestro flows and the offline script
spikes/                   unchanged, reference only
docs/
```

The Python side is seeded with the `/scaffold` skill before any feature code, so later code copies its patterns. The layout follows the skill: a uv workspace at the repo root.

## Backend

### Tables

| Table | Columns that matter | Notes |
|---|---|---|
| `users` | id, apple_sub (unique), email, is_whitelisted, created_at | `is_whitelisted` is set from the `OWNER_EMAILS` env var at sign-in |
| `sessions` | id, user_id, key_hash (unique), created_at, last_used_at, revoked_at | Only the SHA-256 of the key is stored |
| `sources` | id (UUID, generated on the phone), user_id, url, title, kind, state, intent, created_at, updated_at, deleted_at, change_seq | `kind`, `state` and `intent` are `StrEnum`s. In M1, kind is `link` and state is `queued` (Queue it) or `consumed` (Finished) |
| `applied_actions` | action_id (UUID from the phone), user_id, applied_at, result | Makes a retried action a no-op |
| `jobs` | id, kind, payload (jsonb), user_id, status, attempts, max_attempts, next_run_at, last_error, created_at | Status is `queued`, `running`, `done` or `failed` |

- **Sync position:** one Postgres sequence, `change_seq`. Every insert or update of a synced row sets `change_seq = nextval(...)`.
- **Write order:** every write to synced rows first takes `pg_advisory_xact_lock(<user id>)`. That serializes one user's writes, so their positions always commit in order (see Sync).
- **Deletes are soft:** `deleted_at` is set and the row is kept, so deletions sync.

### API

All routes except `/auth/*` and `/health` need `Authorization: Bearer <session key>`.

| Route | Does |
|---|---|
| `POST /auth/apple` | Body: the Apple identity token. Checks its signature against Apple's public keys (cached), the issuer, the audience (`com.sampocs.archie`) and the expiry. Creates or updates the user, then returns a new 32-byte random session key |
| `POST /auth/logout` | Revokes the current session |
| `POST /sync/push` | Body: `{actions: [{id, type, payload}]}`, applied in order. Response: one result per action, `applied`, `duplicate` or `rejected` (with a reason). M1 has one action type, `add_source`, with id, url and intent |
| `GET /sync/pull?since=N` | Returns `{rows: {sources: [...]}, position: M}`: every synced row of this user with `change_seq > N`, at most 500 per page, plus `more: bool` |
| `GET /health` | Returns `ok` and whether the database can be reached |
| `POST /test/session` | Only exists when `ARCHIE_ENV=test` or `dev`. Creates or gets a test user and returns a session key |

- **Session lookup:** each request does one indexed lookup of the key's hash. `last_used_at` is updated at most once an hour, so reads don't turn into writes.
- **Session lifetime:** sessions don't expire; they last until logout or revocation.

### Actions and validation

- **`add_source` rejects:**
  - a URL that isn't http(s), or is longer than 2,048 characters
  - an intent that isn't valid
  - an id that already belongs to another user
- **Another source with the same URL** is allowed in M1. Duplicate detection is a product question for milestone 2.
- **A successful `add_source`** inserts the source and queues a `fetch_title` job in the same transaction, so a source can never exist without its job.

### Jobs and worker

- **Claiming:** the worker loop claims one due job with `SELECT … WHERE status='queued' AND next_run_at <= now() ORDER BY next_run_at FOR UPDATE SKIP LOCKED LIMIT 1`, then runs its handler.
- **Waiting:** it polls every 2 s when idle. `LISTEN/NOTIFY` can come later if latency matters.
- **On failure:** `attempts` goes up, and the job is rescheduled with exponential backoff (10 s, 1 min, 5 min). After `max_attempts` (3) it is marked `failed` with `last_error`.
- **Stale jobs:** a job left `running` for more than 10 minutes, for example because the worker crashed, is put back in the queue.
- **`fetch_title`:**
  - GETs the URL with a 10 s timeout and a 1 MB limit.
  - Reads `og:title`, falling back to `<title>`.
  - Writes the title, which bumps `change_seq` under the user's lock.
  - A page without a title is still a success: the title stays empty.

### Deploy (Railway)

- **Project:** `archie`, holding a Postgres service (with pgvector enabled now, for later) and one app service built from `backend/`.
- **Start command:** run `alembic upgrade head`, then start the API (uvicorn) and the worker as two processes in one container, with a small Python launcher that exits if either one dies, so Railway restarts the whole container.
- **Env vars:** `DATABASE_URL`, `OWNER_EMAILS`, `APPLE_AUDIENCE`, `ARCHIE_ENV=prod`.
- **Environment:** production only. Development runs locally against Postgres in Docker.

## App

- **Framework:** Expo with expo-router, bundle id `com.sampocs.archie`, iOS only, with the Sign in with Apple entitlement.
- **Builds:** built locally and installed over the cable, as in the spike.
- **Screens:**
  - **Sign in:** a full screen with the Apple button (`expo-apple-authentication`), shown whenever there's no session key.
  - **Tabs:** Today · Library · ＋ · Review · Ask. Today, Review and Ask are empty screens.
  - **Account menu:** in the Today header, with sign out.
  - **＋:** a URL field with a Paste button (reading the clipboard automatically would trigger an iOS permission prompt every time) and Finished / Queue it buttons.
  - **Library:** sources newest first, showing title (or URL until the title arrives), state and kind. A source whose action was rejected shows an error mark, and tapping it shows the reason.
  - **Sync status:** "Offline · N changes waiting" appears whenever the outbox isn't empty and the last push failed.
- **Styling:** UX spec chunk 1, which is the color tokens (light and dark), Geist, spacing and radii, and the basic components the screens above need.
- **Local data:**
  - **Storage:** `expo-sqlite` through Drizzle (typed schema, migrations run when the app starts).
  - **Tables:** `sources` (the same synced columns as the server), `outbox` (id, type, payload, created_at, status, error), and `sync_state` (position).
  - **Screens** read through Drizzle live queries.
- **Actions:**
  - `addSource(url, intent)` writes the local source row and the outbox entry in one transaction. The source's id and the action id are UUIDs made on the phone.
- **Sync loop:**
  - **When it runs:** when the app opens or returns to the foreground, when the network comes back, right after an action, and every 60 s while the app is open.
  - **It never runs twice at once.**
  - **Each run:**
    1. Push the pending outbox entries in order, in batches of 50.
    2. Delete entries that came back `applied` or `duplicate`.
    3. Mark `rejected` entries as failed and flag their source.
    4. Then pull pages until `more` is false.
    5. Upsert the rows, with the latest change winning, and save the position.
  - **On a network error,** it stops and waits for the next trigger, with nothing lost.
  - **A 401** clears the session and shows the sign-in screen.
- **Session key:** stored in `expo-secure-store` (the Keychain). The shared Keychain access group the share extension needs is added in milestone 2. Adding it now risks the signing trouble the spike had with App Groups, and moving the key into the group later only costs one re-sign-in.
- **Dev-only login link:** `archie://dev/login`, compiled only into debug builds. It calls `POST /test/session`, saves the key and opens Library. The Maestro flows use it so they skip the Apple sign-in screen.
- **Backend URL:** the deployed Railway URL in release builds, and the local backend in debug builds. Set through the app config.

## Sync correctness

- **Push and then pull, in that order.** A pull therefore never overwrites a local change that hasn't been sent. For the rare row edited on both sides, the latest change wins, which is acceptable for one person editing.
- **Ordering:** because each user's writes run one at a time under their lock, the positions they get commit in increasing order, so a pull with `since=N` can't skip a row that commits later with a smaller position.
- **Retried actions:** an action id already in `applied_actions` comes back as `duplicate` without being applied again. This covers the case where the phone sent an action, the response was lost, and it sent the action again.

## Testing

Per the testing approach in the architecture doc: e2e first, and unit tests only for logic that could be wrong.

**Backend e2e** (pytest):
- **What runs:** the real API (uvicorn on a free port) and a real worker against Postgres in Docker (testcontainers), all driven over HTTP.
- **Outside calls:** recorded and replayed with `pytest-recording`.
- **Cases:**
  - **The main path:** `/test/session` → push `add_source` → the worker runs `fetch_title` against a recorded real page → pull returns the row with its title and a higher position.
  - **A retried action:** pushing the same action id twice applies it once and comes back `duplicate`.
  - **A rejected action:** a bad URL is `rejected`, while a later valid action in the same batch is still applied.
  - **Ordering:** writes running at the same time for one user, with pulls in between, never lose a row.
  - **Auth:** no key or a wrong key gets 401, and a key stops working after logout.
  - **Retries:** a recorded 500 is retried, then the job ends `failed`. A recovery after one failure ends `done`.
  - **Stale jobs:** a stale `running` job is put back in the queue.

**Backend unit:**
- Checking the Apple token, with keys generated in the test: a good token, a bad signature, the wrong audience, an expired token.

**App unit** (jest, on the pure sync module):
- push order
- stopping on a network error
- handling rejected actions
- the paged pull
- latest-change-wins when a row is upserted

**Maestro** (simulator, local backend), each flow starting with `archie://dev/login`:
- Add a link and see it in Library with its title.
- **Offline:** a script stops the backend, the flow adds a link and sees "1 change waiting," the script restarts the backend, and the flow sees it sync.
- Sign out, and see the sign-in screen.

**Live check** (when the milestone finishes):
- Sign in with Apple on the phone against Railway, choosing "Share My Email."
- Add a link with the phone offline and online.
- Check that `/health` returns ok.

## Setup the user does

- **Railway:** done (logged in).
- **Phone:** plugged in for the install.
- **Apple:** if Xcode's automatic signing doesn't turn on the Sign in with Apple capability for `com.sampocs.archie`, tick it in the Apple developer portal.
