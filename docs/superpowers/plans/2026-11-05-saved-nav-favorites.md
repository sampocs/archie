# Saved and Takes, piece 1: Nav + Favorites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four tabs (Today · Library · Review · Ask), a ＋ in the Library header that opens the add sheet as a modal, a four-way Library control (All · Domains · Saved · Takes), and favorites: a ★ on any source (item page and rows) that syncs, Library → Saved listing favorites by domain, and a favorites-by-domain page.

**Architecture:**
- DB (`0008_favorites`): `sources.favorited_at timestamptz null` (null = not starred). Pulled with the other source columns.
- API: one push action `set_favorite` in `source_actions.py`.
- App: drizzle migration 0008 (re-pull), sync of `favorited_at`, optimistic `setFavorite`; the ＋ tab is deleted and `app/src/app/add.tsx` becomes a modal stack route opened from Library's header; Library gets four modes, Saved shows the Favorites section (pure grouping in `app/src/library/favorites.ts`), Takes shows its empty state; a new route `app/src/app/favorites/[domain].tsx`; a gold ★ in row kickers and an item-page navbar button.

**Tech Stack:** as M6 (FastAPI, SQLAlchemy/Alembic, Postgres; Expo Router, drizzle + expo-sqlite, jest, Maestro). No new packages, no new native modules.

**Spec:** `docs/superpowers/specs/2026-11-05-saved-and-takes-design.md` (owner-approved; piece 1 of its Build order). Mocks `2026-11-05-saved-and-takes-mocks.html`, screens 01–05; where the mocks and the spec differ, the spec wins. UX rules: `docs/superpowers/specs/2026-10-29-ux-and-brand-design.md`.

## Global Constraints

- **Python style:** `AGENTS.md` house style (module-qualified imports as the repo does them, e.g. `from archie_db import changes, models` then `changes.touch(...)`; classes/`typing` by name; full typing with `X | None`; `StrEnum`s for compared strings; dataclasses over tuples of >2; named parameters; guard clauses; blank-line paragraphs past ~8 lines; why-comments; docstrings on public functions/classes).
- **Action contract:** every push action handler has the signature `(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None` (rejection reason or None) and runs under the batch's user lock inside a savepoint. **A handler validates everything before its first write**: returning a reason does *not* roll back earlier writes. Every changed source gets a fresh `change_seq` via `changes.touch`.
- **Wire payload** (snake_case; `id` is always the row the action changes, which the phone's "keep the local copy while an action is unsent" rule in `transport.applyPage` relies on; the spec's `source_id` is sent as `id`):

  | type | payload |
  |---|---|
  | `set_favorite` | `{id (source), favorited: bool}` |

  Server effect: `favorited: true` on an unstarred source sets `favorited_at = now()`; `false` on a starred one clears it; either one when the source is already in that state is applied without a write (starring again keeps the first star's time, so "newest star first" stays stable). Rejections: `rows.MALFORMED` ("payload is malformed"), `rows.NO_SOURCE` ("source not found": another user's, deleted or unknown). Starring changes nothing else (state, cards, queue).
