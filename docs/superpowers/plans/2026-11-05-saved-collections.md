# Saved and Takes, piece 2: Collections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collections: just-for-fun scrapbooks the owner saves links into from the add sheet or the share sheet, shown as tiles under Library → Saved and as a feed of posts on a collection page, and never anywhere on the learning side.

**Architecture:**
- DB (`0009_collections`): two new synced tables, `collections` and `collection_items` (client-made ids, `change_seq`, soft delete). Collection items are **not** sources: no existing query reads these tables, so nothing on the learning side needs a filter.
- API: four push actions in a new `services/api/archie_api/sync/collection_actions.py` (`create_collection`, `update_collection`, `add_collection_item`, `update_collection_item`); pull ships both tables.
- Worker: one job, `fetch_collection_item`, that fills a post's preview (title, author, thumbnail, video length) with the existing X (fxtwitter → vxtwitter), YouTube watch-page and og:title/og:image readers.
- App: drizzle migration 0009 and sync of both tables; optimistic actions; a `collections` folder (pure grouping/labels, a live hook, name/delete prompts, and a mirror of the collection list into the shared Keychain group the share extension already reads); the add sheet's "Save to a collection" choice (native action sheet + name prompt); the share extension's same choice (chips + an inline name field); Saved → Collections tiles; the collection page `app/src/app/collection/[id].tsx`.

**Tech Stack:** as piece 1 (FastAPI, SQLAlchemy/Alembic, Postgres; Expo Router, drizzle + expo-sqlite, expo-secure-store, expo-image, jest, Maestro, pytest-recording/vcrpy). No new packages, no new native modules: the dropdown is React Native's `ActionSheetIOS`, the name prompt `Alert.prompt`.

**Spec:** `docs/superpowers/specs/2026-11-05-saved-and-takes-design.md` (owner-approved; piece 2 of its Build order). Mocks `2026-11-05-saved-and-takes-mocks.html`, screens 02, 03 and 06; where the mocks and the spec differ, the spec wins. UX rules: `docs/superpowers/specs/2026-10-29-ux-and-brand-design.md`. Piece 1's plan (`2026-11-05-saved-nav-favorites.md`) is the house template this one follows.

## Global Constraints

