# Saved and Takes, piece 3: Takes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Takes: opinions and talking points the owner writes (or dictates and has Archie clean up), kept as dated versions, listed under Library → Takes, each with 2–4 review cards that Review shows with a "Your take" kicker.

**Architecture:**
- DB (`0010_takes`): two new synced tables, `takes` (kind, title, current version) and `take_versions` (body, raw body, cleaned, clean failed), plus `cards.take_id` / `cards.take_version_id` with the one-origin CHECK widened to four origins. A small shared module `archie_db/takes.py` holds what the API and the worker both need (current version, "is current", queueing a version's next step).
- API: four push actions in a new `services/api/archie_api/sync/take_actions.py` (`save_take`, `update_take`, `restore_take_version`, `retry_take_cleanup`); pull ships both tables and the cards' new columns.
- Worker: `clean_take` (Sonnet 5.5, Opus fallback) turns a version's raw text into markdown and queues `take_cards`; on final failure the raw text becomes the body and the page offers Try again. `take_cards` (Haiku 5.5, Sonnet fallback) writes 2–4 cards for the take's current version only, retiring its previous cards.
- App: drizzle migration 0010 and sync of both tables and the card columns; optimistic actions; a `takes` folder (pure grouping/labels/version logic, a live hook); Review learns the `take` origin (always reviewable while the take lives), a `take` session mode and the "Your take" kicker; `CardsSection` takes a source or a take. Screens: the editor (`app/src/app/take/edit.tsx`), "Write a take ›" in the add sheet, the Takes list with filter chips, the take page (`app/src/app/take/[id].tsx`) and the version viewer (`app/src/app/take/version.tsx`).

**Tech Stack:** as pieces 1–2 (FastAPI, SQLAlchemy/Alembic, Postgres; `archie-llm` over the Anthropic SDK; Expo Router, drizzle + expo-sqlite, jest, Maestro, pytest-recording/vcrpy). No new packages, no new native modules (the Clean it up switch is React Native's `Switch`; dictation is the iOS keyboard mic).

**Spec:** `docs/superpowers/specs/2026-11-05-saved-and-takes-design.md` (owner-approved; piece 3 of its Build order). Mocks `2026-11-05-saved-and-takes-mocks.html`, screens 02, 07, 08 and 09; where the mocks and the spec differ, the spec wins. Card review rules: `docs/superpowers/specs/2026-11-05-m6-review-design.md`. UX rules: `docs/superpowers/specs/2026-10-29-ux-and-brand-design.md`. Piece 2's plan (`2026-11-05-saved-collections.md`) is the house template this one follows.

## Global Constraints

- **Python style:** `AGENTS.md` house style (module-qualified imports as the repo does them, e.g. `from archie_db import changes, models, takes` then `takes.current_version(...)`; classes/`typing` by name; full typing with `X | None`; `StrEnum`s for compared strings; dataclasses over tuples of >2; named parameters; guard clauses; blank-line paragraphs past ~8 lines; why-comments; docstrings on public functions/classes).
- **Takes stay off the source side:** a take is never a source. No code in this piece writes `sources`, `source_artifacts` or pipeline jobs for a take; takes have no domain or topic and never appear in All, Domains, search, Today, Pulse or Ask. Take cards are `cards` rows with `take_id` set and `source_id`, `artifact_id`, `topic_primer_id`, `brief_id` all null.
- **Action contract:** every push action handler has the signature `(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None` (rejection reason or None) and runs under the batch's user lock inside a savepoint. **A handler validates everything before its first write**: returning a reason does *not* roll back earlier writes. Every changed take gets `changes.touch`; a changed version gets `takes.mark_changed` (versions have no `updated_at`); inserts take `changes.next_change_seq()`.
- **Wire payloads** (snake_case; `id` is always the take, the row whose local copy the phone keeps while the action is unsent; `version_id` is a version row made or changed by the action, which the phone also keeps):

  | type | payload | server effect |
  |---|---|---|
  | `save_take` | `{id, version_id, kind, title, body, clean}` | creates the take if `id` is new, else updates its kind and title; makes version `current_version + 1` with id `version_id` **when it is a first save, the body changed, or `clean` is true and the current version isn't cleaned** (`raw_body` = body; `body` = body, or null with `clean`; `cleaned` = `clean`); queues `clean_take` for that version when `clean`, otherwise `take_cards`. No version → no job. |
  | `update_take` | `{id, kind?, title?, deleted?}` | change kind, rename, or delete (`deleted: true` soft-deletes the take and retires its live cards); never a new version |
  | `restore_take_version` | `{id, version, version_id}` | copies that version's `body` (or its `raw_body` if it never got one), `raw_body` and `cleaned` into a new version `version_id` without re-cleaning; queues `take_cards` |
  | `retry_take_cleanup` | `{id, version_id}` | always bumps the version's `change_seq`; when it is `cleaned` and `clean_failed`, sets `body` null and `clean_failed` false and queues `clean_take` (otherwise a no-op, applied) |

  "Body changed" compares the stripped body with the current version's `body`, or its `raw_body` while the cleanup runs. Titles are stored stripped with whitespace collapsed. Rejections (exact strings): `rows.MALFORMED` ("payload is malformed", including an unknown `kind`); "take not found" (unknown, another user's or deleted take); "take version not found"; "take title is empty"; "take title is longer than 200 characters"; "take is empty"; "take is longer than 20000 characters"; "id already exists" (a `version_id` that exists, when the action would make a version). `deleted: false` is ignored.
- **Pulled rows:** `rows.takes: [{id, kind, title, current_version, created_at, updated_at, deleted_at, change_seq}]`, `rows.take_versions: [{id, take_id, version, body, raw_body, cleaned, clean_failed, created_at, change_seq}]`; every pulled card gains `take_id` and `take_version_id`. All three are optional on the phone (`?? []` / `?? null`): an older server omits them.
- **Jobs:** `JobKind.CLEAN_TAKE = "clean_take"` and `JobKind.TAKE_CARDS = "take_cards"`, both with payload `{"take_version_id": "<uuid>"}` (`jobs.TAKE_VERSION_ID_KEY`), standard attempts (3) and backoff. `clean_take` writes only the version it was queued for and only while that version's `body` is null; it queues `take_cards` only when the version is still current. Its failure hook sets `body` = `raw_body`, `clean_failed` = true and (if current) queues `take_cards`. `take_cards` never runs for a non-current version or one without a body, and re-checks "still current" under the lock after the model call (a save during the call already queued a fresh job). Models: `llm.CLEAN_TAKE_MODELS = ModelPair(primary=SONNET, fallback=OPUS)`, `llm.TAKE_CARDS_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)`; every call is logged in `llm_calls` (step = the job kind, `source_id` null).
- **Migration numbers:** server `0010` (`packages/archie-db/archie_db/migrations/versions/0010_takes.py`, revises `0009`); app drizzle `0010_takes`. (The spec's `0009_takes` predates M6 taking 0007.)
- **Cards CHECK:** `models.CARD_ORIGIN_CHECK` and the migration become `num_nonnulls(source_id, topic_primer_id, brief_id, take_id) = 1` (constraint `ck_cards_one_origin`, dropped and re-created). `take_version_id` is informational (which version the card came from) and is not part of the CHECK.
- **Drizzle migrations:** generate with `cd app && npx drizzle-kit generate --name takes`, then **read the generated SQL before committing.** Expected: two `CREATE TABLE` statements (`takes`, `take_versions`) and two `ALTER TABLE \`cards\` ADD \`take_id\` text;` / `ADD \`take_version_id\` text;` lines, nothing else. If drizzle instead emits a `__new_cards` rebuild, inspect its `INSERT INTO __new_cards (...) SELECT ... FROM cards` by hand: it must list **every** column the phone's `cards` table has after `0009` (id, source_id, topic_primer_id, brief_id, kind, question, answer, created_at, deleted_at, fsrs_state, stability, difficulty, due_at, last_review_at, reps, lapses, expires_at) and no column that doesn't exist yet (M6's generated rebuild got this wrong); fix it, or move the two new columns to the end of the `cards` definition and regenerate. Either way the migration ends with the re-pull reset (`UPDATE sync_state SET position = 0;`) and gets a jest test that an existing card with a schedule survives it (Task 2).
- **Review of take cards:** a take card is reviewable as soon as it exists, while its take is live (you wrote what it came from, so there is nothing to "take in" first; `cardDueLabel` never says "After you finish" for one). It is graded, scheduled and dropped exactly like M6 cards. Its question kicker is `Your take · <Opinion|Talking point>` in the take kind's colour. Take cards sort with concepts (order group 1). The session gains mode `take` (`/review/session?mode=take&id=<takeId>`), used by the take page's Practise.
- **Copy (verbatim):** add sheet: divider `or`, row `✎ Write a take` with a trailing `›`. Takes empty state: `Things you think, in your own words` and button `Write a take`. Takes chips `All` · `Opinions` · `Talking points` with counts; filtered-to-nothing line `No opinions yet.` / `No talking points yet.`. Kind labels `Opinion`, `Talking point`. Row meta `Written <date>` (one version) or `Updated <date>`, then `N versions` (hidden at 1), then `1 card` / `N cards` (hidden at 0), joined by ` · `; `<date>` is `Nov 2` this year, `Nov 2024` before. Take page meta `Written|Updated <date> · version N`; origin line `Cleaned up from your dictation · See what you said ›`; raw sheet title `What you said`; cleaning `Cleaning up…`; failed `Couldn't clean this up · Try again ›`; cards header `Cards from this · N` (existing `CardsSection`); earlier versions row `Earlier versions` with `N ›` (N = versions − 1); version rows `Version N` with the date; navbar `Edit` and `•••`; ••• menu `Change kind`, `Delete take`; kind menu `Opinion`, `Talking point`; delete confirm title `Delete “<title>”?`, message `Its versions and cards go with it.`, buttons `Cancel` / `Delete`. Version viewer kicker `Version N · <date>`, button `Restore this version`. Editor: kind toggle `Opinion` | `Talking point` (default Talking point), title placeholder `Title`, body placeholder `Write it out, or dictate with the keyboard's mic`, switch `Clean it up` with `Archie turns this into a short take with main points. Your words and claims only.`, hint `Saving makes version N+1 and rewrites this take's cards.` (a new take: `Saving makes version 1 and writes this take's cards.`), buttons `Cancel` / `Save`. Review kicker `Your take · Opinion` / `Your take · Talking point`.
- **testIDs** (new): `add-write-take`; `takes-view`, `takes-write`, `takes-filter-<all|opinion|talking_point>`, `takes-filter-count-<opinion|talking_point>`, `takes-filter-empty`, `take-row-<id>`; `take-page`, `take-kicker`, `take-title`, `take-meta`, `take-origin`, `take-see-raw`, `take-raw-sheet`, `take-raw-text`, `take-cleaning`, `take-clean-failed`, `take-clean-retry`, `take-body`, `take-edit`, `take-more`, `take-menu-kind`, `take-menu-delete`, `take-kind-opinion`, `take-kind-talking_point`, `take-versions`, `take-version-<n>`; `version-page`, `version-kicker`, `version-restore`; `take-editor`, `editor-kind-opinion`, `editor-kind-talking_point`, `editor-title`, `editor-body`, `editor-clean`, `editor-hint`, `editor-cancel`, `editor-save`. Existing ones stay (`takes-empty`, `library-add`, `library-mode-*`, `add-url`, `add-save`, `add-cancel`, `cards-section`, `cards-practise`, `card-row-<i>`, `card-remove-<i>`, `review-kicker`, `screen-back`, `menu-sheet`).
- **Tests:** e2e first; unit tests only for real logic; outside calls replayed from recorded cassettes, never hand-made response bodies. **Recording a cassette:** delete it, then `TEST_DATABASE_URL=… uv run pytest <test file> --record-mode=once -m postgres` (needs `ANTHROPIC_API_KEY` in the repo-root `.env`; a few cents); only `archie_testing.recording.use_recording_api_key` reads it, only in record mode. After recording, `rg -n "sk-ant|x-api-key|anthropic-organization-id|request-id" <cassette>` prints nothing (recorded keys and account ids are filtered; check anyway). Cassettes match on model + the first 60 characters of the system prompt, so **every new system prompt must differ from every other prompt in its first 60 characters** (Tasks 3 and 4 check this). App logic tests are `*.test.ts` (jest matches only `.ts`); pure app logic never imports a native module (`expo-sqlite`, `expo-secure-store`, `react-native` UI) — keep pure helpers in their own files.
- **Never print secrets** or `.env` values.
- **Branch and worktrees:** branch `saved-takes`, worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/saved-takes`. Foundation tasks (1, 2) run there serially. Each parallel-safe task runs in its own worktree from the last foundation commit (`git gtr new tk-t<N> --from-current --yes`, run inside the `saved-takes` worktree), then merges back into `saved-takes`. Never touch the main checkout except where Task 8's coordinator step says so.
- **App packages in worktrees:** a worktree's `app/node_modules` is a symlink to the main checkout's: `ln -sfn /Users/sampocs/Documents/Personal/second-brain/app/node_modules app/node_modules` (run in every worktree that runs `npm`/`npx`; once per worktree). Keep it out of git: `grep -qx 'app/node_modules' "$(git rev-parse --git-common-dir)/info/exclude" || echo 'app/node_modules' >> "$(git rev-parse --git-common-dir)/info/exclude"`. **npm packages are installed only in the main checkout's `app/`** (none are needed here). **Never run `npx prettier`** (the project has no prettier; it would reformat files wholesale).
- **Postgres from a worktree:** the container `second-brain-postgres-1` (`127.0.0.1:5434`) is already up from the main checkout. **Never run `make db-up`, `make db-down`, `make test-db`, `make migrate-local`, `make start-local`, `make reset-local-data` or any `make maestro*` target from a worktree** (they drive the main checkout's docker-compose stack and local data). Run tests with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t<N> uv run pytest -m "postgres or not postgres"`, where every task uses its own database (tests truncate tables and one downgrades the schema): `docker exec second-brain-postgres-1 createdb -U archie archie_test_t<N>` (ignore "already exists").
- **Maestro:** implementers add the testIDs listed in their task and write/edit flow files; flows are **run only by the coordinator, from the main checkout, against the local backend** (Task 8). Lessons every flow here follows: one `make maestro` run shares one user's server data across flows, so each flow uses titles and text no other flow uses; swipe a `SwipeRow` by screen position, not from an element id; after a sheet or modal's Save, wait for it to close (`notVisible: <its field id>`) before tapping text the sheet also holds; dismiss the keyboard (`hideKeyboard`, or tap a static label) before tapping a button below it; the dev test user isn't whitelisted, so its model calls fail with NEEDS_API_KEY — a flow that needs real model output logs in with `openLink: archie://dev/login?whitelisted=1` (as `maestro/review.yaml` does), spends a few cents, and gets its own `make` target outside `make maestro`.
- **Checks before every commit:** Python: `make lint` and the relevant tests (command above). App: `cd app && npm run typecheck && npx jest`.
- **Commits:** every message ends with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MN7nukQAsqfkk3GiAq6NkX
  ```
- **Out of scope:** deploying, `railway config apply`, pushing or merging to `main`; evidence finding or steelmanning; filing takes under domains/topics, search or Ask over takes; card preferences in take card prompts; a "new take" button on Today; tuning the clean-up and card prompts (the eval pass). The plan ends with `saved-takes` ready for a PR.

## Decisions made while planning

1. **Client-made version ids.** The spec's `save_take` / `restore_take_version` payloads carry no version id, but the phone must show a just-saved version offline and must not end up with two copies of it after the pull. Both actions carry `version_id` (made on the phone, like `add_source` ids); the server uses it for the version it makes. `restore_take_version`'s `take_id` is sent as `id`, per the wire rule.
2. **When a save makes a version:** the spec's "when the body changed", plus one case: Clean it up switched on for a version that wasn't cleaned makes a new (cleaned) version even with the same text — otherwise turning the switch on and tapping Save would silently do nothing. The phone runs the same rule (`saveMakesVersion`) so its optimistic rows match.
3. **"Couldn't clean this up" needs state the spec's columns don't have**, so `take_versions` gains `clean_failed boolean not null default false`, and Try again is a new action, `retry_take_cleanup {id, version_id}`. While the version waits again the page shows "Cleaning up…" with the raw text.
4. **Clean it up "remembers its last setting per take"** by reading the current version's `cleaned`: no extra column. A new take starts off; editing a cleaned version opens the cleaned text with the switch on.
5. **Dates:** "Written" is the first version's `created_at`; "Updated" is the current version's `created_at`, so renaming or changing the kind never changes a take's date or its place in the list. The list sorts by the current version's date, newest first.
6. **Take cards are reviewable once saved** (see Global Constraints), shown in Review as `Your take · <kind>` in the kind colour, and sorted with concepts. The phone does not retire a take's old cards on save: they stay until the new cards arrive with the server's retirement, so a take is never card-less offline.
7. **Editor navigation:** the editor is a modal (like the add sheet). Save always closes it: a new take from the add sheet or the Takes empty state lands back on Library (the spec's "Save closes the sheet and stays on Library"), an edit returns to the take page. From the add sheet, Write a take replaces the sheet with the editor.
8. **Earlier versions** expand inline on the take page (the mock's collapsed row); each opens the version viewer route `take/version` (`?id=<takeId>&version=<n>`), which the spec's screen list doesn't name. Restoring returns to the take page.
9. **Rejections on the phone:** a rejected `save_take` / `restore_take_version` deletes its optimistic version, deletes the take when it has no version left (a new take the server refused) or else points it back at its newest remaining version, and rewinds the sync position; a rejected `update_take` / `retry_take_cleanup` rewinds. None of them touch `sources`.
10. **Unsent versions:** the phone's "keep the local copy while an action is unsent" set also holds each pending payload's `version_id`, so an optimistic version (or one waiting on Try again) isn't overwritten by an older pulled copy; `retry_take_cleanup` always bumps its version so the skipped row comes back.
11. **Deleting a take** soft-deletes it and retires its cards on both sides; its versions stay (there is no `deleted_at` on versions) and are hidden through the take.
12. **Prompts read the reading voice for wording only:** `clean_take` includes `READING_VOICE` (spec) with an explicit rule that it never licenses adding definitions, examples or numbers; `take_cards` doesn't include it (its answers must be the owner's own wording).
13. **Migration 0010 resets the phone's sync position**, as every migration that adds pulled columns or tables does.

---

## File Structure

```
packages/archie-db/archie_db/models.py                                    TakeKind, Take, TakeVersion, CardKind.TAKE, JobKinds, Card.take_*, CHECK (T1)
packages/archie-db/archie_db/{takes,jobs,changes}.py                       current_version/is_current/mark_changed/enqueue_step/KIND_NAMES; TAKE_VERSION_ID_KEY; touch(Take) (T1)
packages/archie-db/archie_db/migrations/versions/0010_takes.py                                                               (T1)
packages/archie-db/tests/test_db_migrations.py                             0010 keeps cards, four-origin CHECK               (T1)
packages/archie-llm/archie_llm/llm.py                                      CLEAN_TAKE_MODELS, TAKE_CARDS_MODELS              (T1)
conftest.py                                                                truncate list                                     (T1)
services/api/archie_api/sync/{schemas,actions,pull}.py                     ActionTypes, Out shapes, HANDLERS, pull tables    (T1)
services/api/archie_api/sync/take_actions.py, services/api/tests/e2e/test_takes_e2e.py                                       (T1)
app/src/db/{schema,actions}.ts, app/drizzle/0010_takes.sql (+ meta, journal, migrations.js)                                  (T2)
app/src/sync/{engine,transport,engine.test}.ts, app/src/db/takes.test.ts, app/src/auth/{session,session.test}.ts             (T2)
app/src/takes/{takes,takes.test}.ts, app/src/takes/useTakesData.ts                                                           (T2)
app/src/review/{eligibility,eligibility.test,kicker,kicker.test,session,session.test,labels,testCards,useReviewData}.ts      (T2)
app/src/review/session/QuestionCard.tsx, app/src/item/CardsSection.tsx, app/src/app/source/[id].tsx                          (T2)
services/worker/archie_worker/{prompts}.py, handlers/{__init__,clean_take}.py, tests/test_clean_take_e2e.py (+ cassette)    (T3)
services/worker/archie_worker/{prompts}.py, handlers/{__init__,take_cards}.py, tests/test_take_cards_e2e.py (+ cassette)    (T4)
app/src/app/take/edit.tsx, app/src/takes/KindToggle.tsx, app/src/app/add.tsx, app/src/app/_layout.tsx (route)                (T5)
app/src/library/TakesView.tsx, app/src/takes/TakeRow.tsx                                                                     (T6)
app/src/app/take/{[id],version}.tsx, app/src/takes/{TakeBody,RawTextSheet,TakeMenus,prompts}.tsx|ts, _layout.tsx (routes)    (T7)
maestro/{takes,takes_clean}.yaml, Makefile, maestro/README.md, docs                                                          (T8)
```

Tasks 3 and 4 both edit `prompts.py` and `handlers/__init__.py`; Tasks 5 and 7 both edit `app/src/app/_layout.tsx`; Task 5 adds the editor route that Tasks 6 and 7 push to by path. The overlaps are textual only (typed routes are generated only when Metro runs, so a worktree's typecheck accepts the pathname — don't commit `.expo/`).

## Foundation tasks (run in `saved-takes`, serially)

### Task 1: Server: tables, migration 0010 with the four-origin CHECK, the four take actions, pull  (tier: most capable)

**Files:**
- Create: `packages/archie-db/archie_db/takes.py`, `packages/archie-db/archie_db/migrations/versions/0010_takes.py`, `services/api/archie_api/sync/take_actions.py`, `services/api/tests/e2e/test_takes_e2e.py`
- Modify: `packages/archie-db/archie_db/models.py`, `packages/archie-db/archie_db/jobs.py`, `packages/archie-db/archie_db/changes.py`, `packages/archie-db/tests/test_db_migrations.py`, `packages/archie-llm/archie_llm/llm.py`, `conftest.py` (`_TRUNCATE_TABLES`), `services/api/archie_api/sync/schemas.py`, `services/api/archie_api/sync/actions.py`, `services/api/archie_api/sync/pull.py`

**Interfaces:**
- Produces:
  - `models.TakeKind` (`OPINION = "opinion"`, `TALKING_POINT = "talking_point"`), `models.CardKind.TAKE = "take"`, `models.JobKind.CLEAN_TAKE = "clean_take"`, `models.JobKind.TAKE_CARDS = "take_cards"`.
  - `models.Take` (`id, user_id, kind, title, current_version, created_at, updated_at, deleted_at, change_seq`), `models.TakeVersion` (`id, user_id, take_id, version, body, raw_body, cleaned, clean_failed, created_at, change_seq`); `models.Card.take_id`, `models.Card.take_version_id`; `models.CARD_ORIGIN_CHECK` with four origins.
  - `jobs.TAKE_VERSION_ID_KEY = "take_version_id"`; `changes.touch(row)` accepts `models.Take`.
  - `archie_db.takes`: `KIND_NAMES: dict[models.TakeKind, str]`, `current_version(db, *, take) -> models.TakeVersion | None`, `is_current(take, version) -> bool`, `mark_changed(version) -> None`, `enqueue_step(db, *, version, kind: models.JobKind) -> None`.
  - `llm.CLEAN_TAKE_MODELS`, `llm.TAKE_CARDS_MODELS`.
  - `schemas.ActionType.SAVE_TAKE / UPDATE_TAKE / RESTORE_TAKE_VERSION / RETRY_TAKE_CLEANUP`; `schemas.TakeOut`, `schemas.TakeVersionOut`; `CardOut.take_id`, `CardOut.take_version_id`; `PulledRows.takes`, `PulledRows.take_versions`.
- Review: yes (migration with a CHECK change, sync shapes, version rules).

- [ ] **Step 1: Test DB.** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t1` (ignore "already exists"). Tests run with `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t1`.

- [ ] **Step 2: Write the failing e2e test** `services/api/tests/e2e/test_takes_e2e.py`:

```python
"""Takes through the real API: write, edit, clean up, restore, change kind and delete; pull takes and versions.

A save that makes a version queues that version's next step (`take_cards`, or `clean_take` with Clean it up on); a save
with an unchanged body makes no version and queues nothing. A take is never a source.
"""

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

BODY = "Crypto's lasting use is moving dollars. Stablecoins settle ~$10T a year."
EDITED = "Crypto's lasting use is moving dollars. Stablecoins settle ~$10T a year, with no bank in the middle."
RAMBLE = "ok so the main thing is people think it's all speculation but stablecoins did like 10 trillion last year"
CLEANED = "Crypto's lasting use is moving dollars.\n\n## Main points\n\n- Stablecoins did ~10 trillion last year."
TITLE = "The argument for crypto"


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


def _versions(rows: dict[str, list[dict[str, Any]]], take_id: str) -> list[dict[str, Any]]:
    return sorted((row for row in rows["take_versions"] if row["take_id"] == take_id), key=lambda row: row["version"])


def _save_payload(
    take_id: str, *, version_id: str, body: str = BODY, title: str = TITLE, kind: str = "talking_point", clean: bool = False
) -> dict[str, Any]:
    return {"id": take_id, "version_id": version_id, "kind": kind, "title": title, "body": body, "clean": clean}


def _save(authed: httpx.Client, *, take_id: str | None = None, **fields: Any) -> tuple[str, str]:
    """Push one save_take that must apply; returns the take id and the version id it sent."""
    take_id = take_id or str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    assert _reasons(_push(authed, _action("save_take", _save_payload(take_id, version_id=version_id, **fields)))) == [
        None
    ]
    return take_id, version_id


def _db(live_stack: LiveStack) -> sqlalchemy.orm.Session:
    return sqlalchemy.orm.Session(session.engine_for(live_stack.database_url))


def _queued(live_stack: LiveStack) -> list[tuple[str, str]]:
    """Every job as (kind, the version it names), oldest first."""
    with _db(live_stack) as db:
        queued = db.scalars(sqlalchemy.select(models.Job).order_by(models.Job.id))
        return [(job.kind, job.payload[jobs.TAKE_VERSION_ID_KEY]) for job in queued]


def _set_version(live_stack: LiveStack, *, version_id: str, body: str, clean_failed: bool) -> None:
    """What the worker writes: a cleaned body, or the raw text after the cleanup gave up."""
    with _db(live_stack) as db:
        version = db.get_one(models.TakeVersion, uuid.UUID(version_id))
        changes.lock_user_writes(db, version.user_id)
        version.body = body
        version.clean_failed = clean_failed
        version.change_seq = changes.next_change_seq()
        db.commit()


def _add_take_card(live_stack: LiveStack, *, take_id: str, version_id: str) -> str:
    """A card as take_cards writes it."""
    card_id = uuid.uuid4()
    with _db(live_stack) as db:
        take = db.get_one(models.Take, uuid.UUID(take_id))
        changes.lock_user_writes(db, take.user_id)
        db.add(
            models.Card(
                id=card_id,
                user_id=take.user_id,
                take_id=take.id,
                take_version_id=uuid.UUID(version_id),
                kind=models.CardKind.TAKE.value,
                question="Roughly how much do stablecoins settle a year?",
                answer="About $10T, Visa scale.",
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    return str(card_id)


def test_writing_a_take_makes_version_one_and_queues_its_cards(live_stack: LiveStack, authed: httpx.Client) -> None:
    """The title is stored with whitespace collapsed; the body is version 1 as written; no source is made."""
    take_id, version_id = _save(authed, title="  The argument   for crypto ", body=f"  {BODY}\n")

    rows = _rows(authed)

    take = _by_id(rows["takes"], take_id)
    assert (take["kind"], take["title"], take["current_version"], take["deleted_at"]) == (
        "talking_point",
        TITLE,
        1,
        None,
    )
    [version] = rows["take_versions"]
    assert (version["id"], version["take_id"], version["version"]) == (version_id, take_id, 1)
    assert (version["body"], version["raw_body"], version["cleaned"], version["clean_failed"]) == (
        BODY,
        BODY,
        False,
        False,
    )
    assert rows["sources"] == []
    assert _queued(live_stack) == [(models.JobKind.TAKE_CARDS.value, version_id)]


def test_clean_it_up_leaves_the_body_empty_and_queues_the_cleanup(live_stack: LiveStack, authed: httpx.Client) -> None:
    """With Clean it up on, the raw text is kept and the shown body waits for clean_take."""
    _, version_id = _save(authed, body=RAMBLE, clean=True)

    [version] = _rows(authed)["take_versions"]

    assert (version["body"], version["raw_body"], version["cleaned"]) == (None, RAMBLE, True)
    assert _queued(live_stack) == [(models.JobKind.CLEAN_TAKE.value, version_id)]


def test_an_unchanged_body_makes_no_version_but_saves_the_title_and_kind(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Fixing a title or the kind keeps the take's version (and so its date), and queues nothing."""
    take_id, first = _save(authed)
    before = _by_id(_rows(authed)["takes"], take_id)

    _save(authed, take_id=take_id, title="Crypto, the case", kind="opinion", body=f"{BODY}  ")
    rows = _rows(authed)

    take = _by_id(rows["takes"], take_id)
    assert (take["title"], take["kind"], take["current_version"]) == ("Crypto, the case", "opinion", 1)
    assert take["change_seq"] > before["change_seq"]
    assert [row["id"] for row in rows["take_versions"]] == [first]
    assert _queued(live_stack) == [(models.JobKind.TAKE_CARDS.value, first)]


def test_an_edit_makes_the_next_version_and_clean_on_alone_asks_for_a_cleanup(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A changed body is version 2; the same body with Clean it up switched on is version 3, waiting for cleanup."""
    take_id, first = _save(authed)
    _, second = _save(authed, take_id=take_id, body=EDITED)
    _, third = _save(authed, take_id=take_id, body=EDITED, clean=True)

    rows = _rows(authed)

    assert [(row["id"], row["version"], row["body"], row["cleaned"]) for row in _versions(rows, take_id)] == [
        (first, 1, BODY, False),
        (second, 2, EDITED, False),
        (third, 3, None, True),
    ]
    assert _by_id(rows["takes"], take_id)["current_version"] == 3
    assert _queued(live_stack) == [
        (models.JobKind.TAKE_CARDS.value, first),
        (models.JobKind.TAKE_CARDS.value, second),
        (models.JobKind.CLEAN_TAKE.value, third),
    ]


def test_saving_while_the_cleanup_runs_compares_against_the_raw_text(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Before clean_take lands, the editor shows the raw text; saving it unchanged makes no version."""
    take_id, first = _save(authed, body=RAMBLE, clean=True)

    _save(authed, take_id=take_id, body=RAMBLE, clean=True)

    assert [row["id"] for row in _versions(_rows(authed), take_id)] == [first]
    assert len(_queued(live_stack)) == 1


def test_restoring_copies_an_earlier_version_without_cleaning_it_again(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """The copy keeps the cleaned body, the raw text and the cleaned flag, and gets fresh cards."""
    take_id, first = _save(authed, body=RAMBLE, clean=True)
    _set_version(live_stack, version_id=first, body=CLEANED, clean_failed=False)
    _save(authed, take_id=take_id, body=EDITED)
    restored = str(uuid.uuid4())

    results = _push(authed, _action("restore_take_version", {"id": take_id, "version": 1, "version_id": restored}))
    rows = _rows(authed)

    assert _reasons(results) == [None]
    copy = _by_id(rows["take_versions"], restored)
    assert (copy["version"], copy["body"], copy["raw_body"], copy["cleaned"]) == (3, CLEANED, RAMBLE, True)
    assert _by_id(rows["takes"], take_id)["current_version"] == 3
    assert _queued(live_stack)[-1] == (models.JobKind.TAKE_CARDS.value, restored)


def test_deleting_a_take_retires_its_cards_and_refuses_later_changes(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """A deleted take's cards leave review with it; every take action then answers "take not found"."""
    take_id, version_id = _save(authed)
    card_id = _add_take_card(live_stack, take_id=take_id, version_id=version_id)

    _push(authed, _action("update_take", {"id": take_id, "deleted": True}))
    rows = _rows(authed)
    after = _push(
        authed,
        _action("update_take", {"id": take_id, "title": "Again"}),
        _action("save_take", _save_payload(take_id, version_id=str(uuid.uuid4()), body=EDITED)),
        _action("restore_take_version", {"id": take_id, "version": 1, "version_id": str(uuid.uuid4())}),
        _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}),
    )

    assert _by_id(rows["takes"], take_id)["deleted_at"] is not None
    card = _by_id(rows["cards"], card_id)
    assert card["deleted_at"] is not None
    assert (card["take_id"], card["take_version_id"], card["source_id"], card["kind"]) == (
        take_id,
        version_id,
        None,
        "take",
    )
    assert _reasons(after) == ["take not found"] * 4


def test_try_again_re_queues_a_failed_cleanup(live_stack: LiveStack, authed: httpx.Client) -> None:
    """After the cleanup gave up (raw text shown), Try again empties the body and queues clean_take again."""
    take_id, version_id = _save(authed, body=RAMBLE, clean=True)
    _set_version(live_stack, version_id=version_id, body=RAMBLE, clean_failed=True)
    before = _by_id(_rows(authed)["take_versions"], version_id)

    results = _push(authed, _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}))
    after = _by_id(_rows(authed)["take_versions"], version_id)
    again = _push(authed, _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}))

    assert _reasons(results) == [None]
    assert (after["body"], after["clean_failed"]) == (None, False)
    assert after["change_seq"] > before["change_seq"]
    # Nothing failed any more, so the second Try again is applied but queues nothing.
    assert _reasons(again) == [None]
    assert _queued(live_stack) == [(models.JobKind.CLEAN_TAKE.value, version_id)] * 2


def test_take_actions_refuse_other_users_and_bad_input(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Another user's take is not found; titles, bodies, kinds, versions and ids are checked before any write."""
    other = live_stack.authed(live_stack.sign_in(apple_sub="mallory"))
    take_id, version_id = _save(authed)

    foreign = _push(
        other,
        _action("save_take", _save_payload(take_id, version_id=str(uuid.uuid4()), body=EDITED)),
        _action("update_take", {"id": take_id, "deleted": True}),
        _action("restore_take_version", {"id": take_id, "version": 1, "version_id": str(uuid.uuid4())}),
        _action("retry_take_cleanup", {"id": take_id, "version_id": version_id}),
    )
    own = _push(
        authed,
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), title="   ")),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), title="t" * 201)),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), body=" \n ")),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), body="b" * 20001)),
        _action("save_take", _save_payload(str(uuid.uuid4()), version_id=str(uuid.uuid4()), kind="rant")),
        _action("update_take", {"id": take_id, "title": "  "}),
        _action("restore_take_version", {"id": take_id, "version": 9, "version_id": str(uuid.uuid4())}),
        _action("restore_take_version", {"id": take_id, "version": 1, "version_id": version_id}),
        _action("save_take", _save_payload(take_id, version_id=version_id, body=EDITED)),
        _action("retry_take_cleanup", {"id": take_id, "version_id": str(uuid.uuid4())}),
    )

    assert _reasons(foreign) == ["take not found"] * 4
    assert _reasons(own) == [
        "take title is empty",
        "take title is longer than 200 characters",
        "take is empty",
        "take is longer than 20000 characters",
        "payload is malformed",
        "take title is empty",
        "take version not found",
        "id already exists",
        "id already exists",
        "take version not found",
    ]
    rows = _rows(authed)
    assert [(row["title"], row["deleted_at"]) for row in rows["takes"]] == [(TITLE, None)]
    assert [row["id"] for row in rows["take_versions"]] == [version_id]
```

Run: `TEST_DATABASE_URL=… uv run pytest services/api/tests/e2e/test_takes_e2e.py -m postgres -v` — fails (no `takes` key in the pull / "action not supported yet").

- [ ] **Step 3: Models.** In `models.py`, after `MetadataStatus`:

```python
class TakeKind(StrEnum):
    """What a take is: what the owner thinks (an opinion), or the case they make for something (a talking point)."""

    OPINION = "opinion"
    TALKING_POINT = "talking_point"
```

`CardKind` gains `TAKE = "take"` after `QUIZ`, and its docstring becomes "The shape of a spaced-repetition card; `foundation` cards come from primers, `quiz` cards from briefs, `take` cards from the owner's takes." `JobKind` gains `CLEAN_TAKE = "clean_take"` and `TAKE_CARDS = "take_cards"` after `FETCH_COLLECTION_ITEM`. After the `CollectionItem` class:

```python
class Take(Base):
    """Something the owner wrote: an opinion or a talking point. Title and kind live here; only the body is versioned."""

    __tablename__ = "takes"
    __table_args__ = (sqlalchemy.Index("ix_takes_user_id_change_seq", "user_id", "change_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    title: Mapped[str] = mapped_column(sqlalchemy.String(200))
    # The `take_versions.version` the take page shows; every save that changes the body adds one.
    current_version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP)
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class TakeVersion(Base):
    """One dated version of a take's body, with the raw text the owner typed or dictated for it."""

    __tablename__ = "take_versions"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("take_id", "version", name="uq_take_versions_version"),
        sqlalchemy.Index("ix_take_versions_user_id_change_seq", "user_id", "change_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    take_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    # What the take page shows (markdown); null while `clean_take` is still writing it.
    body: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    raw_body: Mapped[str] = mapped_column(sqlalchemy.Text)
    # Clean it up was on for this version.
    cleaned: Mapped[bool] = mapped_column(sqlalchemy.Boolean)
    # Clean it up gave up: `body` holds the raw text and the take page offers Try again.
    clean_failed: Mapped[bool] = mapped_column(sqlalchemy.Boolean, server_default=sqlalchemy.false())
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)
```

Replace the CHECK comment and constant:

```python
# Exactly one origin per card; `take_version_id` only records which version a take card came from.
CARD_ORIGIN_CHECK = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id) = 1"
```

In `Card`, after `brief_id`:

```python
    take_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE")
    )
    take_version_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("take_versions.id", ondelete="CASCADE")
    )
```

and its docstring's origin sentence ends "…, a brief (quiz cards) or a take (take cards, with `take_version_id` naming the version they were written from)."

`changes.touch`'s parameter becomes `row: models.Source | models.Topic | models.Collection | models.CollectionItem | models.Take`. `jobs.py` gains, under `COLLECTION_ITEM_ID_KEY`:

```python
# The payload key of `clean_take` and `take_cards` jobs: the take version to clean up or write cards from.
TAKE_VERSION_ID_KEY = "take_version_id"
```

`llm.py` gains, after `NEWS_QUIZ_MODELS`:

```python
# Writing quality matters for a cleaned-up take; its cards are short and checked against the owner's own text.
CLEAN_TAKE_MODELS = ModelPair(primary=SONNET, fallback=OPUS)
TAKE_CARDS_MODELS = ModelPair(primary=HAIKU, fallback=SONNET)
```

`conftest.py` `_TRUNCATE_TABLES` gains `"take_versions", "takes",` right after `"cards",`.

- [ ] **Step 4: Shared take rows** `packages/archie-db/archie_db/takes.py`:

```python
"""Take rows shared by the API and the worker: the current version, marking a version changed, queueing its next step.

Every function that writes expects the caller to hold `changes.lock_user_writes` for the take's user.
"""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, jobs, models

# How prompts name each kind.
KIND_NAMES: dict[models.TakeKind, str] = {
    models.TakeKind.OPINION: "opinion",
    models.TakeKind.TALKING_POINT: "talking point",
}


def current_version(db: sqlalchemy.orm.Session, *, take: models.Take) -> models.TakeVersion | None:
    """The version the take page shows; every take the server stores has one."""
    return db.scalar(
        sqlalchemy.select(models.TakeVersion).where(
            models.TakeVersion.take_id == take.id, models.TakeVersion.version == take.current_version
        )
    )


def is_current(take: models.Take, version: models.TakeVersion) -> bool:
    """Whether `version` is what the live take shows now (a later save or a delete makes it stale)."""
    return take.deleted_at is None and take.current_version == version.version


def mark_changed(version: models.TakeVersion) -> None:
    """Give the version a fresh change position so phones pull it again (versions have no `updated_at`)."""
    version.change_seq = changes.next_change_seq()


def enqueue_step(db: sqlalchemy.orm.Session, *, version: models.TakeVersion, kind: models.JobKind) -> None:
    """Queue `clean_take` or `take_cards` for this version."""
    jobs.enqueue(db, kind=kind, user_id=version.user_id, payload={jobs.TAKE_VERSION_ID_KEY: str(version.id)})
```

- [ ] **Step 5: Migration** `packages/archie-db/archie_db/migrations/versions/0010_takes.py`:

```python
"""Takes: the owner's own opinions and talking points, their dated versions, and take cards as a fourth card origin.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)
_THREE_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id) = 1"
_FOUR_ORIGINS = "num_nonnulls(source_id, topic_primer_id, brief_id, take_id) = 1"


def upgrade() -> None:
    """Create `takes` and `take_versions`, add the cards' take columns, and widen the one-origin CHECK."""
    _create_takes()
    _create_take_versions()

    op.add_column("cards", sqlalchemy.Column("take_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("cards_take_id_fkey", "cards", "takes", ["take_id"], ["id"], ondelete="CASCADE")
    op.add_column("cards", sqlalchemy.Column("take_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "cards_take_version_id_fkey", "cards", "take_versions", ["take_version_id"], ["id"], ondelete="CASCADE"
    )

    # Existing cards all have exactly one of the first three origins, so they satisfy the wider check as they are.
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.create_check_constraint("ck_cards_one_origin", "cards", _FOUR_ORIGINS)


def _create_takes() -> None:
    op.create_table(
        "takes",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column("kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.String(200), nullable=False),
        sqlalchemy.Column("current_version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("deleted_at", _TIMESTAMP, nullable=True),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_takes_user_id_change_seq", "takes", ["user_id", "change_seq"])


def _create_take_versions() -> None:
    op.create_table(
        "take_versions",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sqlalchemy.Column(
            "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sqlalchemy.Column(
            "take_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("takes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("body", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("raw_body", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("cleaned", sqlalchemy.Boolean(), nullable=False),
        sqlalchemy.Column("clean_failed", sqlalchemy.Boolean(), server_default=sqlalchemy.false(), nullable=False),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.UniqueConstraint("take_id", "version", name="uq_take_versions_version"),
    )
    op.create_index("ix_take_versions_user_id_change_seq", "take_versions", ["user_id", "change_seq"])


def downgrade() -> None:
    """Undo `upgrade`; take cards go first so the three-origin CHECK holds again, then takes and their versions."""
    op.drop_constraint("ck_cards_one_origin", "cards", type_="check")
    op.execute("DELETE FROM cards WHERE take_id IS NOT NULL")
    op.drop_constraint("cards_take_version_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "take_version_id")
    op.drop_constraint("cards_take_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "take_id")
    op.create_check_constraint("ck_cards_one_origin", "cards", _THREE_ORIGINS)

    op.drop_table("take_versions")
    op.drop_table("takes")
```

Add to `packages/archie-db/tests/test_db_migrations.py` (after the 0007 test, same style):

```python
def test_0010_keeps_existing_cards_and_allows_exactly_one_origin_including_a_take(test_database_url: str) -> None:
    """A scheduled source card survives 0010 unchanged; a take card is allowed; a card with a source and a take isn't."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0009")
    engine = session.engine_for(test_database_url)
    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("INSERT INTO users (apple_sub, ingest_token) VALUES ('sub', 'token')"))
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO sources (id, user_id, url, normalized_url, kind, state, intent, change_seq) "
                "SELECT '00000000-0000-0000-0000-000000000001', id, 'https://example.com/a', "
                "'https://example.com/a', 'article', 'consumed', 'finished', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, kind, question, answer, fsrs_state, stability, reps, "
                "change_seq) SELECT '00000000-0000-0000-0000-000000000002', user_id, id, 'concept', 'Q?', 'A.', "
                "'review', 3.5, 2, nextval('change_seq') FROM sources"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.connect() as connection:
        card = connection.execute(
            sqlalchemy.text("SELECT source_id, fsrs_state, stability, reps, take_id, take_version_id FROM cards")
        ).one()
    assert (str(card.source_id), card.fsrs_state, card.stability, card.reps) == (
        "00000000-0000-0000-0000-000000000001",
        "review",
        3.5,
        2,
    )
    assert (card.take_id, card.take_version_id) == (None, None)

    with engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO takes (id, user_id, kind, title, current_version, change_seq) "
                "SELECT '00000000-0000-0000-0000-000000000003', id, 'opinion', 'T', 1, nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, take_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), user_id, id, 'take', 'Q?', 'A.', nextval('change_seq') FROM takes"
            )
        )

    # A source and a take on one card breaks the one-origin CHECK.
    with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, take_id, kind, question, answer, change_seq) "
                "SELECT gen_random_uuid(), takes.user_id, sources.id, takes.id, 'take', 'Q?', 'A.', "
                "nextval('change_seq') FROM takes, sources"
            )
        )

    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
    engine.dispose()
```

`test_models_match_the_migrations` and `test_downgrade_then_upgrade_round_trips` cover the rest.

- [ ] **Step 6: Schemas.** `ActionType` gains, after `UPDATE_COLLECTION_ITEM`:

```python
    SAVE_TAKE = "save_take"
    UPDATE_TAKE = "update_take"
    RESTORE_TAKE_VERSION = "restore_take_version"
    RETRY_TAKE_CLEANUP = "retry_take_cleanup"
```

`CardOut` gains `take_id: uuid.UUID | None` and `take_version_id: uuid.UUID | None` after `brief_id`. After `CollectionItemOut`:

```python
class TakeOut(pydantic.BaseModel):
    """A take as the phone stores it; its body lives in its versions."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    current_version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    change_seq: int


class TakeVersionOut(pydantic.BaseModel):
    """One version of a take's body as the phone stores it; `body` is null while Clean it up runs."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    take_id: uuid.UUID
    version: int
    body: str | None
    raw_body: str
    cleaned: bool
    clean_failed: bool
    created_at: datetime.datetime
    change_seq: int
```

`PulledRows` gains `takes: list[TakeOut]` and `take_versions: list[TakeVersionOut]`.

- [ ] **Step 7: Pull.** In `pull.py`: `PulledTable` gains `TAKES = "takes"` and `TAKE_VERSIONS = "take_versions"`; `pull_changes`'s docstring says "the ten synced tables"; `tables` gains

```python
        PulledTable.TAKES: _changed_rows(db, models.Take, user_id=user_id, since=since, limit=limit),
        PulledTable.TAKE_VERSIONS: _changed_rows(db, models.TakeVersion, user_id=user_id, since=since, limit=limit),
```

the response gains `takes=[schemas.TakeOut.model_validate(row) for row in page.rows[PulledTable.TAKES]]` and `take_versions=[schemas.TakeVersionOut.model_validate(row) for row in page.rows[PulledTable.TAKE_VERSIONS]]`, and `_changed_rows`'s type-variable constraint adds `models.Take, models.TakeVersion`. A deleted take ships like every other table's rows; its versions keep shipping (they have no `deleted_at`).

- [ ] **Step 8: Handlers** `services/api/archie_api/sync/take_actions.py`:

```python
"""Take actions: write or edit a take, change its kind, delete it, restore a version, and retry a failed cleanup.

A take's title and kind live on `takes`; only the body is versioned in `take_versions`. A save makes the next version
when it is the first, the body changed, or Clean it up is asked for on a version that wasn't cleaned, and queues that
version's next step: `clean_take` when it has no body yet, otherwise `take_cards`. Each handler returns the rejection
reason or None; the caller holds the user's write lock and every check runs before the first write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pydantic
import sqlalchemy
from archie_db import card_rows, changes, models, takes
from sqlalchemy import orm

from archie_api.sync import rows

MAX_TAKE_TITLE_LENGTH = 200
MAX_TAKE_BODY_LENGTH = 20_000

NO_TAKE = "take not found"
_NO_VERSION = "take version not found"
_EMPTY_TITLE = "take title is empty"
_LONG_TITLE = f"take title is longer than {MAX_TAKE_TITLE_LENGTH} characters"
_EMPTY_BODY = "take is empty"
_LONG_BODY = f"take is longer than {MAX_TAKE_BODY_LENGTH} characters"
_ID_EXISTS = "id already exists"


class _SaveTakePayload(pydantic.BaseModel):
    id: uuid.UUID
    # Made on the phone so the new version shows offline; unused when the save makes no version.
    version_id: uuid.UUID
    kind: models.TakeKind
    title: str
    body: str
    clean: bool = False


class _UpdateTakePayload(pydantic.BaseModel):
    id: uuid.UUID
    kind: models.TakeKind | None = None
    title: str | None = None
    # There is no undelete: false is accepted and ignored.
    deleted: bool = False


class _RestoreTakeVersionPayload(pydantic.BaseModel):
    id: uuid.UUID
    version: int = pydantic.Field(ge=1)
    version_id: uuid.UUID


class _RetryTakeCleanupPayload(pydantic.BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID


@dataclass(frozen=True)
class _VersionText:
    """A new version's text: the shown body (None until `clean_take` writes it), the owner's raw text, the flag."""

    body: str | None
    raw_body: str
    cleaned: bool


def save_take(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Write a new take or save an edit; a version-making save also starts its cleanup or its cards."""
    parsed = rows.parse(_SaveTakePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    title = _clean_title(parsed.title)
    body = parsed.body.strip()
    reason = _title_reason(title) or _body_reason(body)
    if reason is not None:
        return reason
    take = db.get(models.Take, parsed.id)
    if take is not None and not _is_owned_live(take, user=user):
        return NO_TAKE
    current = takes.current_version(db, take=take) if take is not None else None
    makes_version = _save_makes_version(current, body=body, clean=parsed.clean)
    if makes_version and db.get(models.TakeVersion, parsed.version_id) is not None:
        return _ID_EXISTS

    if take is None:
        take = models.Take(
            id=parsed.id,
            user_id=user.id,
            kind=parsed.kind.value,
            title=title,
            current_version=0,
            change_seq=changes.next_change_seq(),
        )
        db.add(take)
        db.flush()

    take.kind = parsed.kind.value
    take.title = title
    if makes_version:
        text = _VersionText(body=None if parsed.clean else body, raw_body=body, cleaned=parsed.clean)
        _add_version(db, take=take, version_id=parsed.version_id, text=text)
    changes.touch(take)
    return None


def update_take(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Rename a take, change its kind, or delete it (its cards leave review with it); none of these makes a version."""
    parsed = rows.parse(_UpdateTakePayload, payload)
    if parsed is None:
        return rows.MALFORMED
    take = _owned_take(db, user=user, take_id=parsed.id)
    if take is None:
        return NO_TAKE
    title = _clean_title(parsed.title) if parsed.title is not None else None
    reason = _title_reason(title) if title is not None else None
    if reason is not None:
        return reason

    if title is not None:
        take.title = title
    if parsed.kind is not None:
        take.kind = parsed.kind.value
    if parsed.deleted:
        take.deleted_at = sqlalchemy.func.now()
        card_rows.retire_cards(db, models.Card.take_id == take.id)
    changes.touch(take)
    return None


def restore_take_version(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Save an earlier version again as the newest one, exactly as it was (no new cleanup), and rewrite the cards."""
    parsed = rows.parse(_RestoreTakeVersionPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    take = _owned_take(db, user=user, take_id=parsed.id)
    if take is None:
        return NO_TAKE
    earlier = db.scalar(
        sqlalchemy.select(models.TakeVersion).where(
            models.TakeVersion.take_id == take.id, models.TakeVersion.version == parsed.version
        )
    )
    if earlier is None:
        return _NO_VERSION
    if db.get(models.TakeVersion, parsed.version_id) is not None:
        return _ID_EXISTS

    # A version replaced while its own cleanup was still running may have no body yet; its raw text stands in.
    body = earlier.body if earlier.body is not None else earlier.raw_body
    text = _VersionText(body=body, raw_body=earlier.raw_body, cleaned=earlier.cleaned)
    _add_version(db, take=take, version_id=parsed.version_id, text=text)
    changes.touch(take)
    return None


def retry_take_cleanup(db: orm.Session, *, user: models.User, payload: dict[str, object]) -> str | None:
    """Try again after Clean it up gave up: the version waits for `clean_take` again, its raw text shown meanwhile."""
    parsed = rows.parse(_RetryTakeCleanupPayload, payload)
    if parsed is None:
        return rows.MALFORMED
    take = _owned_take(db, user=user, take_id=parsed.id)
    if take is None:
        return NO_TAKE
    version = db.get(models.TakeVersion, parsed.version_id)
    if version is None or version.take_id != take.id:
        return _NO_VERSION

    # Always bumped: a phone that skipped this version while the action was unsent pulls it again.
    takes.mark_changed(version)
    if not (version.cleaned and version.clean_failed):
        return None

    version.body = None
    version.clean_failed = False
    takes.enqueue_step(db, version=version, kind=models.JobKind.CLEAN_TAKE)
    return None


def _add_version(db: orm.Session, *, take: models.Take, version_id: uuid.UUID, text: _VersionText) -> None:
    """Make `text` the take's next version and queue its next step: the cleanup when it has no body, else its cards."""
    take.current_version += 1
    version = models.TakeVersion(
        id=version_id,
        user_id=take.user_id,
        take_id=take.id,
        version=take.current_version,
        body=text.body,
        raw_body=text.raw_body,
        cleaned=text.cleaned,
        change_seq=changes.next_change_seq(),
    )
    db.add(version)
    db.flush()

    step = models.JobKind.CLEAN_TAKE if text.body is None else models.JobKind.TAKE_CARDS
    takes.enqueue_step(db, version=version, kind=step)


def _save_makes_version(current: models.TakeVersion | None, *, body: str, clean: bool) -> bool:
    """A first save, a changed body, or Clean it up asked for on a version that wasn't cleaned (the phone agrees)."""
    if current is None:
        return True
    shown = current.body if current.body is not None else current.raw_body
    return body != shown or (clean and not current.cleaned)


def _is_owned_live(take: models.Take, *, user: models.User) -> bool:
    return take.user_id == user.id and take.deleted_at is None


def _owned_take(db: orm.Session, *, user: models.User, take_id: uuid.UUID) -> models.Take | None:
    """The user's live take with this id; another user's or a deleted one is treated as missing."""
    take = db.get(models.Take, take_id)
    return take if take is not None and _is_owned_live(take, user=user) else None


def _clean_title(title: str) -> str:
    return " ".join(title.split())


def _title_reason(title: str) -> str | None:
    if not title:
        return _EMPTY_TITLE
    if len(title) > MAX_TAKE_TITLE_LENGTH:
        return _LONG_TITLE
    return None


def _body_reason(body: str) -> str | None:
    if not body:
        return _EMPTY_BODY
    if len(body) > MAX_TAKE_BODY_LENGTH:
        return _LONG_BODY
    return None
```

Register in `actions.py`: import `take_actions` with the other `archie_api.sync` modules, and in `HANDLERS` after the collections block add a `# Takes` comment and

```python
    schemas.ActionType.SAVE_TAKE: take_actions.save_take,
    schemas.ActionType.UPDATE_TAKE: take_actions.update_take,
    schemas.ActionType.RESTORE_TAKE_VERSION: take_actions.restore_take_version,
    schemas.ActionType.RETRY_TAKE_CLEANUP: take_actions.retry_take_cleanup,
```

(`_apply_action`'s IntegrityError fallback already answers "id already exists" for a raced id.)

- [ ] **Step 9: Run** `make lint` and `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t1 uv run pytest -m "postgres or not postgres"` — all pass, including the migration tests and `test_every_action_type_has_a_handler`. If a pre-existing pull test compares the full `rows` dict or a full card dict, add `"takes": [], "take_versions": []` / `"take_id": None, "take_version_id": None` to its expectation (the only allowed change to an existing test).
- [ ] **Step 10: Commit** "Server: takes and take_versions (migration 0010, four-origin card CHECK), the four take actions, pull".

### Task 2: App data layer: schema 0010, sync, optimistic actions, the takes module, take cards in Review  (tier: most capable)

**Files:**
- Modify: `app/src/db/schema.ts`, `app/src/db/actions.ts`, `app/src/sync/engine.ts`, `app/src/sync/transport.ts`, `app/src/sync/engine.test.ts`, `app/src/auth/session.ts`, `app/src/auth/session.test.ts`, `app/src/review/eligibility.ts`, `app/src/review/eligibility.test.ts`, `app/src/review/session.ts`, `app/src/review/session.test.ts`, `app/src/review/testCards.ts`, `app/src/review/useReviewData.ts`, `app/src/review/session/QuestionCard.tsx`, `app/src/item/CardsSection.tsx`, `app/src/app/source/[id].tsx` (the `CardsSection` call)
- Create: `app/drizzle/0010_takes.sql` (+ `meta/0010_snapshot.json`, journal and `migrations.js` entries, all generated), `app/src/db/takes.test.ts`, `app/src/takes/takes.ts`, `app/src/takes/takes.test.ts`, `app/src/takes/useTakesData.ts`, `app/src/review/kicker.ts`, `app/src/review/kicker.test.ts`

**Interfaces:**
- Consumes: the wire contract in Global Constraints (no code from Task 1).
- Produces:
  - `schema.takes` (`id, kind, title, currentVersion, createdAt, updatedAt, deletedAt`), `schema.takeVersions` (`id, takeId, version, body, rawBody, cleaned, cleanFailed, createdAt`); `schema.cards.takeId`, `schema.cards.takeVersionId`.
  - `actions.ts`: `ActionType` gains `save_take | update_take | restore_take_version | retry_take_cleanup`; `MAX_TAKE_TITLE_LENGTH = 200`; `saveTake(db: AppDb, input: { id: string | null; kind: TakeKind; title: string; body: string; clean: boolean }): string` (returns the take id); `changeTakeKind(db: AppDb, takeId: string, kind: TakeKind): void`; `deleteTake(db: AppDb, takeId: string): void`; `restoreTakeVersion(db: AppDb, takeId: string, version: number): void`; `retryTakeCleanup(db: AppDb, takeId: string, versionId: string): void`.
  - `engine.ts`: `PulledTake`, `PulledTakeVersion`; `PulledCard.take_id?`, `PulledCard.take_version_id?`; `PullPage.rows.takes?`, `PullPage.rows.take_versions?`.
  - `@/takes/takes` (pure): `TakeKind`, `TakeRow`, `TakeVersionRow`, `TakeWithVersions`, `TakeFilter`, `CleanState`, `EditorStart`, `TAKE_FILTERS`, `TAKE_FILTER_LABELS`, `TAKE_KIND_LABELS`, `TAKE_KIND_DOMAIN`, `asTakeKind(kind: string): TakeKind`, `shownBody(version): string`, `cleanState(version): CleanState`, `saveMakesVersion(current, input: { body: string; clean: boolean }): boolean`, `groupTakes(takes: TakeRow[], versions: TakeVersionRow[], cards: CardRow[]): TakeWithVersions[]`, `takeUpdatedAt(take): string`, `filterTakes(list, filter): TakeWithVersions[]`, `takeFilterCounts(list): Record<TakeFilter, number>`, `takeDate(iso: string, now: Date): string`, `takeDateLabel(take, now): string`, `takeListMeta(take, now): string`, `takePageMeta(take, now): string`, `earlierVersions(take): TakeVersionRow[]`, `editorHint(take: TakeWithVersions | null): string`, `editorStart(take: TakeWithVersions | null): EditorStart`.
  - `@/takes/useTakesData` (app only): `useTakesState(): { takes: TakeWithVersions[]; loaded: boolean }`, `useTakesData(): TakeWithVersions[]`.
  - Review: `CardOrigin` gains `{ kind: "take"; takeId: string }`; `ReviewData.takesById: Map<string, TakeRow>`; `makeReviewData({ …, takes?: TakeRow[] })`; `SessionMode` gains `"take"`; `@/review/kicker`: `cardKicker(card: CardRow, data: ReviewData): { label: string | undefined; suffix: string | undefined; domain: string | null }`.
  - `CardsSection({ of }: { of: CardsOf })` with `export type CardsOf = { kind: "source"; id: string } | { kind: "take"; id: string }`.
- Review: yes (migration with a cards change, sync conflict and rejection rules, sign-out wipe, review eligibility).

- [ ] **Step 1: Worktree setup.** In this worktree: the `app/node_modules` symlink and exclude line from Global Constraints.

- [ ] **Step 2: Schema.** In `schema.ts`, `cards` gains, right after `briefId` (update the comment above `sourceId` to "…, a brief (quiz cards) or a take (take cards). Later origins add their own column; see review/eligibility.ts."):

```ts
  takeId: text("take_id"),
  // Which version of the take the card was written from.
  takeVersionId: text("take_version_id"),
```

Append:

```ts
// Takes (Library → Takes): what the owner writes. Title and kind live on the take; only the body is versioned.
export const takes = sqliteTable("takes", {
  id: text("id").primaryKey(),
  // opinion | talking_point
  kind: text("kind").notNull(),
  title: text("title").notNull(),
  // The take_versions.version the take page shows.
  currentVersion: integer("current_version").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});

export const takeVersions = sqliteTable("take_versions", {
  id: text("id").primaryKey(),
  takeId: text("take_id").notNull(),
  version: integer("version").notNull(),
  // What the take page shows (markdown); null while Clean it up runs.
  body: text("body"),
  // What the owner typed or dictated.
  rawBody: text("raw_body").notNull(),
  cleaned: integer("cleaned").notNull(),
  // Clean it up gave up: body holds the raw text and the page offers Try again.
  cleanFailed: integer("clean_failed").notNull().default(0),
  createdAt: text("created_at").notNull(),
});
```

- [ ] **Step 3: Generate the migration**: `cd app && npx drizzle-kit generate --name takes`. Check `drizzle/migrations.js` and `drizzle/meta/_journal.json` gained `0010_takes`, and **read `drizzle/0010_takes.sql`** against the Global Constraints' "Drizzle migrations" rule (two `CREATE TABLE`, two `ALTER TABLE cards ADD`, nothing else; a `__new_cards` rebuild is inspected and fixed by hand). Append, as `0009_collections.sql` does:

```sql
--> statement-breakpoint
-- Takes, their versions and the cards' take columns reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;
```

- [ ] **Step 4: Tests first** (they fail until Steps 5–8).

`app/src/takes/takes.test.ts` (rows from `takeRow` / `takeVersionRow` / `cardRow` in `@/review/testCards` (Step 9 adds the first two; write them first); `NOW = new Date(2026, 10, 5, 12)`):
- `saveMakesVersion(null, …)` → true; same body as `body` → false; same text as `rawBody` while `body` is null → false; changed body → true; same body with `clean: true` on a `cleaned: 0` version → true; same body with `clean: true` on a `cleaned: 1` version → false; same body with `clean: false` on a cleaned version → false.
- `cleanState`: `cleaned: 0` → `"none"`; cleaned with `body: null` → `"cleaning"`; cleaned with a body → `"cleaned"`; cleaned with `cleanFailed: 1` and a body → `"failed"`. `shownBody` returns `rawBody` while `body` is null.
- `groupTakes`: hides deleted takes; versions oldest first; `current` is the version matching `currentVersion` (the newest when none matches, null when there are none); `cardCount` counts only live cards with that `takeId`; order is the current version's `createdAt` newest first — a take renamed today (`updatedAt` today) whose current version is older sorts below a take whose current version is newer.
- `takeDate("2026-11-02T15:00:00Z", NOW)` → `"Nov 2"`; `takeDate(new Date(2024, 10, 3).toISOString(), NOW)` → `"Nov 2024"`.
- `takeListMeta`: one version, no cards → `"Written Nov 2"`; one version, 2 cards → `"Written Nov 2 · 2 cards"`; three versions (current Nov 2), 4 cards → `"Updated Nov 2 · 3 versions · 4 cards"`; one card → `"… · 1 card"`.
- `takePageMeta`: one version → `"Written Nov 2 · version 1"`; three → `"Updated Nov 2 · version 3"`.
- `earlierVersions` on three versions with current 3 → versions 2, 1 (newest first); after a restore (current 3 copied from 1) → 2, 1 still.
- `filterTakes`/`takeFilterCounts`: two opinions and three talking points → `{ all: 5, opinion: 2, talking_point: 3 }`; `"opinion"` keeps only opinions in order; an unknown stored kind counts as a talking point (`asTakeKind`).
- `editorHint(null)` → `"Saving makes version 1 and writes this take's cards."`; a take at version 3 → `"Saving makes version 4 and rewrites this take's cards."`.
- `editorStart(null)` → `{ kind: "talking_point", title: "", body: "", clean: false }`; a cleaned take → its kind, title, the cleaned `body` and `clean: true`; a take whose cleanup is running → the raw text and `clean: true`; an uncleaned take → its body and `clean: false`.

`app/src/db/takes.test.ts` (as `collections.test.ts`: `makeTestDb`, `jest.mock("expo-crypto", …)`, an `outbox(db)` helper, `take(db, id)` and `versions(db, takeId)` (ordered by version) helpers):
- `saveTake` new (`id: null`, title `"  The argument   for crypto "`, body `" Stablecoins settle ~$10T a year. "`, clean false) → returns an id; take `{ kind: "talking_point", title: "The argument for crypto", currentVersion: 1 }`; one version `{ version: 1, body: "Stablecoins settle ~$10T a year.", rawBody: same, cleaned: 0, cleanFailed: 0 }`; outbox `[{ type: "save_take", payload: { id, version_id: <the version's id>, kind: "talking_point", title: "The argument for crypto", body: "Stablecoins settle ~$10T a year.", clean: false } }]`; no `sources` row.
- `saveTake` with clean → version `body: null`, `cleaned: 1`, `rawBody` the text.
- `saveTake` on the existing id with the same body and a new title/kind → still one version, take renamed, a second `save_take` queued (its `version_id` names no row).
- `saveTake` with a changed body → version 2, `currentVersion: 2`; the take's existing card is **not** retired (Decision 6).
- `restoreTakeVersion(db, id, 1)` after two versions → version 3 copies version 1's `body`, `rawBody`, `cleaned`; outbox `{ type: "restore_take_version", payload: { id, version: 1, version_id: <version 3's id> } }`.
- `changeTakeKind(db, id, "opinion")` → `kind: "opinion"`, outbox `{ type: "update_take", payload: { id, kind: "opinion" } }`.
- `deleteTake` → take `deletedAt` set, its live cards' `deletedAt` set (insert one `take` card first), a source card untouched, outbox `{ type: "update_take", payload: { id, deleted: true } }`.
- `retryTakeCleanup(db, id, versionId)` on a failed version → `body: null`, `cleanFailed: 0`, outbox `{ type: "retry_take_cleanup", payload: { id, version_id: versionId } }`.

In `engine.test.ts`, a new `describe("database SyncStore: takes", …)` (local `pulledTake(overrides)` with `id: "k1"`, `kind: "opinion"`, `title: "Remote work is worse for juniors"`, `current_version: 1`, timestamps `"2026-11-05T00:00:00Z"`, `deleted_at: null`; `pulledVersion(overrides)` with `id: "v1"`, `take_id: "k1"`, `version: 1`, `body: "Juniors learn by overhearing."`, `raw_body` the same, `cleaned: false`, `clean_failed: false`):
- stores pulled takes, versions (booleans as 0/1) and a card with `take_id: "k1"`, `take_version_id: "v1"`, `source_id: null`; a page without `takes`/`take_versions` and a card without `take_id` is fine (`takeId` null).
- a re-pull of a take with an unsent `changeTakeKind` keeps the local kind; a re-pull of a version with an unsent `retryTakeCleanup` keeps the local `body: null`.
- a rejected `save_take` of a new take (`saveTake(db, { id: null, … })`, then `rejectAction`) deletes the take and its version and rewinds the position to 0; no source gets a `syncError`.
- a rejected `save_take` on a pulled take (body changed → optimistic version 2) deletes only version 2, sets `currentVersion` back to 1, rewinds.
- a rejected `restore_take_version` deletes the optimistic copy the same way.
- `it.each(["update_take", "retry_take_cleanup"])` a rejected one rewinds and touches no source.
- the `0010_takes` migration keeps an existing card and its schedule (copy the 0008 test's harness: run migrations up to `0010_takes`, `INSERT INTO cards (id, source_id, kind, question, answer, created_at, fsrs_state, stability, due_at, reps) VALUES ('c1', 's1', 'concept', 'Q?', 'A.', 'x', 'review', 3.5, '2026-11-09T00:00:00Z', 2)`, run 0010, expect `[expect.objectContaining({ id: "c1", source_id: "s1", fsrs_state: "review", stability: 3.5, due_at: "2026-11-09T00:00:00Z", reps: 2, take_id: null, take_version_id: null })]`).
- add `"0010_takes"` to the `it.each([...])` list of migrations that end by resetting the saved position.

`app/src/review/eligibility.test.ts` additions: a card with `sourceId: null, takeId: "k1"` → `cardOrigin` `{ kind: "take", takeId: "k1" }`; reviewable while take `k1` is live in `reviewData([...], { takes: [takeRow({ id: "k1" })] })`, not when it is deleted or missing; `cardTopicId`/`cardDomain` → null. `session.test.ts` additions: mode `"take"` with id `"k1"` returns only that take's reviewable cards; a due take card is in the `"due"` session, ordered with concepts (after foundations, before numbers). `kicker.test.ts`: a quiz card → `{ label: "This week", suffix: "News", domain: null }`; a take card of an opinion → `{ label: "Your take", suffix: "Opinion", domain: "History" }`, of a talking point → `"Talking point"`/`"Startups"`, of a take missing from the data → `"Talking point"`/`"Startups"`; a source concept card → `{ label: undefined, suffix: "Concept", domain: "AI" }`.

Run `cd app && npx jest` — the new tests fail.

- [ ] **Step 5: Engine types.** In `engine.ts` add

```ts
export type PulledTake = {
  id: string;
  kind: string;
  title: string;
  current_version: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export type PulledTakeVersion = {
  id: string;
  take_id: string;
  version: number;
  body: string | null;
  raw_body: string;
  cleaned: boolean;
  clean_failed: boolean;
  created_at: string;
};
```

`PulledCard` gains `// Absent when pulling from a server older than Saved piece 3.` `take_id?: string | null; take_version_id?: string | null;` and `PullPage.rows` gains `// Absent when pulling from a server older than Saved piece 3.` `takes?: PulledTake[]; take_versions?: PulledTakeVersion[];`. Update the `rejectAction` comment in `SyncStore` to mention takes (Decision 9).

- [ ] **Step 6: The takes module** `app/src/takes/takes.ts` (pure; imports only types from `@/db/schema` and `cardsWord` from `@/review/labels`):

```ts
import type * as schema from "@/db/schema";
import { cardsWord } from "@/review/labels";

export type TakeKind = "opinion" | "talking_point";
export type TakeRow = typeof schema.takes.$inferSelect;
export type TakeVersionRow = typeof schema.takeVersions.$inferSelect;
type CardRow = typeof schema.cards.$inferSelect;

/** A live take with its versions (oldest first), the version the page shows, and how many live cards it has. */
export type TakeWithVersions = TakeRow & { versions: TakeVersionRow[]; current: TakeVersionRow | null; cardCount: number };
export type TakeFilter = "all" | TakeKind;
export type CleanState = "none" | "cleaning" | "cleaned" | "failed";
export type EditorStart = { kind: TakeKind; title: string; body: string; clean: boolean };

export const TAKE_FILTERS: readonly TakeFilter[] = ["all", "opinion", "talking_point"];
export const TAKE_FILTER_LABELS: Record<TakeFilter, string> = {
  all: "All",
  opinion: "Opinions",
  talking_point: "Talking points",
};
export const TAKE_KIND_LABELS: Record<TakeKind, string> = { opinion: "Opinion", talking_point: "Talking point" };
// Kind kickers borrow two domain colours: Talking point in the Startups blue, Opinion in the History plum.
export const TAKE_KIND_DOMAIN: Record<TakeKind, "Startups" | "History"> = {
  opinion: "History",
  talking_point: "Startups",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A stored kind; anything this phone doesn't know reads as a talking point, the editor's default. */
export function asTakeKind(kind: string): TakeKind {
  return kind === "opinion" ? "opinion" : "talking_point";
}

/** What a version shows: its body, or the raw text while Clean it up runs. */
export function shownBody(version: Pick<TakeVersionRow, "body" | "rawBody">): string {
  return version.body ?? version.rawBody;
}

export function cleanState(version: Pick<TakeVersionRow, "body" | "cleaned" | "cleanFailed">): CleanState {
  if (version.cleaned !== 1) return "none";
  if (version.body === null) return "cleaning";
  return version.cleanFailed === 1 ? "failed" : "cleaned";
}

/** As the server decides: a first save, a changed body, or Clean it up asked for on a version that wasn't cleaned. */
export function saveMakesVersion(
  current: Pick<TakeVersionRow, "body" | "rawBody" | "cleaned"> | null,
  input: { body: string; clean: boolean },
): boolean {
  if (current === null) return true;
  return input.body !== shownBody(current) || (input.clean && current.cleaned !== 1);
}

/** Live takes with their versions and live card counts, the most recently changed body first. */
export function groupTakes(takes: TakeRow[], versions: TakeVersionRow[], cards: CardRow[]): TakeWithVersions[] {
  const versionsByTake = new Map<string, TakeVersionRow[]>();
  for (const version of versions) {
    versionsByTake.set(version.takeId, [...(versionsByTake.get(version.takeId) ?? []), version]);
  }
  const cardCounts = new Map<string, number>();
  for (const card of cards) {
    if (card.takeId && card.deletedAt === null) cardCounts.set(card.takeId, (cardCounts.get(card.takeId) ?? 0) + 1);
  }

  return takes
    .filter((take) => take.deletedAt === null)
    .map((take) => {
      const own = [...(versionsByTake.get(take.id) ?? [])].sort((a, b) => a.version - b.version);
      const current = own.find((version) => version.version === take.currentVersion) ?? own.at(-1) ?? null;
      return { ...take, versions: own, current, cardCount: cardCounts.get(take.id) ?? 0 };
    })
    .sort((a, b) => Date.parse(takeUpdatedAt(b)) - Date.parse(takeUpdatedAt(a)) || a.id.localeCompare(b.id));
}

/** When the body last changed: the current version's date (a rename or a kind change doesn't count). */
export function takeUpdatedAt(take: TakeWithVersions): string {
  return take.current?.createdAt ?? take.createdAt;
}

export function filterTakes(list: TakeWithVersions[], filter: TakeFilter): TakeWithVersions[] {
  return filter === "all" ? list : list.filter((take) => asTakeKind(take.kind) === filter);
}

export function takeFilterCounts(list: TakeWithVersions[]): Record<TakeFilter, number> {
  const opinions = list.filter((take) => asTakeKind(take.kind) === "opinion").length;
  return { all: list.length, opinion: opinions, talking_point: list.length - opinions };
}

/** "Nov 2" this year, "Nov 2024" before. */
export function takeDate(iso: string, now: Date): string {
  const date = new Date(iso);
  const month = MONTHS[date.getMonth()];
  return date.getFullYear() === now.getFullYear() ? `${month} ${date.getDate()}` : `${month} ${date.getFullYear()}`;
}

/** "Written <first version's date>" until a second version exists, then "Updated <current version's date>". */
export function takeDateLabel(take: TakeWithVersions, now: Date): string {
  if (take.versions.length <= 1) return `Written ${takeDate(take.versions[0]?.createdAt ?? take.createdAt, now)}`;
  return `Updated ${takeDate(takeUpdatedAt(take), now)}`;
}

/** A Takes row's line: "Updated Nov 2 · 3 versions · 4 cards" ("N versions" hidden at 1, the cards at 0). */
export function takeListMeta(take: TakeWithVersions, now: Date): string {
  const parts = [takeDateLabel(take, now)];
  if (take.versions.length > 1) parts.push(`${take.versions.length} versions`);
  if (take.cardCount > 0) parts.push(cardsWord(take.cardCount));
  return parts.join(" · ");
}

/** The take page's mono line: "Updated Nov 2 · version 3". */
export function takePageMeta(take: TakeWithVersions, now: Date): string {
  return `${takeDateLabel(take, now)} · version ${take.current?.version ?? take.currentVersion}`;
}

/** Every version but the one shown, newest first. */
export function earlierVersions(take: TakeWithVersions): TakeVersionRow[] {
  return take.versions.filter((version) => version.id !== take.current?.id).reverse();
}

/** The editor's line under Clean it up. */
export function editorHint(take: TakeWithVersions | null): string {
  if (take === null) return "Saving makes version 1 and writes this take's cards.";
  return `Saving makes version ${take.currentVersion + 1} and rewrites this take's cards.`;
}

/** The editor opens on what the page shows, with Clean it up as this take last had it (off for a new take). */
export function editorStart(take: TakeWithVersions | null): EditorStart {
  if (take === null) return { kind: "talking_point", title: "", body: "", clean: false };
  return {
    kind: asTakeKind(take.kind),
    title: take.title,
    body: take.current ? shownBody(take.current) : "",
    clean: take.current?.cleaned === 1,
  };
}
```

`app/src/takes/useTakesData.ts` (app only), mirroring `useCollectionsState`:

```ts
import { isNotNull, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { groupTakes, type TakeWithVersions } from "./takes";

/**
 * Every live take with its versions and card count, plus whether the live queries have answered: drizzle's
 * `useLiveQuery` returns `[]` on first render, so "no take" only means "gone" once `loaded`.
 */
export function useTakesState(): { takes: TakeWithVersions[]; loaded: boolean } {
  const { data: takes, updatedAt: takesUpdatedAt } = useLiveQuery(
    db.select().from(schema.takes).where(isNull(schema.takes.deletedAt)),
  );
  const { data: versions, updatedAt: versionsUpdatedAt } = useLiveQuery(db.select().from(schema.takeVersions));
  const { data: cards } = useLiveQuery(
    db.select().from(schema.cards).where(isNotNull(schema.cards.takeId)),
  );

  const grouped = useMemo(() => groupTakes(takes, versions, cards), [takes, versions, cards]);
  return { takes: grouped, loaded: takesUpdatedAt !== undefined && versionsUpdatedAt !== undefined };
}

/** Every live take, for the Takes list, the take page and the editor. */
export function useTakesData(): TakeWithVersions[] {
  return useTakesState().takes;
}
```

- [ ] **Step 7: Actions.** `actions.ts`: import `type TakeKind` and `saveMakesVersion` from `@/takes/takes`; `ActionType` gains `| "save_take" | "update_take" | "restore_take_version" | "retry_take_cleanup"`. After the collection actions:

```ts
export const MAX_TAKE_TITLE_LENGTH = 200;

// Stored as the server stores it (whitespace collapsed), cut by code point so a typed title is never rejected.
function cleanTakeTitle(title: string): string {
  const collapsed = title.split(/\s+/).filter(Boolean).join(" ");
  return Array.from(collapsed).slice(0, MAX_TAKE_TITLE_LENGTH).join("");
}

function currentTakeVersion(tx: Tx, takeId: string) {
  const take = tx.select().from(schema.takes).where(eq(schema.takes.id, takeId)).get();
  if (!take) return undefined;
  return tx
    .select()
    .from(schema.takeVersions)
    .where(and(eq(schema.takeVersions.takeId, takeId), eq(schema.takeVersions.version, take.currentVersion)))
    .get();
}

// The take's next version, as the server will number it; the take then shows it.
function insertTakeVersion(
  tx: Tx,
  input: { takeId: string; versionId: string; body: string | null; rawBody: string; cleaned: boolean; now: string },
): void {
  const take = tx.select().from(schema.takes).where(eq(schema.takes.id, input.takeId)).get();
  if (!take) return;
  const version = take.currentVersion + 1;
  tx.insert(schema.takeVersions)
    .values({
      id: input.versionId,
      takeId: input.takeId,
      version,
      body: input.body,
      rawBody: input.rawBody,
      cleaned: input.cleaned ? 1 : 0,
      cleanFailed: 0,
      createdAt: input.now,
    })
    .run();
  tx.update(schema.takes)
    .set({ currentVersion: version, updatedAt: input.now })
    .where(eq(schema.takes.id, input.takeId))
    .run();
}

/**
 * Writes a new take (`id: null`) or saves an edit. A new version is made only when the server will make one
 * (`saveMakesVersion`); the take's old cards stay until the server's new ones replace them. Returns the take's id.
 */
export function saveTake(
  db: AppDb,
  input: { id: string | null; kind: TakeKind; title: string; body: string; clean: boolean },
): string {
  const id = input.id ?? randomUUID();
  const versionId = randomUUID();
  const now = new Date().toISOString();
  const title = cleanTakeTitle(input.title);
  const body = input.body.trim();
  db.transaction((tx) => {
    const existing = tx.select().from(schema.takes).where(eq(schema.takes.id, id)).get();
    if (existing) {
      tx.update(schema.takes).set({ kind: input.kind, title, updatedAt: now }).where(eq(schema.takes.id, id)).run();
    } else {
      tx.insert(schema.takes)
        .values({ id, kind: input.kind, title, currentVersion: 0, createdAt: now, updatedAt: now })
        .run();
    }

    if (saveMakesVersion(currentTakeVersion(tx, id) ?? null, { body, clean: input.clean })) {
      insertTakeVersion(tx, {
        takeId: id,
        versionId,
        body: input.clean ? null : body,
        rawBody: body,
        cleaned: input.clean,
        now,
      });
    }
    enqueue(tx, "save_take", { id, version_id: versionId, kind: input.kind, title, body, clean: input.clean });
  });
  return id;
}

export function changeTakeKind(db: AppDb, takeId: string, kind: TakeKind): void {
  db.transaction((tx) => {
    tx.update(schema.takes).set({ kind, updatedAt: new Date().toISOString() }).where(eq(schema.takes.id, takeId)).run();
    enqueue(tx, "update_take", { id: takeId, kind });
  });
}

/** Deletes a take and, as the server does, takes its cards out of review. */
export function deleteTake(db: AppDb, takeId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    tx.update(schema.takes).set({ deletedAt: now, updatedAt: now }).where(eq(schema.takes.id, takeId)).run();
    tx.update(schema.cards)
      .set({ deletedAt: now })
      .where(and(eq(schema.cards.takeId, takeId), isNull(schema.cards.deletedAt)))
      .run();
    enqueue(tx, "update_take", { id: takeId, deleted: true });
  });
}

/** Saves an earlier version again as the newest, exactly as it was (no new cleanup). */
export function restoreTakeVersion(db: AppDb, takeId: string, version: number): void {
  const versionId = randomUUID();
  const now = new Date().toISOString();
  db.transaction((tx) => {
    const earlier = tx
      .select()
      .from(schema.takeVersions)
      .where(and(eq(schema.takeVersions.takeId, takeId), eq(schema.takeVersions.version, version)))
      .get();
    if (!earlier) return;
    insertTakeVersion(tx, {
      takeId,
      versionId,
      body: earlier.body ?? earlier.rawBody,
      rawBody: earlier.rawBody,
      cleaned: earlier.cleaned === 1,
      now,
    });
    enqueue(tx, "restore_take_version", { id: takeId, version, version_id: versionId });
  });
}

/** Try again after Clean it up gave up: the page shows "Cleaning up…" until the cleaned version arrives. */
export function retryTakeCleanup(db: AppDb, takeId: string, versionId: string): void {
  db.transaction((tx) => {
    tx.update(schema.takeVersions)
      .set({ body: null, cleanFailed: 0 })
      .where(eq(schema.takeVersions.id, versionId))
      .run();
    enqueue(tx, "retry_take_cleanup", { id: takeId, version_id: versionId });
  });
}
```

- [ ] **Step 8: Sync.** In `transport.ts`:
  - Above `REWOUND_SOURCE_ACTIONS`:

    ```ts
    // Actions whose payload id is a take: a rejection re-pulls the server's copy and touches no source.
    const TAKE_ACTIONS = new Set(["update_take", "retry_take_cleanup"]);

    // Take actions that add a version on the phone: a rejection removes it (the server never made it).
    const TAKE_VERSION_ACTIONS = new Set(["save_take", "restore_take_version"]);
    ```
  - In `rejectAction`, the parsed payload type gains `version_id?: string`. Right after the `add_collection_item` branch:

    ```ts
        // The server made no version (and, for a new take, no take): drop ours, point the take back at its newest
        // remaining version (or drop a take left with none), and re-pull the server's copy.
        if (TAKE_VERSION_ACTIONS.has(entry.type) && payload.id) {
          const takeId = payload.id;
          if (payload.version_id) {
            tx.delete(schema.takeVersions).where(eq(schema.takeVersions.id, payload.version_id)).run();
          }
          const newest = tx
            .select({ version: max(schema.takeVersions.version) })
            .from(schema.takeVersions)
            .where(eq(schema.takeVersions.takeId, takeId))
            .get()?.version;
          if (newest == null) {
            tx.delete(schema.takes).where(eq(schema.takes.id, takeId)).run();
          } else {
            tx.update(schema.takes).set({ currentVersion: newest }).where(eq(schema.takes.id, takeId)).run();
          }
          tx.update(schema.syncState).set({ position: 0 }).where(eq(schema.syncState.id, 1)).run();
          return;
        }
    ```

    (import `max` from `drizzle-orm`), and `rowIsNotSource` gains `|| TAKE_ACTIONS.has(entry.type)`; extend the comment above it with "a rejected take edit re-pulls the take".
  - In `applyPage`, the `unsent` set holds each pending payload's `id` **and** `version_id`:

    ```ts
        const unsent = new Set(
          tx
            .select()
            .from(schema.outbox)
            .where(eq(schema.outbox.status, "pending"))
            .all()
            .flatMap((entry) => {
              const payload = JSON.parse(entry.payload) as { id?: string; version_id?: string };
              return [payload.id, payload.version_id];
            }),
        );
    ```

    and its comment mentions takes and take versions. The cards loop's `values` gain `takeId: card.take_id ?? null, takeVersionId: card.take_version_id ?? null`. After the collection items loop:

    ```ts
        for (const take of page.rows.takes ?? []) {
          if (unsent.has(take.id)) continue;
          const values = {
            kind: take.kind,
            title: take.title,
            currentVersion: take.current_version,
            createdAt: take.created_at,
            updatedAt: take.updated_at,
            deletedAt: take.deleted_at,
          };
          tx.insert(schema.takes)
            .values({ id: take.id, ...values })
            .onConflictDoUpdate({ target: schema.takes.id, set: values })
            .run();
        }

        for (const version of page.rows.take_versions ?? []) {
          if (unsent.has(version.id)) continue;
          const values = {
            takeId: version.take_id,
            version: version.version,
            body: version.body,
            rawBody: version.raw_body,
            cleaned: version.cleaned ? 1 : 0,
            cleanFailed: version.clean_failed ? 1 : 0,
            createdAt: version.created_at,
          };
          tx.insert(schema.takeVersions)
            .values({ id: version.id, ...values })
            .onConflictDoUpdate({ target: schema.takeVersions.id, set: values })
            .run();
        }
    ```
  - `auth/session.ts` sign-out wipe gains `tx.delete(schema.takes).run(); tx.delete(schema.takeVersions).run();` next to the collections; `session.test.ts`'s wipe expectation covers both tables.

- [ ] **Step 9: Review.**
  - `eligibility.ts`: import `type TakeRow` from `@/takes/takes`; `ReviewData` gains `takesById: Map<string, TakeRow>`; `CardOrigin` gains `| { kind: "take"; takeId: string }` and `cardOrigin` checks `if (card.takeId) return { kind: "take", takeId: card.takeId };` after the brief line; `isReviewable` gains

    ```ts
        // You wrote what a take card came from, so it is reviewable as soon as it exists, while its take lives.
        case "take": {
          const take = data.takesById.get(origin.takeId);
          return take !== undefined && take.deletedAt === null;
        }
    ```

    (its docstring adds "take cards at once"); `cardTopicId` and `cardDomain` return null for take cards (they already do for any non-source/topic origin; keep it that way). `makeReviewData`'s rows gain `takes?: TakeRow[]` and it returns `takesById: new Map((rows.takes ?? []).map((take) => [take.id, take]))`.
  - `useReviewData.ts`: `reviewQueries` gains `takes: database.select().from(schema.takes).where(isNull(schema.takes.deletedAt))`, read in `readReviewData` and live in `useReviewData`, passed to `makeReviewData`; its docstring lists takes.
  - `testCards.ts`: `cardRow` gains `takeId: null, takeVersionId: null`; `reviewData`'s `rows` accepts `takes` (default `[]`, so the `Pick` gains `"takes"`); it also exports `takeRow(overrides: Partial<TakeRow>): TakeRow` (`id: "k1"`, `kind: "talking_point"`, `title: "T"`, `currentVersion: 1`, timestamps `"2026-11-01T00:00:00Z"`, `deletedAt: null`) and `takeVersionRow(overrides: Partial<TakeVersionRow>): TakeVersionRow` (`id: "v1"`, `takeId: "k1"`, `version: 1`, `body: "Body."`, `rawBody: "Body."`, `cleaned: 0`, `cleanFailed: 0`, `createdAt: "2026-11-01T00:00:00Z"`), which `takes.test.ts`, `eligibility.test.ts` and `kicker.test.ts` use.
  - `session.ts`: `ORDER_GROUP` gains `take: 1` (comment: "take cards sit with concepts"); `SessionMode` and `SESSION_MODES` gain `"take"`; `buildSession` gains `case "take": return id !== null && card.takeId === id;`.
  - `labels.ts`: `KIND_LABELS` gains `take: "Take"`.
  - `app/src/review/kicker.ts`:

    ```ts
    import { asTakeKind, TAKE_KIND_DOMAIN, TAKE_KIND_LABELS } from "@/takes/takes";

    import { cardDomain, cardOrigin, type ReviewData } from "./eligibility";
    import { KIND_LABELS } from "./labels";
    import type { CardRow } from "./types";

    export type CardKickerParts = { label: string | undefined; suffix: string | undefined; domain: string | null };

    /** The question card's kicker: "<Domain> · <Kind>", "This week · News" for quiz cards, "Your take · <kind>". */
    export function cardKicker(card: CardRow, data: ReviewData): CardKickerParts {
      if (card.kind === "quiz") return { label: "This week", suffix: "News", domain: null };

      const origin = cardOrigin(card);
      if (origin.kind === "take") {
        // Takes have no domain; the kicker takes the kind's colour instead, as on the Takes list.
        const kind = asTakeKind(data.takesById.get(origin.takeId)?.kind ?? "talking_point");
        return { label: "Your take", suffix: TAKE_KIND_LABELS[kind], domain: TAKE_KIND_DOMAIN[kind] };
      }
      return { label: undefined, suffix: KIND_LABELS[card.kind], domain: cardDomain(card, data) };
    }
    ```
  - `QuestionCard.tsx`: `const kicker = cardKicker(card, data);` replaces the inline ternary (drop the now-unused imports).
  - `CardsSection.tsx`:

    ```ts
    export type CardsOf = { kind: "source"; id: string } | { kind: "take"; id: string };
    ```

    The component becomes `CardsSection({ of }: { of: CardsOf })`: it filters `of.kind === "source" ? card.sourceId === of.id : card.takeId === of.id`; Practise pushes `` `/review/session?mode=${of.kind}&id=${of.id}` ``; a row's second line is `cardDueLabel(card, data, now)` alone for take cards (their kind label adds nothing) and `` `${KIND_LABELS[card.kind] ?? card.kind} · ${cardDueLabel(…)}` `` otherwise. Docstring: "…the source's or take's live cards…". `app/src/app/source/[id].tsx` calls `<CardsSection of={{ kind: "source", id: source.id }} />`.

- [ ] **Step 10: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 11: Commit** "App: takes and take_versions (drizzle 0010), sync, take actions, the takes module, take cards in Review".

## Parallel-safe tasks

Each runs in its own worktree from the last foundation commit (`git gtr new tk-t<N> --from-current --yes` inside `saved-takes`) and merges back into `saved-takes`.

### Task 3: Worker: `clean_take`  (tier: standard)

**Files:**
- Create: `services/worker/archie_worker/handlers/clean_take.py`, `services/worker/tests/test_clean_take_e2e.py`, `services/worker/tests/cassettes/clean_take_crypto.yaml` (recorded)
- Modify: `services/worker/archie_worker/prompts.py`, `services/worker/archie_worker/handlers/__init__.py`

**Interfaces:**
- Consumes (Task 1): `models.Take`, `models.TakeVersion`, `models.TakeKind`, `models.JobKind.CLEAN_TAKE / TAKE_CARDS`, `jobs.TAKE_VERSION_ID_KEY`, `takes.KIND_NAMES`, `takes.is_current`, `takes.mark_changed`, `takes.enqueue_step`, `llm.CLEAN_TAKE_MODELS`.
- Produces: `prompts.CLEAN_TAKE_SYSTEM`, `prompts.clean_take_message(*, kind: models.TakeKind, title: str, raw_body: str) -> str`; `clean_take.handle`, `clean_take.mark_failed`; `HANDLERS[models.JobKind.CLEAN_TAKE]`.
- Depends on: Tasks 1-2.
- Review: yes (outside call, the lock contract, the failure hook, writing only the queued version).

- [ ] **Step 1: Test DB** `archie_test_t3` (Global Constraints).

- [ ] **Step 2: Prompt.** In `prompts.py`, after `clean_text_message` (and add `clean_take` to the module docstring's step list); import `takes` from `archie_db`:

```python
CLEAN_TAKE_SYSTEM = f"""You turn the user's own dictated or typed notes into a short take for a personal learning \
app. A take is something the user thinks (an opinion) or the case they make for something (a talking point), in their \
own words.

Rewrite the notes as markdown:
- First the thesis, in one plain sentence with no heading.
- Then a "## Main points" heading and 2-5 bullets, one per point the user makes.
- Only when the notes answer an objection, end with a heading naming it (for example ## When they say "it's just a \
casino") and the user's answer in a short paragraph.

Keep only what the user said. Never add a fact, number, name, example or argument that isn't in the notes, never \
define a term they didn't define, and never make a claim stronger or weaker than they made it: keep their hedges ("I \
think", "maybe", "roughly") and their stance. Keep their numbers as they gave them. Drop filler ("ok so", "like", "you \
know") and repetition. Answer with the take's markdown only.

The voice below shapes how sentences read; it never licenses adding definitions, examples or numbers.
{READING_VOICE}"""


def clean_take_message(*, kind: models.TakeKind, title: str, raw_body: str) -> str:
    """The take's kind and title, then the user's raw notes."""
    return f"Kind: {takes.KIND_NAMES[kind]}\nTitle: {title}\n\n<notes>\n{raw_body}\n</notes>"
```

Check the replay contract: `uv run python -c "from archie_worker import prompts; from archie_api.review import prompts as review; ps=[v for m in (prompts, review) for k,v in vars(m).items() if k.endswith('SYSTEM')]; heads=[p[:60] for p in ps]; assert len(heads)==len(set(heads)), heads; print(len(heads))"` prints a count and no assertion error.

- [ ] **Step 3: Write the failing test** `services/worker/tests/test_clean_take_e2e.py` (copy `test_news_quiz_e2e.py`'s module docstring shape, `recording_api_key`, `engine` and `replay` fixtures and `_add_user`):
  - Module docstring: "`clean_take` end to end: real jobs in a real Postgres, Anthropic replayed from a recorded real response. Re-record `clean_take_crypto` by deleting it and running `uv run pytest services/worker/tests/test_clean_take_e2e.py --record-mode=once -m postgres` (a few cents of Sonnet; needs ANTHROPIC_API_KEY in the repo root .env)."
  - `RAMBLE` (the mock editor's dictation, with digits so the number check means something): `"ok so the main thing is people think it's all speculation and like most of it is, fine, but the actual use that's working is moving dollars. stablecoins did something like 10 trillion last year which is basically visa. and people in argentina or turkey want dollars and this is the easiest way. and the other thing is anyone can build on it, you don't need a bank partner"`.
  - Helper `_add_take(engine, *, user_id, raw_body, cleaned=True, versions=1) -> TakeIds` (a frozen dataclass `TakeIds(take_id: uuid.UUID, version_ids: list[uuid.UUID])`): inserts a `Take` (`kind` talking_point, title "The argument for crypto", `current_version=versions`) and `versions` `TakeVersion` rows (`body=None`, `raw_body`, `cleaned`), each with `changes.next_change_seq()` under `changes.lock_user_writes`, and enqueues one `CLEAN_TAKE` job for the **first** version with `takes.enqueue_step`. Helpers `_version(engine, version_id)`, `_jobs(engine)`, `_llm_calls(engine)`.
  - `test_a_rambling_dictation_becomes_a_short_take_in_its_own_words`: whitelisted user, one version; `with replay("clean_take_crypto"): loop.run_one(engine, handlers=handlers.HANDLERS)`. Then: the version's `body` is non-empty markdown containing `"## Main points"` and at least two lines starting with `"- "`; it mentions `stablecoin` and `bank` (case-insensitive: the owner's claims stay); every number in it (`re.findall(r"\d+(?:\.\d+)?", body)`) also appears in `RAMBLE`'s numbers (nothing invented); `clean_failed` is false and its `change_seq` grew; the jobs are `[(clean_take, done), (take_cards, queued)]` with the take_cards payload naming the same version; one `llm_calls` row with `(step, model, source_id) == ("clean_take", llm.SONNET, None)`.
  - `test_a_version_replaced_meanwhile_is_still_cleaned_but_gets_no_cards`: `_add_take(..., versions=2)` (the job is for version 1, current is 2); same cassette; version 1 gets its body; no `take_cards` job is queued.
  - `test_without_a_key_the_raw_text_stands_in_and_the_cards_still_come`: a non-whitelisted user (no cassette: replay mode refuses the network, and the handler fails before any call); after `run_one`, the clean_take job is `failed` with `errors.FailureReason.NEEDS_API_KEY`; the version's `body == RAMBLE` and `clean_failed` is true; a `take_cards` job is queued for it.
  - `test_a_deleted_take_is_left_alone`: soft-delete the take before running; no call, the job is `done`, `body` stays null, no other job.
  - `test_a_version_that_already_has_a_body_is_left_alone`: set `body` before running (a duplicate job); no call, nothing changes.
  Run it — fails (no handler for `clean_take`).

- [ ] **Step 4: Handler** `services/worker/archie_worker/handlers/clean_take.py`:

```python
"""`clean_take`: turn what the owner typed or dictated into a short markdown take, in their own words only.

It writes only the version it was queued for, and only while that version still has no body (a duplicate job or the
failure hook may have written it). When the version is still the take's current one it queues `take_cards`; a version
replaced meanwhile is cleaned for the record but gets no cards (the newer save queued its own steps). When the job gives
up, the failure hook shows the raw text as the body and marks the version, so the take page offers Try again.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, jobs, models, takes
from archie_llm import llm

from archie_worker import keys, prompts

MAX_OUTPUT_TOKENS = 2000


@dataclass(frozen=True)
class _CleanRun:
    """What the model call and the write need after the first transaction ends."""

    version_id: uuid.UUID
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Clean the version's raw text into its body, then queue the take's cards if it is still current."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.CLEAN_TAKE_MODELS,
        system=prompts.CLEAN_TAKE_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    body = completion.text.strip()
    if not body:
        raise ValueError(f"clean_take wrote nothing for version {run.version_id}")

    changes.lock_user_writes(db, run.user_id)
    version = db.get_one(models.TakeVersion, run.version_id)
    db.refresh(version)
    # A duplicate job or the failure hook may have written it while the call ran.
    if version.body is not None:
        return

    _write_body(db, version=version, body=body, failed=False)


def mark_failed(db: sqlalchemy.orm.Session, job: models.Job, reason: str) -> None:
    """Failure hook: the raw text becomes the body and the page offers Try again; the take still gets its cards."""
    del reason
    version = db.get(models.TakeVersion, uuid.UUID(job.payload[jobs.TAKE_VERSION_ID_KEY]))
    if version is None:
        return

    changes.lock_user_writes(db, version.user_id)
    db.refresh(version)
    if version.body is not None:
        return

    _write_body(db, version=version, body=version.raw_body, failed=True)


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _CleanRun | None:
    """Read the version and build the call, then commit; None when there is nothing to clean."""
    version = db.get(models.TakeVersion, uuid.UUID(job.payload[jobs.TAKE_VERSION_ID_KEY]))
    take = db.get(models.Take, version.take_id) if version is not None else None
    if version is None or take is None or take.deleted_at is not None or version.body is not None:
        db.commit()
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, version.user_id))
    run = _CleanRun(
        version_id=version.id,
        user_id=version.user_id,
        context=llm.CallContext(
            user_id=version.user_id, source_id=None, job_id=job.id, step=models.JobKind.CLEAN_TAKE
        ),
        api_key=api_key,
        user_message=prompts.clean_take_message(
            kind=models.TakeKind(take.kind), title=take.title, raw_body=version.raw_body
        ),
    )
    db.commit()
    return run


def _write_body(
    db: sqlalchemy.orm.Session, *, version: models.TakeVersion, body: str, failed: bool
) -> None:
    """Store the shown body; the current version of a live take then gets its cards."""
    version.body = body
    version.clean_failed = failed
    takes.mark_changed(version)

    take = db.get_one(models.Take, version.take_id)
    db.refresh(take)
    if takes.is_current(take, version):
        takes.enqueue_step(db, version=version, kind=models.JobKind.TAKE_CARDS)
```

Register in `handlers/__init__.py` (import `clean_take`):

```python
    # When it gives up the take shows its raw text with Try again, and still gets its cards.
    models.JobKind.CLEAN_TAKE: HandlerSpec(run=clean_take.handle, on_final_failure=clean_take.mark_failed),
```

- [ ] **Step 5: Record and replay.** Record the cassette once (Global Constraints' recording rule, `TEST_DATABASE_URL` for `archie_test_t3`), run the secret grep on it, then run the file in replay mode — all pass. If the recorded body fails an assertion (e.g. it invents a number), that is a prompt problem: tighten the prompt and re-record, don't loosen the test.
- [ ] **Step 6: Run** `make lint` and the full suite with `archie_test_t3` — pass.
- [ ] **Step 7: Commit** "Worker: clean_take turns a dictated take into a short markdown take in the owner's own words".

### Task 4: Worker: `take_cards`  (tier: standard)

**Files:**
- Create: `services/worker/archie_worker/handlers/take_cards.py`, `services/worker/tests/test_take_cards_e2e.py`, `services/worker/tests/cassettes/take_cards_crypto.yaml` (recorded)
- Modify: `services/worker/archie_worker/prompts.py`, `services/worker/archie_worker/handlers/__init__.py`

**Interfaces:**
- Consumes (Task 1): `models.Take`, `models.TakeVersion`, `models.CardKind.TAKE`, `models.JobKind.TAKE_CARDS`, `jobs.TAKE_VERSION_ID_KEY`, `takes.KIND_NAMES`, `takes.is_current`, `card_rows.retire_cards`, `llm.TAKE_CARDS_MODELS`.
- Produces: `prompts.TAKE_CARDS_SYSTEM`, `prompts.TAKE_CARDS_SCHEMA`, `prompts.take_cards_message(*, kind: models.TakeKind, title: str, body: str) -> str`; `take_cards.handle`, `take_cards.MAX_TAKE_CARDS = 4`; `HANDLERS[models.JobKind.TAKE_CARDS]`.
- Depends on: Tasks 1-2.
- Review: yes (outside call, the lock contract, retiring cards, never writing for a stale version).

- [ ] **Step 1: Test DB** `archie_test_t4`.

- [ ] **Step 2: Prompt.** Append to `prompts.py` (and add `take_cards` to the module docstring; import `takes` from `archie_db` if Task 3 hasn't — the merge keeps one import):

```python
TAKE_CARDS_SYSTEM = """You write review cards from the user's own take for a personal learning app. A take is \
something the user thinks (an opinion) or the case they make for something (a talking point), in their own words. The \
cards help them remember their own argument well enough to make it out loud.

Write 2-4 open-recall cards. Good questions ask for the take's main points ("What are your three main points for \
...?"), a rough number the take cites, and the user's answer to an objection the take names ("What do you say to \
...?"). Ask only about what the take says. Each answer is 1-3 sentences made of the take's own words and claims: never \
add a fact, number or argument that isn't in the take, and never correct, soften or strengthen what it says. The \
user's spoken answer is graded against these answers."""

TAKE_CARDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
                "required": ["question", "answer"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}


def take_cards_message(*, kind: models.TakeKind, title: str, body: str) -> str:
    """The take's kind, title and body, as the page shows it."""
    return f"Kind: {takes.KIND_NAMES[kind]}\nTitle: {title}\n\n<take>\n{body}\n</take>"
```

Run Task 3 Step 2's 60-character check (it passes without Task 3's prompt too).

- [ ] **Step 3: Write the failing test** `services/worker/tests/test_take_cards_e2e.py` (same fixtures as `test_news_quiz_e2e.py`; docstring names `take_cards_crypto` and the re-record command, "a fraction of a cent of Haiku"):
  - `CLEANED` = the mock's take page body: `"Crypto's lasting use isn't speculation. It's moving dollars, and it already works.\n\n## Main points\n\n- Stablecoins settle ~$10T a year, already Visa scale, with no bank in the middle.\n- Dollar demand abroad: people in high-inflation countries want dollars, and stablecoins are the easiest way to hold them.\n- Open rails: anyone can build payments on them without a bank partnership.\n\n## When they say \"it's just a casino\"\n\nMost volume is speculation, agreed. But the payment use is growing whatever happens to prices."`.
  - Helper `_add_take(engine, *, user_id, bodies: list[str | None]) -> TakeIds` (frozen dataclass `TakeIds(take_id, version_ids)`): a talking point "The argument for crypto" with one version per body (version n = index + 1, `current_version = len(bodies)`, `cleaned=False`, `raw_body` = the body or `"raw"`); helper `_enqueue(engine, version_id)` queues one `TAKE_CARDS` job; helper `_add_old_card(engine, *, take_id, version_id) -> uuid.UUID` inserts a live take card; helpers `_cards(engine)`, `_jobs(engine)`, `_llm_calls(engine)`.
  - `test_a_take_gets_two_to_four_cards_in_its_own_words`: whitelisted user, `bodies=[CLEANED]`, enqueue for version 1, `with replay("take_cards_crypto"): run_one`. Then: 2 ≤ live cards ≤ `take_cards.MAX_TAKE_CARDS`; each has `kind == "take"`, `take_id`, `take_version_id` = version 1, `source_id`/`artifact_id`/`topic_primer_id`/`brief_id` None, `fsrs_state == "new"`, non-blank question and answer, distinct `change_seq`s; every number in every answer (`re.findall(r"\d+(?:\.\d+)?", answer)`) appears in `CLEANED`; one `llm_calls` row `("take_cards", llm.HAIKU, None)`; the job is `done`.
  - `test_a_new_version_retires_the_previous_cards`: `bodies=["Old take.", CLEANED]`, an old card on version 1, enqueue for version 2, same cassette; the old card has `deleted_at` set and a newer `change_seq`; the new cards name version 2.
  - `test_a_version_that_is_no_longer_current_gets_no_cards`: `bodies=[CLEANED, "Newer."]`, enqueue for version 1; no call (no cassette), no cards, job `done`.
  - `test_a_version_still_being_cleaned_gets_no_cards`: `bodies=[None]`; no call, no cards, job `done`.
  - `test_a_save_during_the_call_wins`: `bodies=[CLEANED]`, an old card, enqueue for version 1; `monkeypatch.setattr(llm, "complete", …)` with a wrapper that calls the real `llm.complete` (replayed from the cassette) and then, in its own session under `changes.lock_user_writes`, adds a version 2 and sets `current_version = 2` (what a `save_take` landing mid-call does); after `run_one`: no new cards, the old card is still live.
  - `test_without_a_key_the_job_fails_and_nothing_is_written`: non-whitelisted user; the job is `failed` with `NEEDS_API_KEY`; no cards; the old card (if any) untouched.
  Run it — fails (no handler for `take_cards`).

- [ ] **Step 4: Handler** `services/worker/archie_worker/handlers/take_cards.py`:

```python
"""`take_cards`: 2-4 review cards from a take's current version, answered in the owner's own words.

It runs only for the take's current version once it has a body: a version replaced before the call is skipped, and so
is one replaced during it, re-checked under the lock (the save that replaced it queued its own job). Writing the new
cards retires the take's previous ones, so their review history stays on the old rows. There is no failure hook: a take
without cards still reads fine, and the next save tries again.

Follows the loop's handler contract: read and commit, call the model holding no transaction, then lock and write.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pydantic
import sqlalchemy
import sqlalchemy.orm
from archie_db import card_rows, changes, jobs, models, takes
from archie_llm import llm

from archie_worker import keys, prompts

MAX_TAKE_CARDS = 4
MAX_OUTPUT_TOKENS = 2000


class _TakeCard(pydantic.BaseModel):
    question: str = pydantic.Field(min_length=1)
    answer: str = pydantic.Field(min_length=1)


class _TakeCardsOutput(pydantic.BaseModel):
    cards: list[_TakeCard]


@dataclass(frozen=True)
class _CardsRun:
    """What the model call and the write need after the first transaction ends."""

    take_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    user_id: int
    context: llm.CallContext
    api_key: str
    user_message: str


def handle(db: sqlalchemy.orm.Session, job: models.Job) -> None:
    """Replace the take's cards with new ones written from its current version."""
    run = _prepare(db, job)
    if run is None:
        return

    engine = db.get_bind()
    assert isinstance(engine, sqlalchemy.Engine)
    completion = llm.complete(
        engine,
        api_key=run.api_key,
        context=run.context,
        models=llm.TAKE_CARDS_MODELS,
        system=prompts.TAKE_CARDS_SYSTEM,
        user_message=run.user_message,
        max_tokens=MAX_OUTPUT_TOKENS,
        json_schema=prompts.TAKE_CARDS_SCHEMA,
    )
    output = _TakeCardsOutput.model_validate(json.loads(completion.text))

    changes.lock_user_writes(db, run.user_id)
    take = db.get_one(models.Take, run.take_id)
    db.refresh(take)
    # Saved again or deleted during the call: a newer save queued its own job, and a deleted take wants none.
    if take.deleted_at is not None or take.current_version != run.version:
        return

    card_rows.retire_cards(db, models.Card.take_id == take.id)
    for card in output.cards[:MAX_TAKE_CARDS]:
        db.add(
            models.Card(
                id=uuid.uuid4(),
                user_id=run.user_id,
                take_id=take.id,
                take_version_id=run.version_id,
                kind=models.CardKind.TAKE.value,
                question=card.question.strip(),
                answer=card.answer.strip(),
                change_seq=changes.next_change_seq(),
            )
        )


def _prepare(db: sqlalchemy.orm.Session, job: models.Job) -> _CardsRun | None:
    """Read the take's current version and build the call, then commit; None when this version gets no cards."""
    version = db.get(models.TakeVersion, uuid.UUID(job.payload[jobs.TAKE_VERSION_ID_KEY]))
    take = db.get(models.Take, version.take_id) if version is not None else None
    # A version still being cleaned has no body yet; `clean_take` queues this job again when it lands.
    if version is None or take is None or not takes.is_current(take, version) or version.body is None:
        db.commit()
        return None

    api_key = keys.anthropic_key_for(db.get_one(models.User, take.user_id))
    run = _CardsRun(
        take_id=take.id,
        version_id=version.id,
        version=version.version,
        user_id=take.user_id,
        context=llm.CallContext(user_id=take.user_id, source_id=None, job_id=job.id, step=models.JobKind.TAKE_CARDS),
        api_key=api_key,
        user_message=prompts.take_cards_message(kind=models.TakeKind(take.kind), title=take.title, body=version.body),
    )
    db.commit()
    return run
```

Register in `handlers/__init__.py` (import `take_cards`):

```python
    # No failure hook: a take without cards still reads fine.
    models.JobKind.TAKE_CARDS: HandlerSpec(run=take_cards.handle),
```

- [ ] **Step 5: Record and replay** (as Task 3 Step 5, `archie_test_t4`; secret grep). A recorded answer that cites a number not in the take is a prompt problem: tighten and re-record.
- [ ] **Step 6: Run** `make lint` and the full suite with `archie_test_t4` — pass.
- [ ] **Step 7: Commit** "Worker: take_cards writes 2-4 cards from a take's current version and retires the old ones".

### Task 5: App: the take editor and "Write a take ›" in the add sheet  (tier: standard)

**Files:**
- Create: `app/src/app/take/edit.tsx`, `app/src/takes/KindToggle.tsx`
- Modify: `app/src/app/add.tsx`, `app/src/app/_layout.tsx` (register the route)

**Interfaces:**
- Consumes (Task 2): `saveTake`, `useTakesState`, `editorStart`, `editorHint`, `TakeKind`, `TAKE_KIND_LABELS`; `Screen`, `TextField`, `Text`, `Button`, `haptic`, `requestSync`.
- Produces: route `/take/edit` (`?id=<takeId>` edits an existing take); `KindToggle({ value, onChange, testIDPrefix }: { value: TakeKind; onChange: (kind: TakeKind) => void; testIDPrefix: string })` (renders `<prefix>-opinion` / `<prefix>-talking_point`); testIDs `add-write-take`, `take-editor`, `editor-kind-*`, `editor-title`, `editor-body`, `editor-clean`, `editor-hint`, `editor-cancel`, `editor-save`.
- Depends on: Tasks 1-2.
- Review: no.

- [ ] **Step 1: Route.** In the root `_layout.tsx` signed-in block add `<Stack.Screen name="take/edit" options={{ presentation: "modal" }} />` next to `add`.

- [ ] **Step 2: `KindToggle`** — a two-segment control like the Library mode switch (press-coloured track, radius 10, 2pt padding; the selected segment on `surface` with the small shadow, `ink`; the other `ink3`), segments in the order `Opinion` | `Talking point` from `TAKE_KIND_LABELS`, `haptic("selection")` on change.

- [ ] **Step 3: The editor** (`app/src/app/take/edit.tsx`):
  - `const { id } = useLocalSearchParams<{ id?: string }>()`; `const { takes, loaded } = useTakesState()`; `const take = id ? (takes.find((candidate) => candidate.id === id) ?? null) : null`. Until `loaded` (when editing), render nothing. Seed state **once** from `editorStart(take)` when it first becomes available (a `useRef` flag; later pulls must not overwrite what's being typed): `kind`, `title`, `body`, `clean`.
  - `<Screen title={take ? "Edit take" : "New take"} sheet headerRight={…}>` where `headerRight` is a row with `Cancel` (`editor-cancel`, `ink2`; `router.back()`, discarding everything, no confirm) and `Save` (`editor-save`, a chrome pill like the mock's primary navbar button, `onChrome` label; disabled and dimmed until `title.trim()` and `body.trim()` are both non-empty). Root view `testID="take-editor"`.
  - Body, in order with `gap: 12`: `<KindToggle value={kind} onChange={setKind} testIDPrefix="editor-kind" />`; a title `TextField` (`editor-title`, placeholder `Title`, `headline` weight, `maxLength={200}`, `returnKeyType="next"`); a multiline body `TextField` (`editor-body`, placeholder `Write it out, or dictate with the keyboard's mic`, `multiline`, `minHeight: 250`, `textAlignVertical: "top"`, `scrollEnabled={false}` so the screen scrolls); a card-styled row with `Clean it up` (`headline`) and `Archie turns this into a short take with main points. Your words and claims only.` (`secondary`, `ink3`) and a React Native `Switch` (`testID="editor-clean"`, `value={clean}`, `onValueChange={setClean}`, `trackColor={{ true: theme.colors.got }}`); then `editorHint(take)` (`secondary`, `ink3`, `testID="editor-hint"`).
  - Save: `Keyboard.dismiss(); saveTake(db, { id: take?.id ?? null, kind, title, body, clean }); haptic("success"); requestSync(); router.back();` (comment: "Save always closes the editor: a new take lands back on Library, an edit on its page (Decision 7).").
  - Save sits in the header, above the keyboard, so typing never hides it.

- [ ] **Step 4: Add sheet** (`app/src/app/add.tsx`): below the `add-save` button render an "or" divider (a row: a 1pt `line` rule, `or` in `monoLabel`/`ink3` uppercased by the variant, another rule) and a card-styled `Pressable` (`testID="add-write-take"`, surface, radius 14, card shadow, padding 13/14) with `✎ Write a take` (`headline`) and a trailing `›` (`ink3`). It needs no URL and is never disabled. `onPress`: `haptic("light"); router.replace("/take/edit");` (the sheet is replaced by the editor). If on the simulator the replace keeps a broken presentation, use `router.back()` and then `router.push("/take/edit")` in the next frame (`requestAnimationFrame`); note which in the commit message.
- [ ] **Step 5: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 6: Commit** "App: the take editor (kind, title, body, Clean it up) and Write a take in the add sheet".

### Task 6: App: Library → Takes list  (tier: standard)

**Files:**
- Create: `app/src/takes/TakeRow.tsx`
- Modify: `app/src/library/TakesView.tsx`

**Interfaces:**
- Consumes (Task 2): `useTakesData`, `TakeWithVersions`, `TAKE_FILTERS`, `TAKE_FILTER_LABELS`, `TAKE_KIND_LABELS`, `TAKE_KIND_DOMAIN`, `asTakeKind`, `filterTakes`, `takeFilterCounts`, `takeListMeta`; `ItemRow`, `GroupedList`, `Kicker`, `Button`, `useNow`, `haptic`.
- Produces: rows push `/take/[id]` with `router.push({ pathname: "/take/[id]", params: { id } })` (the screen is Task 7's); the empty state's button pushes `/take/edit` (Task 5's). testIDs `takes-view`, `takes-write`, `takes-filter-*`, `takes-filter-count-*`, `takes-filter-empty`, `take-row-<id>`; keeps `takes-empty`.
- Depends on: Tasks 1-2.
- Review: no.

- [ ] **Step 1: `TakeRow`** (props `{ take: TakeWithVersions; now: Date }`, `testID="take-row-<id>"`): an `ItemRow` whose artwork is a 46pt ❝ tile (radius 10, `press` background, a 1pt inset `rgba(0,0,0,0.05)` border, `❝` in a 24pt serif, `ink2`), kicker `<Kicker domain={TAKE_KIND_DOMAIN[kind]} label={TAKE_KIND_LABELS[kind]} />` (kind from `asTakeKind(take.kind)`), title `take.title`, meta `takeListMeta(take, now)`; `onPress` → `router.push({ pathname: "/take/[id]", params: { id: take.id } })`. If `ItemRow`'s artwork prop doesn't take an arbitrary node, render the same layout with the row's own primitives.

- [ ] **Step 2: `TakesView`** (root `testID="takes-view"`): `const takes = useTakesData(); const now = useNow(); const [filter, setFilter] = useState<TakeFilter>("all")`.
  - No takes: the centred empty state — the existing `takes-empty` line `Things you think, in your own words`, then `<Button testID="takes-write" label="Write a take" variant="secondary" onPress={() => router.push("/take/edit")} />`. Update the docstring ("Library's Takes mode: the owner's takes, most recently updated first, filtered by kind").
  - Otherwise: a horizontal row of chips styled like `LibraryList`'s `FilterChips` (one per `TAKE_FILTERS`, `testID="takes-filter-<f>"`, label from `TAKE_FILTER_LABELS`, the count from `takeFilterCounts(takes)` beside it — shown for every chip including All, as in the mock — with `testID="takes-filter-count-<f>"` on the Opinions and Talking points counts; selected chip `chrome`/`onChrome`; `haptic("selection")`), then a `GroupedList` of `TakeRow`s for `filterTakes(takes, filter)` (already newest first). A filter with nothing in it shows `No opinions yet.` / `No talking points yet.` (`ink2`, `testID="takes-filter-empty"`).
- [ ] **Step 3: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 4: Commit** "App: Library → Takes: filter chips and take rows, the Write a take empty state".

### Task 7: App: the take page and the version viewer  (tier: standard)

**Files:**
- Create: `app/src/app/take/[id].tsx`, `app/src/app/take/version.tsx`, `app/src/takes/TakeBody.tsx`, `app/src/takes/RawTextSheet.tsx`, `app/src/takes/TakeMenus.tsx`, `app/src/takes/prompts.ts`
- Modify: `app/src/app/_layout.tsx` (register the routes)

**Interfaces:**
- Consumes (Task 2): `useTakesState`, `TakeWithVersions`, `TakeVersionRow`, `cleanState`, `shownBody`, `takePageMeta`, `takeDate`, `earlierVersions`, `asTakeKind`, `TAKE_KIND_LABELS`, `TAKE_KIND_DOMAIN`, `changeTakeKind`, `deleteTake`, `restoreTakeVersion`, `retryTakeCleanup`, `CardsSection` with `of={{ kind: "take", id }}`; the Markdown renderer in `@/ui/Markdown`, `BottomSheet`, `MenuSheet`, `Screen`, `Kicker`, `Button`, `haptic`, `requestSync`, `useNow`. Edit pushes `/take/edit?id=<id>` (Task 5's route).
- Produces: routes `/take/[id]`, `/take/version` (`?id=<takeId>&version=<n>`); `TakeBody({ markdown, testID }: { markdown: string; testID?: string })`; `confirmDeleteTake(input: { title: string; onConfirm: () => void }): void`; testIDs listed in Global Constraints for the take page and version viewer.
- Depends on: Tasks 1-2.
- Review: no.

- [ ] **Step 1: Routes.** In the root `_layout.tsx` signed-in block add `<Stack.Screen name="take/[id]" />` and `<Stack.Screen name="take/version" />` after `collection/[id]`.

- [ ] **Step 2: Shared pieces.**
  - `TakeBody`: renders `markdown` with the existing `@/ui/Markdown` component (headings, bullets, emphasis) at body size with the mock's 1.62 line height if the component takes a style; `##` headings read as the mock's small mono uppercase labels if the component has that variant, otherwise as it renders them.
  - `RawTextSheet` (props `{ visible: boolean; rawBody: string; onClose: () => void }`): a `BottomSheet` (`testID="take-raw-sheet"`) titled `What you said` (`headline`) with the raw text read-only (`Text testID="take-raw-text"`, selectable).
  - `prompts.ts`: `confirmDeleteTake({ title, onConfirm })` → `Alert.alert(\`Delete “${title}”?\`, "Its versions and cards go with it.", [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: onConfirm }])`.
  - `TakeMenus` (props `{ take: TakeWithVersions; visible: boolean; onClose: () => void; onDeleted: () => void }`): a `MenuSheet` with `Change kind` (`take-menu-kind` → opens a second `MenuSheet` with `Opinion` (`take-kind-opinion`) and `Talking point` (`take-kind-talking_point`), each `changeTakeKind(db, take.id, kind); haptic("success"); requestSync();`) and `Delete take` (`take-menu-delete`, destructive, `startsGroup` → `confirmDeleteTake({ title: take.title, onConfirm: () => { deleteTake(db, take.id); haptic("success"); requestSync(); onDeleted(); } })`). The second sheet opens from the first's chosen action (which `MenuSheet` runs after dismissal), so two modals are never up at once.

- [ ] **Step 3: The take page** (`take/[id].tsx`): `const { id } = useLocalSearchParams<{ id: string }>()`; `const { takes, loaded } = useTakesState()`; `const take = takes.find((candidate) => candidate.id === id)`; `useEffect(() => { if (loaded && !take) router.back(); }, [loaded, take, router])` (deleted here or elsewhere; wait for `loaded` — piece 2's collection page left on mount without it); render nothing until both hold.
  - `<Screen title="" onBack={router.back} headerRight={…}>` with `Edit` (`take-edit`, a `press`-coloured pill; `router.push({ pathname: "/take/edit", params: { id: take.id } })`) and `•••` (`take-more`, as `source/[id].tsx` draws `item-more`). If `Screen` needs a non-empty title, follow the collection page's choice.
  - Root `View testID="take-page"`: `<Kicker testID="take-kicker" domain={TAKE_KIND_DOMAIN[kind]} label={TAKE_KIND_LABELS[kind]} />`; the title (`largeTitle`, `take-title`); `takePageMeta(take, now)` (`monoLabel`, `ink3`, `take-meta`).
  - Under it, by `cleanState(take.current)`:
    - `"cleaned"`: `Text testID="take-origin"` `Cleaned up from your dictation · ` + a pressable `See what you said ›` (`take-see-raw`, `ink2`, semibold) that opens `RawTextSheet` with `take.current.rawBody`.
    - `"cleaning"`: `Cleaning up…` (`secondary`, `ink3`, `take-cleaning`).
    - `"failed"`: `Couldn't clean this up · ` (`take-clean-failed`) + a pressable `Try again ›` (`take-clean-retry` → `retryTakeCleanup(db, take.id, take.current.id); haptic("light"); requestSync();`).
    - `"none"`: nothing.
  - The body: `<TakeBody testID="take-body" markdown={shownBody(take.current)} />` (the raw text while cleaning).
  - `<CardsSection of={{ kind: "take", id: take.id }} />` (its own `Cards from this · N` header, swipe to Remove, Practise opening `mode=take`; renders nothing until the cards arrive).
  - Earlier versions, only when `take.versions.length > 1`: a collapsed row (`take-versions`) `Earlier versions` with `${take.versions.length - 1} ›` on the right; tapping toggles an inline list of `earlierVersions(take)`: each row (`take-version-<n>`) `Version n` and `takeDate(version.createdAt, now)` (`ink3`), pushing `{ pathname: "/take/version", params: { id: take.id, version: String(n) } }`.
  - `TakeMenus` for •••, with `onDeleted={() => router.back()}`.

- [ ] **Step 4: The version viewer** (`take/version.tsx`): `const { id, version } = useLocalSearchParams<{ id: string; version: string }>()`; find the take (as Step 3, leaving when it's gone once `loaded`) and `const shown = take.versions.find((candidate) => candidate.version === Number(version))` (missing → `router.back()`).
  - `<Screen title="" onBack={router.back}>`, root `testID="version-page"`: kicker `Version ${n} · ${takeDate(shown.createdAt, now)}` (`kicker` variant, `ink3`, `version-kicker`); the take's title (`largeTitle`); `<TakeBody markdown={shownBody(shown)} />` read-only.
  - When `shown` is not the current version: `<Button testID="version-restore" label="Restore this version" onPress={() => { restoreTakeVersion(db, take.id, shown.version); haptic("success"); requestSync(); router.back(); }} />` (comment: "Saved as a new version, as it was; the take's cards are rewritten from it.").
- [ ] **Step 5: Run** `cd app && npm run typecheck && npx jest` — pass.
- [ ] **Step 6: Commit** "App: the take page (cleanup states, cards, earlier versions, Change kind / Delete) and the version viewer with Restore".

---

## Integration task (serial, in `saved-takes`, after Tasks 3–7 are merged)

### Task 8: Merge check, Maestro flows, docs, full verification  (tier: standard; Maestro runs by the coordinator)

**Files:**
- Create: `maestro/takes.yaml`, `maestro/takes_clean.yaml`
- Modify: `Makefile` (`maestro` list, new `maestro-takes-clean` target, `.PHONY`), `maestro/README.md`, `docs/superpowers/specs/2026-10-26-product-scope.md`, `docs/superpowers/specs/2026-11-05-saved-and-takes-design.md` (status line), `docs/superpowers/specs/2026-11-05-m6-review-design.md` (Out of scope: drop "reviewing take cards (Saved and Takes)" and note it shipped in Saved piece 3)
- Review: no.

- [ ] **Step 1: Merge check.** `git log --oneline` shows Tasks 3–7 merged. `handlers/__init__.py` registers both `CLEAN_TAKE` and `TAKE_CARDS`; `prompts.py` has one `takes` import and both prompts; the root `_layout.tsx` has `take/edit` (modal), `take/[id]` and `take/version`. Takes stay off the source side: `rg -n "schema\.takes|takeVersions|take_versions" app/src/library app/src/today app/src/topics app/src/item` lists only `app/src/library/TakesView.tsx` (through `useTakesData`, if at all) and nothing else, and `rg -n "models\.Take\b|TakeVersion" services/worker/archie_worker/handlers` lists only `clean_take.py` and `take_cards.py`. Re-run Task 3 Step 2's 60-character prompt check.

- [ ] **Step 2: Suites:** `docker exec second-brain-postgres-1 createdb -U archie archie_test_t8` (ignore "already exists"); `make lint`; `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_t8 uv run pytest -m "postgres or not postgres"` — all pass (cassettes replay); `cd app && npm run typecheck && npx jest` — pass.

- [ ] **Step 3: Free flow** `maestro/takes.yaml` (the dev user isn't whitelisted, so `take_cards` fails with NEEDS_API_KEY and no cards appear; this flow doesn't need them):

```yaml
appId: com.sampocs.archie
---
# Write a take from the add sheet, open it from Library → Takes, edit it into version 2, see Earlier versions and
# version 1, then delete the take.
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
      id: "add-write-take"
    timeout: 5000
- tapOn:
    id: "add-write-take"
- extendedWaitUntil:
    visible:
      id: "take-editor"
    timeout: 5000
- tapOn:
    id: "editor-kind-opinion"
- tapOn:
    id: "editor-title"
# A title no other flow uses: `make maestro` keeps one user's data across flows.
- inputText: "Maestro takes flow"
- tapOn:
    id: "editor-body"
- inputText: "Juniors learn by overhearing. Remote work takes that away."
- assertVisible:
    id: "editor-hint"
    text: "Saving makes version 1 and writes this take's cards."
- tapOn:
    id: "editor-save"
- extendedWaitUntil:
    notVisible:
      id: "take-editor"
    timeout: 5000
- tapOn:
    id: "library-mode-takes"
- tapOn: "Maestro takes flow"
- assertVisible:
    id: "take-page"
- assertVisible:
    id: "take-meta"
    text: "(?i).*version 1.*"
- assertNotVisible:
    id: "take-versions"
- tapOn:
    id: "take-edit"
- extendedWaitUntil:
    visible:
      id: "take-editor"
    timeout: 5000
- tapOn:
    id: "editor-body"
- inputText: " Mentors can't see their work."
- tapOn:
    id: "editor-save"
- extendedWaitUntil:
    notVisible:
      id: "take-editor"
    timeout: 5000
- assertVisible:
    id: "take-meta"
    text: "(?i).*updated.*version 2.*"
- assertVisible:
    id: "take-versions"
- tapOn:
    id: "take-versions"
- tapOn:
    id: "take-version-1"
- assertVisible:
    id: "version-page"
- assertVisible:
    id: "version-restore"
- tapOn:
    id: "screen-back"
- tapOn:
    id: "take-more"
- tapOn:
    id: "take-menu-delete"
- tapOn: "Delete"
- extendedWaitUntil:
    notVisible: "Maestro takes flow"
    timeout: 5000
```

(If the meta's `text` regex doesn't match because of the variant's uppercase transform, keep the `(?i)` and match on the visible text; if `inputText` into the body lands before the field is focused, `tapOn` it again first; if the delete leaves the take page on a different screen, assert `library-mode-takes` instead.)

- [ ] **Step 4: Paid flow** `maestro/takes_clean.yaml` (a few cents: one Sonnet cleanup and one Haiku card call; whitelisted login as `maestro/review.yaml` does):

```yaml
# Clean it up: a rambling dictation becomes a cleaned take with "See what you said", and the take gets cards.
# Needs the owner's keys in .env (a few cents: Sonnet cleanup + Haiku cards); local backend only;
# run it through `make maestro-takes-clean`.
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
    id: "library-mode-takes"
# Takes is empty for this user, so the empty state's button opens the editor.
- tapOn:
    id: "takes-write"
- extendedWaitUntil:
    visible:
      id: "take-editor"
    timeout: 5000
- tapOn:
    id: "editor-title"
- inputText: "Maestro clean take"
- tapOn:
    id: "editor-body"
- inputText: "ok so the main thing is people think its all speculation but stablecoins did like 10 trillion last year which is basically visa and anyone can build on it without a bank"
- tapOn:
    id: "editor-clean"
- tapOn:
    id: "editor-save"
- extendedWaitUntil:
    notVisible:
      id: "take-editor"
    timeout: 5000
- tapOn: "Maestro clean take"
- assertVisible:
    id: "take-page"
# The cleanup is one Sonnet call; the page shows the raw text under "Cleaning up…" until the next pull brings it
# (follow-up pulls at 2/5/10 s after the save, then the 60 s poll).
- extendedWaitUntil:
    visible:
      id: "take-see-raw"
    timeout: 150000
- assertVisible:
    id: "take-origin"
- tapOn:
    id: "take-see-raw"
- assertVisible:
    id: "take-raw-text"
    text: ".*stablecoins did like 10 trillion.*"
- swipe:
    direction: DOWN
    from:
      id: "take-raw-sheet"
- extendedWaitUntil:
    notVisible:
      id: "take-raw-sheet"
    timeout: 5000
# Then take_cards (Haiku) writes its cards, which arrive with a later pull.
- extendedWaitUntil:
    visible:
      id: "cards-section"
    timeout: 150000
```

(The sheet may close another way — a backdrop tap or a close control — use whatever `BottomSheet` supports. The page refreshes through the app's own pulls (follow-ups after a push, then the 60 s poll), as `review.yaml`'s wait for Today's review card does.)

- [ ] **Step 5: Makefile and docs.**
  - `Makefile`: add `maestro/takes.yaml` to the `maestro` target's list right after `maestro/collections.yaml`; add

    ```make
    # Spends a few cents of the owner's Anthropic key (a Sonnet cleanup and Haiku cards); local backend only.
    maestro-takes-clean: reset-local-data
    	@PATH="$(MAESTRO_PATH)" maestro test maestro/takes_clean.yaml
    ```

    and `maestro-takes-clean` to `.PHONY`.
  - `maestro/README.md`: table rows for `takes.yaml` ("Write a take from the Library ＋, open it from Takes, edit it into version 2, see Earlier versions and version 1, delete it") and `takes_clean.yaml` ("Write a take with Clean it up on (whitelisted, a few cents), see the cleaned take, See what you said, and its cards"); add `takes.yaml` to the `make maestro` list and `make maestro-takes-clean` to the paid targets in Running.
  - Product scope (`2026-10-26-product-scope.md`): in the Library bullets, the **Takes** bullet describes what shipped: opinions and talking points written in the take editor (from the add sheet's "Write a take ›" or the Takes empty state), dictated with the keyboard mic, optional Clean it up (Archie turns it into a one-line thesis, main points and an answered objection, using only the owner's words; the raw text is kept and shown under "See what you said"); every save that changes the body makes a dated version (Earlier versions, Restore this version); Library → Takes lists them by last update with All · Opinions · Talking points chips; each take gets 2–4 review cards graded against the owner's wording, rewritten on each new version, reviewable at once, shown in Review as "Your take"; takes aren't filed, searchable or in Ask. In the Review section, mention take cards.
  - Spec (`2026-11-05-saved-and-takes-design.md`): the **Status** line becomes "Piece 1 (Nav + Favorites) implemented on `saved-nav-favorites` (plan `docs/superpowers/plans/2026-11-05-saved-nav-favorites.md`); piece 2 (Collections) implemented on `saved-collections` (plan `docs/superpowers/plans/2026-11-05-saved-collections.md`); piece 3 (Takes) implemented on `saved-takes` (plan `docs/superpowers/plans/2026-11-05-saved-takes.md`); migration numbers moved to `0008_favorites`, `0009_collections` and `0010_takes` because M6 took 0007." In **Data**, the cards CHECK line becomes "check: exactly one of (source_id, topic_primer_id, brief_id, take_id) is set" and `take_versions` gains `clean_failed boolean not null default false`; the actions table gains `version_id` on `save_take` / `restore_take_version` (whose `take_id` is `id`) and the `retry_take_cleanup {id, version_id}` row (plan Decisions 1–3).
- [ ] **Step 6: Commit** "Saved piece 3: Maestro takes flows, docs".
- [ ] **Step 7 (coordinator, main checkout):** the branch is held by its worktree, so in the main checkout `git checkout --detach saved-takes`. Then `make db-up`, `make migrate-local`, `make start-local` in one terminal (API + worker, so the jobs run); boot the simulator and `cd app && npx expo run:ios` (no new native modules, so the installed dev build with `npx expo start` also works; the app's migration 0010 runs on launch). Run `make maestro` (every existing flow plus `takes.yaml`) and `make maestro-offline`, then `make maestro-takes-clean` (a few cents; this is the spec's Clean it up flow, run against the real model since Maestro can't replay a cassette). `make maestro-review`/`maestro-podcast` spend credits on things this piece only touched through `CardsSection` and the review kicker: run `make maestro-review` once (it covers both). A failure caused by a real outside change is reported, not papered over. Afterwards stop the backend and Metro and `git checkout main` in the main checkout.
- [ ] **Step 8:** `git status` clean apart from intended changes; `saved-takes` ready for a PR (do not push or merge unless asked).

---

## Self-review notes

- Spec coverage (piece 3 of Build order): `takes` and `take_versions` with the spec's columns plus `clean_failed`, client ids, soft delete on takes, `change_seq` (T1 server, T2 phone); cards' `take_id` / `take_version_id` and the widened exactly-one CHECK (T1 migration + migration test; T2 drizzle 0010 + "existing cards survive" test); `CardKind.take` (T1); `save_take` (creates/updates, new version only on a changed body — plus Decision 2 — `raw_body` = body, `body` null with clean, queues `clean_take` or `take_cards`), `update_take` (kind, rename, delete), `restore_take_version` (copies without re-cleaning, queues `take_cards`) (T1, wire contract in Global Constraints, Decision 1); "Couldn't clean this up" + Try again (T1 `retry_take_cleanup`, T3 failure hook, T7 page, Decision 3); `clean_take` on Sonnet 5.5 in the reading voice, no new facts/numbers/arguments, keeps hedges and stance, writes only its version, falls back to `raw_body` when retries run out, then queues `take_cards` (T3); `take_cards` on Haiku 5.5 with the fallback, 2–4 cards in the owner's words, typical questions, logged in `llm_calls`, retires previous cards, never for a non-current version, a save mid-run wins (T4); Library → Takes with All · Opinions · Talking points chips and counts, sorted by most recent update, ❝ tile, kind kicker colours, "Updated/Written · N versions · N cards" (T6, T2 labels, Decision 5); take page with kind kicker, title, "Updated <date> · version N", "Cleaned up from your dictation · See what you said ›", "Cleaning up…" with the raw text, markdown body, Cards from this · N with swipe-away, Earlier versions › N, version viewer with Restore this version, Edit, ••• Change kind / Delete take (T7, Decision 8); editor at `app/src/app/take/edit.tsx` with `?id=`, Opinion | Talking point (default Talking point), title, multiline markdown body, Save disabled until both, Clean it up switch with the spec's copy, off for a new take and remembered per take, editing a cleaned version opens the cleaned text, Cancel discards, the version hint (T5, T2 `editorStart`/`editorHint`, Decision 4); "Write a take ›" below an "or" divider in the add sheet, no URL needed (T5); the Takes empty state with its "Write a take" button (T6); Review shows take cards with a "Your take" kicker (T2, Decision 6). "Takes aren't filed or searchable": separate tables, no domain/topic, checked by T8's `rg`.
- Testing (spec): server e2e for each action through push then pull, unchanged body makes no version (T1); the exactly-one-of check (T1 migration test); `clean_take` cassette on a rambling dictation checking kept claims and no new numbers (T3); `take_cards` cassette checking 2–4 cards citing only the take's numbers, and retiring old cards on a new version (T4); app jest for the version and Written/Updated label logic (T2 `takes.test.ts`), plus actions, sync and review eligibility (T2); Maestro "write a take, edit it, see version 2 and Earlier versions" (T8 `takes.yaml`) and "Clean it up on, see 'See what you said'" (T8 `takes_clean.yaml`, against the real model, Global Constraints' Maestro rule).
- Not in this piece by design: evidence/steelman, filing or searching takes, Ask over takes, card preferences in take prompts, prompt tuning.
- Types: `TakeKind`, `TakeWithVersions`, `saveMakesVersion`, `editorStart`, `CardsOf`, `cardKicker`, `saveTake(db, { id, kind, title, body, clean }): string`, `restoreTakeVersion(db, takeId, version)`, `retryTakeCleanup(db, takeId, versionId)`, `jobs.TAKE_VERSION_ID_KEY`, `takes.KIND_NAMES` / `is_current` / `enqueue_step` / `mark_changed`, `llm.CLEAN_TAKE_MODELS` / `TAKE_CARDS_MODELS` are each defined once (T1, T2) and used with the same names and shapes by later tasks. Wire keys (`version_id`, `current_version`, `raw_body`, `clean_failed`, `take_id`, `take_version_id`) match between T1's schemas, T2's `Pulled*` types and the payloads T2 enqueues. The server's and phone's "makes a version" rules are the same expression (`_save_makes_version` / `saveMakesVersion`).
- Review tags: T1 yes (migration, CHECK, sync), T2 yes (migration, sync, sign-out, eligibility), T3 yes (outside call, lock contract, failure hook), T4 yes (outside call, lock contract, retiring cards), T5, T6, T7, T8 no.