- **Pulled rows:** `sources` gain `favorited_at: ISO-8601 | null`. The phone's `PulledSource.favorited_at?: string | null` is optional (an older server omits it) and stored as `favoritedAt` (`?? null`).
- **Migration numbers:** server `0008` (`packages/archie-db/archie_db/migrations/versions/0008_favorites.py`, revises `0007`); app drizzle `0008_favorites`. (The spec's `0007_favorites` predates M6 taking 0007.)
- **Drizzle migrations:** generate with `cd app && npx drizzle-kit generate --name favorites`, then **read the generated SQL before committing.** M6's generated `cards` table rebuild selected columns that didn't exist and had to be hand-trimmed. This change should generate a single `ALTER TABLE \`sources\` ADD \`favorited_at\` text;` — if drizzle instead emits a `__new_sources` rebuild, check every column its `INSERT … SELECT` names exists in 0007's `sources`. Every app migration that adds server columns ends with the re-pull reset (`UPDATE sync_state SET position = 0;`), and gets a jest migration test (Task 1).
- **Copy (verbatim):** segment labels `All`, `Domains`, `Saved`, `Takes`; Saved section header `Favorites · N`; Saved empty state "Star items to keep them here, or save something just for fun to a collection."; Takes empty state "Things you think, in your own words"; item by-line suffix ` · ★ Favorite`; favorites row meta `<Kind> · starred <Mon> <D>` (e.g. "X post · starred Nov 3"); favorites page kicker `Favorites`; add sheet title `Add`.
- **Star color:** a new signal token `favorite`: light `#B8892A` (the mock's gold), dark `#D9B45A`. Only the ★ uses it.
- **testIDs** (new): `library-add` (header ＋), `library-mode-all` / `library-mode-domains` / `library-mode-saved` / `library-mode-takes` (`library-mode-list` is renamed `library-mode-all`), `add-cancel`, `saved-view`, `saved-favorites` (the Favorites section), `saved-empty`, `takes-empty`, `favorites-domain-<slug>` (slug from `@/topics/topicName`'s `slugify`, e.g. `favorites-domain-other`), `favorites-page`, `favorite-row-<sourceId>`, `favorite-unstar-<sourceId>`, `item-favorite`. Existing ones stay: `add-url`, `add-paste`, `add-save`, `intent-*`, `reaction-*`, `capture-note`, `queue-primer`, `library-search`, `filter-*`, `item-byline`, `item-more`, `tab-today`, `tab-library`, `tab-review`, `tab-ask`. **`tab-add` disappears**; every Maestro flow that used it moves to `library-add` (Task 6).
- **Tests:** e2e first; unit tests only for real logic; outside calls replayed from cassettes (none in this piece). App logic tests are `*.test.ts` (jest matches only `.ts`); pure app logic never imports a native module.
- **Never print secrets** or `.env` values.
- **Branch and worktrees:** branch `saved-nav-favorites`, worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/saved-nav-favorites`. Foundation tasks run there serially. Each parallel-safe task runs in its own worktree from the last foundation commit (`git gtr new snf-t<N> --from-current --yes`, run inside the `saved-nav-favorites` worktree), then merges back into `saved-nav-favorites`.
- **App packages in worktrees:** a worktree's `app/node_modules` is a symlink to the main checkout's: `ln -sfn /Users/sampocs/Documents/Personal/second-brain/app/node_modules app/node_modules` (run in every worktree that runs `npm`/`npx`; once per worktree). Keep it out of git: `grep -qx 'app/node_modules' "$(git rev-parse --git-common-dir)/info/exclude" || echo 'app/node_modules' >> "$(git rev-parse --git-common-dir)/info/exclude"`. **npm packages are installed only in the main checkout's `app/`** (none are needed here). **Never run `npx prettier`** (the project has no prettier; it would reformat files wholesale).
- **Postgres from a worktree:** the container `second-brain-postgres-1` (`127.0.0.1:5434`) is already up from the main checkout. **Never run `make db-up`, `make db-down`, `make test-db`, `make migrate-local`, `make start-local`, `make reset-local-data` or any `make maestro*` target from a worktree** (they drive the main checkout's docker-compose stack and local data). Run tests with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t<N> uv run pytest -m "postgres or not postgres"`, where every task uses its own database (tests truncate tables and one downgrades the schema): `docker exec second-brain-postgres-1 createdb -U archie archie_test_t<N>` (ignore "already exists").
- **Maestro:** implementers add the testIDs listed in their task and write/edit flow files; flows are **run only by the coordinator, from the main checkout, against the local backend** (Task 6, Step 6).
- **Checks before every commit:** Python: `make lint` and the relevant tests (command above). App: `cd app && npm run typecheck && npx jest`.
- **Commits:** every message ends with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MN7nukQAsqfkk3GiAq6NkX
  ```
- **Out of scope:** deploying, `railway config apply`, pushing or merging to `main`; collections (tables, add-sheet choice, share extension, Saved tiles, collection page), takes (tables, editor, list, the "Write a take" link and button), named favorite folders, a ＋ on Today, starring topic primers. The plan ends with `saved-nav-favorites` ready for a PR.

## Decisions made while planning

1. **Takes segment in piece 1** shows only the empty-state line "Things you think, in your own words" (testID `takes-empty`), **without** the "Write a take" button: the editor arrives in piece 3, and a button that does nothing is worse than none. Piece 3 adds the button and the list.
2. **Saved's empty state** uses the spec's copy verbatim even though collections arrive in piece 2 ("…or save something just for fun to a collection."), so the copy doesn't churn between pieces. Saved has no Collections section yet.
3. **Search and filter chips show only under All** (spec: "Search and filter chips belong to All"). Today, typing in search under Domains switched to the list; now Domains, Saved and Takes have no search field. Today's `?filter=` links switch to All.
4. **A favorite with no domain** (not filed yet, or filing failed) is grouped under **Other**, via `asDomain` — the same fallback the row kicker already uses. This matters for Maestro: the dev test user isn't whitelisted, so its sources never get a domain.
5. **Favorites groups** are sorted by count, ties in `DOMAINS` order; each group's preview is its two newest-starred titles joined with " · " (a title falls back to the URL, as rows do).
6. **Only sources can be starred** (spec: "Any source can be starred"); the mock's mention of primers means a source's primer page shares its source's star, and topic primers have no star in this piece.
7. **The ★ in row kickers** comes from `SourceRow`, so every source row (Library, Today, topic page, favorites page) shows it. Queued-primer rows (`QueuedPrimerRow`) don't.
8. **The add sheet** is a native-stack modal (`presentation: "modal"`, the iOS page sheet, swipe down to dismiss) with an `add-cancel` text button. Save calls `router.back()`, so it lands on whatever presented it (Library). Its fields are `CaptureOptions` unchanged (the mock's choice subtitles are not added: the spec says Finished/Queue work "exactly as `CaptureOptions` does today", and the share extension shares that component).
9. **`set_favorite` is idempotent** (see Global Constraints) and a rejected one rewinds the sync position (it's in `REWOUND_SOURCE_ACTIONS`), so the next pull restores the server's star and the source shows `syncError`, like other optimistic source actions.

---

## File Structure

```
packages/archie-db/archie_db/models.py                          Source.favorited_at (T2)
packages/archie-db/archie_db/migrations/versions/0008_favorites.py                                         (T2)
services/api/archie_api/sync/{schemas,actions,source_actions}.py SourceOut.favorited_at, ActionType.SET_FAVORITE, handler (T2)
services/api/tests/e2e/test_favorites_e2e.py                                                                (T2)
app/src/db/{schema,actions,actions.test}.ts, app/drizzle/0008_favorites.sql (+ meta, journal, migrations.js), app/src/sync/{engine,transport,engine.test}.ts (T1)
app/src/app/(tabs)/{_layout,add→deleted}.tsx, app/src/app/add.tsx, app/src/app/_layout.tsx, app/src/theme/components/Screen.tsx, app/src/app/(tabs)/library.tsx (header ＋)  (T3)
app/src/library/{favorites,favorites.test}.ts, app/src/library/{SavedView,TakesView}.tsx, app/src/app/(tabs)/library.tsx (modes), app/src/app/favorites/[domain].tsx, app/src/app/_layout.tsx, app/src/ui/SourceRow.tsx (kickerSuffix)  (T4)
app/src/theme/tokens.ts, app/src/ui/{Kicker,SourceRow}.tsx, app/src/item/ItemHeader.tsx, app/src/app/source/[id].tsx                  (T5)
maestro/{favorites.yaml, add_link, add_podcast, finish_item, library_queue, library_search, offline_2_add, review, source_page, today_primer}.yaml, Makefile, maestro/README.md, docs (T6)
```

Tasks 3, 4 and 5 overlap textually (`library.tsx`, root `_layout.tsx`, `SourceRow.tsx`) but not semantically; the coordinator resolves the merge conflicts.

## Foundation task (run in `saved-nav-favorites`)

### Task 1: App data layer: schema 0008, sync of `favorited_at`, `setFavorite`  (tier: most capable)

**Files:**
- Modify: `app/src/db/schema.ts`, `app/src/db/actions.ts`, `app/src/db/actions.test.ts`, `app/src/sync/engine.ts` (`PulledSource`), `app/src/sync/transport.ts`, `app/src/sync/engine.test.ts`
- Create: `app/drizzle/0008_favorites.sql` (+ `meta/0008_snapshot.json`, journal and `migrations.js` entries, all generated)

**Interfaces:**
- Produces:
  - `schema.sources.favoritedAt: text("favorited_at")` (ISO string or null; null = not starred).
  - `actions.ts`: `ActionType` gains `"set_favorite"`; `setFavorite(db: AppDb, sourceId: string, favorited: boolean): void`.
  - `engine.ts`: `PulledSource.favorited_at?: string | null`.
- Review: yes (migration, sync conflict rules).

- [ ] **Step 1: Worktree setup.** In this worktree: the `app/node_modules` symlink and exclude line from Global Constraints.

- [ ] **Step 2: Schema.** In `schema.ts`, `sources`, after `cardsOff`:

```ts
  // When the user starred it; null = not starred. Favorites sort newest star first.
  favoritedAt: text("favorited_at"),
```

- [ ] **Step 3: Generate the migration**: `cd app && npx drizzle-kit generate --name favorites`. Check `drizzle/migrations.js` and `drizzle/meta/_journal.json` gained `0008_favorites`, and **read `drizzle/0008_favorites.sql`**: it should be the single `ALTER TABLE \`sources\` ADD \`favorited_at\` text;` (see Global Constraints if it is a rebuild). Append, as `0007_review.sql` does:

```sql
--> statement-breakpoint
-- Sources' favorited_at reaches this phone only through a full re-pull.
UPDATE sync_state SET position = 0;
```

- [ ] **Step 4: Tests first** (they fail until Step 5).

In `actions.test.ts`: add `favorited_at text` to the hand-written `sources` table in `createTables` (after `cards_off integer DEFAULT 0 NOT NULL`; drizzle inserts name every column, so the hand-made table must have it), import `setFavorite`, and add:

```ts
describe("setFavorite", () => {
  it("stars a source with the current time and queues set_favorite", () => {
    const db = makeTestDb();
    seedSource(db, {});

    setFavorite(db, "s1", true);

    expect(sourceById(db, "s1")?.favoritedAt).not.toBeNull();
    expect(outboxEntries(db)).toEqual([{ type: "set_favorite", payload: { id: "s1", favorited: true } }]);
  });

  it("unstarring clears the star and changes nothing else", () => {
    const db = makeTestDb();
    seedSource(db, { favoritedAt: "2026-11-03T00:00:00Z", state: "queued", queuePosition: 2 });

    setFavorite(db, "s1", false);

    expect(sourceById(db, "s1")).toMatchObject({ favoritedAt: null, state: "queued", queuePosition: 2 });
    expect(outboxEntries(db)).toEqual([{ type: "set_favorite", payload: { id: "s1", favorited: false } }]);
  });

  it("starring an already-starred source keeps its first star time", () => {
    const db = makeTestDb();
    seedSource(db, { favoritedAt: "2026-11-03T00:00:00Z" });

    setFavorite(db, "s1", true);

    expect(sourceById(db, "s1")?.favoritedAt).toBe("2026-11-03T00:00:00Z");
  });
});
```

In `engine.test.ts` ("database SyncStore" block; import `setFavorite`):

```ts
  it("stores a pulled source's favorited_at, and a missing one as null", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({ favorited_at: "2026-11-03T00:00:00Z" })], artifacts: [], cards: [] },
      position: 1,
      more: false,
    });
    expect(sourceRow(db)?.favoritedAt).toBe("2026-11-03T00:00:00Z");

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });
    expect(sourceRow(db)?.favoritedAt).toBeNull();
  });

  it("a re-pull of a source with an unsent set_favorite keeps the local star", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 1, more: false });
    setFavorite(db, "s1", true);

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });

    expect(sourceRow(db)?.favoritedAt).not.toBeNull();
  });

  it("a rejected set_favorite rewinds the position and surfaces syncError on the source", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 5, more: false });
    setFavorite(db, "s1", true);
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "source not found");

    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBe("source not found");
  });

  // 0008 only adds a column; the test guards against a generated table rebuild that drops or mis-copies rows.
  it("the 0008_favorites migration keeps existing sources, unstarred", () => {
    const sqlite = new Database(":memory:");
    const sqlByKey = migrations.migrations as Record<string, string>;
    const runMigration = (idx: number) => {
      for (const statement of sqlByKey[`m${String(idx).padStart(4, "0")}`].split("--> statement-breakpoint")) {
        if (statement.trim()) sqlite.exec(statement);
      }
    };
    const favoritesIdx = migrations.journal.entries.find((entry) => entry.tag === "0008_favorites")!.idx;
    for (let idx = 0; idx < favoritesIdx; idx++) runMigration(idx);
    sqlite
      .prepare(
        "INSERT INTO sources (id, url, kind, state, intent, created_at, updated_at, domain, cards_off) " +
          "VALUES ('s1', 'https://example.com/a', 'article', 'queued', 'queue', 'x', 'x', 'AI', 1)",
      )
      .run();

    runMigration(favoritesIdx);

    expect(sqlite.prepare("SELECT * FROM sources").all()).toEqual([
      expect.objectContaining({ id: "s1", state: "queued", domain: "AI", cards_off: 1, favorited_at: null }),
    ]);
  });
```

and add `"0008_favorites"` to the `it.each([...])` list of migrations that end by resetting the saved position.

- [ ] **Step 5: Implement.**

`actions.ts`: add `| "set_favorite"` to `ActionType` (after `"request_news_quiz"`), and after `setCardsOff`:

```ts
/** Stars or unstars a source; starring again keeps the first star's time, as the server does. */
export function setFavorite(db: AppDb, sourceId: string, favorited: boolean): void {
  db.transaction((tx) => {
    const favoritedAt = favorited ? sql`coalesce(${schema.sources.favoritedAt}, ${new Date().toISOString()})` : null;
    updateSource(tx, sourceId, { favoritedAt });
    enqueue(tx, "set_favorite", { id: sourceId, favorited });
  });
}
```

`engine.ts` `PulledSource`: add `favorited_at?: string | null;` after `cards_off?: boolean;`.

`transport.ts`:
- `applyPage` sources `values`: `favoritedAt: source.favorited_at ?? null,` after `cardsOff`.
- `REWOUND_SOURCE_ACTIONS` gains `"set_favorite"` (a rejection must undo the optimistic star by re-pulling the server's copy).

- [ ] **Step 6: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 7: Commit** "App: favorites data layer (sources.favorited_at, migration 0008, set_favorite)".

---

## Parallel-safe tasks

Each runs in its own worktree from Task 1's commit (`git gtr new snf-t<N> --from-current --yes` inside `saved-nav-favorites`), with the `app/node_modules` symlink, and merges back when done.

### Task 2: Server: `sources.favorited_at`, migration 0008, `set_favorite`  (tier: standard)

**Files:**
- Create: `packages/archie-db/archie_db/migrations/versions/0008_favorites.py`, `services/api/tests/e2e/test_favorites_e2e.py`
- Modify: `packages/archie-db/archie_db/models.py` (`Source`), `services/api/archie_api/sync/schemas.py` (`ActionType`, `SourceOut`), `services/api/archie_api/sync/actions.py` (`HANDLERS`), `services/api/archie_api/sync/source_actions.py`

**Interfaces:**
- Consumes: nothing from other tasks (the wire contract is in Global Constraints).
- Produces: `models.Source.favorited_at: Mapped[datetime.datetime | None]`; `schemas.ActionType.SET_FAVORITE = "set_favorite"`; `schemas.SourceOut.favorited_at: datetime.datetime | None`; `source_actions.set_favorite`.
- Depends on: Task 1 (only for ordering; no code dependency).
- Review: yes (migration, sync shape).

- [ ] **Step 1: Test DB.** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t2` (ignore "already exists"). Tests below run with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t2`.

- [ ] **Step 2: Write the failing e2e test** `services/api/tests/e2e/test_favorites_e2e.py`:

```python
"""Favorites through the real API: set_favorite stars and unstars a source, and the pull carries favorited_at."""

import uuid
from typing import Any

import httpx
import pytest
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

# Columns a star is allowed to change; everything else about the source must stay as it was.
_STAR_COLUMNS = {"favorited_at", "updated_at", "change_seq"}


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _source(authed: httpx.Client, source_id: str) -> dict[str, Any]:
    rows = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return next(row for row in rows["sources"] if row["id"] == source_id)


def _add(authed: httpx.Client) -> str:
    source_id = str(uuid.uuid4())
    _push(authed, _action("add_source", {"id": source_id, "url": f"https://example.com/{source_id}", "intent": "queue"}))
    return source_id


def _star(authed: httpx.Client, source_id: str, *, favorited: bool) -> dict[str, Any]:
    return _push(authed, _action("set_favorite", {"id": source_id, "favorited": favorited}))[0]


def test_starring_and_unstarring_round_trip_through_the_pull(authed: httpx.Client) -> None:
    """A star sets favorited_at and a fresh change_seq; unstarring clears it with another."""
    source_id = _add(authed)
    before = _source(authed, source_id)

    _star(authed, source_id, favorited=True)
    starred = _source(authed, source_id)
    _star(authed, source_id, favorited=False)
    unstarred = _source(authed, source_id)

    assert before["favorited_at"] is None
    assert starred["favorited_at"] is not None
    assert starred["change_seq"] > before["change_seq"]
    assert unstarred["favorited_at"] is None
    assert unstarred["change_seq"] > starred["change_seq"]


def test_starring_changes_nothing_else_about_the_source(authed: httpx.Client) -> None:
    """State, queue position, processing and the rest are untouched by a star."""
    source_id = _add(authed)
    before = _source(authed, source_id)

    _star(authed, source_id, favorited=True)
    after = _source(authed, source_id)

    unchanged_before = {key: value for key, value in before.items() if key not in _STAR_COLUMNS}
    unchanged_after = {key: value for key, value in after.items() if key not in _STAR_COLUMNS}
    assert unchanged_after == unchanged_before


def test_starring_a_starred_source_again_keeps_its_first_star(authed: httpx.Client) -> None:
    """A second star (a new action id) is applied without a write, so favorites keep their order."""
    source_id = _add(authed)
    _star(authed, source_id, favorited=True)
    first = _source(authed, source_id)

    result = _star(authed, source_id, favorited=True)
    second = _source(authed, source_id)

    assert result["result"] == "applied"
    assert (second["favorited_at"], second["change_seq"]) == (first["favorited_at"], first["change_seq"])


def test_set_favorite_refuses_other_users_deleted_and_malformed(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Someone else's source and a deleted one are not found; a payload without `favorited` is malformed."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    source_id = _add(authed)
    deleted_id = _add(authed)
    _push(authed, _action("delete_source", {"id": deleted_id}))

    foreign = _push(other, _action("set_favorite", {"id": source_id, "favorited": True}))
    own = _push(
        authed,
        _action("set_favorite", {"id": deleted_id, "favorited": True}),
        _action("set_favorite", {"id": source_id}),
    )

    assert [result["reason"] for result in foreign + own] == [
        "source not found",
        "source not found",
        "payload is malformed",
    ]
    assert _source(authed, source_id)["favorited_at"] is None
```

Run: `TEST_DATABASE_URL=… uv run pytest services/api/tests/e2e/test_favorites_e2e.py -m postgres -v` — fails (`favorited_at` missing from the pull / action not supported).

- [ ] **Step 3: Model.** In `models.py` `Source`, after `cards_off`:

```python
    # When the user starred it; null = not starred. Starring changes nothing else about the source.
    favorited_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
```

- [ ] **Step 4: Migration** `packages/archie-db/archie_db/migrations/versions/0008_favorites.py`:

```python
"""Favorites: when a source was starred.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy
from alembic import op

revision = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add `sources.favorited_at` (null = not starred)."""
    op.add_column("sources", sqlalchemy.Column("favorited_at", sqlalchemy.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop `sources.favorited_at`; stars are lost."""
    op.drop_column("sources", "favorited_at")
```

`test_db_migrations.py`'s `test_models_match_the_migrations` and `test_downgrade_then_upgrade_round_trips` cover it; no new migration test is needed for a nullable column add.

- [ ] **Step 5: Schemas.** `ActionType` gains `SET_FAVORITE = "set_favorite"` after `REQUEST_NEWS_QUIZ`; `SourceOut` gains `favorited_at: datetime.datetime | None` after `cards_off`.

- [ ] **Step 6: Handler** in `source_actions.py` (payload class beside `_ReadPayload`; function after `set_read`):

```python
class _FavoritePayload(_SourcePayload):
    favorited: bool


def set_favorite(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Star a source or clear its star; asking for the state it is already in writes nothing.

    Starring again keeps the first star's time, so "newest star first" doesn't reshuffle when a phone resends.
    """
    parsed = rows.parse(_FavoritePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    source = rows.owned_source(db, user=user, source_id=parsed.id)
    if source is None:
        return rows.NO_SOURCE
    if parsed.favorited == (source.favorited_at is not None):
        return None

    source.favorited_at = sqlalchemy.func.now() if parsed.favorited else None
    changes.touch(source)
    return None
```

Register in `actions.py` `HANDLERS` after `SET_PREP_ME`: `schemas.ActionType.SET_FAVORITE: source_actions.set_favorite,`. Also add `("set_favorite", {"id": source_id, "favorited": True})` to the payload list of `test_another_users_source_is_not_found` in `services/api/tests/e2e/test_source_actions_e2e.py`.

- [ ] **Step 7: Run** `make lint` and `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t2 uv run pytest -m "postgres or not postgres"` — all pass (including the migration tests and M6's `set(actions.HANDLERS) == set(schemas.ActionType)` check).
- [ ] **Step 8: Commit** "Server: sources.favorited_at (migration 0008) and the set_favorite action".

### Task 3: App navigation: four tabs, the Library header ＋, the add sheet as a modal  (tier: standard)

**Files:**
- Delete: `app/src/app/(tabs)/add.tsx`
- Create: `app/src/app/add.tsx`
- Modify: `app/src/app/(tabs)/_layout.tsx`, `app/src/app/_layout.tsx`, `app/src/theme/components/Screen.tsx`, `app/src/app/(tabs)/library.tsx` (header only)

**Interfaces:**
- Consumes: nothing from Tasks 4–5.
- Produces: route `/add` (modal); `Screen` prop `sheet?: boolean`; testIDs `library-add`, `add-cancel` (plus the existing `add-url`, `add-paste`, `add-save`, `intent-*`).
- Depends on: Task 1 (ordering only).
- Review: no.

- [ ] **Step 1: Tab bar** (`(tabs)/_layout.tsx`): `TABS` becomes Today, Library, Review, Ask (remove the `add` entry). Delete `AddCircle`, `ADD_BUTTON_SIZE` and the `tab.name === "add"` branch: every tab now uses `tabBarIcon: ({ color, size }) => <Ionicons … />`. Delete `app/src/app/(tabs)/add.tsx`.

- [ ] **Step 2: `Screen` for a sheet.** Add `sheet?: boolean` to `ScreenProps` (comment: "Presented as a modal sheet: the sheet already sits below the status bar, so no top safe-area inset."). When `sheet`, the root's `paddingTop` is `theme.spacing.md` instead of `insets.top`, and the footer's bottom padding stays as is.

- [ ] **Step 3: The add route** `app/src/app/add.tsx`: move the old tab's body here with these changes:
  - `<Screen title="Add" sheet headerRight={<Pressable testID="add-cancel" onPress={router.back} hitSlop={12}><Text tone="ink2">Cancel</Text></Pressable>}>`.
  - Keep the hint text, `add-url` field, `add-paste` button, `<CaptureOptions value={choice} onChange={setChoice} />` and `add-save` exactly as they were (same `isHttpUrl`, same `addSource` call, `requestSync()`).
  - `save()` ends with `router.back()` instead of resetting state and `router.navigate("/library")` (the screen unmounts, so no reset is needed). Comment: "Save closes the sheet and stays on whatever presented it (Library)."
  - Root `_layout.tsx`: inside the signed-in `Stack.Protected` block add `<Stack.Screen name="add" options={{ presentation: "modal" }} />`.

- [ ] **Step 4: Library header ＋** (`(tabs)/library.tsx`): pass `headerRight` to `Screen`:

```tsx
// Adding starts here now that the ＋ tab is gone: the same filled chrome circle, opening the add sheet.
<Pressable
  testID="library-add"
  accessibilityLabel="Add"
  onPress={() => {
    haptic("light");
    router.push("/add");
  }}
  hitSlop={8}
  style={{
    width: HEADER_ADD_SIZE,
    height: HEADER_ADD_SIZE,
    borderRadius: HEADER_ADD_SIZE / 2,
    backgroundColor: theme.colors.chrome,
    alignItems: "center",
    justifyContent: "center",
  }}
>
  <Ionicons name="add" size={24} color={theme.colors.onChrome} />
</Pressable>
```

with `const HEADER_ADD_SIZE = 36;` and `const router = useRouter();`. Touch nothing else in `library.tsx` (Task 4 rewrites the modes).

- [ ] **Step 5: Check** `rg -n "tab-add|\"/add\"|/\(tabs\)/add|navigate\(\"/add" app/src` — only the new `router.push("/add")` remains. Run `cd app && npm run typecheck && npx jest` — pass. (Typed routes: if `/add` isn't known to the type checker yet, `npx expo customize` is not needed; starting Metro once with `npx expo start` regenerates `.expo/types`. Don't commit `.expo/`.)
- [ ] **Step 6: Commit** "App: four tabs; Library header ＋ opens the add sheet as a modal".

### Task 4: App Library modes, Saved → Favorites, and the favorites-by-domain page  (tier: standard)

**Files:**
- Create: `app/src/library/favorites.ts`, `app/src/library/favorites.test.ts`, `app/src/library/SavedView.tsx`, `app/src/library/TakesView.tsx`, `app/src/app/favorites/[domain].tsx`
- Modify: `app/src/app/(tabs)/library.tsx` (modes), `app/src/app/_layout.tsx` (route), `app/src/ui/SourceRow.tsx` (`kickerSuffix`)

**Interfaces:**
- Consumes: `schema.sources.favoritedAt` and `setFavorite(db, sourceId, favorited)` (Task 1); `LibraryData`/`LibrarySource` (`@/library/join`), `asDomain`/`DOMAINS`/`DomainName` (`@/topics/domains`), `slugify` (`@/topics/topicName`), `kindLabel` (`@/ui/sourceLabels`), `MONTHS` (`@/today/todayLabels`), `SwipeRow` (`@/library/SwipeRow`), `GroupedList`, `Kicker`.
- Produces: `favoriteDomains(sources: LibrarySource[]): FavoriteDomain[]`, `domainFavorites(sources: LibrarySource[], domain: DomainName): LibrarySource[]`, `favoriteMeta(source: { kind: string; favoritedAt: string }): string`, `FAVORITE_PREVIEW_TITLES = 2`; route `/favorites/[domain]`; `SourceRow` prop `kickerSuffix?: string`.
- Depends on: Task 1.
- Review: yes (the largest UI change; the Library is the app's main screen).

- [ ] **Step 1: Write the failing tests** `app/src/library/favorites.test.ts` (rows from `testRows.ts` helpers if they fit, otherwise a local `source(overrides)` that spreads a `LibrarySource` with `topic: null, summary: null, primerCreatedAt: null, primerWords: null`):
  - `favoriteDomains` with no starred sources → `[]`.
  - Three AI favorites, one Crypto, one with `domain: null`, and an unstarred Macro source → `[{domain: "AI", count: 3, …}, {domain: "Crypto", count: 1}, {domain: "Other", count: 1}]` (Macro hidden; Crypto before Other on the tie, by `DOMAINS` order).
  - An AI group's `newestTitles` are its two newest-starred titles (by `favoritedAt`, not `createdAt`), and an untitled one shows its URL.
  - `domainFavorites(sources, "AI")` returns only starred AI sources, newest star first; `domainFavorites(sources, "Other")` includes the domain-less one.
  - `favoriteMeta({ kind: "x", favoritedAt: new Date(2026, 10, 3, 12).toISOString() })` → `"X post · starred Nov 3"`.

  Run `cd app && npx jest src/library/favorites.test.ts` — fails (module missing).

- [ ] **Step 2: Implement** `app/src/library/favorites.ts`:

```ts
import { MONTHS } from "@/today/todayLabels";
import { asDomain, DOMAINS, type DomainName } from "@/topics/domains";
import { kindLabel } from "@/ui/sourceLabels";

import type { LibrarySource } from "./join";

export const FAVORITE_PREVIEW_TITLES = 2;

export type FavoriteDomain = { domain: DomainName; count: number; newestTitles: string[] };

/** A source with no domain yet (unfiled, or filing failed) is grouped under Other, as its row's kicker reads. */
function favoriteDomain(source: LibrarySource): DomainName {
  return asDomain(source.domain);
}

function newestStarFirst(sources: LibrarySource[]): LibrarySource[] {
  return [...sources].sort((a, b) => (b.favoritedAt ?? "").localeCompare(a.favoritedAt ?? ""));
}

/** The starred sources of one domain, newest star first. */
export function domainFavorites(sources: LibrarySource[], domain: DomainName): LibrarySource[] {
  return newestStarFirst(sources.filter((source) => source.favoritedAt !== null && favoriteDomain(source) === domain));
}

/** Saved's Favorites rows: one per domain with stars, biggest first, ties in `DOMAINS` order. */
export function favoriteDomains(sources: LibrarySource[]): FavoriteDomain[] {
  const groups = DOMAINS.map((domain): FavoriteDomain => {
    const favorites = domainFavorites(sources, domain);
    return {
      domain,
      count: favorites.length,
      newestTitles: favorites.slice(0, FAVORITE_PREVIEW_TITLES).map((source) => source.title ?? source.url),
    };
  });

  // Array.sort is stable, so equal counts keep DOMAINS order.
  return groups.filter((group) => group.count > 0).sort((a, b) => b.count - a.count);
}

/** The favorites page's row meta: "X post · starred Nov 3". */
export function favoriteMeta(source: { kind: string; favoritedAt: string }): string {
  const starred = new Date(source.favoritedAt);
  return `${kindLabel(source.kind)} · starred ${MONTHS[starred.getMonth()]} ${starred.getDate()}`;
}
```

  Run the test — passes.

- [ ] **Step 3: `SourceRow` kicker suffix.** Add `kickerSuffix?: string` to `SourceRowProps`; pass `kicker={{ domain: source.domain, suffix: kickerSuffix }}`.

- [ ] **Step 4: `SavedView`** (`app/src/library/SavedView.tsx`, props `{ data: LibraryData }`), root `View testID="saved-view"`:
  - `const groups = favoriteDomains(data.sources)`. When empty: a centered `Text tone="ink2"` with testID `saved-empty`: "Star items to keep them here, or save something just for fun to a collection."
  - Otherwise `<GroupedList testID="saved-favorites" title={`Favorites · ${total}`}>` (total = sum of counts; the monoLabel title renders uppercase) with one `Pressable` row per group, testID `favorites-domain-${slugify(group.domain)}`, `onPress` → `router.push({ pathname: "/favorites/[domain]", params: { domain: group.domain } })` with `haptic("light")`. Row layout as `DomainsView`'s card header: a 10pt domain-colored dot (`theme.domains[group.domain]`), a column with the domain name (`variant="headline"`) over `group.newestTitles.join(" · ")` (`variant="secondary" tone="ink3" numberOfLines={1}`), and on the right `Text tone="ink3"` `${group.count} ›`.
  - No Collections section (piece 2).

- [ ] **Step 5: `TakesView`** (`app/src/library/TakesView.tsx`, no props): a centered `Text tone="ink2"` with testID `takes-empty`: "Things you think, in your own words". Comment: "Piece 3 adds the Write a take button and the list; until then only the empty state shows."

- [ ] **Step 6: Library modes** (`(tabs)/library.tsx`):
  - `type Mode = "all" | "domains" | "saved" | "takes";` and `MODES` = All, Domains, Saved, Takes (testIDs stay `library-mode-${mode}`, so List's becomes `library-mode-all`). The segmented control stays full width under the title, as it is.
  - Initial mode `"all"`; the Today-link effect sets `"all"`.
  - The search field and `LibraryList` render only when `mode === "all"` (drop the `showList` "typing switches to the list" rule; comment: "Search and filter chips belong to All."). `domains` → `<DomainsView data={data} />`, `saved` → `<SavedView data={data} />`, `takes` → `<TakesView />`.
  - Leave the header's `headerRight` alone if Task 3's ＋ is already there after merge.

- [ ] **Step 7: The favorites page** `app/src/app/favorites/[domain].tsx`, registered as `<Stack.Screen name="favorites/[domain]" />` in the root `_layout.tsx`'s signed-in block:
  - `const domain = asDomain(useLocalSearchParams<{ domain: string }>().domain ?? null)`; `const favorites = domainFavorites(useLibraryData().sources, domain)`.
  - `<Screen title={domain} onBack={router.back}>` with a root `View testID="favorites-page"`; first child `<Kicker domain={domain} label="Favorites" />`.
  - The list: `<GroupedList>` of `<SwipeRow actions={[unstar]}>` wrapping `<SourceRow source={source} testID={`favorite-row-${source.id}`} kickerSuffix={source.topic?.name} meta={favoriteMeta({ kind: source.kind, favoritedAt: source.favoritedAt! })} />`, where `unstar = { key: "unstar", label: "Unstar", tone: "neutral", testID: `favorite-unstar-${source.id}`, onPress: () => { setFavorite(db, source.id, false); requestSync(); } }`. Tapping a row opens the item page (SourceRow's default).
  - With no favorites left (the last one was unstarred): `Text tone="ink2"` "No favorites in {domain} yet." in place of the list (the page stays open; back returns to Saved).

- [ ] **Step 8: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 9: Commit** "App: Library All · Domains · Saved · Takes; Saved favorites by domain and the favorites page".

### Task 5: App ★ on the item page and in row kickers  (tier: cheap)

**Files:**
- Modify: `app/src/theme/tokens.ts`, `app/src/ui/Kicker.tsx`, `app/src/ui/SourceRow.tsx`, `app/src/item/ItemHeader.tsx`, `app/src/app/source/[id].tsx`

**Interfaces:**
- Consumes: `schema.sources.favoritedAt`, `setFavorite` (Task 1).
- Produces: `Signal` gains `"favorite"` (`theme.signals.favorite`); `Kicker` prop `starred?: boolean`; testID `item-favorite`.
- Depends on: Task 1.
- Review: no.

- [ ] **Step 1: Token.** `tokens.ts`: `Signal` gains `"favorite"`; `signalColors.light.favorite = "#B8892A"`, `signalColors.dark.favorite = "#D9B45A"` (comment: "The favorites ★, and nothing else.").

- [ ] **Step 2: Kicker star.** `Kicker` gains `starred?: boolean`; when set, the kicker text is followed by a nested `<Text style={{ color: theme.signals.favorite }}> ★</Text>` inside the same one-line `Text` (so it stays on the kicker's line and truncates with it). `SourceRow` passes `starred: source.favoritedAt !== null` in its `kicker` prop.

- [ ] **Step 3: Item page button.** In `source/[id].tsx`, `headerRight` becomes a row (`flexDirection: "row", alignItems: "center", gap: theme.spacing.lg`) of:

```tsx
<Pressable
  testID="item-favorite"
  accessibilityLabel={starred ? "Remove from favorites" : "Add to favorites"}
  onPress={() => {
    haptic("selection");
    setFavorite(db, source.id, !starred);
    requestSync();
  }}
  hitSlop={12}
>
  <Ionicons name={starred ? "star" : "star-outline"} size={24} color={starred ? theme.signals.favorite : theme.colors.ink} />
</Pressable>
```

followed by the existing `item-more` •••, with `const starred = source.favoritedAt !== null;` after the source guard.

- [ ] **Step 4: By-line.** In `ItemHeader.tsx`, the `item-byline` text becomes `` `${datedByline(source, now)}${source.favoritedAt ? " · ★ Favorite" : ""}` `` (comment: "The star is repeated in the by-line so it's visible below the navbar too.").

- [ ] **Step 5: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 6: Commit** "App: ★ favorite button on the item page and a gold star in starred rows".

---

## Integration task (serial, in `saved-nav-favorites`, after Tasks 2–5 are merged)

### Task 6: Merge check, Maestro flows, docs, full verification  (tier: standard; Maestro runs by the coordinator)

**Files:**
- Create: `maestro/favorites.yaml`
- Modify (off `tab-add`): `maestro/add_link.yaml`, `maestro/add_podcast.yaml`, `maestro/finish_item.yaml`, `maestro/library_queue.yaml`, `maestro/library_search.yaml`, `maestro/offline_2_add.yaml`, `maestro/review.yaml`, `maestro/source_page.yaml`, `maestro/today_primer.yaml`
- Modify: `Makefile` (`maestro` target), `maestro/README.md`, `docs/superpowers/specs/2026-10-26-product-scope.md`, `docs/superpowers/specs/2026-11-05-saved-and-takes-design.md` (status line)
- Review: no.

- [ ] **Step 1: Merge check.** `git log --oneline` shows Tasks 2–5 merged. `cd app && rg -n "library-mode-list|tab-add|\"list\"" src` prints nothing relevant (no leftover List mode or add tab). `library.tsx` has both Task 3's `headerRight` ＋ and Task 4's four modes; root `_layout.tsx` registers both `add` (modal) and `favorites/[domain]`; `SourceRow` has both `kickerSuffix` and `starred`.

- [ ] **Step 2: Suites:** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t6` (ignore "already exists"); `make lint`; `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t6 uv run pytest -m "postgres or not postgres"` — all pass; `cd app && npm run typecheck && npx jest` — pass.

- [ ] **Step 3: Move every flow off `tab-add`.** In each of the nine flows listed above, every `id: "tab-add"` becomes `id: "library-add"` (keep each flow's "first tap is sometimes swallowed" retry block, now retrying `library-add`). Every flow reaches the add step from Library (login lands there, and Save now returns to it), except where a flow taps another tab first: before each `library-add` tap that follows a `tab-today`/`tab-review` tap, insert `- tapOn:\n    id: "tab-library"`. Confirm with `rg -n "tab-add" maestro` (nothing) and `rg -n "library-mode-list" maestro` (nothing). Comments that say "Saving lands on Library" stay true.

- [ ] **Step 4: New flow** `maestro/favorites.yaml` (free to run: the dev user isn't whitelisted, so the source fails at analyze, keeps no domain and groups under Other):

```yaml
appId: com.sampocs.archie
---
# Star an item from its page, find it under Library → Saved → its domain, then unstar it there with a swipe.
# The dev test user isn't whitelisted, so the source never gets a domain and is grouped under Other.
- runFlow: login.yaml
- tapOn:
    id: "library-add"
# The first tap right after login is sometimes swallowed while the screen settles.
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
- inputText: "https://example.com/"
- tapOn:
    id: "intent-queue"
- tapOn:
    id: "add-save"
# Save closes the sheet and stays on Library; open the new row.
- tapOn:
    text: ".*example\\.com.*"
- tapOn:
    id: "item-favorite"
- assertVisible:
    id: "item-byline"
    text: ".*★ Favorite.*"
- tapOn:
    id: "screen-back"
- tapOn:
    id: "library-mode-saved"
- assertVisible:
    id: "saved-favorites"
- tapOn:
    id: "favorites-domain-other"
- assertVisible:
    id: "favorites-page"
- assertVisible:
    text: ".*example\\.com.*"
- swipe:
    from:
      text: ".*example\\.com.*"
    direction: LEFT
- tapOn:
    id: "favorite-unstar-.*"
- assertVisible: "No favorites in Other yet."
- tapOn:
    id: "screen-back"
- assertVisible:
    id: "saved-empty"
```

(If `assertVisible` with both `id` and `text` doesn't match the byline on the simulator, assert `text: ".*★ Favorite.*"` alone. The row text matches the meta line "Link · example.com" or the title "Example Domain" depending on whether the title arrived; `.*example\\.com.*` matches the meta either way, as `library_queue.yaml` relies on.)

- [ ] **Step 5: Makefile and docs.**
  - `Makefile`: add `maestro/favorites.yaml` to the `maestro` target's list (after `maestro/library_search.yaml`).
  - `maestro/README.md`: a table row for `favorites.yaml` ("Star an item from its page, find it under Library → Saved → Other, unstar it with a swipe; Saved shows its empty state"); `add_link.yaml`'s row says the link is added from the Library ＋.
  - Product scope (`2026-10-26-product-scope.md`), Screens: the tab bar line becomes **Today · Library · Review · Carl** (keep the doc's assistant name); the "### ＋ (Add)" section becomes "The ＋ in the Library header opens the add sheet: the same Finished / Queue flow as the share sheet."; Library: a four-way control under the title, **All · Domains · Saved · Takes** (search and filters belong to All); a **Saved** bullet: Favorites, a ★ on any library item (item page navbar, a gold ★ on its row), grouped by domain on Saved, each domain's favorites newest star first, swipe to unstar; Takes is a placeholder until takes ship. Replace "a toggle at the top of Library" in the Domains bullet with "the Domains segment".
  - Spec (`2026-11-05-saved-and-takes-design.md`): under the title add "**Status:** Piece 1 (Nav + Favorites) implemented on `saved-nav-favorites` (plan `docs/superpowers/plans/2026-11-05-saved-nav-favorites.md`); migration numbers moved to `0008_favorites` because M6 took 0007."
- [ ] **Step 6: Commit** "Saved piece 1: Maestro favorites flow, flows off the add tab, docs".
- [ ] **Step 7 (coordinator, main checkout):** the branch is held by its worktree, so in the main checkout `git checkout --detach saved-nav-favorites`. Then `make db-up`, `make migrate-local`, `make start-local` in one terminal; boot the simulator and `cd app && npx expo run:ios` (no new native modules, so the installed dev build with `npx expo start` also works; the app's migration 0008 runs on launch). Run `make maestro` (every existing flow plus `favorites.yaml`), and `make maestro-offline`. `make maestro-review`/`maestro-podcast` spend real credits: run them only if the owner asks (their only change is the `library-add` tap, which the free flows exercise). A failure caused by a real outside change is reported, not papered over. Afterwards stop the backend and Metro and `git checkout main` in the main checkout.
- [ ] **Step 8:** `git status` clean apart from intended changes; `saved-nav-favorites` ready for a PR (do not push or merge unless asked).

---

## Self-review notes

- Spec coverage (piece 1 of Build order): tab bar to four tabs and delete the add tab (T3); Library header ＋ in the filled chrome circle (T3); four-way segmented control with List → All, search and chips under All only (T4, Decision 3); add sheet as a modal route `app/src/app/add.tsx` with Finished/Queue exactly as `CaptureOptions`, Save closes and stays on Library (T3, Decision 8); `sources.favorited_at` + `set_favorite` (T2 server, T1 phone, wire contract in Global Constraints); ★ navbar button next to ••• and "· ★ Favorite" by-line (T5); gold ★ after the domain kicker on starred rows (T5, Decision 7); any source starrable, newsletters included (T2 has no kind check, T5 shows the button on every source); Library → Saved with "Favorites · N", one row per domain sorted by count with the dot, name, newest two titles and count, no section when nothing is starred, Saved empty state (T4, Decisions 2, 4, 5); favorites-by-domain page `app/src/app/favorites/[domain].tsx` newest star first, "Domain · Topic" kicker, swipe left to unstar, tap opens the item (T4); Takes segment empty state (T4, Decision 1). Testing: server e2e push → pull for the new action (T2); app jest favorites grouping (counts, order, empty domains hidden) (T4); Maestro "star an item, then find it under Saved → its domain" (T6). Docs: product scope updated as the spec asks "when each piece ships" (T6).
- Not in this piece by design: Collections section and add-sheet choice, share extension, "Write a take", Takes list (pieces 2 and 3).
- Types: `setFavorite(db, sourceId, favorited)` (T1) is what T4 and T5 call; `favoritedAt` (phone) / `favorited_at` (wire, server) match; `favoriteDomains`/`domainFavorites`/`favoriteMeta` are defined and used only in T4; `SourceRow` gets `kickerSuffix` (T4) and passes `starred` to `Kicker` (T5) — both edits are additive.
- Review tags: T1 yes (migration, sync), T2 yes (migration, sync shape), T4 yes (main screen), T3, T5, T6 no.