- **Python style:** `AGENTS.md` house style (module-qualified imports as the repo does them, e.g. `from archie_db import changes, models` then `changes.touch(...)`; classes/`typing` by name; full typing with `X | None`; `StrEnum`s for compared strings; dataclasses over tuples of >2; named parameters; guard clauses; blank-line paragraphs past ~8 lines; why-comments; docstrings on public functions/classes).
- **The boundary:** a collection item is never a source. No code in this piece writes `sources`, `source_captures`, `source_artifacts`, `cards` or pipeline jobs for a collection item, and no existing source/library/search/Today/Pulse/Ask/review query is changed to read the new tables. The only places collections show are Library → Saved and the collection page.
- **Action contract:** every push action handler has the signature `(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None` (rejection reason or None) and runs under the batch's user lock inside a savepoint. **A handler validates everything before its first write**: returning a reason does *not* roll back earlier writes. Every changed collection or item gets a fresh `change_seq` via `changes.touch` (inserts take `changes.next_change_seq()`).
- **Wire payloads** (snake_case; `id` is always the row the action changes, which the phone's "keep the local copy while an action is unsent" rule in `transport.applyPage` relies on):

  | type | payload | server effect |
  |---|---|---|
  | `create_collection` | `{id, name}` | inserts it at the end (`position` = highest live position + 1, or 0) |
  | `update_collection` | `{id, name?, position?, deleted?}` | rename, reorder, or delete (`deleted: true` soft-deletes it **and every live item in it**) |
  | `add_collection_item` | `{id, collection_id, url, note?}` | inserts it (`kind` from the URL: `x`, `youtube`, else `link`; `metadata_status` `pending`) and queues one `fetch_collection_item` job |
  | `update_collection_item` | `{id, note?, collection_id?, deleted?}` | edit the note (`note` present: blank or null clears it), move it to another of the user's live collections, or remove it (`deleted: true`) |

  Rejections (exact strings): `rows.MALFORMED` ("payload is malformed"); "collection not found" (unknown, another user's or deleted collection, including a move target); "collection item not found"; "collection name is empty"; "collection name is longer than 100 characters"; "note is longer than 2000 characters"; "id already exists"; the URL reasons from `capture.validate_url` ("url must be http or https", "url is longer than 2048 characters", "url is not a valid URL"). Names are stored with whitespace collapsed; duplicate names are allowed. `deleted: false` is ignored (there is no undelete).
- **Pulled rows:** `rows.collections: [{id, name, position, created_at, updated_at, deleted_at, change_seq}]` and `rows.collection_items: [{id, collection_id, url, kind, title, author, image_url, duration_seconds, note, metadata_status, created_at, updated_at, deleted_at, change_seq}]`. Both keys are optional on the phone (`?? []`): an older server omits them.
- **Job:** `JobKind.FETCH_COLLECTION_ITEM = "fetch_collection_item"`, payload `{"collection_item_id": "<uuid>"}` (`jobs.COLLECTION_ITEM_ID_KEY`). Standard attempts (3) and backoff. A 4xx page (other than 429) fails it at once; anything else retries. When it fails for good the item's `metadata_status` becomes `failed` and it keeps its URL. No Retry button.
- **Migration numbers:** server `0009` (`packages/archie-db/archie_db/migrations/versions/0009_collections.py`, revises `0008`); app drizzle `0009_collections`. (The spec's `0008_collections` predates M6 taking 0007.)
- **Drizzle migrations:** generate with `cd app && npx drizzle-kit generate --name collections`, then **read the generated SQL before committing.** It should be exactly two `CREATE TABLE` statements (`collections`, `collection_items`) and nothing touching existing tables; if drizzle emits any `__new_*` rebuild of an existing table, stop and fix the schema diff. It ends with the re-pull reset (`UPDATE sync_state SET position = 0;`), and the migration gets the jest reset test (Task 2).
- **Shared store for the share extension:** there is no App Group container (the `withSharedKeychain` plugin removes it); the app and the extension share the Keychain access group `3W3H65F89G.com.sampocs.archie.shared` (`SHARED_OPTIONS` in `app/src/auth/keychain.ts`), where the extension already reads the session key. Two new items live there: `archie.collections` (JSON `[{id, name}]`, live collections in tile order; written **only by the app**, mirroring its local table) and `archie.lastCollection` (the id of the last collection saved into; written by both the app and the extension). Sign-out deletes both.
- **Copy (verbatim):** add-sheet choice `Save to a collection`; dropdown default with no collections `New collection…`; dropdown menu last entry `＋ New collection…`; name prompt title `New collection` with buttons `Cancel` / `Create`; rename prompt title `Rename collection` with `Cancel` / `Save`; delete confirm title `Delete “<name>”?`, message `Its N saved posts go with it.` (`Its 1 saved post goes with it.`; no message for an empty collection), buttons `Cancel` / `Delete`; Saved section header `Collections · N`; tile caption `N saved`; new tile `＋ New collection`; collection page kicker `Collection · N saved`; empty collection `Nothing saved here yet.`; post menus `Edit note`, `Move to…`, `Remove`; collection ••• menu `Rename`, `Delete collection`; note prompt title `Note` with `Cancel` / `Save`; share-extension name field placeholder `Collection name`; share-extension saved line stays `Saved to Archie`. Post source labels: `X video` (X post with a video length), `X post`, `YouTube`, otherwise the host without `www.`.
- **testIDs** (new): `intent-collection`, `collection-dropdown`, `share-collection-<id>`, `share-collection-new`, `share-collection-name`, `saved-collections`, `collection-tile-<id>`, `collection-new-tile`, `collection-menu-rename`, `collection-menu-delete`, `collection-page`, `collection-kicker`, `collection-more`, `collection-empty`, `collection-post-<itemId>`, `post-menu-note`, `post-menu-move`, `post-menu-remove`, `post-move-<collectionId>`. Existing ones stay (`add-url`, `add-paste`, `add-save`, `add-cancel`, `intent-finished`, `intent-queue`, `library-add`, `library-mode-*`, `saved-view`, `saved-favorites`, `saved-empty`, `screen-back`, `menu-sheet`).
- **Tests:** e2e first; unit tests only for real logic; outside calls replayed from recorded cassettes, never hand-made response bodies. App logic tests are `*.test.ts` (jest matches only `.ts`); pure app logic never imports a native module (`expo-secure-store`, `expo-sqlite`, `react-native` UI) — keep pure helpers in their own files.
- **Never print secrets** or `.env` values.
- **Branch and worktrees:** branch `saved-collections`, worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/saved-collections`. Foundation tasks (1, 2) run there serially. Each parallel-safe task runs in its own worktree from the last foundation commit (`git gtr new col-t<N> --from-current --yes`, run inside the `saved-collections` worktree), then merges back into `saved-collections`.
- **App packages in worktrees:** a worktree's `app/node_modules` is a symlink to the main checkout's: `ln -sfn /Users/sampocs/Documents/Personal/second-brain/app/node_modules app/node_modules` (run in every worktree that runs `npm`/`npx`; once per worktree). Keep it out of git: `grep -qx 'app/node_modules' "$(git rev-parse --git-common-dir)/info/exclude" || echo 'app/node_modules' >> "$(git rev-parse --git-common-dir)/info/exclude"`. **npm packages are installed only in the main checkout's `app/`** (none are needed here). **Never run `npx prettier`** (the project has no prettier; it would reformat files wholesale).
- **Postgres from a worktree:** the container `second-brain-postgres-1` (`127.0.0.1:5434`) is already up from the main checkout. **Never run `make db-up`, `make db-down`, `make test-db`, `make migrate-local`, `make start-local`, `make reset-local-data` or any `make maestro*` target from a worktree** (they drive the main checkout's docker-compose stack and local data). Run tests with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t<N> uv run pytest -m "postgres or not postgres"`, where every task uses its own database (tests truncate tables and one downgrades the schema): `docker exec second-brain-postgres-1 createdb -U archie archie_test_t<N>` (ignore "already exists").
- **Maestro:** implementers add the testIDs listed in their task and write/edit flow files; flows are **run only by the coordinator, from the main checkout, against the local backend** (Task 7). Lessons from piece 1 that every flow here follows: one `make maestro` run shares one user's server data across flows, so each flow uses a URL and names no other flow uses; a swipe started from an element id may never reach a swipeable on a plain page, so swipe by screen position; after Save, wait for the add sheet to close (`notVisible: add-url`) before tapping anything whose text matches the sheet's field.
- **Checks before every commit:** Python: `make lint` and the relevant tests (command above). App: `cd app && npm run typecheck && npx jest`.
- **Commits:** every message ends with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MN7nukQAsqfkk3GiAq6NkX
  ```
- **Out of scope:** deploying, `railway config apply`, pushing or merging to `main`; takes (tables, editor, list, "Write a take"); reordering collections in the UI (the server accepts `position`, nothing sends it yet); a note field at capture time; playing anything inside Archie; a Retry for failed previews. The plan ends with `saved-collections` ready for a PR.

## Decisions made while planning

1. **The share extension's collection list lives in the shared Keychain group**, not an App Group: there is no App Group (piece M2's `withSharedKeychain` plugin deletes it because the Apple portal has none for the extension), and the Keychain group is the "shared store the extension already reads" (the session key). The app mirrors `[{id, name}]` there whenever its local collections change (`CollectionsMirror`, Task 2); the extension only reads it, plus reads and writes `archie.lastCollection`.
2. **The dropdown is a native action sheet in the app and chips in the share extension.** In the app, tapping `collection-dropdown` opens `ActionSheetIOS` (collection names, then `＋ New collection…`, then Cancel) and "New collection…" asks for the name with `Alert.prompt` — both React Native core, so no new native module. In the extension, React Native's action sheet and alerts can't present (they look up the shared application's key window, which an app extension doesn't have), so the extension shows the spec's "same chips": one chip per collection plus `＋ New collection…`, which reveals an inline name field. Both feed the same `CollectionPick`.
3. **Preselection:** the last collection saved into (`archie.lastCollection`) if it is still live; otherwise the newest collection; otherwise "New collection…". With no collections the app's Save asks for the name; the extension's "New collection…" chip is selected with its name field shown, and Save is disabled until it has a name.
4. **No note at capture.** The spec's `add_collection_item` accepts `note?`, and the server keeps it, but neither sheet adds a field: notes are added with Edit note on the collection page (keeps the sheets short, and the mock shows none).
5. **Previews:** an X post's caption is its text (capped at 1,000 characters), its author is `@handle`, its image is its own first video thumbnail or photo, else the quoted post's, else none; a video's length is `duration_seconds`. YouTube uses the existing watch-page fetch: `og:title`, `ownerChannelName`, `lengthSeconds`, and the standard `hqdefault` thumbnail. Anything else: `og:title`/`<title>` and `og:image`, no author. The spec's "neutral tile" wins over the mock's "collection's color": a post with no image shows the theme's `press` color with the site name.
6. **Video badge:** ▶ shows for `kind === "youtube"` or any post with `duration_seconds`; the duration chip shows when `duration_seconds` is set.
7. **Saved layout:** the Collections section always renders (header `Collections · N`, tiles, then `＋ New collection`) so Saved is never a dead end; the existing `saved-empty` line shows above it only when nothing is starred and there are no collections. Favorites (unchanged) stay on top.
8. **Rejections on the phone:** a rejected `create_collection` deletes the optimistic collection and its items, a rejected `add_collection_item` deletes the optimistic item (the server has neither); a rejected `update_collection` or `update_collection_item` rewinds the sync position so the next pull restores the server copy. None of them touch `sources`.
9. **Optimistic kind:** the phone inserts a new item as `kind: "link"`, as `addSource` does for sources; the pulled row carries the server's `x`/`youtube`/`link`.
10. **Remove has no confirmation** (one post, one tap, haptic); Delete collection confirms because it removes every post. Delete from the collection page returns to Saved. `Move to…` lists the other live collections and is hidden when there are none.
11. **Migration 0009 resets the sync position** although it only adds tables: an older build ignores unknown pull keys, so a phone that pulled from the new server before updating would otherwise never receive collection rows it skipped.
12. **Names** are trimmed and whitespace-collapsed on both sides, cut to 100 characters on the phone (so an `Alert.prompt` name can't be rejected), and may repeat.

---

## File Structure

```
packages/archie-db/archie_db/models.py                                   Collection, CollectionItem, CollectionItemKind, MetadataStatus, JobKind.FETCH_COLLECTION_ITEM (T1)
packages/archie-db/archie_db/{changes,jobs}.py                            touch() accepts the new rows; COLLECTION_ITEM_ID_KEY (T1)
packages/archie-db/archie_db/migrations/versions/0009_collections.py                                                        (T1)
conftest.py                                                               truncate list (T1)
services/api/archie_api/sync/{schemas,actions,pull,capture}.py            ActionTypes, Out shapes, HANDLERS, pull tables, public validate_url (T1)
services/api/archie_api/sync/collection_actions.py                                                                          (T1)
services/api/tests/e2e/test_collections_e2e.py                                                                              (T1)
app/src/db/{schema,actions}.ts, app/drizzle/0009_collections.sql (+ meta, journal, migrations.js)                          (T2)
app/src/sync/{engine,transport,engine.test}.ts, app/src/db/collections.test.ts                                             (T2)
app/src/collections/{collections,collections.test,sharedCollectionsFormat,sharedCollectionsFormat.test,boundary.test}.ts    (T2)
app/src/collections/{sharedCollections,prompts}.ts, app/src/collections/{useCollectionsData,CollectionsMirror}.tsx         (T2)
app/src/auth/{session,session.test}.ts, app/src/app/_layout.tsx (mirror)                                                   (T2)
services/worker/archie_worker/{content/__init__,content/x,content/youtube,content/preview,errors}.py                       (T3)
services/worker/archie_worker/handlers/{__init__,fetch_collection_item}.py                                                  (T3)
services/worker/tests/test_fetch_collection_item_e2e.py, services/worker/tests/cassettes/collection_x_video.yaml           (T3)
packages/archie-testing/archie_testing/media.py                                                                              (T3)
app/src/capture/{types,CaptureOptions,collectionChoice,collectionChoice.test,CollectionDropdown,CollectionChips}.ts(x)      (T4)
app/src/app/{add,share}.tsx, app/src/share/{ShareSheet,submit,submit.test,deepLink,deepLink.test}.ts(x), app/src/auth/keychain.ts (T4)
app/src/library/{SavedView,CollectionsSection,CollectionTile}.tsx                                                           (T5)
app/src/app/collection/[id].tsx, app/src/collections/{PostCard,PostMenus}.tsx, app/src/app/_layout.tsx (route)              (T6)
maestro/collections.yaml, Makefile, maestro/README.md, docs                                                                 (T7)
```

Tasks 2 and 6 both edit `app/src/app/_layout.tsx` (a mirror component vs. a route), and Tasks 4 and 5 both read `useCollectionsData`; the overlaps are textual only. Task 3 touches no app file.

## Foundation tasks (run in `saved-collections`, serially)

### Task 1: Server: tables, migration 0009, the four collection actions, pull  (tier: most capable)

**Files:**
- Create: `packages/archie-db/archie_db/migrations/versions/0009_collections.py`, `services/api/archie_api/sync/collection_actions.py`, `services/api/tests/e2e/test_collections_e2e.py`
- Modify: `packages/archie-db/archie_db/models.py`, `packages/archie-db/archie_db/changes.py`, `packages/archie-db/archie_db/jobs.py`, `conftest.py` (`_TRUNCATE_TABLES`), `services/api/archie_api/sync/schemas.py`, `services/api/archie_api/sync/actions.py`, `services/api/archie_api/sync/pull.py`, `services/api/archie_api/sync/capture.py` (`_validate_url` → `validate_url`)

**Interfaces:**
- Produces:
  - `models.CollectionItemKind` (`X = "x"`, `YOUTUBE = "youtube"`, `LINK = "link"`), `models.MetadataStatus` (`PENDING`, `READY`, `FAILED`), `models.JobKind.FETCH_COLLECTION_ITEM = "fetch_collection_item"`.
  - `models.Collection` (`id, user_id, name, position, created_at, updated_at, deleted_at, change_seq`), `models.CollectionItem` (`id, user_id, collection_id, url, kind, title, author, image_url, duration_seconds, note, metadata_status, created_at, updated_at, deleted_at, change_seq`).
  - `jobs.COLLECTION_ITEM_ID_KEY = "collection_item_id"`; `changes.touch(row)` accepts `Collection` and `CollectionItem`.
  - `schemas.ActionType.CREATE_COLLECTION / UPDATE_COLLECTION / ADD_COLLECTION_ITEM / UPDATE_COLLECTION_ITEM`; `schemas.CollectionOut`, `schemas.CollectionItemOut`; `PulledRows.collections`, `PulledRows.collection_items`.
  - `capture.validate_url(url: str) -> str | None`.
- Review: yes (migration, sync shapes, the learning-side boundary).

- [ ] **Step 1: Test DB.** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t1` (ignore "already exists"). Tests run with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t1`.

- [ ] **Step 2: Write the failing e2e test** `services/api/tests/e2e/test_collections_e2e.py`:

```python
"""Collections through the real API: make, rename and delete them; save, edit, move and remove posts; pull both tables.

A saved post is never a source: saving one adds no source row and queues only its `fetch_collection_item` preview.
"""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import jobs, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

X_POST_URL = "https://x.com/BearsFilmRoom/status/1850000000000000000"
YOUTUBE_URL = "https://www.youtube.com/watch?v=e0gVE3YxZs8"
PAGE_URL = "https://example.com/bears"


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A signed-in client of a fresh user."""
    return live_stack.authed(live_stack.sign_in())


def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "type": action_type, "payload": payload}


def _push(authed: httpx.Client, *actions: dict[str, Any]) -> list[dict[str, Any]]:
    response = authed.post("/sync/push", json={"actions": list(actions)})
    response.raise_for_status()
    return response.json()["results"]


def _reasons(results: list[dict[str, Any]]) -> list[str | None]:
    return [result["reason"] for result in results]


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    return authed.get("/sync/pull", params={"since": 0}).json()["rows"]


def _by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next(row for row in rows if row["id"] == row_id)


def _create(authed: httpx.Client, name: str = "Bears hype") -> str:
    collection_id = str(uuid.uuid4())
    _push(authed, _action("create_collection", {"id": collection_id, "name": name}))
    return collection_id


def _save(authed: httpx.Client, collection_id: str, *, url: str = X_POST_URL, **extra: Any) -> str:
    item_id = str(uuid.uuid4())
    _push(authed, _action("add_collection_item", {"id": item_id, "collection_id": collection_id, "url": url, **extra}))
    return item_id


def _jobs(live_stack: LiveStack) -> list[models.Job]:
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        return list(db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id)))


def test_collections_are_made_at_the_end_with_cleaned_names(authed: httpx.Client) -> None:
    """Each new collection goes after the last one; names are stored with whitespace collapsed."""
    first = _create(authed, name="  Bears   hype ")
    second = _create(authed, name="Funny")

    collections = _rows(authed)["collections"]

    assert [(row["name"], row["position"]) for row in collections] == [("Bears hype", 0.0), ("Funny", 1.0)]
    assert [row["id"] for row in collections] == [first, second]
    assert all(row["deleted_at"] is None for row in collections)


def test_a_saved_post_is_not_a_source_and_queues_only_its_preview(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Posts get their kind from the URL and a pending preview; no source, capture or pipeline job is made."""
    collection_id = _create(authed)
    x_item = _save(authed, collection_id, note="  the 4th-quarter scramble ")
    youtube_item = _save(authed, collection_id, url=YOUTUBE_URL)
    page_item = _save(authed, collection_id, url=PAGE_URL)

    rows = _rows(authed)
    queued = _jobs(live_stack)

    assert rows["sources"] == []
    items = rows["collection_items"]
    assert [(row["id"], row["kind"]) for row in items] == [(x_item, "x"), (youtube_item, "youtube"), (page_item, "link")]
    assert _by_id(items, x_item)["note"] == "the 4th-quarter scramble"
    assert {row["metadata_status"] for row in items} == {"pending"}
    assert all(row["collection_id"] == collection_id for row in items)
    assert [job.kind for job in queued] == [models.JobKind.FETCH_COLLECTION_ITEM.value] * 3
    assert [job.payload[jobs.COLLECTION_ITEM_ID_KEY] for job in queued] == [x_item, youtube_item, page_item]


def test_renaming_and_deleting_a_collection(authed: httpx.Client) -> None:
    """A rename bumps the row; a delete soft-deletes the collection and every post in it, and then refuses changes."""
    collection_id = _create(authed)
    first_item = _save(authed, collection_id)
    second_item = _save(authed, collection_id, url=PAGE_URL)
    before = _by_id(_rows(authed)["collections"], collection_id)

    _push(authed, _action("update_collection", {"id": collection_id, "name": "Bears  film room"}))
    renamed = _by_id(_rows(authed)["collections"], collection_id)
    _push(authed, _action("update_collection", {"id": collection_id, "deleted": True}))
    rows = _rows(authed)
    after_delete = _push(
        authed,
        _action("update_collection", {"id": collection_id, "name": "Again"}),
        _action("add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": PAGE_URL}),
        _action("update_collection_item", {"id": first_item, "note": "late"}),
    )

    assert renamed["name"] == "Bears film room"
    assert renamed["change_seq"] > before["change_seq"]
    assert _by_id(rows["collections"], collection_id)["deleted_at"] is not None
    assert all(_by_id(rows["collection_items"], item)["deleted_at"] is not None for item in (first_item, second_item))
    assert _reasons(after_delete) == ["collection not found", "collection not found", "collection item not found"]


def test_a_post_can_have_its_note_edited_moved_and_removed(authed: httpx.Client) -> None:
    """A blank note clears it, an absent note keeps it, a move changes the collection, a remove soft-deletes."""
    first = _create(authed)
    second = _create(authed, name="Funny")
    item_id = _save(authed, first, note="keep me")

    _push(authed, _action("update_collection_item", {"id": item_id, "collection_id": second}))
    moved = _by_id(_rows(authed)["collection_items"], item_id)
    _push(authed, _action("update_collection_item", {"id": item_id, "note": "   "}))
    cleared = _by_id(_rows(authed)["collection_items"], item_id)
    _push(authed, _action("update_collection_item", {"id": item_id, "deleted": True}))
    removed = _by_id(_rows(authed)["collection_items"], item_id)

    assert (moved["collection_id"], moved["note"]) == (second, "keep me")
    assert cleared["note"] is None
    assert removed["deleted_at"] is not None
    assert removed["change_seq"] > cleared["change_seq"] > moved["change_seq"]


def test_collection_actions_refuse_other_users_and_bad_input(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Another user's collection or post is not found; names, URLs, notes and ids are checked before any write."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    collection_id = _create(authed)
    item_id = _save(authed, collection_id)
    others_collection = _create(other, name="Mallory's")

    foreign = _push(
        other,
        _action("add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": PAGE_URL}),
        _action("update_collection_item", {"id": item_id, "note": "mine now"}),
        _action("update_collection", {"id": collection_id, "deleted": True}),
    )
    own = _push(
        authed,
        _action("create_collection", {"id": str(uuid.uuid4()), "name": "   "}),
        _action("create_collection", {"id": str(uuid.uuid4()), "name": "x" * 101}),
        _action("create_collection", {"id": collection_id, "name": "Again"}),
        _action("add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": "ftp://x.com/a"}),
        _action("add_collection_item", {"id": str(uuid.uuid4()), "collection_id": collection_id}),
        _action(
            "add_collection_item",
            {"id": str(uuid.uuid4()), "collection_id": collection_id, "url": PAGE_URL, "note": "n" * 2001},
        ),
        _action("update_collection_item", {"id": item_id, "collection_id": others_collection}),
    )

    assert _reasons(foreign) == ["collection not found", "collection item not found", "collection not found"]
    assert _reasons(own) == [
        "collection name is empty",
        "collection name is longer than 100 characters",
        "id already exists",
        "url must be http or https",
        "payload is malformed",
        "note is longer than 2000 characters",
        "collection not found",
    ]
    rows = _rows(authed)
    assert _by_id(rows["collection_items"], item_id)["collection_id"] == collection_id
    assert [row["name"] for row in rows["collections"]] == ["Bears hype"]
```

Run: `TEST_DATABASE_URL=… uv run pytest services/api/tests/e2e/test_collections_e2e.py -m postgres -v` — fails (no `collections` key in the pull / "action not supported yet").

- [ ] **Step 3: Models.** In `models.py`, after `SourceKind`:

```python
class CollectionItemKind(StrEnum):
    """What a saved post links to; only X and YouTube have their own preview lookups."""

    X = "x"
    YOUTUBE = "youtube"
    LINK = "link"


class MetadataStatus(StrEnum):
    """Whether a saved post's preview (title, author, thumbnail) has been fetched."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
```

`JobKind` gains `FETCH_COLLECTION_ITEM = "fetch_collection_item"` after `NEWS_QUIZ`. After the `Brief` class:

```python
class Collection(Base):
    """A just-for-fun scrapbook ("Bears hype"). Its posts are never sources and never reach the learning side."""

    __tablename__ = "collections"
    __table_args__ = (sqlalchemy.Index("ix_collections_user_id_change_seq", "user_id", "change_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(sqlalchemy.String(200))
    # Tile order on Saved; a new collection goes at the end, so this is creation order until something reorders it.
    position: Mapped[float] = mapped_column(sqlalchemy.Double)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class CollectionItem(Base):
    """A link saved into a collection, with the preview `fetch_collection_item` fills in once.

    Lives in its own table rather than `sources`, so no library, search, review or pipeline query can see it.
    """

    __tablename__ = "collection_items"
    __table_args__ = (
        sqlalchemy.Index("ix_collection_items_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.Index("ix_collection_items_collection_id", "collection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    collection_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("collections.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(sqlalchemy.String(2048))
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    # The preview: the post's caption or the page's title, who posted it, its thumbnail and a video's length.
    title: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    author: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    image_url: Mapped[str | None] = mapped_column(sqlalchemy.String(2048))
    duration_seconds: Mapped[int | None] = mapped_column(sqlalchemy.Integer)
    note: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    metadata_status: Mapped[str] = mapped_column(sqlalchemy.String(16), server_default=MetadataStatus.PENDING.value)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)
```

`changes.touch`'s parameter becomes `row: models.Source | models.Topic | models.Collection | models.CollectionItem`. `jobs.py` gains, under the module docstring:

```python
# A `fetch_collection_item` job's payload key: the saved post to fill in.
COLLECTION_ITEM_ID_KEY = "collection_item_id"
```

`conftest.py` `_TRUNCATE_TABLES` gains `"collection_items", "collections",` before `"llm_calls"`.

- [ ] **Step 4: Migration** `packages/archie-db/archie_db/migrations/versions/0009_collections.py`:

```python
"""Collections: just-for-fun scrapbooks and their saved posts, kept apart from sources.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def upgrade() -> None:
    """Create `collections` and `collection_items` with their pull indexes."""
    op.create_table(
        "collections",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("name", sqlalchemy.String(200), nullable=False),
        sqlalchemy.Column("position", sqlalchemy.Double(), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_collections_user_id_change_seq", "collections", ["user_id", "change_seq"])

    op.create_table(
        "collection_items",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("url", sqlalchemy.String(2048), nullable=False),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("author", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("image_url", sqlalchemy.String(2048), nullable=True),
        sqlalchemy.Column("duration_seconds", sqlalchemy.Integer(), nullable=True),
        sqlalchemy.Column("note", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("metadata_status", sqlalchemy.String(16), server_default="pending", nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_collection_items_user_id_change_seq", "collection_items", ["user_id", "change_seq"])
    op.create_index("ix_collection_items_collection_id", "collection_items", ["collection_id"])


def downgrade() -> None:
    """Drop both tables (items first, for the foreign key); collections are lost."""
    op.drop_table("collection_items")
    op.drop_table("collections")
```

`test_db_migrations.py`'s `test_models_match_the_migrations` and `test_downgrade_then_upgrade_round_trips` cover it; no new migration test is needed for new tables.

- [ ] **Step 5: Schemas.** `ActionType` gains, after `SET_FAVORITE`:

```python
    CREATE_COLLECTION = "create_collection"
    UPDATE_COLLECTION = "update_collection"
    ADD_COLLECTION_ITEM = "add_collection_item"
    UPDATE_COLLECTION_ITEM = "update_collection_item"
```

After `BriefOut`:

```python
class CollectionOut(pydantic.BaseModel):
    """A collection as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    position: float
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class CollectionItemOut(pydantic.BaseModel):
    """A saved post as the phone stores it; the preview fields stay null until `fetch_collection_item` fills them."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    url: str
    kind: str
    title: str | None
    author: str | None
    image_url: str | None
    duration_seconds: int | None
    note: str | None
    metadata_status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int
```

`PulledRows` gains `collections: list[CollectionOut]` and `collection_items: list[CollectionItemOut]`.

- [ ] **Step 6: Pull.** In `pull.py`: `PulledTable` gains `COLLECTIONS = "collections"` and `COLLECTION_ITEMS = "collection_items"`; `pull_changes`'s docstring says "the eight synced tables"; `tables` gains

```python
        PulledTable.COLLECTIONS: _changed_rows(db, models.Collection, user_id=user_id, since=since, limit=limit),
        PulledTable.COLLECTION_ITEMS: _changed_rows(
            db, models.CollectionItem, user_id=user_id, since=since, limit=limit
        ),
```

the response gains `collections=[schemas.CollectionOut.model_validate(row) for row in page.rows[PulledTable.COLLECTIONS]]` and the same for `collection_items` with `CollectionItemOut`, and `_changed_rows`'s type-variable constraint adds `models.Collection, models.CollectionItem`. Deleted rows ship like every other table's.

- [ ] **Step 7: Make the URL check public.** In `capture.py`, rename `_validate_url` to `validate_url`, give it the docstring `"""Why \`url\` can't be stored (too long, not http(s), unparseable), or None."""`, and update its one call in `_validate_add_source`.

- [ ] **Step 8: Handlers** `services/api/archie_api/sync/collection_actions.py`:

```python
"""Collection actions: make, rename, reorder and delete a collection; save, edit, move and remove a post.

Collections are scrapbooks kept apart from the learning side: nothing here reads or writes sources, cards or the
pipeline, and the only job queued is `fetch_collection_item`, which fills in a post's preview. Each handler returns the
rejection reason or None; the caller holds the user's write lock and every check runs before the first write.
"""

from __future__ import annotations

import uuid

import pydantic
import sqlalchemy
from archie_db import changes, jobs, models
from archie_shared import urls
from sqlalchemy import orm

from archie_api.sync import capture, rows

MAX_COLLECTION_NAME_LENGTH = 100

NO_COLLECTION = "collection not found"
NO_COLLECTION_ITEM = "collection item not found"
_EMPTY_NAME = "collection name is empty"
_LONG_NAME = f"collection name is longer than {MAX_COLLECTION_NAME_LENGTH} characters"
_LONG_NOTE = f"note is longer than {capture.MAX_NOTE_LENGTH} characters"
_ID_EXISTS = "id already exists"

# Only X and YouTube get their own preview lookups; every other URL is a plain link.
_ITEM_KIND_BY_URL_KIND = {
    urls.UrlKind.X: models.CollectionItemKind.X,
    urls.UrlKind.YOUTUBE: models.CollectionItemKind.YOUTUBE,
}


class _CreateCollectionPayload(pydantic.BaseModel):
    id: uuid.UUID
    name: str


class _UpdateCollectionPayload(pydantic.BaseModel):
    id: uuid.UUID
    name: str | None = None
    position: float | None = pydantic.Field(default=None, allow_inf_nan=False)
    # There is no undelete: false is accepted and ignored.
    deleted: bool = False


class _AddCollectionItemPayload(pydantic.BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    url: str
    note: str | None = None


class _UpdateCollectionItemPayload(pydantic.BaseModel):
    id: uuid.UUID
    # Only applied when the key is present (see `model_fields_set`); null or blank clears the note.
    note: str | None = None
    collection_id: uuid.UUID | None = None
    deleted: bool = False


def create_collection(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Make an empty collection after the user's last one."""
    parsed = rows.parse(_CreateCollectionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    name = _clean_name(parsed.name)
    reason = _name_reason(name)
    if reason is not None:
        return reason
    if db.get(models.Collection, parsed.id) is not None:
        return _ID_EXISTS

    db.add(
        models.Collection(
            id=parsed.id,
            user_id=user.id,
            name=name,
            position=_end_position(db, user_id=user.id),
            change_seq=changes.next_change_seq(),
        )
    )
    db.flush()
    return None


def update_collection(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Rename, move or delete a collection; deleting it removes every post in it too."""
    parsed = rows.parse(_UpdateCollectionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    collection = _owned_collection(db, user=user, collection_id=parsed.id)
    if collection is None:
        return NO_COLLECTION
    name = _clean_name(parsed.name) if parsed.name is not None else None
    reason = _name_reason(name) if name is not None else None
    if reason is not None:
        return reason

    if name is not None:
        collection.name = name
    if parsed.position is not None:
        collection.position = parsed.position
    if parsed.deleted:
        _delete_with_items(db, collection=collection)
    changes.touch(collection)
    return None


def add_collection_item(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Save a link into one of the user's collections and queue its preview; it never becomes a source."""
    parsed = rows.parse(_AddCollectionItemPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    url_reason = capture.validate_url(parsed.url)
    if url_reason is not None:
        return url_reason
    note = _clean_note(parsed.note)
    if note is not None and len(note) > capture.MAX_NOTE_LENGTH:
        return _LONG_NOTE
    if _owned_collection(db, user=user, collection_id=parsed.collection_id) is None:
        return NO_COLLECTION
    if db.get(models.CollectionItem, parsed.id) is not None:
        return _ID_EXISTS

    kind = _ITEM_KIND_BY_URL_KIND.get(urls.detect_kind(parsed.url), models.CollectionItemKind.LINK)
    item = models.CollectionItem(
        id=parsed.id,
        user_id=user.id,
        collection_id=parsed.collection_id,
        url=parsed.url,
        kind=kind.value,
        note=note,
        change_seq=changes.next_change_seq(),
    )
    db.add(item)
    db.flush()
    jobs.enqueue(
        db,
        kind=models.JobKind.FETCH_COLLECTION_ITEM,
        user_id=user.id,
        payload={jobs.COLLECTION_ITEM_ID_KEY: str(item.id)},
    )
    return None


def update_collection_item(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Edit a post's note, move it to another of the user's collections, or remove it."""
    parsed = rows.parse(_UpdateCollectionItemPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    item = _owned_item(db, user=user, item_id=parsed.id)
    if item is None:
        return NO_COLLECTION_ITEM
    note = _clean_note(parsed.note)
    if note is not None and len(note) > capture.MAX_NOTE_LENGTH:
        return _LONG_NOTE
    target_id = parsed.collection_id
    if target_id is not None and _owned_collection(db, user=user, collection_id=target_id) is None:
        return NO_COLLECTION

    if "note" in parsed.model_fields_set:
        item.note = note
    if target_id is not None:
        item.collection_id = target_id
    if parsed.deleted:
        item.deleted_at = sqlalchemy.func.now()
    changes.touch(item)
    return None


def _owned_collection(db: orm.Session, *, user: models.User, collection_id: uuid.UUID) -> models.Collection | None:
    """The user's live collection with this id; another user's or a deleted one is treated as missing."""
    collection = db.get(models.Collection, collection_id)
    if collection is None or collection.user_id != user.id or collection.deleted_at is not None:
        return None
    return collection


def _owned_item(db: orm.Session, *, user: models.User, item_id: uuid.UUID) -> models.CollectionItem | None:
    """The user's live post with this id (a deleted collection's posts are deleted with it)."""
    item = db.get(models.CollectionItem, item_id)
    if item is None or item.user_id != user.id or item.deleted_at is not None:
        return None
    return item


def _clean_name(name: str) -> str:
    return " ".join(name.split())


def _name_reason(name: str) -> str | None:
    if not name:
        return _EMPTY_NAME
    if len(name) > MAX_COLLECTION_NAME_LENGTH:
        return _LONG_NAME
    return None


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    return note.strip() or None


def _end_position(db: orm.Session, *, user_id: int) -> float:
    """One past the user's last live collection, or 0 for the first."""
    last = db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(models.Collection.position)).where(
            models.Collection.user_id == user_id, models.Collection.deleted_at.is_(None)
        )
    )
    return 0.0 if last is None else last + 1


def _delete_with_items(db: orm.Session, *, collection: models.Collection) -> None:
    """Soft-delete the collection and its live posts, each with a fresh position so phones pull the deletion."""
    collection.deleted_at = sqlalchemy.func.now()
    live_items = db.scalars(
        sqlalchemy.select(models.CollectionItem).where(
            models.CollectionItem.collection_id == collection.id, models.CollectionItem.deleted_at.is_(None)
        )
    )
    for item in live_items:
        item.deleted_at = sqlalchemy.func.now()
        changes.touch(item)
```

Register in `actions.py`: import `collection_actions` with the other `archie_api.sync` modules, and in `HANDLERS` after `SET_FAVORITE` add a `# Collections` comment and

```python
    schemas.ActionType.CREATE_COLLECTION: collection_actions.create_collection,
    schemas.ActionType.UPDATE_COLLECTION: collection_actions.update_collection,
    schemas.ActionType.ADD_COLLECTION_ITEM: collection_actions.add_collection_item,
    schemas.ActionType.UPDATE_COLLECTION_ITEM: collection_actions.update_collection_item,
```

(`_apply_action`'s IntegrityError fallback already answers "id already exists" for a raced id.)

- [ ] **Step 9: Run** `make lint` and `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t1 uv run pytest -m "postgres or not postgres"` — all pass, including the migration tests and `test_every_action_type_has_a_handler`. If a pre-existing pull test compares the full `rows` dict, add `"collections": [], "collection_items": []` to its expectation (that is the only allowed change to an existing test).
- [ ] **Step 10: Commit** "Server: collections and collection_items (migration 0009), the four collection actions, pull".

### Task 2: App data layer: schema 0009, sync, optimistic actions, the collections module, the share-extension mirror  (tier: most capable)

**Files:**
- Modify: `app/src/db/schema.ts`, `app/src/db/actions.ts`, `app/src/sync/engine.ts`, `app/src/sync/transport.ts`, `app/src/sync/engine.test.ts`, `app/src/auth/session.ts`, `app/src/auth/session.test.ts`, `app/src/app/_layout.tsx` (mount the mirror)
- Create: `app/drizzle/0009_collections.sql` (+ `meta/0009_snapshot.json`, journal and `migrations.js` entries, all generated), `app/src/db/collections.test.ts`, `app/src/collections/collections.ts`, `app/src/collections/collections.test.ts`, `app/src/collections/boundary.test.ts`, `app/src/collections/sharedCollectionsFormat.ts`, `app/src/collections/sharedCollectionsFormat.test.ts`, `app/src/collections/sharedCollections.ts`, `app/src/collections/prompts.ts`, `app/src/collections/useCollectionsData.ts`, `app/src/collections/CollectionsMirror.tsx`

**Interfaces:**
- Consumes: the wire contract in Global Constraints (no code from Task 1).
- Produces:
  - `schema.collections` (`id, name, position, createdAt, updatedAt, deletedAt`), `schema.collectionItems` (`id, collectionId, url, kind, title, author, imageUrl, durationSeconds, note, metadataStatus, createdAt, updatedAt, deletedAt`).
  - `actions.ts`: `ActionType` gains the four types; `MAX_COLLECTION_NAME_LENGTH = 100`; `createCollection(db: AppDb, name: string): string`; `renameCollection(db: AppDb, collectionId: string, name: string): void`; `deleteCollection(db: AppDb, collectionId: string): void`; `addCollectionItem(db: AppDb, input: { collectionId: string; url: string }): string`; `editCollectionItemNote(db: AppDb, itemId: string, note: string): void`; `moveCollectionItem(db: AppDb, itemId: string, collectionId: string): void`; `removeCollectionItem(db: AppDb, itemId: string): void`.
  - `engine.ts`: `PulledCollection`, `PulledCollectionItem`; `PullPage.rows.collections?`, `PullPage.rows.collection_items?`.
  - `@/collections/collections`: `CollectionRow`, `CollectionItemRow`, `CollectionWithItems = CollectionRow & { items: CollectionItemRow[] }`, `MOSAIC_SIZE = 4`, `groupCollections(collections: CollectionRow[], items: CollectionItemRow[]): CollectionWithItems[]`, `mosaicImages(collection: CollectionWithItems): (string | null)[]`, `savedCountLabel(count: number): string`, `postSiteName(url: string): string`, `postSourceLabel(item: { kind: string; url: string; durationSeconds: number | null }): string`, `postByline(item: { kind: string; url: string; author: string | null; durationSeconds: number | null }): string`, `isVideo(item: { kind: string; durationSeconds: number | null }): boolean`, `formatDuration(seconds: number): string`, `savedDate(createdAt: string): string`, `defaultCollectionId(collections: { id: string }[], lastUsedId: string | null): string | null`.
  - `@/collections/sharedCollectionsFormat`: `SharedCollection = { id: string; name: string }`, `encodeSharedCollections(list: SharedCollection[]): string`, `parseSharedCollections(raw: string | null): SharedCollection[]`.
  - `@/collections/sharedCollections` (expo-secure-store only; safe to import from the share extension): `SHARED_COLLECTIONS_KEY = "archie.collections"`, `LAST_COLLECTION_KEY = "archie.lastCollection"`, `writeSharedCollections(list: SharedCollection[]): Promise<void>`, `readSharedCollections(): Promise<SharedCollection[]>`, `readLastCollectionId(): Promise<string | null>`, `writeLastCollectionId(id: string): Promise<void>`, `clearSharedCollections(): Promise<void>`.
  - `@/collections/prompts` (app only): `promptCollectionName(input: { title: string; submitLabel: string; initialName?: string; onSubmit: (name: string) => void }): void`, `confirmDeleteCollection(input: { name: string; count: number; onConfirm: () => void }): void`, `promptNote(input: { initialNote: string; onSubmit: (note: string) => void }): void`.
  - `@/collections/useCollectionsData` (app only): `useCollectionsData(): CollectionWithItems[]`.
- Review: yes (migration, sync conflict and rejection rules, sign-out wipe).

- [ ] **Step 1: Worktree setup.** In this worktree: the `app/node_modules` symlink and exclude line from Global Constraints.

- [ ] **Step 2: Schema.** Append to `schema.ts`:

```ts
// Collections (Library → Saved): just-for-fun scrapbooks. Their posts live in their own table and are never sources,
// so no library, search, Today or review query can see them.
export const collections = sqliteTable("collections", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  // Tile order; a new collection goes at the end.
  position: real("position").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});

export const collectionItems = sqliteTable("collection_items", {
  id: text("id").primaryKey(),
  collectionId: text("collection_id").notNull(),
  url: text("url").notNull(),
  // x | youtube | link; "link" until the server classifies it.
  kind: text("kind").notNull(),
  // The preview the server fetches once: caption or title, who posted it, thumbnail, a video's length.
  title: text("title"),
  author: text("author"),
  imageUrl: text("image_url"),
  durationSeconds: integer("duration_seconds"),
  note: text("note"),
  // pending | ready | failed
  metadataStatus: text("metadata_status").notNull().default("pending"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});
```

- [ ] **Step 3: Generate the migration**: `cd app && npx drizzle-kit generate --name collections`. Check `drizzle/migrations.js` and `drizzle/meta/_journal.json` gained `0009_collections`, and **read `drizzle/0009_collections.sql`**: two `CREATE TABLE` statements and nothing else (see Global Constraints). Append, as `0008_favorites.sql` does:

```sql
--> statement-breakpoint
-- An older build ignores unknown pull keys, so collection rows pulled before this table existed come only through a re-pull.
UPDATE sync_state SET position = 0;
```

- [ ] **Step 4: Tests first** (they fail until Step 6).

`app/src/db/collections.test.ts`:

```ts
import { eq } from "drizzle-orm";

import {
  addCollectionItem,
  createCollection,
  deleteCollection,
  editCollectionItemNote,
  moveCollectionItem,
  removeCollectionItem,
  renameCollection,
} from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";
import { makeTestDb } from "./testDb";

// expo-crypto is a native module; node's crypto gives the same UUIDs.
jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

const outbox = (db: AppDb) =>
  db.select().from(schema.outbox).all().map((entry) => ({ type: entry.type, payload: JSON.parse(entry.payload) }));
const collection = (db: AppDb, id: string) =>
  db.select().from(schema.collections).where(eq(schema.collections.id, id)).get();
const item = (db: AppDb, id: string) =>
  db.select().from(schema.collectionItems).where(eq(schema.collectionItems.id, id)).get();

describe("collections", () => {
  it("makes collections at the end, with whitespace collapsed, and queues create_collection", () => {
    const db = makeTestDb();

    const first = createCollection(db, "  Bears   hype ");
    const second = createCollection(db, "Funny");

    expect(collection(db, first)).toMatchObject({ name: "Bears hype", position: 0, deletedAt: null });
    expect(collection(db, second)?.position).toBe(1);
    expect(outbox(db)).toEqual([
      { type: "create_collection", payload: { id: first, name: "Bears hype" } },
      { type: "create_collection", payload: { id: second, name: "Funny" } },
    ]);
  });

  it("cuts a long name to 100 characters so the server accepts it", () => {
    const db = makeTestDb();

    const id = createCollection(db, "x".repeat(150));

    expect(collection(db, id)?.name).toHaveLength(100);
  });

  it("saves a post as a pending link that is never a source", () => {
    const db = makeTestDb();
    const collectionId = createCollection(db, "Bears hype");

    const itemId = addCollectionItem(db, { collectionId, url: "https://x.com/a/status/1" });

    expect(item(db, itemId)).toMatchObject({ collectionId, kind: "link", metadataStatus: "pending", note: null });
    expect(db.select().from(schema.sources).all()).toEqual([]);
    expect(outbox(db).at(-1)).toEqual({
      type: "add_collection_item",
      payload: { id: itemId, collection_id: collectionId, url: "https://x.com/a/status/1" },
    });
  });

  it("deleting a collection soft-deletes its posts and queues one update_collection", () => {
    const db = makeTestDb();
    const collectionId = createCollection(db, "Bears hype");
    const itemId = addCollectionItem(db, { collectionId, url: "https://example.com/a" });

    deleteCollection(db, collectionId);

    expect(collection(db, collectionId)?.deletedAt).not.toBeNull();
    expect(item(db, itemId)?.deletedAt).not.toBeNull();
    expect(outbox(db).at(-1)).toEqual({ type: "update_collection", payload: { id: collectionId, deleted: true } });
  });

  it("renames, edits a note (blank clears it), moves and removes", () => {
    const db = makeTestDb();
    const first = createCollection(db, "Bears hype");
    const second = createCollection(db, "Funny");
    const itemId = addCollectionItem(db, { collectionId: first, url: "https://example.com/a" });

    renameCollection(db, first, " Bears  film room ");
    editCollectionItemNote(db, itemId, " the scramble ");
    const noted = item(db, itemId)?.note;
    editCollectionItemNote(db, itemId, "   ");
    moveCollectionItem(db, itemId, second);
    removeCollectionItem(db, itemId);

    expect(collection(db, first)?.name).toBe("Bears film room");
    expect(noted).toBe("the scramble");
    expect(item(db, itemId)).toMatchObject({ note: null, collectionId: second });
    expect(item(db, itemId)?.deletedAt).not.toBeNull();
    expect(outbox(db).slice(-5)).toEqual([
      { type: "update_collection", payload: { id: first, name: "Bears film room" } },
      { type: "update_collection_item", payload: { id: itemId, note: "the scramble" } },
      { type: "update_collection_item", payload: { id: itemId, note: null } },
      { type: "update_collection_item", payload: { id: itemId, collection_id: second } },
      { type: "update_collection_item", payload: { id: itemId, deleted: true } },
    ]);
  });
});
```

In `engine.test.ts`, a new `describe("database SyncStore: collections", …)` (import the new actions; a local `pulledCollection(overrides)` and `pulledItem(overrides)` with every field, `id: "c1"` / `"i1"`, `collection_id: "c1"`, `kind: "x"`, `metadata_status: "ready"`, timestamps `"2026-11-05T00:00:00Z"`, nulls elsewhere):

```ts
  it("stores pulled collections and posts, and a page without them is fine", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: {
        sources: [],
        artifacts: [],
        cards: [],
        collections: [pulledCollection({ name: "Bears hype" })],
        collection_items: [pulledItem({ title: "Walk-off pick six", duration_seconds: 65 })],
      },
      position: 3,
      more: false,
    });
    await store.applyPage({ rows: { sources: [], artifacts: [], cards: [] }, position: 4, more: false });

    expect(db.select().from(schema.collections).get()).toMatchObject({ id: "c1", name: "Bears hype", position: 0 });
    expect(db.select().from(schema.collectionItems).get()).toMatchObject({
      id: "i1",
      collectionId: "c1",
      kind: "x",
      title: "Walk-off pick six",
      durationSeconds: 65,
      metadataStatus: "ready",
    });
  });

  it("a re-pull of a post with an unsent edit keeps the local copy", async () => {
    const { db, store } = makeDbStore();
    const page = { rows: { sources: [], artifacts: [], cards: [], collections: [pulledCollection({})], collection_items: [pulledItem({})] }, position: 1, more: false };
    await store.applyPage(page);
    editCollectionItemNote(db, "i1", "mine");

    await store.applyPage({ ...page, position: 2 });

    expect(db.select().from(schema.collectionItems).get()?.note).toBe("mine");
  });

  it("a rejected create_collection deletes the optimistic collection and its posts", async () => {
    const { db, store } = makeDbStore();
    const collectionId = createCollection(db, "Bears hype");
    addCollectionItem(db, { collectionId, url: "https://example.com/a" });
    const create = db.select().from(schema.outbox).all().find((entry) => entry.type === "create_collection")!;

    await store.rejectAction(create.id, "id already exists");

    expect(db.select().from(schema.collections).all()).toEqual([]);
    expect(db.select().from(schema.collectionItems).all()).toEqual([]);
  });

  it("a rejected add_collection_item deletes the optimistic post and touches no source", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [], collections: [pulledCollection({})] }, position: 5, more: false });
    addCollectionItem(db, { collectionId: "c1", url: "https://example.com/a" });
    const add = db.select().from(schema.outbox).get()!;

    await store.rejectAction(add.id, "collection not found");

    expect(db.select().from(schema.collectionItems).all()).toEqual([]);
    expect(sourceRow(db)?.syncError).toBeNull();
    expect(await store.getPosition()).toBe(5);
  });

  it.each(["update_collection", "update_collection_item"])(
    "a rejected %s rewinds the position and touches no source",
    async (type) => {
      const { db, store } = makeDbStore();
      await store.applyPage({
        rows: { sources: [pulledSource({})], artifacts: [], cards: [], collections: [pulledCollection({})], collection_items: [pulledItem({})] },
        position: 5,
        more: false,
      });
      if (type === "update_collection") renameCollection(db, "c1", "New name");
      else removeCollectionItem(db, "i1");
      const entry = db.select().from(schema.outbox).get()!;

      await store.rejectAction(entry.id, "collection not found");

      expect(await store.getPosition()).toBe(0);
      expect(sourceRow(db)?.syncError).toBeNull();
    },
  );
```

and add `"0009_collections"` to the `it.each([...])` list of migrations that end by resetting the saved position.

`app/src/collections/collections.test.ts` (rows built with a local `collectionRow(overrides)` / `itemRow(overrides)` that spread full rows):
- `groupCollections` hides deleted collections and deleted posts, orders collections by `position` (ties by `createdAt`), and each collection's `items` newest `createdAt` first; a post whose collection is missing or deleted appears nowhere.
- `mosaicImages`: five posts, the newest without an image → the four newest *image URLs* in newest-first order; two images → `[a, b, null, null]`; none → four nulls.
- `postSourceLabel`: `{kind: "x", durationSeconds: 48}` → `"X video"`; `{kind: "x", durationSeconds: null}` → `"X post"`; `{kind: "youtube"}` → `"YouTube"`; `{kind: "link", url: "https://www.theathletic.com/a"}` → `"theathletic.com"`; an unparseable URL → the URL itself.
- `postByline({author: "@BearsFilmRoom", kind: "x", durationSeconds: 48, …})` → `"@BearsFilmRoom · X video"`; with `author: null` on a link → `"example.com"`.
- `isVideo`: YouTube without a duration → true; a link with a duration → true; an X post without one → false.
- `formatDuration`: `48` → `"0:48"`, `192` → `"3:12"`, `3725` → `"1:02:05"`.
- `savedCountLabel(14)` → `"14 saved"`; `savedDate(new Date(2026, 10, 3, 12).toISOString())` → `"Nov 3"`.
- `defaultCollectionId([{id: "a"}, {id: "b"}], "a")` → `"a"`; with `"gone"` → `"b"` (the newest, last in tile order); with `[]` → `null`.

`app/src/collections/sharedCollectionsFormat.test.ts`: `parseSharedCollections(encodeSharedCollections(list))` round-trips; `null`, `"not json"`, `"{}"` and `[{"id": 1}]` parse to `[]`; a list with one malformed entry keeps the good ones.

`app/src/collections/boundary.test.ts` — the boundary the spec calls most important:

```ts
import { isNull } from "drizzle-orm";

import { addCollectionItem, addSource, createCollection } from "@/db/actions";
import * as schema from "@/db/schema";
import { makeTestDb } from "@/db/testDb";
import { joinLibrary } from "@/library/join";
import { matchesQuery, searchText } from "@/library/search";

jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

// Collection posts live in their own table, so the Library's queries (the same ones `useLibraryData` runs) and its
// search can't see them: All, Domains, Today and search read only `sources`.
it("a saved post never reaches the library's sources or its search", async () => {
  const db = makeTestDb();
  await addSource(db, { url: "https://example.com/reading", intent: "queue" });
  const collectionId = createCollection(db, "Bears hype");
  addCollectionItem(db, { collectionId, url: "https://x.com/BearsFilmRoom/status/1" });

  const sources = db.select().from(schema.sources).where(isNull(schema.sources.deletedAt)).all();
  const library = joinLibrary({ sources, artifacts: [], topics: [], topicPrimers: [] });

  expect(library.sources.map((source) => source.url)).toEqual(["https://example.com/reading"]);
  expect(library.sources.filter((source) => matchesQuery(searchText(source), "bears"))).toEqual([]);
});
```

Run `cd app && npx jest` — the new tests fail.

- [ ] **Step 5: Engine types.** In `engine.ts` add

```ts
export type PulledCollection = {
  id: string;
  name: string;
  position: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export type PulledCollectionItem = {
  id: string;
  collection_id: string;
  url: string;
  kind: string;
  title: string | null;
  author: string | null;
  image_url: string | null;
  duration_seconds: number | null;
  note: string | null;
  metadata_status: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
```

and in `PullPage.rows`: `// Absent when pulling from a server older than Saved piece 2.` `collections?: PulledCollection[]; collection_items?: PulledCollectionItem[];`. Update the `rejectAction` comment in `SyncStore`: "a rejected create_collection / add_collection_item deletes its optimistic rows; a rejected update_collection / update_collection_item rewinds".

- [ ] **Step 6: Implement.**

`actions.ts`: `ActionType` gains `| "create_collection" | "update_collection" | "add_collection_item" | "update_collection_item"`. After `setFavorite`:

```ts
export const MAX_COLLECTION_NAME_LENGTH = 100;

// Stored as the server stores it (whitespace collapsed), and cut to its limit so a typed name is never rejected.
function cleanCollectionName(name: string): string {
  return name.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_COLLECTION_NAME_LENGTH);
}

// A new collection goes after the last live one, as on the server.
function endCollectionPosition(tx: Tx): number {
  const last = tx
    .select({ highest: max(schema.collections.position) })
    .from(schema.collections)
    .where(isNull(schema.collections.deletedAt))
    .get()?.highest;
  return last == null ? 0 : last + 1;
}

function updateCollectionItem(tx: Tx, itemId: string, values: SQLiteUpdateSetSource<typeof schema.collectionItems>): void {
  tx.update(schema.collectionItems)
    .set({ ...values, updatedAt: new Date().toISOString() })
    .where(eq(schema.collectionItems.id, itemId))
    .run();
}

/** Makes an empty collection at the end of the list; returns its id. */
export function createCollection(db: AppDb, name: string): string {
  const id = randomUUID();
  const now = new Date().toISOString();
  const cleaned = cleanCollectionName(name);
  db.transaction((tx) => {
    tx.insert(schema.collections)
      .values({ id, name: cleaned, position: endCollectionPosition(tx), createdAt: now, updatedAt: now })
      .run();
    enqueue(tx, "create_collection", { id, name: cleaned });
  });
  return id;
}

export function renameCollection(db: AppDb, collectionId: string, name: string): void {
  const cleaned = cleanCollectionName(name);
  db.transaction((tx) => {
    tx.update(schema.collections)
      .set({ name: cleaned, updatedAt: new Date().toISOString() })
      .where(eq(schema.collections.id, collectionId))
      .run();
    enqueue(tx, "update_collection", { id: collectionId, name: cleaned });
  });
}

/** Deletes a collection and, as the server does, every post in it. */
export function deleteCollection(db: AppDb, collectionId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    tx.update(schema.collections)
      .set({ deletedAt: now, updatedAt: now })
      .where(eq(schema.collections.id, collectionId))
      .run();
    tx.update(schema.collectionItems)
      .set({ deletedAt: now, updatedAt: now })
      .where(and(eq(schema.collectionItems.collectionId, collectionId), isNull(schema.collectionItems.deletedAt)))
      .run();
    enqueue(tx, "update_collection", { id: collectionId, deleted: true });
  });
}

/** Saves a link into a collection (never as a source); the server fills in its preview. Returns the post's id. */
export function addCollectionItem(db: AppDb, input: { collectionId: string; url: string }): string {
  const id = randomUUID();
  const now = new Date().toISOString();
  db.transaction((tx) => {
    // "link" until the pulled row carries the server's x / youtube / link, as addSource does for sources.
    tx.insert(schema.collectionItems)
      .values({ id, collectionId: input.collectionId, url: input.url, kind: "link", createdAt: now, updatedAt: now })
      .run();
    enqueue(tx, "add_collection_item", { id, collection_id: input.collectionId, url: input.url });
  });
  return id;
}

/** A blank note clears it. */
export function editCollectionItemNote(db: AppDb, itemId: string, note: string): void {
  const cleaned = note.trim() || null;
  db.transaction((tx) => {
    updateCollectionItem(tx, itemId, { note: cleaned });
    enqueue(tx, "update_collection_item", { id: itemId, note: cleaned });
  });
}

export function moveCollectionItem(db: AppDb, itemId: string, collectionId: string): void {
  db.transaction((tx) => {
    updateCollectionItem(tx, itemId, { collectionId });
    enqueue(tx, "update_collection_item", { id: itemId, collection_id: collectionId });
  });
}

export function removeCollectionItem(db: AppDb, itemId: string): void {
  db.transaction((tx) => {
    updateCollectionItem(tx, itemId, { deletedAt: new Date().toISOString() });
    enqueue(tx, "update_collection_item", { id: itemId, deleted: true });
  });
}
```

(add `max` to the `drizzle-orm` import).

`transport.ts`:
- After `CARD_ACTIONS`:

```ts
// Actions whose payload id is a collection or a saved post: a rejection re-pulls the server's copy and touches no source.
const COLLECTION_ACTIONS = new Set(["update_collection", "update_collection_item"]);
```

- In `rejectAction`, right after the `choose_topics` block:

```ts
        // The server never created these, so the optimistic rows would otherwise linger forever.
        if (entry.type === "create_collection" && payload.id) {
          tx.delete(schema.collectionItems).where(eq(schema.collectionItems.collectionId, payload.id)).run();
          tx.delete(schema.collections).where(eq(schema.collections.id, payload.id)).run();
          return;
        }
        if (entry.type === "add_collection_item" && payload.id) {
          tx.delete(schema.collectionItems).where(eq(schema.collectionItems.id, payload.id)).run();
          return;
        }
```

  and `rowIsNotSource` also includes `COLLECTION_ACTIONS.has(entry.type)` (extend its comment: "a rejected collection edit re-pulls the collection or post").
- In `applyPage`, after the briefs loop:

```ts
        for (const collection of page.rows.collections ?? []) {
          if (unsent.has(collection.id)) continue;
          const values = {
            name: collection.name,
            position: collection.position,
            createdAt: collection.created_at,
            updatedAt: collection.updated_at,
            deletedAt: collection.deleted_at,
          };
          tx.insert(schema.collections)
            .values({ id: collection.id, ...values })
            .onConflictDoUpdate({ target: schema.collections.id, set: values })
            .run();
        }

        for (const item of page.rows.collection_items ?? []) {
          if (unsent.has(item.id)) continue;
          const values = {
            collectionId: item.collection_id,
            url: item.url,
            kind: item.kind,
            title: item.title,
            author: item.author,
            imageUrl: item.image_url,
            durationSeconds: item.duration_seconds,
            note: item.note,
            metadataStatus: item.metadata_status,
            createdAt: item.created_at,
            updatedAt: item.updated_at,
            deletedAt: item.deleted_at,
          };
          tx.insert(schema.collectionItems)
            .values({ id: item.id, ...values })
            .onConflictDoUpdate({ target: schema.collectionItems.id, set: values })
            .run();
        }
```

`app/src/collections/collections.ts` (pure; imports only `@/db/schema` types and `@/today/todayLabels`'s `MONTHS`):

```ts
import type * as schema from "@/db/schema";
import { MONTHS } from "@/today/todayLabels";

export type CollectionRow = typeof schema.collections.$inferSelect;
export type CollectionItemRow = typeof schema.collectionItems.$inferSelect;
export type CollectionWithItems = CollectionRow & { items: CollectionItemRow[] };

export const MOSAIC_SIZE = 4;

/** Live collections in tile order, each with its live posts newest first. */
export function groupCollections(collections: CollectionRow[], items: CollectionItemRow[]): CollectionWithItems[] {
  const live = collections
    .filter((collection) => collection.deletedAt === null)
    .sort((a, b) => a.position - b.position || a.createdAt.localeCompare(b.createdAt));
  const newestFirst = items
    .filter((item) => item.deletedAt === null)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return live.map((collection) => ({
    ...collection,
    items: newestFirst.filter((item) => item.collectionId === collection.id),
  }));
}

/** The tile's 2×2 mosaic: the four newest thumbnails, padded with null (a neutral cell). */
export function mosaicImages(collection: CollectionWithItems): (string | null)[] {
  const images = collection.items.map((item) => item.imageUrl).filter((url): url is string => url !== null);
  const newest = images.slice(0, MOSAIC_SIZE);
  return [...newest, ...Array<null>(MOSAIC_SIZE - newest.length).fill(null)];
}

export function savedCountLabel(count: number): string {
  return `${count} saved`;
}

/** The link's host without "www.", or the URL itself when it can't be parsed. */
export function postSiteName(url: string): string {
  if (!URL.canParse(url)) return url;
  return new URL(url).hostname.replace(/^www\./, "");
}

export function isVideo(item: { kind: string; durationSeconds: number | null }): boolean {
  return item.kind === "youtube" || item.durationSeconds !== null;
}

/** Where a post is from: "X video", "X post", "YouTube", or the site. */
export function postSourceLabel(item: { kind: string; url: string; durationSeconds: number | null }): string {
  if (item.kind === "x") return item.durationSeconds !== null ? "X video" : "X post";
  if (item.kind === "youtube") return "YouTube";
  return postSiteName(item.url);
}

/** "@BearsFilmRoom · X video"; just the source when the author isn't known. */
export function postByline(item: {
  kind: string;
  url: string;
  author: string | null;
  durationSeconds: number | null;
}): string {
  return [item.author, postSourceLabel(item)].filter(Boolean).join(" · ");
}

/** "0:48", "3:12", "1:02:05". */
export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = String(seconds % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}

/** The date a post was saved, as the feed shows it: "Nov 3". */
export function savedDate(createdAt: string): string {
  const saved = new Date(createdAt);
  return `${MONTHS[saved.getMonth()]} ${saved.getDate()}`;
}

/** The collection a save preselects: the last one used if it still exists, else the newest, else none. */
export function defaultCollectionId(collections: { id: string }[], lastUsedId: string | null): string | null {
  if (lastUsedId && collections.some((collection) => collection.id === lastUsedId)) return lastUsedId;
  return collections.at(-1)?.id ?? null;
}
```

`app/src/collections/sharedCollectionsFormat.ts` (pure):

```ts
/** A collection as the share extension needs it: just enough to list and pick it. */
export type SharedCollection = { id: string; name: string };

export function encodeSharedCollections(list: SharedCollection[]): string {
  return JSON.stringify(list.map(({ id, name }) => ({ id, name })));
}

// The Keychain item may be missing, from an older build, or half-written; anything unreadable is "no collections".
export function parseSharedCollections(raw: string | null): SharedCollection[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(
    (entry): entry is SharedCollection =>
      typeof entry === "object" && entry !== null && typeof entry.id === "string" && typeof entry.name === "string",
  );
}
```

`app/src/collections/sharedCollections.ts`:

```ts
import * as SecureStore from "expo-secure-store";

import { SHARED_OPTIONS } from "@/auth/keychain";

import { encodeSharedCollections, parseSharedCollections, type SharedCollection } from "./sharedCollectionsFormat";

// Both items live in the Keychain group the share extension already reads the session key from (there is no App
// Group). The app alone writes the list, mirroring its database; both write the last-used id.
export const SHARED_COLLECTIONS_KEY = "archie.collections";
export const LAST_COLLECTION_KEY = "archie.lastCollection";

export async function writeSharedCollections(list: SharedCollection[]): Promise<void> {
  await SecureStore.setItemAsync(SHARED_COLLECTIONS_KEY, encodeSharedCollections(list), SHARED_OPTIONS);
}

export async function readSharedCollections(): Promise<SharedCollection[]> {
  return parseSharedCollections(await SecureStore.getItemAsync(SHARED_COLLECTIONS_KEY, SHARED_OPTIONS));
}

export async function readLastCollectionId(): Promise<string | null> {
  return SecureStore.getItemAsync(LAST_COLLECTION_KEY, SHARED_OPTIONS);
}

export async function writeLastCollectionId(id: string): Promise<void> {
  await SecureStore.setItemAsync(LAST_COLLECTION_KEY, id, SHARED_OPTIONS);
}

/** Sign-out: the next account must not see this one's collection names in the share sheet. */
export async function clearSharedCollections(): Promise<void> {
  await SecureStore.deleteItemAsync(SHARED_COLLECTIONS_KEY, SHARED_OPTIONS);
  await SecureStore.deleteItemAsync(LAST_COLLECTION_KEY, SHARED_OPTIONS);
}
```

`app/src/collections/useCollectionsData.ts`: live queries of `schema.collections` and `schema.collectionItems` (both `where(isNull(deletedAt))`), `useMemo(() => groupCollections(collections, items), [collections, items])`. Docstring: "Every live collection with its posts, for Saved, the collection page and the add sheet."

`app/src/collections/CollectionsMirror.tsx`: renders null; reads `useCollectionsData()`, maps to `{ id, name }`, and calls `writeSharedCollections` only when `encodeSharedCollections(list)` differs from the last string it wrote (a `useRef`); a failed write is ignored (`.catch(() => undefined)`, comment: "the share sheet then shows the last list it saw; the next change retries"). Mount it in the root `_layout.tsx` right after `<ReminderRoot />` under `session.status === "signedIn"`.

`app/src/collections/prompts.ts` (React Native `Alert`; app only, never imported by the share extension):

```ts
import { Alert } from "react-native";

/** Asks for a collection name with the system prompt; a blank answer does nothing. */
export function promptCollectionName(input: {
  title: string;
  submitLabel: string;
  initialName?: string;
  onSubmit: (name: string) => void;
}): void {
  Alert.prompt(
    input.title,
    undefined,
    [
      { text: "Cancel", style: "cancel" },
      {
        text: input.submitLabel,
        onPress: (value?: string) => {
          const name = value?.trim();
          if (name) input.onSubmit(name);
        },
      },
    ],
    "plain-text",
    input.initialName ?? "",
  );
}

/** Deleting a collection removes every post in it, so it asks first. */
export function confirmDeleteCollection(input: { name: string; count: number; onConfirm: () => void }): void {
  const message =
    input.count === 0 ? undefined : `Its ${input.count} saved ${input.count === 1 ? "post goes" : "posts go"} with it.`;
  Alert.alert(`Delete “${input.name}”?`, message, [
    { text: "Cancel", style: "cancel" },
    { text: "Delete", style: "destructive", onPress: input.onConfirm },
  ]);
}

/** Edit a post's note; saving a blank note clears it. */
export function promptNote(input: { initialNote: string; onSubmit: (note: string) => void }): void {
  Alert.prompt(
    "Note",
    undefined,
    [
      { text: "Cancel", style: "cancel" },
      { text: "Save", onPress: (value?: string) => input.onSubmit(value ?? "") },
    ],
    "plain-text",
    input.initialNote,
  );
}
```

`session.ts` `clearSession`: inside the wipe transaction add `tx.delete(schema.collections).run();` and `tx.delete(schema.collectionItems).run();` after briefs; after the transaction (still inside `try`) `await clearSharedCollections();`. `session.test.ts`: its `clearSession` beforeEach also inserts one collection and one item; the first test expects `mockCalls` to be `["/auth/logout:key-1", "keychain-delete", "keychain-delete", "keychain-delete", "keychain-delete"]` and both new tables empty.

- [ ] **Step 7: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 8: Commit** "App: collections data layer (migration 0009, sync, actions, share-extension mirror)".

---

## Parallel-safe tasks

Each runs in its own worktree from Task 2's commit (`git gtr new col-t<N> --from-current --yes` inside `saved-collections`), with the `app/node_modules` symlink when it runs `npm`/`npx`, and merges back when done.

### Task 3: Worker: `fetch_collection_item`  (tier: standard)

**Files:**
- Create: `services/worker/archie_worker/content/preview.py`, `services/worker/archie_worker/handlers/fetch_collection_item.py`, `services/worker/tests/test_fetch_collection_item_e2e.py`, `services/worker/tests/cassettes/collection_x_video.yaml` (recorded)
- Modify: `services/worker/archie_worker/content/__init__.py` (`LinkPreview`), `services/worker/archie_worker/content/x.py` (`fetch_post_preview`), `services/worker/archie_worker/content/youtube.py` (`fetch_preview`), `services/worker/archie_worker/errors.py` (`PREVIEW_UNAVAILABLE`), `services/worker/archie_worker/handlers/__init__.py` (registry), `packages/archie-testing/archie_testing/media.py` (`X_VIDEO_POST_URL`)

**Interfaces:**
- Consumes (Task 1): `models.CollectionItem`, `models.CollectionItemKind`, `models.MetadataStatus`, `models.JobKind.FETCH_COLLECTION_ITEM`, `jobs.COLLECTION_ITEM_ID_KEY`, `changes.touch(item)`.
- Produces: `content.LinkPreview(title, author, image_url, duration_seconds)`; `x.fetch_post_preview(*, post_id: str) -> content.LinkPreview`; `youtube.fetch_preview(*, video_id: str) -> content.LinkPreview`; `preview.fetch(*, url: str, kind: models.CollectionItemKind) -> content.LinkPreview`; `fetch_collection_item.handle`, `fetch_collection_item.mark_failed`.
- Depends on: Tasks 1-2 (Task 1's models; Task 2 only for ordering).
- Review: yes (outside calls, the lock-after-fetch handler contract, the boundary).

- [ ] **Step 1: Test DB.** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t3` (ignore "already exists").

- [ ] **Step 2: Pick and record the X video.** Find a public X post with a native video (any short sports clip from a large account, e.g. @NFL; it must play logged out). Add to `media.py`:

```python
# A public X post with a native video, for `fetch_collection_item`'s preview test (cassette `collection_x_video.yaml`).
# Found on <date>; fxtwitter returned a video thumbnail and length for it.
X_VIDEO_POST_URL = "https://x.com/<handle>/status/<id>"
```

Write the test file (Step 3) first, then record only that test: `TEST_DATABASE_URL=… uv run pytest services/worker/tests/test_fetch_collection_item_e2e.py --record-mode=once -m postgres -k x_video`. fxtwitter needs no key. **Open the recorded cassette**: confirm `status.media.videos[0]` has `thumbnail_url` and `duration` (seconds); if fxtwitter names them differently, adjust `_thread_preview` to the recorded shape (the test's assertions stay). Confirm no cookie or auth header was recorded.

- [ ] **Step 3: Write the failing e2e test** `services/worker/tests/test_fetch_collection_item_e2e.py`:

```python
"""`fetch_collection_item` end to end: real jobs in Postgres, the preview lookups replayed from recorded cassettes.

The X post, YouTube watch page, og page and failure cassettes are the pipeline's own; only the X video was recorded
for this test. Re-record it: delete `collection_x_video.yaml`, then
`uv run pytest services/worker/tests/test_fetch_collection_item_e2e.py --record-mode=once -m postgres -k x_video`
with `TEST_DATABASE_URL` set (fxtwitter needs no key).
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy
import sqlalchemy.orm
import vcr as vcr_module
from archie_db import changes, jobs, models, session
from archie_testing import media, recording
from archie_worker import handlers, loop

pytestmark = pytest.mark.postgres

Replay = Callable[[str], contextlib.AbstractContextManager[vcr_module.cassette.Cassette]]

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"

# The shared post has no media of its own; its quoted post has this photo.
X_QUOTE_URL = "https://x.com/hwchase17/status/2116230499140251964"
X_QUOTE_PHOTO = "https://pbs.twimg.com/media/HV4_v0saYAAwybe.jpg?name=orig"
X_TEXT_ONLY_URL = "https://x.com/sama/status/2107691261776052633"
YOUTUBE_TITLE = "Jay Powell and the Fed Pause in 60 Seconds"
YOUTUBE_CHANNEL = "Bloomberg Television"
YOUTUBE_LENGTH_SECONDS = 57
YOUTUBE_THUMBNAIL = "https://i.ytimg.com/vi/e0gVE3YxZs8/hqdefault.jpg"
OG_PAGE_URL = "https://ogp.me/"


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[sqlalchemy.Engine]:
    """An engine on the migrated test database."""
    database_engine = session.engine_for(migrated_database_url)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def replay(request: pytest.FixtureRequest) -> Replay:
    """Returns `use_cassette(name)`; replay-only unless pytest is given `--record-mode`."""
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    # A recorded failure may replay on every retry of a job.
    return lambda name: recorder.use_cassette(f"{name}.yaml", allow_playback_repeats=True)


def test_an_x_video_gets_its_thumbnail_author_caption_and_length(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """fxtwitter's video gives the post its thumbnail and length; the author is the @handle."""
    item_id = _add_item(engine, url=media.X_VIDEO_POST_URL, kind=models.CollectionItemKind.X)

    with replay("collection_x_video"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert item.metadata_status == models.MetadataStatus.READY
    assert item.image_url is not None and item.image_url.startswith("https://")
    assert item.duration_seconds is not None and item.duration_seconds > 0
    assert item.author is not None and item.author.startswith("@")
    assert item.title


def test_an_x_post_without_media_uses_its_quoted_posts_photo(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A quote post with no media of its own shows the quoted post's photo; it is not a video."""
    item_id = _add_item(engine, url=X_QUOTE_URL, kind=models.CollectionItemKind.X)

    with replay("x_quote"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.image_url, item.duration_seconds, item.author) == (X_QUOTE_PHOTO, None, "@hwchase17")
    assert item.metadata_status == models.MetadataStatus.READY


def test_a_text_only_x_post_has_a_caption_and_no_image(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """No media anywhere: the post shows its caption over a neutral tile."""
    item_id = _add_item(engine, url=X_TEXT_ONLY_URL, kind=models.CollectionItemKind.X)

    with replay("x_thread_sama"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert item.image_url is None
    assert item.title is not None and item.title.startswith("looking up at the stars")
    assert item.author == "@sama"


def test_a_youtube_video_gets_title_channel_length_and_thumbnail(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The existing watch-page fetch gives the title, channel and length; the thumbnail is the standard one."""
    item_id = _add_item(engine, url=media.YOUTUBE_VIDEO_URL, kind=models.CollectionItemKind.YOUTUBE)

    with replay("youtube_powell"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.title, item.author, item.duration_seconds, item.image_url) == (
        YOUTUBE_TITLE,
        YOUTUBE_CHANNEL,
        YOUTUBE_LENGTH_SECONDS,
        YOUTUBE_THUMBNAIL,
    )


def test_any_other_link_gets_its_og_title_and_image(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A plain page: og:title and og:image, no author, no length; phones see a newer change position."""
    item_id = _add_item(engine, url=OG_PAGE_URL, kind=models.CollectionItemKind.LINK)
    seq_before = _item(engine, item_id).change_seq

    with replay("og_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.title, item.image_url, item.author) == ("Open Graph protocol", "https://ogp.me/logo.png", None)
    assert item.change_seq > seq_before
    assert _job(engine).status == models.JobStatus.DONE


def test_the_preview_never_makes_a_source_or_queues_other_work(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """The boundary: a saved post's job writes only the post."""
    _add_item(engine, url=OG_PAGE_URL, kind=models.CollectionItemKind.LINK)

    with replay("og_page"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    with sqlalchemy.orm.Session(engine) as db:
        assert db.scalar(sqlalchemy.select(sqlalchemy.func.count()).select_from(models.Source)) == 0
        assert [job.kind for job in db.scalars(sqlalchemy.select(models.Job))] == [
            models.JobKind.FETCH_COLLECTION_ITEM.value
        ]


def test_a_missing_page_fails_at_once_and_keeps_the_url(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A 4xx can't be fixed by retrying: one attempt, the post is marked failed and keeps only its URL."""
    url = "https://httpbin.org/status/404"
    item_id = _add_item(engine, url=url, kind=models.CollectionItemKind.LINK)

    with replay("page_status_404"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    item = _item(engine, item_id)
    assert (item.metadata_status, item.url, item.title, item.image_url) == (models.MetadataStatus.FAILED, url, None, None)
    assert (_job(engine).attempts, _job(engine).status) == (1, models.JobStatus.FAILED)


def test_a_server_error_is_retried_and_the_post_stays_pending(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """A 5xx is transient: the job is re-queued with backoff."""
    item_id = _add_item(engine, url="https://httpbin.org/status/500", kind=models.CollectionItemKind.LINK)

    with replay("server_error"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert _item(engine, item_id).metadata_status == models.MetadataStatus.PENDING
    assert (_job(engine).attempts, _job(engine).status) == (1, models.JobStatus.QUEUED)


def test_a_post_removed_before_the_job_runs_is_left_alone(engine: sqlalchemy.Engine, replay: Replay) -> None:
    """No request is made (the missing cassette raises on any) and nothing is written."""
    item_id = _add_item(engine, url=OG_PAGE_URL, kind=models.CollectionItemKind.LINK)
    with sqlalchemy.orm.Session(engine) as db:
        db.get_one(models.CollectionItem, item_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    seq_before = _item(engine, item_id).change_seq

    with replay("no_requests") as cassette:
        loop.run_one(engine, handlers=handlers.HANDLERS)

    assert cassette.play_count == 0
    assert _item(engine, item_id).change_seq == seq_before
    assert _job(engine).status == models.JobStatus.DONE


def _add_item(engine: sqlalchemy.Engine, *, url: str, kind: models.CollectionItemKind) -> uuid.UUID:
    """A user's collection, one post in it and its queued job, as the sync push makes them."""
    item_id = uuid.uuid4()
    with sqlalchemy.orm.Session(engine) as db:
        user = models.User(apple_sub=f"sub-{uuid.uuid4()}")
        db.add(user)
        db.flush()

        changes.lock_user_writes(db, user.id)
        collection = models.Collection(
            id=uuid.uuid4(), user_id=user.id, name="Bears hype", position=0.0, change_seq=changes.next_change_seq()
        )
        db.add(collection)
        db.flush()
        db.add(
            models.CollectionItem(
                id=item_id,
                user_id=user.id,
                collection_id=collection.id,
                url=url,
                kind=kind.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        jobs.enqueue(
            db,
            kind=models.JobKind.FETCH_COLLECTION_ITEM,
            user_id=user.id,
            payload={jobs.COLLECTION_ITEM_ID_KEY: str(item_id)},
        )
        db.commit()
    return item_id


def _item(engine: sqlalchemy.Engine, item_id: uuid.UUID) -> models.CollectionItem:
    with sqlalchemy.orm.Session(engine) as db:
        return db.get_one(models.CollectionItem, item_id)


def _job(engine: sqlalchemy.Engine) -> models.Job:
    with sqlalchemy.orm.Session(engine) as db:
        return db.scalars(sqlalchemy.select(models.Job)).one()
```

Run (replay): `TEST_DATABASE_URL=… uv run pytest services/worker/tests/test_fetch_collection_item_e2e.py -m postgres -v` — fails (no handler for the kind).

- [ ] **Step 4: Content.** In `content/__init__.py`, after `ExtractedText`:

```python
# Longest caption kept for a saved post; a long X thread's first post can run to thousands of characters.
MAX_PREVIEW_TITLE_LENGTH = 1000


@dataclass(frozen=True)
class LinkPreview:
    """What a saved post shows: its caption or title, who posted it, a thumbnail, and a video's length."""

    title: str | None
    author: str | None
    image_url: str | None
    duration_seconds: int | None
```

In `x.py`, after `fetch_thread`:

```python
def fetch_post_preview(*, post_id: str) -> content.LinkPreview:
    """The shared post's caption, @handle, first video thumbnail or photo, and a video's length.

    fxtwitter with retries, then vxtwitter's single post; raises if both fail (the job retries). A post with no media
    of its own shows its quoted post's.
    """
    try:
        return _thread_preview(data=_get_json_with_retries(url=FXTWITTER_THREAD_URL.format(post_id=post_id)))
    except (httpx.HTTPError, ValueError, KeyError) as error:
        _logger.warning("fxtwitter preview failed for post %s (%r); trying vxtwitter", post_id, error)

    return _single_post_preview(data=_get_json(url=VXTWITTER_STATUS_URL.format(post_id=post_id)))


def _thread_preview(*, data: dict[str, Any]) -> content.LinkPreview:
    post = data["status"]
    quote = post.get("quote") or {}
    media = post.get("media") or quote.get("media") or {}
    videos = media.get("videos") or []
    photos = media.get("photos") or []

    video = videos[0] if videos else None
    image_url = video.get("thumbnail_url") if video else (photos[0]["url"] if photos else None)
    duration = video.get("duration") if video else None
    return content.LinkPreview(
        title=_caption(post["text"]),
        author=f"@{post['author']['screen_name']}",
        image_url=image_url,
        duration_seconds=round(duration) if duration else None,
    )


def _single_post_preview(*, data: dict[str, Any]) -> content.LinkPreview:
    media = data.get("media_extended") or (data.get("qrt") or {}).get("media_extended") or []
    first = media[0] if media else None
    duration_millis = first.get("duration_millis") if first else None
    return content.LinkPreview(
        title=_caption(data["text"]),
        author=f"@{data['user_screen_name']}",
        image_url=(first.get("thumbnail_url") or first.get("url")) if first else None,
        duration_seconds=round(duration_millis / 1000) if duration_millis else None,
    )


def _caption(text: str) -> str | None:
    caption = content.strip_nul(text).strip()
    return caption[: content.MAX_PREVIEW_TITLE_LENGTH] or None
```

In `youtube.py` (add `import json`, `import re`, and `from archie_worker import content`):

```python
# The watch page embeds its player response as JSON; the first match is the video's own (later ones are suggestions).
_LENGTH_SECONDS = re.compile(r'"lengthSeconds":"(\d+)"')
_OWNER_CHANNEL_NAME = re.compile(r'"ownerChannelName":"((?:[^"\\]|\\.)*)"')


def fetch_preview(*, video_id: str) -> content.LinkPreview:
    """The watch page's title, channel and length, with the standard thumbnail; raises if the page can't be fetched."""
    page = title_page.fetch_page(
        url=WATCH_URL.format(video_id=video_id), timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES
    )
    length = _LENGTH_SECONDS.search(page)
    owner = _OWNER_CHANNEL_NAME.search(page)
    return content.LinkPreview(
        title=title_page.extract_title(page=page),
        # The channel name is a JSON string, so its escapes (&, \") decode as JSON does.
        author=content.strip_nul(json.loads(f'"{owner.group(1)}"')) if owner else None,
        image_url=thumbnail_url(video_id),
        duration_seconds=int(length.group(1)) if length else None,
    )
```

`errors.FailureReason` gains `PREVIEW_UNAVAILABLE = "Couldn't load a preview for this link."` (stored only as the job's `last_error`; the phone shows no reason).

`content/preview.py`:

```python
"""A saved post's preview: X and YouTube use their own lookups, any other link its og:title and og:image."""

from __future__ import annotations

import httpx
from archie_db import models
from archie_shared import urls

from archie_worker import content, errors
from archie_worker.content import x, youtube
from archie_worker.handlers import fetch_title

_PAGE_TIMEOUT_SECONDS = 15
_PAGE_MAX_BYTES = 2_000_000
_TOO_MANY_REQUESTS = 429


def fetch(*, url: str, kind: models.CollectionItemKind) -> content.LinkPreview:
    """The post's preview; raises PermanentJobError when retrying can't help, anything else when it might."""
    post_id = urls.x_post_id(url) if kind == models.CollectionItemKind.X else None
    if post_id is not None:
        return x.fetch_post_preview(post_id=post_id)

    video_id = urls.youtube_video_id(url) if kind == models.CollectionItemKind.YOUTUBE else None
    if video_id is not None:
        return youtube.fetch_preview(video_id=video_id)

    # A profile or channel link (no post or video id) is previewed like any page.
    return _page_preview(url=url)


def _page_preview(*, url: str) -> content.LinkPreview:
    try:
        page = fetch_title.fetch_page(url=url, timeout_seconds=_PAGE_TIMEOUT_SECONDS, max_bytes=_PAGE_MAX_BYTES)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if 400 <= status < 500 and status != _TOO_MANY_REQUESTS:
            raise errors.PermanentJobError(errors.FailureReason.PREVIEW_UNAVAILABLE) from error
        raise

    return content.LinkPreview(
        title=fetch_title.extract_title(page=page),
        author=None,
        image_url=fetch_title.extract_image(page=page, base_url=url),
        duration_seconds=None,
    )
```

- [ ] **Step 5: Handler** `handlers/fetch_collection_item.py`:

```python
"""`fetch_collection_item`: fill a saved post's preview once, when it is saved.

A collection item is never a source: this reads only the post's URL and writes only its preview columns and
`metadata_status`. Following the loop's handler contract, it commits before the outside call and takes the user's
write lock only to write. When the job fails for good, `mark_failed` leaves the post with its URL (the phone shows a
neutral tile); there is nothing to retry by hand.
"""

from __future__ import annotations

import uuid

import sqlalchemy.orm
from archie_db import changes, jobs, models

from archie_worker.content import preview


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Fetch the post's preview and store it, bumping its change position so phones pull it."""
    item = db.get(models.CollectionItem, uuid.UUID(job.payload[jobs.COLLECTION_ITEM_ID_KEY]))
    if item is None or item.deleted_at is not None:
        return

    # Read what the fetch needs and end the transaction, so no connection is held during the outside calls.
    url, kind, user_id = item.url, models.CollectionItemKind(item.kind), item.user_id
    db.commit()
    fetched = preview.fetch(url=url, kind=kind)

    # The user may have removed the post during the fetch; the lock makes the refreshed state final.
    changes.lock_user_writes(db, user_id)
    db.refresh(item)
    if item.deleted_at is not None:
        return

    item.title = fetched.title
    item.author = fetched.author
    item.image_url = fetched.image_url
    item.duration_seconds = fetched.duration_seconds
    item.metadata_status = models.MetadataStatus.READY.value
    changes.touch(item)


def mark_failed(db: sqlalchemy.orm.Session, job: models.Job, reason: str) -> None:
    """Failure hook: mark the post's preview failed, unless the user removed it; `reason` stays on the job only."""
    del reason
    item = db.get(models.CollectionItem, uuid.UUID(job.payload[jobs.COLLECTION_ITEM_ID_KEY]))
    if item is None:
        return

    changes.lock_user_writes(db, item.user_id)
    db.refresh(item)
    if item.deleted_at is not None:
        return

    item.metadata_status = models.MetadataStatus.FAILED.value
    changes.touch(item)
```

Register in `handlers/__init__.py` (import `fetch_collection_item` in the alphabetical import list):

```python
    # A saved post's preview; when it gives up the post keeps its URL and shows a neutral tile.
    models.JobKind.FETCH_COLLECTION_ITEM: HandlerSpec(
        run=fetch_collection_item.handle, on_final_failure=fetch_collection_item.mark_failed
    ),
```

- [ ] **Step 6: Run** `make lint` and `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t3 uv run pytest -m "postgres or not postgres"` — all pass (replay only; nothing reaches the network).
- [ ] **Step 7: Commit** "Worker: fetch_collection_item fills a saved post's preview (X, YouTube, og)".

### Task 4: App: "Save to a collection" in the add sheet and the share extension  (tier: standard)

**Files:**
- Create: `app/src/capture/collectionChoice.ts`, `app/src/capture/collectionChoice.test.ts`, `app/src/capture/CollectionDropdown.tsx` (app only), `app/src/capture/CollectionChips.tsx` (extension)
- Modify: `app/src/capture/types.ts`, `app/src/capture/types.test.ts` (if its `chooseIntent` cases need the new field), `app/src/capture/CaptureOptions.tsx`, `app/src/app/add.tsx`, `app/src/share/ShareSheet.tsx`, `app/src/share/submit.ts`, `app/src/share/submit.test.ts`, `app/src/share/deepLink.ts`, `app/src/share/deepLink.test.ts`, `app/src/app/share.tsx`, `app/src/auth/keychain.ts` (comment only)

**Interfaces:**
- Consumes (Task 2): `createCollection`, `addCollectionItem`, `useCollectionsData`, `defaultCollectionId`, `SharedCollection`, `readSharedCollections`, `readLastCollectionId`, `writeLastCollectionId`, `promptCollectionName`.
- Produces:
  - `types.ts`: `Destination = Intent | "collection"`; `CollectionPick = { kind: "existing"; id: string } | { kind: "new"; name: string }`; `CaptureChoice` gains `collection: CollectionPick | null` and its `intent` becomes `Destination | null`; `EMPTY_CHOICE.collection = null`; `chooseIntent(choice, intent: Destination, defaultPick?: CollectionPick)`.
  - `collectionChoice.ts` (pure): `defaultCollectionPick(collections: SharedCollection[], lastUsedId: string | null): CollectionPick`, `collectionPickLabel(pick: CollectionPick, collections: SharedCollection[]): string`, `canSaveToCollection(pick: CollectionPick | null, opts: { asksForName: boolean }): boolean`.
  - `CaptureOptions` prop `collectionPicker?: ReactNode` (the third choice shows only when given).
  - `submit.ts`: `buildCollectionShareActions(input: { url: string; pick: CollectionPick }): { actions: OutboxEntry[]; collectionId: string }`; `submitShare(actions: OutboxEntry[], sessionKey: string | null)`; `shareDeepLink` carries `intent=collection` plus `collection=<id>` or `collection_name=<encoded>`.
  - `deepLink.ts`: `ShareParams` gains `collection?`, `collection_name?`; `sharedCollectionItemFromParams(params: ShareParams): { url: string; pick: CollectionPick } | null`.
  - testIDs `intent-collection`, `collection-dropdown`, `share-collection-<id>`, `share-collection-new`, `share-collection-name`.
- Depends on: Tasks 1-2.
- Review: yes (the share extension runs outside the app: no database, no React Native alerts; a wrong import breaks every share).

- [ ] **Step 1: Pure choice logic first.** `collectionChoice.test.ts`:
  - `defaultCollectionPick([{id:"a",…},{id:"b",…}], "a")` → `{kind:"existing", id:"a"}`; `"gone"` → `{kind:"existing", id:"b"}`; `[]` → `{kind:"new", name:""}` (delegates to `defaultCollectionId`).
  - `collectionPickLabel` → the collection's name for an existing pick; `"New collection…"` for a new pick with a blank name; the typed name otherwise; an existing pick whose id is no longer listed → `"New collection…"`.
  - `canSaveToCollection(null, …)` false; an existing pick true; a new pick with a blank name → `true` with `asksForName: true` (the app prompts on Save), `false` with `asksForName: false` (the extension needs the field filled).
  - `chooseIntent(choice, "collection", pick)` sets `collection: pick` and clears reaction/note/primer; switching back to `"queue"` clears `collection`.
  Implement `collectionChoice.ts` and the `types.ts` changes until they pass.

- [ ] **Step 2: `CaptureOptions`.** Add `collectionPicker?: ReactNode`. When given, render a third `Button` after "Queue it": `testID="intent-collection"`, label `Save to a collection`, primary when `value.intent === "collection"`, `onPress` → `onChange(chooseIntent(value, "collection", value.collection ?? undefined))` (the parent supplies the default pick through `collectionPicker`'s own state; see Steps 3 and 5); under it, when selected, render `collectionPicker`. Keep the file importing only theme components and `react-native` (it is shared with the extension). The `queue-primer` and reaction UI is unchanged.

- [ ] **Step 3: App dropdown** `CollectionDropdown.tsx` (props `{ collections: SharedCollection[]; pick: CollectionPick; onPick: (pick: CollectionPick) => void }`): a full-width row (`theme.colors.press` background, chip radius, `paddingHorizontal: theme.spacing.md`, height 40) with `testID="collection-dropdown"`, the label `collectionPickLabel(pick, collections)` and a trailing `▾` in `ink3`. Tapping opens `ActionSheetIOS.showActionSheetWithOptions({ options: [...names, "＋ New collection…", "Cancel"], cancelButtonIndex: names.length + 1 })`: a name picks `{kind:"existing", id}`; `＋ New collection…` calls `promptCollectionName({ title: "New collection", submitLabel: "Create", onSubmit: (name) => onPick({ kind: "new", name }) })` (cancelling the prompt keeps the previous pick). Haptic `selection` on a pick.

- [ ] **Step 4: Add sheet** (`app/src/app/add.tsx`):
  - `const collections = useCollectionsData().map(({ id, name }) => ({ id, name }))`; `const [lastUsedId, setLastUsedId] = useState<string | null>(null)` loaded once with `readLastCollectionId().then(setLastUsedId).catch(() => undefined)`.
  - `<CaptureOptions value={choice} onChange={setChoice} collectionPicker={<CollectionDropdown collections={collections} pick={choice.collection ?? defaultCollectionPick(collections, lastUsedId)} onPick={(collection) => setChoice({ ...choice, collection })} />} />`. When the intent becomes `"collection"` with `choice.collection === null`, set it to `defaultCollectionPick(collections, lastUsedId)` (so Save reads the shown pick).
  - `canSave = isHttpUrl(url) && (choice.intent === "collection" ? canSaveToCollection(choice.collection, { asksForName: true }) : choice.intent !== null)`.
  - `save()`: for a library intent, unchanged (`addSource`). For `"collection"`: a new pick with a blank name calls `promptCollectionName({ title: "New collection", submitLabel: "Create", onSubmit: (name) => saveToCollection({ kind: "new", name }) })` and returns; otherwise `saveToCollection(choice.collection)`, where `saveToCollection(pick)` does `const collectionId = pick.kind === "existing" ? pick.id : createCollection(db, pick.name); addCollectionItem(db, { collectionId, url: url.trim() }); void writeLastCollectionId(collectionId).catch(() => undefined); haptic("success"); requestSync(); router.back();` (comment: "Save drops the link into the collection only: no summary, no cards, nothing in the Library.").

- [ ] **Step 5: Share extension.**
  - `CollectionChips.tsx` (props `{ collections: SharedCollection[]; pick: CollectionPick; onPick: (pick: CollectionPick) => void }`; theme components and `react-native` only — no `Alert`, no `ActionSheetIOS`, no `@/db`, no `@/collections/useCollectionsData`): a wrapping row of pill chips (radius 999, `press` background, `ink2` text; selected = `chrome` background with `onChrome` text), one per collection (`testID="share-collection-<id>"`), then `＋ New collection…` (`testID="share-collection-new"`, outlined with `ink3`). When the new chip is selected, a `TextField` (`testID="share-collection-name"`, placeholder `Collection name`, `maxLength={100}`, `autoFocus`) under the chips edits `pick.name`.
  - `ShareSheet.tsx`: on mount load `readSharedCollections()` and `readLastCollectionId()` (both `.catch` to `[]`/`null`); pass `collectionPicker={<CollectionChips … />}` to `CaptureOptions`, with the pick defaulted as in Step 4. Save is enabled when `choice.intent` is a library intent, or `"collection"` with `canSaveToCollection(choice.collection, { asksForName: false })`. For `"collection"`: `const { actions, collectionId } = buildCollectionShareActions({ url, pick })`, `submitShare(actions, key)`, and after `"saved"` `void writeLastCollectionId(collectionId).catch(() => undefined)`. The library path becomes `submitShare([buildShareAction(...)], key)`. "Open Archie" passes the same choice to `shareDeepLink`.
  - `submit.ts`: `buildCollectionShareActions` returns, for an existing pick, one `add_collection_item` `{id, collection_id, url}`; for a new pick, `create_collection` `{id: newId, name: pick.name.trim()}` then `add_collection_item` into `newId` — two actions in one push, in that order. `submitShare(actions, sessionKey)` posts them all; the outcome is `"saved"` when every result is `applied` or `duplicate`, otherwise it throws the first rejection's reason. `shareDeepLink` for `"collection"`: `intent=collection` and `collection=<id>` or `collection_name=<encodeShareParam(name)>` (no reaction/note/primer). Update `submit.test.ts`: the existing `buildShareAction` cases are unchanged; add cases for both collection picks (action order, payload shapes, a shared `collection_id`), for `submitShare` with two results where the second is rejected (throws its reason), and for the collection deep link.
  - `deepLink.ts`: `sharedSourceFromParams` still returns null for `intent=collection`; new `sharedCollectionItemFromParams` decodes `url` and `collection_name`, returns `{url, pick}` for `intent=collection` with exactly one of `collection` / a non-blank `collection_name`, else null. Tests in `deepLink.test.ts` for both picks and the null cases.
  - `app/src/app/share.tsx`: when `sharedCollectionItemFromParams(params)` returns a value, do what the add sheet's `saveToCollection` does (create when new, then `addCollectionItem`, `writeLastCollectionId`), then `requestSync()` and `router.replace("/(tabs)/library")`; a library share is unchanged.
  - `keychain.ts`: the comment on `readSharedSessionKey` becomes "What the share extension uses: it never writes the session key and never touches the database (it reads and writes only the collection items in `@/collections/sharedCollections`)."

- [ ] **Step 6: Check the extension's imports.** `rg -n "from \"@/(db|collections/(useCollectionsData|prompts|CollectionsMirror))|Alert|ActionSheetIOS" app/src/share app/src/capture/CollectionChips.tsx app/src/capture/CaptureOptions.tsx app/index.share.tsx` prints nothing.
- [ ] **Step 7: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 8: Commit** "App: Save to a collection from the add sheet and the share extension".

### Task 5: App: Saved → Collections tiles  (tier: standard)

**Files:**
- Create: `app/src/library/CollectionsSection.tsx`, `app/src/library/CollectionTile.tsx`
- Modify: `app/src/library/SavedView.tsx`

**Interfaces:**
- Consumes (Task 2): `useCollectionsData`, `CollectionWithItems`, `mosaicImages`, `savedCountLabel`, `createCollection`, `renameCollection`, `deleteCollection`, `promptCollectionName`, `confirmDeleteCollection`; `MenuSheet` (`@/ui/MenuSheet`), `haptic`, `requestSync`.
- Produces: tiles push `/collection/[id]` with `router.push({ pathname: "/collection/[id]", params: { id } })` (the screen is Task 6's; typed routes are generated only when Metro runs, so a worktree's typecheck accepts the pathname — don't commit `.expo/`). testIDs `saved-collections`, `collection-tile-<id>`, `collection-new-tile`, `collection-menu-rename`, `collection-menu-delete`.
- Depends on: Tasks 1-2.
- Review: no.

- [ ] **Step 1: `SavedView`.** Keep the Favorites section exactly as it is. Below it render `<CollectionsSection />`. The `saved-empty` line now shows only when there are no favorites **and** `useCollectionsData()` is empty, and it sits above the Collections section (Decision 7). Update the component's docstring ("Library's Saved mode: starred items by domain, then collections").

- [ ] **Step 2: `CollectionsSection`** (`testID="saved-collections"`): a `monoLabel` `ink3` header `Collections · ${collections.length}` (uppercased by the variant), then a two-column grid (`flexDirection: "row"`, `flexWrap: "wrap"`, `gap: theme.spacing.sm`; each cell `width: "48.5%"` or computed from `onLayout`) of one `CollectionTile` per collection in `useCollectionsData()` order, then the new tile: `testID="collection-new-tile"`, transparent with a 1.5pt `line` border, min height 140, centered `＋ New collection` (`variant="headline"`, `ink2`); tapping it calls `promptCollectionName({ title: "New collection", submitLabel: "Create", onSubmit: (name) => { createCollection(db, name); haptic("success"); requestSync(); } })`.
  - Long-press state: `const [menuFor, setMenuFor] = useState<CollectionWithItems | null>(null)` and one `MenuSheet` with `Rename` (`collection-menu-rename` → `promptCollectionName({ title: "Rename collection", submitLabel: "Save", initialName: menuFor.name, onSubmit: (name) => { renameCollection(db, menuFor.id, name); requestSync(); } })`) and `Delete collection` (`collection-menu-delete`, destructive, `startsGroup` → `confirmDeleteCollection({ name, count: items.length, onConfirm: () => { deleteCollection(db, id); haptic("success"); requestSync(); } })`). `MenuSheet` already runs the chosen action after the sheet dismisses, so the native prompt can present.

- [ ] **Step 3: `CollectionTile`** (props `{ collection: CollectionWithItems; onPress: () => void; onLongPress: () => void }`, `testID="collection-tile-<id>"`): a `Card`-styled `Pressable` (surface, radius 16, card shadow, `overflow: "hidden"`); a 92-high 2×2 mosaic from `mosaicImages(collection)` (2pt gaps; each cell an `expo-image` `Image` with `contentFit="cover"`, or a `press`-colored `View` for null); under it a caption block (padding 9/11/11) with the name (`variant="headline"`, one line) and `savedCountLabel(collection.items.length)` (`monoLabel`, `ink3`, not uppercased by hand). `onPress` → `haptic("light")` then `router.push({ pathname: "/collection/[id]", params: { id } })`; `onLongPress` → `haptic("selection")` then open the menu. `delayLongPress` default.

- [ ] **Step 4: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 5: Commit** "App: Saved → Collections tiles with a mosaic, ＋ New collection, Rename and Delete".

### Task 6: App: the collection page  (tier: standard)

**Files:**
- Create: `app/src/app/collection/[id].tsx`, `app/src/collections/PostCard.tsx`, `app/src/collections/PostMenus.tsx`
- Modify: `app/src/app/_layout.tsx` (register the route)

**Interfaces:**
- Consumes (Task 2): `useCollectionsData`, `CollectionWithItems`, `CollectionItemRow`, `postByline`, `postSiteName`, `isVideo`, `formatDuration`, `savedDate`, `savedCountLabel`, `renameCollection`, `deleteCollection`, `editCollectionItemNote`, `moveCollectionItem`, `removeCollectionItem`, `promptCollectionName`, `confirmDeleteCollection`, `promptNote`; `MenuSheet`, `Screen`, `haptic`, `requestSync`.
- Produces: route `/collection/[id]`; testIDs `collection-page`, `collection-kicker`, `collection-more`, `collection-empty`, `collection-post-<itemId>`, `post-menu-note`, `post-menu-move`, `post-menu-remove`, `post-move-<collectionId>`, `collection-menu-rename`, `collection-menu-delete`.
- Depends on: Tasks 1-2.
- Review: no.

- [ ] **Step 1: Route.** In the root `_layout.tsx` signed-in block add `<Stack.Screen name="collection/[id]" />` after `favorites/[domain]`.

- [ ] **Step 2: The page** (`collection/[id].tsx`): `const { id } = useLocalSearchParams<{ id: string }>()`; `const collections = useCollectionsData()`; `const collection = collections.find((candidate) => candidate.id === id)`. When it is missing (deleted here or elsewhere), `router.back()` in an effect and render nothing.
  - `<Screen title="" onBack={router.back} headerRight={<Pressable testID="collection-more" accessibilityLabel="More" hitSlop={12} onPress={…}><Ionicons name="ellipsis-horizontal" size={24} color={theme.colors.ink} /></Pressable>}>`. (Match how `source/[id].tsx` draws its `item-more` •••; if `Screen` needs a non-empty `title`, pass the collection name and skip the separate title below.)
  - Root `View testID="collection-page"`: the kicker `Text variant="kicker" tone="ink3" testID="collection-kicker"` `Collection · ${savedCountLabel(n)}`, then the name in `largeTitle`.
  - The feed: `gap: 14`, one `PostCard` per `collection.items` (already newest first). With no posts: `Text tone="ink2" testID="collection-empty"` `Nothing saved here yet.`
  - ••• opens a `MenuSheet` with `Rename` (`collection-menu-rename` → `promptCollectionName({ title: "Rename collection", submitLabel: "Save", initialName: collection.name, … renameCollection … })`) and `Delete collection` (`collection-menu-delete`, destructive, `startsGroup` → `confirmDeleteCollection({ …, onConfirm: () => { deleteCollection(db, collection.id); haptic("success"); requestSync(); router.back(); } })`).

- [ ] **Step 3: `PostCard`** (props `{ item: CollectionItemRow; onLongPress: () => void }`, `testID="collection-post-<id>"`): a surface card (radius 18, card shadow, `overflow: "hidden"`) that is a `Pressable`:
  - Media, 16:9 (`aspectRatio: 16 / 9`): `expo-image` `Image` `contentFit="cover"` when `imageUrl`; otherwise a `press`-colored tile with `postSiteName(item.url)` centered (`variant="headline"`, `ink3`). When `isVideo(item)`: a centered 46pt circle (`rgba(0,0,0,0.45)`) with a white `▶`; when `durationSeconds !== null`, a bottom-right chip (`rgba(0,0,0,0.5)`, white mono 11) with `formatDuration(item.durationSeconds)`.
  - Body (padding 11/14/13): a row with `postByline(item)` (`secondary`, `ink3`, author part may be bold `ink` if simple; otherwise plain) and `savedDate(item.createdAt)` right-aligned; then `item.title ?? item.url` (`body`); then, when `item.note`, the note in italics (`secondary`, `ink2`, `fontStyle: "italic"`).
  - `onPress` → `haptic("light")`; `void Linking.openURL(item.url)` (react-native `Linking`; comment: "Opens in X, YouTube or Safari: nothing plays inside Archie."). `onLongPress` → `haptic("selection")`; `onLongPress()`.

- [ ] **Step 4: `PostMenus`** (props `{ item: CollectionItemRow | null; collections: CollectionWithItems[]; onClose: () => void }`): a `MenuSheet` for the long-pressed post with `Edit note` (`post-menu-note` → `promptNote({ initialNote: item.note ?? "", onSubmit: (note) => { editCollectionItemNote(db, item.id, note); requestSync(); } })`), `Move to…` (`post-menu-move`, only when another live collection exists → opens a second `MenuSheet` listing the other collections, each `post-move-<collectionId>` → `moveCollectionItem(db, item.id, target.id); haptic("success"); requestSync();`), and `Remove` (`post-menu-remove`, destructive, `startsGroup` → `removeCollectionItem(db, item.id); haptic("success"); requestSync();`). The second sheet opens from the first's chosen action (which `MenuSheet` runs after dismissal), so two modals are never up at once.

- [ ] **Step 5: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 6: Commit** "App: the collection page: a feed of saved posts, open the original, Edit note / Move to… / Remove, Rename / Delete".

---

## Integration task (serial, in `saved-collections`, after Tasks 3–6 are merged)

### Task 7: Merge check, Maestro flow, docs, full verification  (tier: standard; Maestro runs by the coordinator)

**Files:**
- Create: `maestro/collections.yaml`
- Modify: `Makefile` (`maestro` target), `maestro/README.md`, `docs/superpowers/specs/2026-10-26-product-scope.md`, `docs/superpowers/specs/2026-11-05-saved-and-takes-design.md` (status line)
- Review: no.

- [ ] **Step 1: Merge check.** `git log --oneline` shows Tasks 3–6 merged. Root `_layout.tsx` has both `<CollectionsMirror />` (Task 2) and the `collection/[id]` route (Task 6); The boundary still holds: `rg -n "collectionItems|collection_items" app/src/library app/src/today app/src/review app/src/topics app/src/item` lists only `app/src/library/{SavedView,CollectionsSection,CollectionTile}.tsx` (Saved is allowed), and `rg -n "CollectionItem|collection_items" services/worker/archie_worker/handlers` lists only `fetch_collection_item.py` and the registry.

- [ ] **Step 2: Suites:** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t7` (ignore "already exists"); `make lint`; `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t7 uv run pytest -m "postgres or not postgres"` — all pass; `cd app && npm run typecheck && npx jest` — pass.

- [ ] **Step 3: New flow** `maestro/collections.yaml` (free to run: the preview fetch is one page request, no model calls):

```yaml
appId: com.sampocs.archie
---
# Make a collection from the add sheet while saving a link into it, see the post on the collection page and not in
# Library → All, then delete the collection from its tile's long-press menu.
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
# A path and a name no other flow uses: `make maestro` keeps one user's data across flows.
- inputText: "https://example.com/collections-flow"
- tapOn:
    id: "intent-collection"
# No collections yet, so the dropdown reads "New collection…" and Save asks for the name.
- assertVisible:
    id: "collection-dropdown"
    text: ".*New collection….*"
- tapOn:
    id: "add-save"
- extendedWaitUntil:
    visible: "New collection"
    timeout: 5000
- inputText: "Maestro scrapbook"
- tapOn: "Create"
# Save closes the sheet; wait for it to go (its field holds the URL the checks below look for).
- extendedWaitUntil:
    notVisible:
      id: "add-url"
    timeout: 5000
- tapOn:
    id: "library-mode-saved"
- assertVisible:
    id: "saved-collections"
- tapOn: "Maestro scrapbook"
- assertVisible:
    id: "collection-page"
- assertVisible:
    id: "collection-kicker"
    text: "(?i).*1 saved.*"
# The post's caption becomes the page title once the preview lands, so match the post by id.
- assertVisible:
    id: "collection-post-.*"
- tapOn:
    id: "screen-back"
# A collection post is never a source: All doesn't list it.
- tapOn:
    id: "library-mode-all"
- assertNotVisible:
    text: ".*collections-flow.*"
- tapOn:
    id: "library-mode-saved"
- longPressOn: "Maestro scrapbook"
- tapOn:
    id: "collection-menu-delete"
- tapOn: "Delete"
- extendedWaitUntil:
    notVisible: "Maestro scrapbook"
    timeout: 5000
```

(If the kicker's `text` regex doesn't match because of the variant's uppercase transform, assert `id: "collection-kicker"` alone and `assertVisible: "(?i).*1 saved.*"`. If the native prompt's field isn't focused on the simulator, `tapOn` the prompt's text field before `inputText`. If `screen-back` is not on this page, use the page's back control id from `Screen`.)

- [ ] **Step 4: Makefile and docs.**
  - `Makefile`: add `maestro/collections.yaml` to the `maestro` target's list right after `maestro/favorites.yaml` (favorites ends by asserting `saved-empty`, which holds only while no collection exists; this flow deletes its own collection at the end).
  - `maestro/README.md`: a table row for `collections.yaml` ("Save a link from the Library ＋ into a new collection, see it on the collection page and not in All, delete the collection from its tile"); add it to the `make maestro` list in Running step 2.
  - Product scope (`2026-10-26-product-scope.md`): in the Library bullets, the **Saved** bullet gains: Collections, just-for-fun scrapbooks saved from the add sheet's or share sheet's "Save to a collection" (a dropdown preselected to the last one used, ＋ New collection…), shown under Saved as tiles with a mosaic of the newest thumbnails and "N saved" (long-press to rename or delete); a collection page is a feed of posts (thumbnail, who posted it, where it's from, date saved, caption, note) that open the original; posts never appear in All, Domains, search, Today, Pulse, Ask or the pipeline. Mention the ＋ (Add) section's third choice.
  - Spec (`2026-11-05-saved-and-takes-design.md`): the **Status** line becomes "Piece 1 (Nav + Favorites) implemented on `saved-nav-favorites` (plan `docs/superpowers/plans/2026-11-05-saved-nav-favorites.md`); piece 2 (Collections) implemented on `saved-collections` (plan `docs/superpowers/plans/2026-11-05-saved-collections.md`); migration numbers moved to `0008_favorites` and `0009_collections` because M6 took 0007."
- [ ] **Step 5: Commit** "Saved piece 2: Maestro collections flow, docs".
- [ ] **Step 6 (coordinator, main checkout):** the branch is held by its worktree, so in the main checkout `git checkout --detach saved-collections`. Then `make db-up`, `make migrate-local`, `make start-local` in one terminal; boot the simulator and `cd app && npx expo run:ios` (no new native modules, so the installed dev build with `npx expo start` also works; the app's migration 0009 runs on launch). Run `make maestro` (every existing flow plus `collections.yaml`) and `make maestro-offline`. `make maestro-review`/`maestro-podcast` spend real credits and nothing they cover changed: run them only if the owner asks. A failure caused by a real outside change is reported, not papered over. Afterwards stop the backend and Metro and `git checkout main` in the main checkout.
- [ ] **Step 7: Manual check for the owner** (the share sheet can't be automated; list it in the PR description): on a device or simulator build with this branch, (1) open Archie once so the collection list reaches the Keychain; (2) in Safari or X, Share → Archie: "Save to a collection" shows chips for each collection and `＋ New collection…`, preselected to the last one used; (3) save into an existing collection, then into a new one typed in the field; (4) both posts appear on their collection pages in Archie (after a sync) and not in Library → All; (5) the next share preselects the collection just used; (6) with the backend unreachable, "Open Archie" saves the post into the chosen (or new) collection from the app.
- [ ] **Step 8:** `git status` clean apart from intended changes; `saved-collections` ready for a PR (do not push or merge unless asked).

---

## Self-review notes

- Spec coverage (piece 2 of Build order): `collections` + `collection_items` tables with the spec's columns, client ids, soft delete and `change_seq` (T1 server, T2 phone); `create_collection` / `update_collection` (rename, reorder, delete soft-deleting its items) / `add_collection_item` (queues the job) / `update_collection_item` (note, move, remove) with "a collection item saved to an unknown or deleted collection is rejected" (T1, wire contract in Global Constraints); `fetch_collection_item` with X via fxtwitter → vxtwitter, YouTube via the existing watch-page lookup, else og:title/og:image, standard retries, failure leaves the URL and a neutral tile, no Retry (T3, Decision 5); add sheet "Save to a collection" with a native-menu dropdown preselected to the last collection used, "＋ New collection…" asking for a name, "New collection…" asking on Save, Save closes and stays on Library (T4, Decisions 2–3); the share extension's same choice with chips, fed by the shared Keychain store (T2 mirror, T4 sheet, Decision 1); Saved → Collections · N, two-column tiles in creation order with a 2×2 mosaic of the newest four thumbnails, name, "N saved", last tile "＋ New collection", long-press Rename/Delete (T5, Decision 7); collection page with kicker "Collection · N saved", the name as title, newest-first feed of 16:9 thumbnails with ▶ and duration, author, "X video"/"YouTube"/site, date saved, caption or title, italic note, tap opens the URL, long-press Edit note / Move to… / Remove, ••• Rename / Delete collection, neutral tile with the site name (T6, Decisions 5, 6, 10). The boundary (never sources, never in All/Domains/search/Today/Pulse/Ask/pipeline) is enforced by separate tables and checked by T1's e2e (no source, only the preview job), T2's jest boundary test, T3's worker test, T7's `rg` check and the Maestro flow's "not in All".
- Testing (spec): server e2e for each action through push then pull, delete soft-deletes items (T1); worker `fetch_collection_item` for an X video and a YouTube link from cassettes (T3, plus X photo/text-only, og, 4xx, 5xx, deleted); app jest boundary test (T2); Maestro "make a collection from the add sheet and save a link into it, on the collection page and not in All" (T7); manual share-sheet check (T7 Step 7).
- Not in this piece by design: takes, collection reordering UI, a capture-time note, Retry for previews.
- Types: `CollectionPick`, `SharedCollection`, `defaultCollectionId`/`defaultCollectionPick`, `createCollection(db, name): string`, `addCollectionItem(db, {collectionId, url}): string`, `jobs.COLLECTION_ITEM_ID_KEY`, `content.LinkPreview` are each defined once (T1, T2, T3, T4) and used with the same names and shapes by later tasks. Wire keys (`collection_id`, `duration_seconds`, `metadata_status`, …) match between T1's schemas, T2's `Pulled*` types and the payloads T2/T4 enqueue.
- Review tags: T1 yes (migration, sync), T2 yes (migration, sync, sign-out), T3 yes (outside calls, lock contract), T4 yes (share extension), T5, T6, T7 no.
