# Edits Through Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-fast:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ask can propose edits to a source's summary or primer, a topic primer, a take or a review card; the owner applies each from the chat (with Undo), every change is a new version, every editable thing has an Earlier-versions sheet with Restore, and Archie's own regeneration never replaces a version the owner chose.

**Architecture:**
- DB (`0013_chat_edits`): `VersionOrigin` on artifacts, topic primers and take versions; `cards.version`; new synced tables `card_versions` (lazy: written on a card's first change) and `edit_proposals`. A new `archie_db/versions.py` is the one place that reads a target's current content, writes its next version and restores an earlier one, for all five kinds; `pipeline.write_artifact` carries the regeneration rule.
- API: five new client tools in the Ask loop (`read_item`, `find_cards`, `propose_summary_edit`, `propose_text_edit`, `propose_card_edit`, in `ask/edit_tools.py`), new SSE events `editing` and `edit`, proposals stored with the answer; `POST /ask/edits/{id}/apply|undo|discard` and `POST /versions/restore` (in `archie_api/edits/routes.py`), each one transaction under the user's write lock, no model calls.
- App: drizzle `0013_chat_edits` and sync of the new rows; a proposal card with a line diff under each answer; one `VersionsSheet` opened from the source and topic ••• menus and a card row's swipe action.

**Tech Stack:** as M7 (FastAPI, SQLAlchemy/Alembic, Postgres with pgvector; Anthropic Python SDK 2.4 via the Ask loop; Expo 58 Router, drizzle + expo-sqlite, jest, Maestro, pytest-recording/vcrpy). **No new Python or npm packages.**

**Spec:** `docs/superpowers/specs/2026-11-08-chat-edits-design.md`. Background: `docs/superpowers/specs/2026-11-06-m7-search-ask-design.md` (Ask), `docs/superpowers/specs/2026-11-05-saved-and-takes-design.md` (take versions), `docs/superpowers/plans/2026-11-06-m7-search-ask.md` (how the Ask loop and its tests are built).

## Global Constraints

- **Python style:** `AGENTS.md` house style (module-qualified imports as the repo does them, e.g. `from archie_db import changes, models, versions` then `versions.write(...)`; classes/`typing` by name; full typing with `X | None`; `StrEnum`s for compared strings; dataclasses over tuples of >2; named parameters; guard clauses; blank-line paragraphs past ~8 lines; why-comments; docstrings on public functions/classes).
- **No transaction across an outside call:** the Ask loop's tools each open their own short `sqlalchemy.orm.Session(engine)` between model rounds and commit or close it before the next round; `_save` stores the answer and its proposals in one session. Apply / Undo / Discard / Restore make no outside call: `changes.lock_user_writes(db, user.id)` first, then read, write, `db.commit()`.
- **Every synced write** takes `changes.next_change_seq()` under `changes.lock_user_writes` (see `packages/archie-db/archie_db/changes.py`).
- **Models:** chat stays `llm.SONNET` with `answer.THINKING = {"type": "between_tools"}` and `answer.OUTPUT_CONFIG = {"effort": "medium"}`. `tool_choice` `any`/`tool` is a 400 on Sonnet 5.5: tools are steered by the prompt only. New tools are `"strict": True` with `"additionalProperties": False` on every object, nullable values as `{"anyOf": [{"type": "string"}, {"type": "null"}]}`, and **no** `eager_input_streaming` (their inputs are validated by the API before streaming finishes).
- **Ask loop limits:** `answer.MAX_ROUNDS = 6`, `answer.MAX_TOKENS = 8000`.
- **Prompt prefix:** `prompts.ASK_SYSTEM` must still start with `You are Archie's Ask, answering the owner's questions from th` (its first 60 characters); the edit rules are appended after the existing rules. No other new system prompt.
- **Enums (exact values):** `models.VersionOrigin`: `ARCHIE="archie"`, `OWNER="owner"`, `CHAT_EDIT="chat_edit"`, `CARE="care"`, `RESTORE="restore"`. `models.EditTarget`: `SUMMARY="summary"`, `PRIMER="primer"`, `TOPIC_PRIMER="topic_primer"`, `TAKE="take"`, `CARD="card"`. `models.EditStatus`: `PROPOSED="proposed"`, `APPLIED="applied"`, `UNDONE="undone"`, `DISCARDED="discarded"`, `STALE="stale"`, `SUPERSEDED="superseded"`.
- **Edit shapes (exact):** summary `{"gist": str, "key_ideas": [{"timestamp": str|null, "idea": str}], "numbers": [{"timestamp": str|null, "fact": str}]}`; primer, topic primer, take `{"markdown": str}`; card `{"question": str, "answer": str}`. A summary edit replaces only the artifact content's `summary` key.
- **Target ids:** summary and primer → the source id; topic primer → the **topic** id (tools also accept any `topic_primers.id` of that topic); take → the take id; card → the card id.
- **Limits:** gist ≤ 2,000 chars; ≤ 30 key ideas and ≤ 30 numbers; markdown ≤ 60,000 chars (a take ≤ 20,000, `take_actions.MAX_TAKE_BODY_LENGTH`); card question 1–500, answer 1–2,000; description 1–300; replacements 1–20; `find_cards` returns ≤ 10.
- **Wire shapes (exact, snake_case):**
  - SSE `editing {"target_kind": null}` (sent when a `read_item`, `find_cards` or `propose_*` block starts); SSE `edit {"id", "target_kind", "target_id", "title", "description", "base_version", "before", "after", "status": "proposed"}`.
  - Pulled `rows.edit_proposals: [{id, conversation_id, message_id, target_kind, target_id, title, description, base_version, before, after, status, applied_version, created_at, updated_at, change_seq}]`; `rows.card_versions: [{id, card_id, version, question, answer, origin, instruction, created_at, change_seq}]`; `artifacts` and `topic_primers` gain `origin`, `instruction`; `take_versions` gains `origin`; `cards` gain `version`. The phone treats each as optional (`?? []`, `?? "archie"`, `?? "owner"`, `?? 1`, `?? null`).
  - `POST /ask/edits/{proposal_id}/apply` → 200 `EditProposalOut` (status `applied` or `stale`), 409 `{"detail": "edit is <status>"}`; `POST /ask/edits/{proposal_id}/undo` → 200 (`undone`), 409 `"changed since"` or `"edit is <status>"`; `POST /ask/edits/{proposal_id}/discard` → 200 (`discarded`), 409 `"edit is <status>"`; `POST /versions/restore` `{"target_kind", "target_id", "version"}` → 200 `{"version": int}`, 404 `"not found"` / `"version not found"`, 409 `"already current"`. 404 `"edit not found"` for another user's proposal or one in a deleted chat.
- **Migration numbers:** server `packages/archie-db/archie_db/migrations/versions/0013_chat_edits.py`, `revision = "0013"`, `down_revision = "0012"` (the `item-dates` branch's `0012_published_at`); app drizzle `0013_chat_edits`, ending with `UPDATE sync_state SET position = 0;`. **Prerequisite:** `0012_published_at.py` and drizzle `0012_*` exist on `chat-edits` before Task 1 starts (Task 1 Step 1).
- **Copy (verbatim):** proposal kickers `Edit · Summary`, `Edit · Primer`, `Edit · Topic primer`, `Edit · Take`, `Edit · Card`; buttons `Apply`, `Discard`, `Undo`; status lines `Applied`, `Undone`, `Discarded`, `Replaced by a newer suggestion`, `Changed since you asked. Ask again to redo it.`; streaming line `Drafting an edit…`; offline `Needs a connection`; toasts `Couldn't reach Archie. Try again.`, `This was changed since. Use Earlier versions to go back.`, `Restored version N`; sheet titles `Summary versions`, `Primer versions`, `Card versions`; menu rows `Summary versions`, `Primer versions`; swipe action `Versions`; row label `Version N · <date>`; origin labels `Archie`, `You`, `Edited in Ask`, `Rewritten from your note`, `Restored`; tag `Current`; buttons `Restore this version`, `Back`; offline restore `Restoring needs a connection`; card subtitle suffix ` · Edited`.
- **testIDs (new):** `edit-proposal-<id>`, `edit-diff-<id>`, `edit-apply-<id>`, `edit-discard-<id>`, `edit-undo-<id>`, `edit-status-<id>`, `edit-title-<id>`, `chat-editing`; `versions-sheet`, `version-row-<n>`, `version-current-<n>`, `version-preview`, `version-restore`, `version-back`, `version-offline`; `menu-summary-versions`, `menu-primer-versions`, `topic-menu-primer-versions`, `card-versions-<index>`. Existing ones stay (`item-more`, `menu-ask`, `ask-composer-input`, `ask-send`, `chat-screen`, `chat-answer-<index>`, `card-row-<index>`, `take-versions`).
- **Tests:** e2e first; unit tests only for real logic; outside calls replayed from recorded cassettes, never hand-made response bodies. **Recording a cassette:** delete it, then `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e<N> uv run pytest <test file> --record-mode=once -m postgres` (needs `ANTHROPIC_API_KEY` in the repo-root `.env`; only `archie_testing.recording.use_recording_api_key` reads it, only in record mode; a few cents). After recording, `rg -n "sk-ant|x-api-key|anthropic-organization-id|request-id" <cassette>` prints nothing. Anthropic cassettes match on model + the first 60 characters of the system prompt; multi-round chats replay with `allow_playback_repeats=False`. App logic tests are `*.test.ts`; pure helpers never import a native module.
- **Never print secrets** or `.env` values.
- **Branch and worktrees:** branch `chat-edits`, worktree `/Users/sampocs/Documents/Personal/second-brain-worktrees/chat-edits`. Foundation tasks (1–3) run there serially. Each parallel-safe task runs in its own worktree from the last foundation commit (`git gtr new chat-edits-e<N> --from-current --yes`, run inside the `chat-edits` worktree), then merges back into `chat-edits`. Never touch the main checkout except where Task 8's coordinator step says so.
- **App packages in worktrees:** `ln -sfn /Users/sampocs/Documents/Personal/second-brain/app/node_modules app/node_modules` once per worktree that runs `npm`/`npx`; keep it out of git with `grep -qx 'app/node_modules' "$(git rev-parse --git-common-dir)/info/exclude" || echo 'app/node_modules' >> "$(git rev-parse --git-common-dir)/info/exclude"`. No npm installs. **Never run `npx prettier`.**
- **Postgres from a worktree:** the container `second-brain-postgres-1` (`127.0.0.1:5434`) is already up from the main checkout. **Never run `make db-up`, `make db-down`, `make test-db`, `make migrate-local`, `make start-local`, `make reset-local-data` or any `make maestro*` target from a worktree.** Task N uses its own database: `docker exec second-brain-postgres-1 createdb -U archie archie_test_e<N>` (ignore "already exists"), then `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e<N> uv run pytest -m "postgres or not postgres"` (or the narrower file the step names).
- **Maestro:** implementers add the testIDs in their task; the flow is written in Task 8 and **run only by the coordinator, from the main checkout, against the local backend**. Lessons from M7: one `make maestro` run shares one user's data across flows; swipe a `SwipeRow` by screen position; after a sheet's action wait for it to close; `hideKeyboard` before tapping below the keyboard; a flow that needs model output logs in with `openLink: archie://dev/login?whitelisted=1` and gets its own `make` target outside `make maestro`.
- **Checks before every commit:** Python `make lint` and the task's tests (command above). App `cd app && npm run typecheck && npx jest`.
- **Commits:** every message ends with exactly these two lines:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01XcYDkHG569wyzZcbNoxSyL`
- **Out of scope:** the spec's "Not in scope" list; deploying, `railway config apply`, pushing or merging to `main`. The plan ends with `chat-edits` ready for a PR.

## Decisions made while planning

1. **One versions module for five kinds.** `archie_db/versions.py` exposes `resolve`, `title`, `current`, `at_version`, `write`, `restore` over a `Target(kind, id)`. The API's tools, the edit routes and Review's care route all go through it, so "every change is a new version" lives in one file.
2. **Writers move into `archie_db` so the API can call them:** `write_topic_primer` moves from the worker handler to `archie_db/topic_primers.py` (`topic_primers.write`), and a take's version-making moves from `take_actions._add_version` to `takes.add_version`. Behavior is unchanged; both gain an `origin`.
3. **The regeneration rule lives in `pipeline.write_artifact`:** with `origin=ARCHIE`, when the current version's origin is not `archie` and the source's current `text` artifact is not newer than it, the new version is inserted with `is_current=False` and the current one is left alone. Analyze and primer pass nothing new; their cards are still tied to the version they wrote (`summary.id` / `primer.id`), which is what `_retire_cards_before` and the primer's retire already compare against.
4. **Card versions are lazy** (spec). `versions.write` on a card with no `card_versions` rows first inserts version 1 from the card as it is (origin `archie`), then the new version.
5. **Restore always goes through `versions.write`** with origin `restore`; for a take it copies the earlier version's `raw_body` and `cleaned` too (as the outbox `restore_take_version` does), via `takes.add_version`.
6. **Proposals live in memory until `_save`.** `edit_tools.run` validates and returns a `Proposal`; the loop sends the `edit` event and keeps it on `_Progress`; `_save` inserts the proposals after the answer row (same session), marking older still-proposed proposals of the same target in the chat `superseded` as each is inserted. A failed answer keeps its proposals.
7. **Ids reach the model three ways:** the about block gains an id line; each `search_result` title ends with ` [<item kind> <uuid>]`; history assistant turns gain `[cited: …]` and `[edit proposed: …]` lines. Citation chips are built from the server's own `ChunkHit`s, so the title suffix never reaches the phone.
8. **`find_cards`** ranks by `ts_rank_cd(to_tsvector('english', question || ' ' || answer), websearch_to_tsquery('english', <words joined by " or ">))`, computed on the fly (a user has hundreds of cards, not millions); `search.any_terms(query)` is made public for the joining.
9. **`ClientError` gains `status`** on the phone, so the proposal card can tell a 409 (changed since) from other refusals.
10. **The drizzle migration resets the sync position,** so card versions and proposals written by the server before the app update are pulled.

---

## File Structure

```
packages/archie-db/archie_db/models.py                                    enums, CardVersion, EditProposal, new columns (T1)
packages/archie-db/archie_db/migrations/versions/0013_chat_edits.py       (T1)
packages/archie-db/tests/test_db_migrations.py                            0013 test (T1)
conftest.py                                                               truncate list (T1)
services/api/archie_api/sync/{schemas,pull}.py                            pulled rows (T1)
services/api/tests/e2e/test_versions_pull_e2e.py                          (T1)
packages/archie-db/archie_db/{versions,topic_primers}.py                  (T2, new)
packages/archie-db/archie_db/{pipeline,takes,search}.py                   origin + regeneration rule, add_version, any_terms (T2)
packages/archie-db/tests/test_versions.py                                 (T2)
services/worker/archie_worker/handlers/topic_primer.py                    uses topic_primers.write (T2)
services/worker/tests/test_analyze_primer_e2e.py                          regeneration rule through analyze (T2)
services/api/archie_api/sync/take_actions.py                              uses takes.add_version, restore origin (T2)
services/api/archie_api/review/routes.py, tests/e2e/test_review_routes_e2e.py   care writes card versions (T2)
app/src/db/schema.ts, app/drizzle/0013_chat_edits.sql (+ meta, journal, migrations.js)   (T3)
app/src/sync/{engine,transport,engine.test}.ts, app/src/auth/session.ts, app/src/api/client.ts   (T3)
app/src/edits/{types,content,content.test,versions,versions.test,useTargetVersions,api}.ts   (T3, new)
services/api/archie_api/edits/{__init__,routes}.py, services/api/archie_api/main.py   (T4)
services/api/tests/e2e/test_edits_e2e.py                                  (T4)
services/api/archie_api/ask/{edit_tools}.py (new), ask/{answer,prompts,context,citations}.py   (T5)
services/api/tests/test_edit_tools_units.py, tests/e2e/test_ask_edit_e2e.py (+ cassettes ask_edit_summary.yaml, ask_edit_card.yaml)   (T5)
app/src/edits/{diff,diff.test,proposalState,proposalState.test,useProposals}.ts, app/src/edits/EditProposalCard.tsx   (T6, new)
app/src/ask/{types,stream,sections,sections.test}.ts, app/src/ask/AnswerView.tsx, app/src/app/ask/[id].tsx   (T6)
app/src/edits/{VersionsSheet,VersionPreview}.tsx (new), app/src/item/{ItemMenu,CardsSection}.tsx, app/src/app/source/[id].tsx,
  app/src/topics/TopicMenu.tsx, app/src/app/topic/[id].tsx, app/src/app/take/[id].tsx, app/src/app/take/version.tsx,
  app/src/takes/{versionView,versionView.test}.ts, app/src/db/actions.ts   (T7)
maestro/edit.yaml, Makefile, maestro/README.md, AGENTS.md, docs                (T8)
```

Overlaps between parallel tasks are textual only: `services/api/archie_api/main.py` (T4 adds one `include_router` line). T5 and T4 both import `archie_db.versions` (Task 2) and never each other. T6 and T7 both import `@/edits/*` from Task 3 and never each other; T6 edits the chat, T7 the item pages.

## Foundation tasks (run in `chat-edits`, serially)

### Task 1: Server data: enums, migration 0013, card versions and proposals, pulled rows  (tier: most capable)

**Files:**
- Create: `packages/archie-db/archie_db/migrations/versions/0013_chat_edits.py`, `services/api/tests/e2e/test_versions_pull_e2e.py`
- Modify: `packages/archie-db/archie_db/models.py`, `packages/archie-db/tests/test_db_migrations.py`, `conftest.py` (`_TRUNCATE_TABLES`), `services/api/archie_api/sync/schemas.py`, `services/api/archie_api/sync/pull.py`

**Interfaces:**
- Produces:
  - `models.VersionOrigin`, `models.EditTarget`, `models.EditStatus` (values in Global Constraints); `models.OWNER_CHOSEN_ORIGINS = frozenset({OWNER, CHAT_EDIT, CARE, RESTORE})`.
  - Columns: `SourceArtifact.origin: str` (default `"archie"`); `TopicPrimer.origin: str`, `TopicPrimer.derived_from_id: uuid.UUID | None`, `TopicPrimer.instruction: str | None`; `TakeVersion.origin: str` (default `"owner"`); `Card.version: int` (default `1`).
  - `models.CardVersion` (`id, user_id, card_id, version, question, answer, origin, instruction, created_at, change_seq`), `models.EditProposal` (`id, user_id, conversation_id, message_id, target_kind, target_id, title, description, base_version, before: dict, after: dict, status, applied_version, created_at, updated_at, change_seq`).
  - `schemas.CardVersionOut`, `schemas.EditProposalOut` (fields = the pulled row shapes in Global Constraints), `ArtifactOut.origin/instruction`, `TopicPrimerOut.origin/instruction`, `TakeVersionOut.origin`, `CardOut.version`, `PulledRows.card_versions`, `PulledRows.edit_proposals`.
- Review: yes (migration, sync shapes).

- [ ] **Step 1: Prerequisite and test DB.** In the `chat-edits` worktree: `git merge main`. Check `ls packages/archie-db/archie_db/migrations/versions/0012_*.py app/drizzle/0012_*.sql` lists one file each. If not, `git merge item-dates` (the parallel branch) and check again; if still missing, stop and report (the build waits for `item-dates`). Then `docker exec second-brain-postgres-1 createdb -U archie archie_test_e1` (ignore "already exists").

- [ ] **Step 2: Write the failing migration test.** Append to `packages/archie-db/tests/test_db_migrations.py`:

```python
def test_0013_keeps_versions_with_their_defaults_and_cascades_proposals(test_database_url: str) -> None:
    """Rows written before 0013 get origin archie/owner and card version 1; proposals and card versions cascade."""
    migrate.downgrade(test_database_url)
    migrate.upgrade(test_database_url, "0012")
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
                "INSERT INTO source_artifacts (id, user_id, source_id, kind, version, content, is_current, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-000000000001', 'primer', 1, "
                "'{\"markdown\": \"## A\"}', true, nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO cards (id, user_id, source_id, kind, question, answer, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000c1', id, '00000000-0000-0000-0000-000000000001', "
                "'concept', 'Q?', 'A.', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO takes (id, user_id, kind, title, current_version, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000d1', id, 'opinion', 'T', 1, nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO take_versions (id, user_id, take_id, version, body, raw_body, cleaned, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000d1', 1, 'B', 'B', false, "
                "nextval('change_seq') FROM users"
            )
        )

    migrate.upgrade(test_database_url)

    with engine.begin() as connection:
        assert connection.execute(sqlalchemy.text("SELECT origin FROM source_artifacts")).scalar_one() == "archie"
        assert connection.execute(sqlalchemy.text("SELECT version FROM cards")).scalar_one() == 1
        assert connection.execute(sqlalchemy.text("SELECT origin FROM take_versions")).scalar_one() == "owner"

        connection.execute(
            sqlalchemy.text(
                "INSERT INTO card_versions (id, user_id, card_id, version, question, answer, origin, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000c1', 1, 'Q?', 'A.', 'archie', "
                "nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO conversations (id, user_id, title, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000a1', id, 'Q', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO messages (id, user_id, conversation_id, role, text, status, change_seq) "
                "SELECT '00000000-0000-0000-0000-0000000000b1', id, '00000000-0000-0000-0000-0000000000a1', "
                "'assistant', 'A', 'complete', nextval('change_seq') FROM users"
            )
        )
        connection.execute(
            sqlalchemy.text(
                "INSERT INTO edit_proposals (id, user_id, conversation_id, message_id, target_kind, target_id, title, "
                "description, base_version, before, after, status, change_seq) "
                "SELECT gen_random_uuid(), id, '00000000-0000-0000-0000-0000000000a1', "
                "'00000000-0000-0000-0000-0000000000b1', 'card', '00000000-0000-0000-0000-0000000000c1', 'Q?', "
                "'Say B', 1, '{\"question\": \"Q?\", \"answer\": \"A.\"}', '{\"question\": \"Q?\", \"answer\": \"B.\"}', "
                "'proposed', nextval('change_seq') FROM users"
            )
        )

        connection.execute(sqlalchemy.text("DELETE FROM conversations"))
        connection.execute(sqlalchemy.text("DELETE FROM cards"))
        assert connection.execute(sqlalchemy.text("SELECT count(*) FROM edit_proposals")).scalar_one() == 0
        assert connection.execute(sqlalchemy.text("SELECT count(*) FROM card_versions")).scalar_one() == 0

    migrate.downgrade(test_database_url, "0012")
    migrate.upgrade(test_database_url)
    engine.dispose()
```

(`migrate.downgrade(database_url, revision)` and `migrate.upgrade(database_url, revision)` take an optional target revision; the last two lines prove 0013's downgrade runs and re-applies.)

- [ ] **Step 3: Run it to see it fail.** `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e1 uv run pytest packages/archie-db/tests/test_db_migrations.py -m postgres -k 0013 -v` → FAIL (`column "origin" does not exist` or no revision 0013).

- [ ] **Step 4: Models.** In `packages/archie-db/archie_db/models.py`, after `class ActionResult`, add:

```python
class VersionOrigin(StrEnum):
    """Who made a version of a summary, primer, take or card; every origin but `archie` is one the owner chose."""

    ARCHIE = "archie"
    OWNER = "owner"
    CHAT_EDIT = "chat_edit"
    CARE = "care"
    RESTORE = "restore"


# Archie's own regeneration never replaces a current version with one of these origins (see pipeline.write_artifact).
OWNER_CHOSEN_ORIGINS = frozenset(
    {VersionOrigin.OWNER, VersionOrigin.CHAT_EDIT, VersionOrigin.CARE, VersionOrigin.RESTORE}
)


class EditTarget(StrEnum):
    """What an Ask edit changes. Summary and primer are named by their source, a topic primer by its topic."""

    SUMMARY = "summary"
    PRIMER = "primer"
    TOPIC_PRIMER = "topic_primer"
    TAKE = "take"
    CARD = "card"


class EditStatus(StrEnum):
    """Where an Ask edit stands: waiting for the owner, applied (then maybe undone), or set aside."""

    PROPOSED = "proposed"
    APPLIED = "applied"
    UNDONE = "undone"
    DISCARDED = "discarded"
    STALE = "stale"
    SUPERSEDED = "superseded"
```

Add to `TopicPrimer` (after `prompt_version`):

```python
    origin: Mapped[str] = mapped_column(
        sqlalchemy.String(16), default=VersionOrigin.ARCHIE.value, server_default=VersionOrigin.ARCHIE.value
    )
    # The version an Ask edit or a restore was made from, and the edit's one-line description.
    derived_from_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("topic_primers.id")
    )
    instruction: Mapped[str | None] = mapped_column(sqlalchemy.Text)
```

Add to `TakeVersion` (after `clean_failed`):

```python
    # `owner` for a save in the take editor; `chat_edit` and `restore` for the other ways a version is made.
    origin: Mapped[str] = mapped_column(
        sqlalchemy.String(16), default=VersionOrigin.OWNER.value, server_default=VersionOrigin.OWNER.value
    )
```

Add to `SourceArtifact` (after `instruction`; update the class docstring's second paragraph to "Exactly one version per (source, kind) is current, which the partial unique index enforces. `origin` says who made it; Archie's rewrites never displace an owner-chosen current version."):

```python
    origin: Mapped[str] = mapped_column(
        sqlalchemy.String(16), default=VersionOrigin.ARCHIE.value, server_default=VersionOrigin.ARCHIE.value
    )
```

Add to `Card` (after `expires_at`):

```python
    # The current version; `card_versions` holds the history once the card has been changed at least once.
    version: Mapped[int] = mapped_column(sqlalchemy.Integer, default=1, server_default="1")
```

After `class Review`, add:

```python
class CardVersion(Base):
    """One version of a card's question and answer. Written lazily: a card's first change writes versions 1 and 2."""

    __tablename__ = "card_versions"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("card_id", "version", name="uq_card_versions_version"),
        sqlalchemy.Index("ix_card_versions_user_id_change_seq", "user_id", "change_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    card_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("cards.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    question: Mapped[str] = mapped_column(sqlalchemy.Text)
    answer: Mapped[str] = mapped_column(sqlalchemy.Text)
    origin: Mapped[str] = mapped_column(sqlalchemy.String(16))
    # An Ask edit's description, or the note behind a care rewrite.
    instruction: Mapped[str | None] = mapped_column(sqlalchemy.Text)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)


class EditProposal(Base):
    """An edit Ask proposed in a chat; nothing changes until the owner applies it.

    `target_id` names the source (summary, primer), the topic (topic primer), the take or the card; it has no foreign
    key because those are soft-deleted, and Apply checks the target is still live. `before` and `after` hold the
    content in its edit shape (see `archie_db.versions`), `base_version` the version it was proposed against.
    """

    __tablename__ = "edit_proposals"
    __table_args__ = (
        sqlalchemy.Index("ix_edit_proposals_user_id_change_seq", "user_id", "change_seq"),
        sqlalchemy.Index("ix_edit_proposals_conversation_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(sqlalchemy.BigInteger, sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE")
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sqlalchemy.ForeignKey("messages.id", ondelete="CASCADE")
    )
    target_kind: Mapped[str] = mapped_column(sqlalchemy.String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(sqlalchemy.Text)
    description: Mapped[str] = mapped_column(sqlalchemy.Text)
    base_version: Mapped[int] = mapped_column(sqlalchemy.Integer)
    before: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    after: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB)
    status: Mapped[str] = mapped_column(sqlalchemy.String(16))
    applied_version: Mapped[int | None] = mapped_column(sqlalchemy.Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=sqlalchemy.func.now())
    change_seq: Mapped[int] = mapped_column(sqlalchemy.BigInteger)
```

- [ ] **Step 5: Migration** `packages/archie-db/archie_db/migrations/versions/0013_chat_edits.py`:

```python
"""Edits through chat: who made each version, card versions, and the edits Ask proposes.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None

_TIMESTAMP = sqlalchemy.DateTime(timezone=True)


def upgrade() -> None:
    """Add `origin` to every versioned row, `cards.version`, and the `card_versions` and `edit_proposals` tables.

    Existing rows take the defaults: Archie wrote every artifact and topic primer, the owner every take version, and
    every card is at version 1 with no history rows yet.
    """
    op.add_column("source_artifacts", _origin_column(default="archie"))
    op.add_column("topic_primers", _origin_column(default="archie"))
    op.add_column("topic_primers", sqlalchemy.Column("derived_from_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "topic_primers_derived_from_id_fkey", "topic_primers", "topic_primers", ["derived_from_id"], ["id"]
    )
    op.add_column("topic_primers", sqlalchemy.Column("instruction", sqlalchemy.Text(), nullable=True))
    op.add_column("take_versions", _origin_column(default="owner"))
    op.add_column("cards", sqlalchemy.Column("version", sqlalchemy.Integer(), server_default="1", nullable=False))
    _create_card_versions()
    _create_edit_proposals()


def downgrade() -> None:
    """Drop the two tables and the added columns."""
    op.drop_table("edit_proposals")
    op.drop_table("card_versions")
    op.drop_column("cards", "version")
    op.drop_column("take_versions", "origin")
    op.drop_column("topic_primers", "instruction")
    op.drop_constraint("topic_primers_derived_from_id_fkey", "topic_primers", type_="foreignkey")
    op.drop_column("topic_primers", "derived_from_id")
    op.drop_column("topic_primers", "origin")
    op.drop_column("source_artifacts", "origin")


def _origin_column(*, default: str) -> sqlalchemy.Column[str]:
    return sqlalchemy.Column("origin", sqlalchemy.String(16), server_default=default, nullable=False)


def _user_column() -> sqlalchemy.Column[int]:
    return sqlalchemy.Column(
        "user_id", sqlalchemy.BigInteger(), sqlalchemy.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def _create_card_versions() -> None:
    op.create_table(
        "card_versions",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_column(),
        sqlalchemy.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("question", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("answer", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("origin", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("instruction", sqlalchemy.Text(), nullable=True),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
        sqlalchemy.UniqueConstraint("card_id", "version", name="uq_card_versions_version"),
    )
    op.create_index("ix_card_versions_user_id_change_seq", "card_versions", ["user_id", "change_seq"])


def _create_edit_proposals() -> None:
    op.create_table(
        "edit_proposals",
        sqlalchemy.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_column(),
        sqlalchemy.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sqlalchemy.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sqlalchemy.Column("target_kind", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sqlalchemy.Column("title", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("description", sqlalchemy.Text(), nullable=False),
        sqlalchemy.Column("base_version", sqlalchemy.Integer(), nullable=False),
        sqlalchemy.Column("before", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("after", postgresql.JSONB(), nullable=False),
        sqlalchemy.Column("status", sqlalchemy.String(16), nullable=False),
        sqlalchemy.Column("applied_version", sqlalchemy.Integer(), nullable=True),
        sqlalchemy.Column("created_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("updated_at", _TIMESTAMP, server_default=sqlalchemy.func.now(), nullable=False),
        sqlalchemy.Column("change_seq", sqlalchemy.BigInteger(), nullable=False),
    )
    op.create_index("ix_edit_proposals_user_id_change_seq", "edit_proposals", ["user_id", "change_seq"])
    op.create_index("ix_edit_proposals_conversation_id", "edit_proposals", ["conversation_id"])
```

Add `"edit_proposals", "card_versions",` at the start of `_TRUNCATE_TABLES` in `conftest.py`.

- [ ] **Step 6: Run the migration tests.** `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e1 uv run pytest packages/archie-db/tests/test_db_migrations.py -m postgres -v` → PASS, including `test_models_match_the_migrations` (fix any column whose model and migration disagree, e.g. a missing `server_default`).

- [ ] **Step 7: Write the failing pull test** `services/api/tests/e2e/test_versions_pull_e2e.py`:

```python
"""Pull carries what edits through chat add: version origins, card versions and Ask's edit proposals."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy.orm
from archie_db import changes, models, session
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres


def _user_id(authed: httpx.Client) -> int:
    return int(authed.get("/me").json()["user_id"])


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def test_pull_carries_origins_card_versions_and_proposals(live_stack: LiveStack) -> None:
    """An edited card's versions and the chat's proposal reach the phone with every field the app stores."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    card_id, proposal_id = uuid.uuid4(), uuid.uuid4()

    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        conversation = models.Conversation(
            id=uuid.uuid4(), user_id=user_id, title="Q", change_seq=changes.next_change_seq()
        )
        db.add(conversation)
        db.flush()
        message = models.Message(
            id=uuid.uuid4(),
            user_id=user_id,
            conversation_id=conversation.id,
            role=models.MessageRole.ASSISTANT.value,
            text="A",
            segments=[],
            web_search=False,
            status=models.MessageStatus.COMPLETE.value,
            change_seq=changes.next_change_seq(),
        )
        db.add(message)
        db.add(
            models.Card(
                id=card_id,
                user_id=user_id,
                conversation_id=conversation.id,
                kind=models.CardKind.CONCEPT.value,
                question="Q?",
                answer="B.",
                version=2,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()
        for version, answer in ((1, "A."), (2, "B.")):
            db.add(
                models.CardVersion(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    card_id=card_id,
                    version=version,
                    question="Q?",
                    answer=answer,
                    origin=(models.VersionOrigin.ARCHIE if version == 1 else models.VersionOrigin.CHAT_EDIT).value,
                    instruction=None if version == 1 else "Say B",
                    change_seq=changes.next_change_seq(),
                )
            )
        db.add(
            models.EditProposal(
                id=proposal_id,
                user_id=user_id,
                conversation_id=conversation.id,
                message_id=message.id,
                target_kind=models.EditTarget.CARD.value,
                target_id=card_id,
                title="Q?",
                description="Say B",
                base_version=1,
                before={"question": "Q?", "answer": "A."},
                after={"question": "Q?", "answer": "B."},
                status=models.EditStatus.APPLIED.value,
                applied_version=2,
                change_seq=changes.next_change_seq(),
            )
        )
        db.commit()
    engine.dispose()

    rows = _rows(authed)
    [card] = rows["cards"]
    assert card["version"] == 2
    assert [(row["version"], row["answer"], row["origin"]) for row in rows["card_versions"]] == [
        (1, "A.", "archie"),
        (2, "B.", "chat_edit"),
    ]
    [proposal] = rows["edit_proposals"]
    assert proposal["id"] == str(proposal_id)
    assert (proposal["target_kind"], proposal["target_id"], proposal["status"], proposal["applied_version"]) == (
        "card",
        str(card_id),
        "applied",
        2,
    )
    assert proposal["after"] == {"question": "Q?", "answer": "B."}
    assert set(proposal) == {
        "id", "conversation_id", "message_id", "target_kind", "target_id", "title", "description", "base_version",
        "before", "after", "status", "applied_version", "created_at", "updated_at", "change_seq",
    }  # fmt: skip
```

Run: `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e1 uv run pytest services/api/tests/e2e/test_versions_pull_e2e.py -m postgres -v` → FAIL (`KeyError: 'version'` / `'card_versions'`).

- [ ] **Step 8: Schemas and pull.** In `services/api/archie_api/sync/schemas.py` add `origin: str` and `instruction: str | None` to `ArtifactOut` and `TopicPrimerOut` (after `content`), `origin: str` to `TakeVersionOut` (after `clean_failed`), `version: int` to `CardOut` (after `answer`), and:

```python
class CardVersionOut(pydantic.BaseModel):
    """One version of a card's question and answer as the phone stores it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    card_id: uuid.UUID
    version: int
    question: str
    answer: str
    origin: str
    instruction: str | None
    created_at: datetime.datetime
    change_seq: int


class EditProposalOut(pydantic.BaseModel):
    """An edit Ask proposed in a chat, as the phone stores it and as the edit routes return it."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    target_kind: str
    target_id: uuid.UUID
    title: str
    description: str
    base_version: int
    before: dict[str, Any]
    after: dict[str, Any]
    status: str
    applied_version: int | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    change_seq: int
```

and `card_versions: list[CardVersionOut]`, `edit_proposals: list[EditProposalOut]` at the end of `PulledRows`. In `services/api/archie_api/sync/pull.py`: add `CARD_VERSIONS = "card_versions"` and `EDIT_PROPOSALS = "edit_proposals"` to `PulledTable`; add `models.CardVersion` and `models.EditProposal` to `_changed_rows`'s type-parameter tuple; add both to `tables` (`_changed_rows(db, models.CardVersion, user_id=user_id, since=since, limit=limit)` and the same for `models.EditProposal`) and to `PulledRows(...)` (`card_versions=[schemas.CardVersionOut.model_validate(row) for row in page.rows[PulledTable.CARD_VERSIONS]]`, likewise `edit_proposals`); change the docstring's "twelve synced tables" to "fourteen synced tables".

- [ ] **Step 9: Run the pull test and the sync suites.** `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e1 uv run pytest services/api/tests/e2e/test_versions_pull_e2e.py services/api/tests/e2e/test_sync_e2e.py services/api/tests/e2e/test_takes_e2e.py -m postgres -v` → PASS. Then `make lint`.

- [ ] **Step 10: Commit.**

```bash
git add packages/archie-db/archie_db/models.py packages/archie-db/archie_db/migrations/versions/0013_chat_edits.py packages/archie-db/tests/test_db_migrations.py conftest.py services/api/archie_api/sync/schemas.py services/api/archie_api/sync/pull.py services/api/tests/e2e/test_versions_pull_e2e.py
git commit -m "Chat edits: version origins, card versions and edit proposals (migration 0013), pulled to the phone

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XcYDkHG569wyzZcbNoxSyL"
```

### Task 2: Versions core: `archie_db.versions`, the regeneration rule, takes and topic primers through it, care writes card versions  (tier: most capable)

**Files:**
- Create: `packages/archie-db/archie_db/versions.py`, `packages/archie-db/archie_db/topic_primers.py`, `packages/archie-db/tests/test_versions.py`
- Modify: `packages/archie-db/archie_db/pipeline.py` (`write_artifact`, new `keeps_owner_version`), `packages/archie-db/archie_db/takes.py` (`add_version`, `version_at`, `shown_body`), `packages/archie-db/archie_db/search.py` (`any_terms`), `services/api/archie_api/sync/take_actions.py`, `services/worker/archie_worker/handlers/topic_primer.py`, `services/worker/tests/test_topic_primer_e2e.py` (`_write`), `services/worker/tests/test_analyze_primer_e2e.py`, `services/api/archie_api/review/routes.py` (`care`), `services/api/tests/e2e/test_review_routes_e2e.py`

**Interfaces:**
- Consumes (Task 1): the enums and columns.
- Produces:
  - `versions.Target(kind: models.EditTarget, id: uuid.UUID)`, `versions.Snapshot(version: int, content: dict[str, Any])`; constants `versions.MARKDOWN_KEY = "markdown"`, `SUMMARY_KEY = "summary"`, `QUESTION_KEY = "question"`, `ANSWER_KEY = "answer"`.
  - `versions.resolve(db, *, user_id: int, kind: models.EditTarget, item_id: uuid.UUID) -> Target | None`
  - `versions.title(db, *, target: Target) -> str`
  - `versions.current(db, *, target: Target) -> Snapshot`
  - `versions.at_version(db, *, target: Target, version: int) -> dict[str, Any] | None`
  - `versions.write(db, *, target: Target, content: dict[str, Any], origin: models.VersionOrigin, instruction: str | None, derived_from: int | None) -> int` (the new current version number)
  - `versions.restore(db, *, target: Target, version: int) -> int | None`
  - `pipeline.write_artifact(..., origin: models.VersionOrigin = ARCHIE, derived_from_id: uuid.UUID | None = None, instruction: str | None = None)`; `pipeline.keeps_owner_version(db, *, previous: models.SourceArtifact | None, origin: models.VersionOrigin) -> bool`.
  - `topic_primers.current(db, *, topic_id) -> models.TopicPrimer | None`, `topic_primers.at_version(db, *, topic_id, version) -> models.TopicPrimer | None`, `topic_primers.write(db, *, topic, markdown, model, prompt_version, origin=ARCHIE, derived_from_id=None, instruction=None) -> models.TopicPrimer`.
  - `takes.add_version(db, *, take, version_id, body: str | None, raw_body: str, cleaned: bool, origin: models.VersionOrigin) -> models.TakeVersion`, `takes.version_at(db, *, take_id, version) -> models.TakeVersion | None`, `takes.shown_body(version: models.TakeVersion) -> str`.
  - `search.any_terms(query: str) -> str` (the words joined by `" or "`, for `websearch_to_tsquery`).
- Review: yes (versioning state, the regeneration rule, cards).

- [ ] **Step 1: Test DB.** `docker exec second-brain-postgres-1 createdb -U archie archie_test_e2` (ignore "already exists").

- [ ] **Step 2: Write the failing tests** `packages/archie-db/tests/test_versions.py`:

```python
"""Versions of what Ask can edit: writing, restoring and resolving each kind, and Archie's regeneration rule."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session, takes, topic_primers, versions

pytestmark = pytest.mark.postgres

SUMMARY: dict[str, Any] = {
    "gist": "Index funds beat most stock pickers.",
    "key_ideas": [
        {"timestamp": None, "idea": "They track an index."},
        {"timestamp": None, "idea": "Low fees compound."},
    ],
    "numbers": [{"timestamp": None, "fact": "~90% of managers trail the index."}],
}


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[sqlalchemy.orm.Session]:
    """A session on the migrated test database."""
    engine = session.engine_for(migrated_database_url)
    with sqlalchemy.orm.Session(engine) as database:
        yield database
    engine.dispose()


def _user(db: sqlalchemy.orm.Session, sub: str = "editor") -> int:
    user = models.User(apple_sub=sub)
    db.add(user)
    db.flush()
    changes.lock_user_writes(db, user.id)
    return user.id


def _source_with_summary(db: sqlalchemy.orm.Session, *, user_id: int) -> models.Source:
    url = f"https://example.com/{uuid.uuid4()}"
    source = models.Source(
        id=uuid.uuid4(),
        user_id=user_id,
        url=url,
        normalized_url=url,
        title="Index funds",
        kind=models.SourceKind.ARTICLE.value,
        state=models.SourceState.CONSUMED.value,
        intent=models.SourceIntent.FINISHED.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(source)
    db.flush()
    pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.TEXT, content={"text": "..."}, model=None, prompt_version=None
    )
    pipeline.write_artifact(
        db,
        source=source,
        kind=models.ArtifactKind.SUMMARY,
        content={"summary": SUMMARY, "domain": "Finance", "tags": ["funds"], "cards": []},
        model="claude-haiku-5-5",
        prompt_version="analyze-v2",
    )
    return source


def _summaries(db: sqlalchemy.orm.Session, source_id: uuid.UUID) -> list[models.SourceArtifact]:
    return list(
        db.scalars(
            sqlalchemy.select(models.SourceArtifact)
            .where(
                models.SourceArtifact.source_id == source_id,
                models.SourceArtifact.kind == models.ArtifactKind.SUMMARY.value,
            )
            .order_by(models.SourceArtifact.version)
        )
    )


def _queued(db: sqlalchemy.orm.Session) -> list[str]:
    return list(db.scalars(sqlalchemy.select(models.Job.kind).order_by(models.Job.id)))


def test_a_summary_edit_is_the_next_current_version_and_keeps_the_rest_of_the_analysis(
    db: sqlalchemy.orm.Session,
) -> None:
    """Version 2 is current with the new summary, origin chat_edit and its description; domain and tags carry over."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    target = versions.resolve(db, user_id=user_id, kind=models.EditTarget.SUMMARY, item_id=source.id)
    assert target is not None
    edited = {**SUMMARY, "key_ideas": SUMMARY["key_ideas"][:1]}

    new_version = versions.write(
        db,
        target=target,
        content=edited,
        origin=models.VersionOrigin.CHAT_EDIT,
        instruction="Drop the fees idea",
        derived_from=1,
    )

    first, second = _summaries(db, source.id)
    assert new_version == 2
    assert (first.is_current, second.is_current) == (False, True)
    assert second.content == {"summary": edited, "domain": "Finance", "tags": ["funds"], "cards": []}
    assert (second.origin, second.instruction, second.derived_from_id) == ("chat_edit", "Drop the fees idea", first.id)
    assert versions.current(db, target=target) == versions.Snapshot(version=2, content=edited)
    assert versions.at_version(db, target=target, version=1) == SUMMARY
    assert models.JobKind.EMBED.value in _queued(db)


def test_restoring_copies_an_earlier_version_as_the_newest(db: sqlalchemy.orm.Session) -> None:
    """Restore makes version 3 a copy of version 1 (origin restore); an unknown version restores nothing."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    target = versions.Target(kind=models.EditTarget.SUMMARY, id=source.id)
    versions.write(
        db, target=target, content={**SUMMARY, "gist": "Edited."}, origin=models.VersionOrigin.CHAT_EDIT,
        instruction=None, derived_from=1,
    )  # fmt: skip

    assert versions.restore(db, target=target, version=1) == 3
    assert versions.restore(db, target=target, version=9) is None

    third = _summaries(db, source.id)[-1]
    assert (third.version, third.is_current, third.origin) == (3, True, "restore")
    assert third.content["summary"] == SUMMARY


def test_archie_rewrites_never_replace_an_owner_chosen_version_unless_the_text_changed(
    db: sqlalchemy.orm.Session,
) -> None:
    """Archie's version 3 lands not current over an edit; after a new text artifact, Archie's version 4 is current."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    target = versions.Target(kind=models.EditTarget.SUMMARY, id=source.id)
    versions.write(
        db, target=target, content={**SUMMARY, "gist": "Mine."}, origin=models.VersionOrigin.CHAT_EDIT,
        instruction=None, derived_from=1,
    )  # fmt: skip
    archie_content = {"summary": SUMMARY, "domain": "Finance", "tags": [], "cards": []}

    rewrite = pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.SUMMARY, content=archie_content, model="m", prompt_version="p"
    )
    assert (rewrite.version, rewrite.is_current) == (3, False)
    assert versions.current(db, target=target).content["gist"] == "Mine."

    # A newer text (a re-fetch, "Wrong episode?") means the owner's edit described other text.
    db.execute(sqlalchemy.text("SELECT pg_sleep(0.01)"))
    db.commit()
    changes.lock_user_writes(db, user_id)
    pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.TEXT, content={"text": "new"}, model=None, prompt_version=None
    )
    db.commit()
    changes.lock_user_writes(db, user_id)
    after_refetch = pipeline.write_artifact(
        db, source=source, kind=models.ArtifactKind.SUMMARY, content=archie_content, model="m", prompt_version="p"
    )
    assert (after_refetch.version, after_refetch.is_current) == (4, True)
    assert [summary.is_current for summary in _summaries(db, source.id)] == [False, False, False, True]


def test_a_topic_primer_is_resolved_from_any_version_and_edits_carry_its_read_state(
    db: sqlalchemy.orm.Session,
) -> None:
    """A primer version id resolves to its topic; the edit becomes current and keeps the primer's opened_at."""
    user_id = _user(db)
    topic = models.Topic(
        id=uuid.uuid4(), user_id=user_id, domain="Macro", name="The Fed", origin=models.TopicOrigin.USER.value,
        change_seq=changes.next_change_seq(),
    )  # fmt: skip
    db.add(topic)
    db.flush()
    first = topic_primers.write(db, topic=topic, markdown="## The Fed\nIt sets rates.", model="m", prompt_version="p")
    first.opened_at = sqlalchemy.func.now()
    db.flush()

    target = versions.resolve(db, user_id=user_id, kind=models.EditTarget.TOPIC_PRIMER, item_id=first.id)
    assert target == versions.Target(kind=models.EditTarget.TOPIC_PRIMER, id=topic.id)
    assert versions.write(
        db, target=target, content={"markdown": "## The Fed\nIt sets short-term rates."},
        origin=models.VersionOrigin.CHAT_EDIT, instruction="Be precise", derived_from=1,
    ) == 2  # fmt: skip

    current = topic_primers.current(db, topic_id=topic.id)
    assert current is not None
    db.refresh(current)
    assert (current.version, current.origin, current.derived_from_id) == (2, "chat_edit", first.id)
    assert current.opened_at is not None
    assert versions.resolve(db, user_id=user_id + 1, kind=models.EditTarget.TOPIC_PRIMER, item_id=topic.id) is None


def test_a_take_edit_makes_a_take_version_and_rewrites_its_cards(db: sqlalchemy.orm.Session) -> None:
    """A chat edit of a take is version 2 (origin chat_edit, not cleaned) and queues take_cards and embed."""
    user_id = _user(db)
    take = models.Take(
        id=uuid.uuid4(), user_id=user_id, kind=models.TakeKind.OPINION.value, title="Rates", current_version=0,
        change_seq=changes.next_change_seq(),
    )  # fmt: skip
    db.add(take)
    db.flush()
    takes.add_version(
        db, take=take, version_id=uuid.uuid4(), body="Rates stay high.", raw_body="Rates stay high.", cleaned=False,
        origin=models.VersionOrigin.OWNER,
    )  # fmt: skip
    db.execute(sqlalchemy.delete(models.Job))
    target = versions.Target(kind=models.EditTarget.TAKE, id=take.id)

    assert versions.write(
        db, target=target, content={"markdown": "Rates stay high into 2027."}, origin=models.VersionOrigin.CHAT_EDIT,
        instruction="Add the year", derived_from=1,
    ) == 2  # fmt: skip

    version = takes.version_at(db, take_id=take.id, version=2)
    assert version is not None
    assert (version.body, version.raw_body, version.cleaned, version.origin) == (
        "Rates stay high into 2027.",
        "Rates stay high into 2027.",
        False,
        "chat_edit",
    )
    assert _queued(db) == [models.JobKind.TAKE_CARDS.value, models.JobKind.EMBED.value]
    assert versions.restore(db, target=target, version=1) == 3


def test_a_card_gets_versions_one_and_two_on_its_first_change(db: sqlalchemy.orm.Session) -> None:
    """The card as it was becomes version 1 (archie); the edit is version 2; the card keeps its schedule."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)
    card = models.Card(
        id=uuid.uuid4(), user_id=user_id, source_id=source.id, kind=models.CardKind.CONCEPT.value,
        question="What do fees do?", answer="They compound.", fsrs_state=models.FsrsState.REVIEW.value, reps=3,
        change_seq=changes.next_change_seq(),
    )  # fmt: skip
    db.add(card)
    db.flush()
    target = versions.Target(kind=models.EditTarget.CARD, id=card.id)

    versions.write(
        db, target=target, content={"question": "What do fees do?", "answer": "They compound over decades."},
        origin=models.VersionOrigin.CHAT_EDIT, instruction="Say over decades", derived_from=1,
    )  # fmt: skip
    versions.restore(db, target=target, version=1)

    rows = db.scalars(
        sqlalchemy.select(models.CardVersion).where(models.CardVersion.card_id == card.id).order_by(models.CardVersion.version)
    ).all()
    assert [(row.version, row.answer, row.origin) for row in rows] == [
        (1, "They compound.", "archie"),
        (2, "They compound over decades.", "chat_edit"),
        (3, "They compound.", "restore"),
    ]
    db.refresh(card)
    assert (card.version, card.answer, card.fsrs_state, card.reps) == (3, "They compound.", "review", 3)


def test_resolve_refuses_other_users_deleted_items_and_missing_content(db: sqlalchemy.orm.Session) -> None:
    """Another user's source, a deleted source, and a source with no primer are not targets."""
    user_id = _user(db)
    source = _source_with_summary(db, user_id=user_id)

    assert versions.resolve(db, user_id=user_id, kind=models.EditTarget.PRIMER, item_id=source.id) is None
    assert versions.resolve(db, user_id=user_id + 1, kind=models.EditTarget.SUMMARY, item_id=source.id) is None
    source.deleted_at = sqlalchemy.func.now()
    db.flush()
    assert versions.resolve(db, user_id=user_id, kind=models.EditTarget.SUMMARY, item_id=source.id) is None
    assert versions.resolve(db, user_id=user_id, kind=models.EditTarget.CARD, item_id=uuid.uuid4()) is None
```

- [ ] **Step 3: Run them to see them fail.** `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e2 uv run pytest packages/archie-db/tests/test_versions.py -m postgres -v` → FAIL (`cannot import name 'versions'`).

- [ ] **Step 4: `takes.py` helpers.** Add to `packages/archie-db/archie_db/takes.py` (add `import uuid` at the top):

```python
def version_at(db: sqlalchemy.orm.Session, *, take_id: uuid.UUID, version: int) -> models.TakeVersion | None:
    """The take's version numbered `version`, or None."""
    return db.scalar(
        sqlalchemy.select(models.TakeVersion).where(
            models.TakeVersion.take_id == take_id, models.TakeVersion.version == version
        )
    )


def shown_body(version: models.TakeVersion) -> str:
    """What the take page shows for a version: its body, or its raw text while Clean it up hasn't written one."""
    return version.body if version.body is not None else version.raw_body


def add_version(
    db: sqlalchemy.orm.Session,
    *,
    take: models.Take,
    version_id: uuid.UUID,
    body: str | None,
    raw_body: str,
    cleaned: bool,
    origin: models.VersionOrigin,
) -> models.TakeVersion:
    """Make the take's next version and queue its next step: the cleanup when it has no body yet, else its cards."""
    take.current_version += 1
    version = models.TakeVersion(
        id=version_id,
        user_id=take.user_id,
        take_id=take.id,
        version=take.current_version,
        body=body,
        raw_body=raw_body,
        cleaned=cleaned,
        origin=origin.value,
        change_seq=changes.next_change_seq(),
    )
    db.add(version)
    db.flush()
    enqueue_step(db, version=version, kind=models.JobKind.CLEAN_TAKE if body is None else models.JobKind.TAKE_CARDS)
    return version
```

In `services/api/archie_api/sync/take_actions.py`, delete `_add_version` and replace its two calls: in `save_take`, `takes.add_version(db, take=take, version_id=parsed.version_id, body=text.body, raw_body=text.raw_body, cleaned=text.cleaned, origin=models.VersionOrigin.OWNER)`; in `restore_take_version`, the same with `origin=models.VersionOrigin.RESTORE` (and replace its `body = earlier.body if earlier.body is not None else earlier.raw_body` with `body = takes.shown_body(earlier)`). Keep `_VersionText`.

- [ ] **Step 5: `topic_primers.py`** (new) `packages/archie-db/archie_db/topic_primers.py`:

```python
"""Topic primer versions, shared by the worker (Archie writes them) and the API (Ask edits and restores).

Each version is its own row and exactly one per topic is current. Every function that writes expects the caller to
hold `changes.lock_user_writes` for the topic's user.
"""

from __future__ import annotations

import uuid

import sqlalchemy
import sqlalchemy.orm

from archie_db import changes, models


def current(db: sqlalchemy.orm.Session, *, topic_id: uuid.UUID) -> models.TopicPrimer | None:
    """The topic's current primer version, or None when it has none."""
    return db.scalars(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == topic_id, models.TopicPrimer.is_current
        )
    ).one_or_none()


def at_version(db: sqlalchemy.orm.Session, *, topic_id: uuid.UUID, version: int) -> models.TopicPrimer | None:
    """The topic's primer version numbered `version`, or None."""
    return db.scalar(
        sqlalchemy.select(models.TopicPrimer).where(
            models.TopicPrimer.topic_id == topic_id, models.TopicPrimer.version == version
        )
    )


def write(
    db: sqlalchemy.orm.Session,
    *,
    topic: models.Topic,
    markdown: str,
    model: str | None,
    prompt_version: str | None,
    origin: models.VersionOrigin = models.VersionOrigin.ARCHIE,
    derived_from_id: uuid.UUID | None = None,
    instruction: str | None = None,
) -> models.TopicPrimer:
    """Add the next version as current; the previous current one stays, no longer current.

    The read state (opened, snoozed) carries over, so an edit doesn't make the primer look unread again.
    """
    previous = current(db, topic_id=topic.id)
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
        prompt_version=prompt_version,
        origin=origin.value,
        derived_from_id=derived_from_id,
        instruction=instruction,
        opened_at=previous.opened_at if previous is not None else None,
        snoozed_until=previous.snoozed_until if previous is not None else None,
        change_seq=changes.next_change_seq(),
    )
    db.add(primer)
    db.flush()
    return primer
```

In `services/worker/archie_worker/handlers/topic_primer.py`: delete `write_topic_primer`; in `handle` call `primer = topic_primers.write(db, topic=topic, markdown=output.markdown, model=completion.model, prompt_version=prompts.TOPIC_PRIMER_PROMPT_VERSION)`; import `topic_primers` from `archie_db`; in `_prepare` replace the `has_current_primer` query with `if topic_primers.current(db, topic_id=topic.id) is not None: return None`. In `services/worker/tests/test_topic_primer_e2e.py::_write`, call `topic_primers.write(db, topic=topic, markdown=markdown, model=llm.SONNET, prompt_version=prompts.TOPIC_PRIMER_PROMPT_VERSION)` (import `topic_primers` from `archie_db` and `prompts` from `archie_worker` if not yet imported).

- [ ] **Step 6: The regeneration rule in `pipeline.py`.** Replace `write_artifact` in `packages/archie-db/archie_db/pipeline.py` with:

```python
def write_artifact(
    db: sqlalchemy.orm.Session,
    *,
    source: models.Source,
    kind: models.ArtifactKind,
    content: dict[str, Any],
    model: str | None,
    prompt_version: str | None,
    origin: models.VersionOrigin = models.VersionOrigin.ARCHIE,
    derived_from_id: uuid.UUID | None = None,
    instruction: str | None = None,
) -> models.SourceArtifact:
    """Add the next version of `kind`, normally as the current one; the previous current version is kept.

    Archie's rewrite of a version the owner chose is stored but not made current (`keeps_owner_version`), so an Ask
    edit or a restore is never silently replaced; the owner can still restore Archie's newer version.
    """
    previous = current_artifact(db, source_id=source.id, kind=kind)
    becomes_current = not keeps_owner_version(db, previous=previous, origin=origin)
    if previous is not None and becomes_current:
        # Flushed first so the partial unique index never sees two current rows.
        previous.is_current = False
        previous.change_seq = changes.next_change_seq()
        db.flush()

    latest_version = db.scalar(
        sqlalchemy.select(sqlalchemy.func.max(models.SourceArtifact.version)).where(
            models.SourceArtifact.source_id == source.id, models.SourceArtifact.kind == kind.value
        )
    )
    artifact = models.SourceArtifact(
        id=uuid.uuid4(),
        user_id=source.user_id,
        source_id=source.id,
        kind=kind.value,
        version=(latest_version or 0) + 1,
        content=content,
        is_current=becomes_current,
        model=model,
        prompt_version=prompt_version,
        origin=origin.value,
        derived_from_id=derived_from_id,
        instruction=instruction,
        change_seq=changes.next_change_seq(),
    )
    db.add(artifact)
    db.flush()
    return artifact


def keeps_owner_version(
    db: sqlalchemy.orm.Session, *, previous: models.SourceArtifact | None, origin: models.VersionOrigin
) -> bool:
    """Whether a new version must leave `previous` current: Archie wrote the new one, the owner chose `previous`, and
    the source's text hasn't been replaced since (after a re-fetch the owner's edit described other text)."""
    if origin != models.VersionOrigin.ARCHIE or previous is None:
        return False
    if previous.origin not in models.OWNER_CHOSEN_ORIGINS:
        return False
    text = current_artifact(db, source_id=previous.source_id, kind=models.ArtifactKind.TEXT)
    return text is None or text.created_at <= previous.created_at
```

Update the module docstring's first line to mention it: "The capture pipeline's shared state: artifact versions (and the rule that Archie never replaces an owner-chosen one), a source's processing status, and which steps to retry."

- [ ] **Step 7: `search.any_terms`.** In `packages/archie-db/archie_db/search.py`, add above `search_chunks`:

```python
def any_terms(query: str) -> str:
    """The query's words joined with `or`, so `websearch_to_tsquery` matches text holding any one of them."""
    return " or ".join(_TERM.findall(query))
```

and change `search_chunks`'s `keyword_query = " or ".join(_TERM.findall(query)) if match_any else query` to `keyword_query = any_terms(query) if match_any else query`.

- [ ] **Step 8: `versions.py`** (new) `packages/archie-db/archie_db/versions.py`:

```python
"""What Ask can edit, as versions: read a target's current content, write its next version, restore an earlier one.

A target is a source's summary or primer, a topic's primer, a take or a card (`Target`). Every change adds a version
and makes it current; nothing is overwritten. Content travels in one edit shape per kind:
- summary: the artifact's `summary` object (`gist`, `key_ideas`, `numbers`); writing copies the rest of the
  artifact's content (domain, tags, the cards it came with) from the current version;
- primer, topic primer and take: `{"markdown": ...}` (a take's body);
- card: `{"question": ..., "answer": ...}`.
Cards are versioned lazily: a card has no `card_versions` rows until its first change, which writes version 1 (the
card as it was) and version 2 together. Every function that writes expects the caller to hold
`changes.lock_user_writes` for the target's user.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy
import sqlalchemy.orm

from archie_db import card_rows, changes, jobs, models, pipeline, takes, topic_primers

MARKDOWN_KEY = "markdown"
SUMMARY_KEY = "summary"
QUESTION_KEY = "question"
ANSWER_KEY = "answer"

_ARTIFACT_KINDS: dict[models.EditTarget, models.ArtifactKind] = {
    models.EditTarget.SUMMARY: models.ArtifactKind.SUMMARY,
    models.EditTarget.PRIMER: models.ArtifactKind.PRIMER,
}


@dataclass(frozen=True)
class Target:
    """One editable thing; `id` is the source (summary, primer), the topic (topic primer), the take or the card."""

    kind: models.EditTarget
    id: uuid.UUID


@dataclass(frozen=True)
class Snapshot:
    """A target's version number and its content in the edit shape."""

    version: int
    content: dict[str, Any]


def resolve(
    db: sqlalchemy.orm.Session, *, user_id: int, kind: models.EditTarget, item_id: uuid.UUID
) -> Target | None:
    """The user's live target, or None. A topic primer may be named by its topic or by any of its version ids."""
    if kind in _ARTIFACT_KINDS:
        return _source_target(db, user_id=user_id, kind=kind, source_id=item_id)
    if kind == models.EditTarget.TOPIC_PRIMER:
        return _topic_target(db, user_id=user_id, item_id=item_id)
    if kind == models.EditTarget.TAKE:
        take = db.get(models.Take, item_id)
        is_live = take is not None and take.user_id == user_id and take.deleted_at is None
        return Target(kind=kind, id=item_id) if is_live else None
    card = card_rows.owned_live_card(db, user_id=user_id, card_id=item_id)
    return Target(kind=kind, id=item_id) if card is not None else None


def title(db: sqlalchemy.orm.Session, *, target: Target) -> str:
    """What the chat calls the target: the source's title, the topic's name, the take's title or the card's question."""
    if target.kind in _ARTIFACT_KINDS:
        source = db.get_one(models.Source, target.id)
        return source.title or source.url
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        return db.get_one(models.Topic, target.id).name
    if target.kind == models.EditTarget.TAKE:
        return db.get_one(models.Take, target.id).title
    return db.get_one(models.Card, target.id).question


def current(db: sqlalchemy.orm.Session, *, target: Target) -> Snapshot:
    """The target's current version and content; `target` came from `resolve`, so it has one."""
    if target.kind in _ARTIFACT_KINDS:
        artifact = pipeline.current_artifact(db, source_id=target.id, kind=_ARTIFACT_KINDS[target.kind])
        assert artifact is not None
        return Snapshot(version=artifact.version, content=_artifact_shape(target.kind, artifact.content))
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        primer = topic_primers.current(db, topic_id=target.id)
        assert primer is not None
        return Snapshot(version=primer.version, content={MARKDOWN_KEY: primer.content[MARKDOWN_KEY]})
    if target.kind == models.EditTarget.TAKE:
        take = db.get_one(models.Take, target.id)
        version = takes.current_version(db, take=take)
        assert version is not None
        return Snapshot(version=take.current_version, content={MARKDOWN_KEY: takes.shown_body(version)})
    card = db.get_one(models.Card, target.id)
    return Snapshot(version=card.version, content={QUESTION_KEY: card.question, ANSWER_KEY: card.answer})


def at_version(db: sqlalchemy.orm.Session, *, target: Target, version: int) -> dict[str, Any] | None:
    """The content of the target's version numbered `version`, or None when there is no such version."""
    if target.kind in _ARTIFACT_KINDS:
        artifact = _artifact_at(db, source_id=target.id, kind=_ARTIFACT_KINDS[target.kind], version=version)
        return _artifact_shape(target.kind, artifact.content) if artifact is not None else None
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        primer = topic_primers.at_version(db, topic_id=target.id, version=version)
        return {MARKDOWN_KEY: primer.content[MARKDOWN_KEY]} if primer is not None else None
    if target.kind == models.EditTarget.TAKE:
        take_version = takes.version_at(db, take_id=target.id, version=version)
        return {MARKDOWN_KEY: takes.shown_body(take_version)} if take_version is not None else None

    card = db.get_one(models.Card, target.id)
    if version == card.version:
        return {QUESTION_KEY: card.question, ANSWER_KEY: card.answer}
    row = _card_version(db, card_id=card.id, version=version)
    return {QUESTION_KEY: row.question, ANSWER_KEY: row.answer} if row is not None else None


def write(
    db: sqlalchemy.orm.Session,
    *,
    target: Target,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
    derived_from: int | None,
) -> int:
    """Save `content` as the target's next, current version and return its number.

    Side effects match a normal save of that kind: a source or topic primer is re-indexed for search, a take version
    queues its cards and indexing, a card keeps its schedule.
    """
    if target.kind in _ARTIFACT_KINDS:
        return _write_artifact(
            db, target=target, content=content, origin=origin, instruction=instruction, derived_from=derived_from
        )
    if target.kind == models.EditTarget.TOPIC_PRIMER:
        return _write_topic_primer(
            db, target=target, content=content, origin=origin, instruction=instruction, derived_from=derived_from
        )
    if target.kind == models.EditTarget.TAKE:
        markdown = content[MARKDOWN_KEY]
        return _write_take(db, take_id=target.id, body=markdown, raw_body=markdown, cleaned=False, origin=origin)
    return _write_card(db, card_id=target.id, content=content, origin=origin, instruction=instruction)


def restore(db: sqlalchemy.orm.Session, *, target: Target, version: int) -> int | None:
    """Save version `version` again as the newest, current one (origin `restore`); None when there is no such version.

    A take keeps the restored version's raw text and Clean it up flag, as the take page's own Restore does.
    """
    if target.kind == models.EditTarget.TAKE:
        earlier = takes.version_at(db, take_id=target.id, version=version)
        if earlier is None:
            return None
        return _write_take(
            db,
            take_id=target.id,
            body=takes.shown_body(earlier),
            raw_body=earlier.raw_body,
            cleaned=earlier.cleaned,
            origin=models.VersionOrigin.RESTORE,
        )

    content = at_version(db, target=target, version=version)
    if content is None:
        return None
    return write(
        db, target=target, content=content, origin=models.VersionOrigin.RESTORE, instruction=None, derived_from=version
    )


def _source_target(
    db: sqlalchemy.orm.Session, *, user_id: int, kind: models.EditTarget, source_id: uuid.UUID
) -> Target | None:
    source = db.get(models.Source, source_id)
    if source is None or source.user_id != user_id or source.deleted_at is not None:
        return None
    if source.merged_into_id is not None:
        return None
    if pipeline.current_artifact(db, source_id=source_id, kind=_ARTIFACT_KINDS[kind]) is None:
        return None
    return Target(kind=kind, id=source_id)


def _topic_target(db: sqlalchemy.orm.Session, *, user_id: int, item_id: uuid.UUID) -> Target | None:
    """Search results and the about block name a primer version; the target is always its topic."""
    primer = db.get(models.TopicPrimer, item_id)
    topic = db.get(models.Topic, primer.topic_id if primer is not None else item_id)
    if topic is None or topic.user_id != user_id or topic.removed_at is not None or topic.merged_into_id is not None:
        return None
    if topic_primers.current(db, topic_id=topic.id) is None:
        return None
    return Target(kind=models.EditTarget.TOPIC_PRIMER, id=topic.id)


def _artifact_shape(kind: models.EditTarget, content: dict[str, Any]) -> dict[str, Any]:
    if kind == models.EditTarget.SUMMARY:
        return dict(content[SUMMARY_KEY])
    return {MARKDOWN_KEY: content[MARKDOWN_KEY]}


def _artifact_at(
    db: sqlalchemy.orm.Session, *, source_id: uuid.UUID, kind: models.ArtifactKind, version: int
) -> models.SourceArtifact | None:
    return db.scalar(
        sqlalchemy.select(models.SourceArtifact).where(
            models.SourceArtifact.source_id == source_id,
            models.SourceArtifact.kind == kind.value,
            models.SourceArtifact.version == version,
        )
    )


def _write_artifact(
    db: sqlalchemy.orm.Session,
    *,
    target: Target,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
    derived_from: int | None,
) -> int:
    kind = _ARTIFACT_KINDS[target.kind]
    source = db.get_one(models.Source, target.id)
    base = pipeline.current_artifact(db, source_id=source.id, kind=kind)
    assert base is not None
    derived = _artifact_at(db, source_id=source.id, kind=kind, version=derived_from) if derived_from else None

    # A summary edit changes only the summary; the analysis around it (domain, tags, the cards it came with) stays.
    full_content = (
        {**base.content, SUMMARY_KEY: content}
        if target.kind == models.EditTarget.SUMMARY
        else {MARKDOWN_KEY: content[MARKDOWN_KEY]}
    )
    artifact = pipeline.write_artifact(
        db,
        source=source,
        kind=kind,
        content=full_content,
        model=None,
        prompt_version=None,
        origin=origin,
        derived_from_id=derived.id if derived is not None else None,
        instruction=instruction,
    )
    jobs.enqueue_embed(db, user_id=source.user_id, item_kind=models.SearchItemKind.SOURCE, item_id=source.id)
    return artifact.version


def _write_topic_primer(
    db: sqlalchemy.orm.Session,
    *,
    target: Target,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
    derived_from: int | None,
) -> int:
    topic = db.get_one(models.Topic, target.id)
    derived = topic_primers.at_version(db, topic_id=topic.id, version=derived_from) if derived_from else None
    primer = topic_primers.write(
        db,
        topic=topic,
        markdown=content[MARKDOWN_KEY],
        model=None,
        prompt_version=None,
        origin=origin,
        derived_from_id=derived.id if derived is not None else None,
        instruction=instruction,
    )
    jobs.enqueue_embed(db, user_id=topic.user_id, item_kind=models.SearchItemKind.TOPIC_PRIMER, item_id=primer.id)
    return primer.version


def _write_take(
    db: sqlalchemy.orm.Session,
    *,
    take_id: uuid.UUID,
    body: str,
    raw_body: str,
    cleaned: bool,
    origin: models.VersionOrigin,
) -> int:
    take = db.get_one(models.Take, take_id)
    takes.add_version(
        db, take=take, version_id=uuid.uuid4(), body=body, raw_body=raw_body, cleaned=cleaned, origin=origin
    )
    changes.touch(take)
    return take.current_version


def _write_card(
    db: sqlalchemy.orm.Session,
    *,
    card_id: uuid.UUID,
    content: dict[str, Any],
    origin: models.VersionOrigin,
    instruction: str | None,
) -> int:
    card = db.get_one(models.Card, card_id)

    # A card's history starts at its first change: the card as it was becomes the version it is at.
    if _card_version(db, card_id=card.id, version=card.version) is None:
        _add_card_version(
            db, card=card, question=card.question, answer=card.answer, origin=models.VersionOrigin.ARCHIE, instruction=None
        )

    # Only the words change: the card keeps its schedule and its review history.
    card.version += 1
    card.question = content[QUESTION_KEY]
    card.answer = content[ANSWER_KEY]
    card.updated_at = sqlalchemy.func.now()
    card.change_seq = changes.next_change_seq()
    _add_card_version(
        db, card=card, question=card.question, answer=card.answer, origin=origin, instruction=instruction
    )
    db.flush()
    return card.version


def _card_version(db: sqlalchemy.orm.Session, *, card_id: uuid.UUID, version: int) -> models.CardVersion | None:
    return db.scalar(
        sqlalchemy.select(models.CardVersion).where(
            models.CardVersion.card_id == card_id, models.CardVersion.version == version
        )
    )


def _add_card_version(
    db: sqlalchemy.orm.Session,
    *,
    card: models.Card,
    question: str,
    answer: str,
    origin: models.VersionOrigin,
    instruction: str | None,
) -> None:
    db.add(
        models.CardVersion(
            id=uuid.uuid4(),
            user_id=card.user_id,
            card_id=card.id,
            version=card.version,
            question=question,
            answer=answer,
            origin=origin.value,
            instruction=instruction,
            change_seq=changes.next_change_seq(),
        )
    )
    db.flush()
```

- [ ] **Step 9: Run the versions tests.** `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e2 uv run pytest packages/archie-db/tests/test_versions.py -m postgres -v` → PASS. If the regeneration test's text and summary land with equal `created_at` (one transaction), the `db.commit()` between them in the test already separates them; keep the `pg_sleep`.

- [ ] **Step 10: The rule through analyze (worker, existing cassette).** Append to `services/worker/tests/test_analyze_primer_e2e.py` (add `versions` to the `archie_db` import):

```python
@pytest.mark.usefixtures("no_embed_jobs")
def test_reanalyzing_keeps_an_ask_edit_current_and_still_replaces_the_cards(
    engine: sqlalchemy.Engine, replay: Replay
) -> None:
    """After an applied Ask edit, analyze's version 3 is stored but not current; its cards replace version 1's."""
    source_id = _add_source(engine, text=GREATWORK_TEXT)
    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)
    first_cards = {card.id for card in _live_cards(engine, source_id)}

    with sqlalchemy.orm.Session(engine) as db:
        source = db.get_one(models.Source, source_id)
        changes.lock_user_writes(db, source.user_id)
        target = versions.Target(kind=models.EditTarget.SUMMARY, id=source_id)
        edited = {**versions.current(db, target=target).content, "gist": "The owner's own gist."}
        versions.write(
            db, target=target, content=edited, origin=models.VersionOrigin.CHAT_EDIT, instruction="Mine",
            derived_from=1,
        )  # fmt: skip
        db.commit()

    _enqueue(engine, source_id, models.JobKind.ANALYZE)
    with replay("analyze_greatwork"):
        loop.run_one(engine, handlers=handlers.HANDLERS)

    summaries = _artifacts(engine, source_id, models.ArtifactKind.SUMMARY)
    assert [(summary.version, summary.is_current, summary.origin) for summary in summaries] == [
        (1, False, "archie"),
        (2, True, "chat_edit"),
        (3, False, "archie"),
    ]
    live = _live_cards(engine, source_id)
    assert live and all(card.artifact_id == summaries[2].id for card in live)
    assert not first_cards & {card.id for card in live}
```

Run: `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e2 uv run pytest services/worker/tests/test_analyze_primer_e2e.py services/worker/tests/test_topic_primer_e2e.py services/worker/tests/test_take_cards_e2e.py -m postgres -v` → PASS.

- [ ] **Step 11: Care writes card versions.** In `services/api/archie_api/review/routes.py::care`, replace the four lines from `live_card.answer = rewritten.answer` through `live_card.change_seq = changes.next_change_seq()` with:

```python
    # The rewrite is the card's next version, so the answer it replaces can be restored.
    versions.write(
        db,
        target=versions.Target(kind=models.EditTarget.CARD, id=live_card.id),
        content={versions.QUESTION_KEY: live_card.question, versions.ANSWER_KEY: rewritten.answer},
        origin=models.VersionOrigin.CARE,
        instruction=body.note,
        derived_from=None,
    )
```

(add `versions` to the `archie_db` import). In `services/api/tests/e2e/test_review_routes_e2e.py::test_a_care_note_rewrites_the_answer_and_is_remembered`, after the `pulled` assertions add:

```python
    card_versions = [row for row in _rows(authed)["card_versions"] if row["card_id"] == str(card.id)]
    assert [(row["version"], row["origin"]) for row in card_versions] == [(1, "archie"), (2, "care")]
    assert card_versions[0]["answer"] == ANSWER and card_versions[1]["answer"] == returned["answer"]
    assert pulled["version"] == 2
```

(If the file has no `_rows` helper, add `def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]: return authed.get("/sync/pull", params={"since": 0}).json()["rows"]` with the imports it needs.)

- [ ] **Step 12: Run everything touched.** `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e2 uv run pytest -m "postgres or not postgres"` → PASS (all cassettes replay); `make lint` → clean.

- [ ] **Step 13: Commit.**

```bash
git add packages/archie-db services/worker services/api/archie_api/sync/take_actions.py services/api/archie_api/review/routes.py services/api/tests/e2e/test_review_routes_e2e.py
git commit -m "Versions core: one module for summary, primer, topic primer, take and card versions; Archie never replaces an owner-chosen version

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XcYDkHG569wyzZcbNoxSyL"
```

### Task 3: App data layer: drizzle 0013, sync of versions and proposals, shared edit types, the edit API client  (tier: most capable)

**Files:**
- Create: `app/src/edits/types.ts`, `app/src/edits/content.ts`, `app/src/edits/content.test.ts`, `app/src/edits/versions.ts`, `app/src/edits/versions.test.ts`, `app/src/edits/useTargetVersions.ts`, `app/src/edits/api.ts`, `app/drizzle/0013_chat_edits.sql` (+ `app/drizzle/meta/0013_snapshot.json`, journal entry — generated)
- Modify: `app/src/db/schema.ts`, `app/drizzle/migrations.js` (generated), `app/src/sync/engine.ts` (pulled types), `app/src/sync/transport.ts` (`applyPage`), `app/src/sync/engine.test.ts`, `app/src/auth/session.ts` (sign-out wipe), `app/src/api/client.ts` (`ClientError.status`)

**Interfaces:**
- Consumes (Task 1): the pulled row shapes in Global Constraints.
- Produces:
  - Drizzle: `schema.artifacts.origin` (`"archie"` default), `.instruction`; `schema.topicPrimers.origin`, `.instruction`; `schema.takeVersions.origin` (`"owner"` default); `schema.cards.version` (default 1); `schema.cardVersions` (`id, cardId, version, question, answer, origin, instruction, createdAt`); `schema.editProposals` (`id, conversationId, messageId, targetKind, targetId, title, description, baseVersion, before` (JSON text), `after` (JSON text), `status, appliedVersion, createdAt, updatedAt`).
  - `@/edits/types`: `EditTargetKind = "summary" | "primer" | "topic_primer" | "take" | "card"`, `EditStatus`, `VersionOrigin`, `EditProposalRow`, `CardVersionRow`, `EditProposalWire` (the `edit` event's data), `ProposalView`, `viewOfRow(row) -> ProposalView`, `viewOfWire(wire) -> ProposalView`, `proposalValues(row: PulledEditProposal)`, `cardVersionValues(row: PulledCardVersion)`.
  - `@/edits/content`: `SummaryShape`, `MarkdownShape`, `CardShape`, `EditContent`, `parseContent(kind, value: unknown): EditContent | null`, `editLines(kind, content: EditContent | null): string[]`, `summaryAsMarkdown(summary: SummaryShape): string`.
  - `@/edits/versions`: `VersionEntry = { version; createdAt; origin: VersionOrigin; instruction: string | null; content: EditContent | null; current: boolean }`, `ORIGIN_LABELS`, `originLabel(origin: string): string`, `artifactEntries(kind: "summary" | "primer", rows)`, `topicPrimerEntries(rows)`, `takeEntries(take, rows)`, `cardEntries(card, rows)` — all newest first.
  - `@/edits/useTargetVersions`: `useTargetVersions(kind: EditTargetKind | null, id: string | null): { current: number | null; entries: VersionEntry[] }` (`current` is null until the rows load or when the target is gone).
  - `@/edits/api`: `sendEditAction({ proposalId, action: "apply" | "undo" | "discard", sessionKey }): Promise<PulledEditProposal>` (stores the returned row locally), `restoreVersion({ targetKind, targetId, version, sessionKey }): Promise<number>`, `isConflict(error: unknown): boolean`.
  - `ClientError` gains `readonly status: number | null`.
- Review: yes (migration, sync, sign-out wipe).

- [ ] **Step 1: Symlink node_modules** (Global Constraints).

- [ ] **Step 2: Schema.** In `app/src/db/schema.ts` add **at the end** of each existing table definition (so drizzle emits `ALTER TABLE … ADD`, not a rebuild):

```ts
// artifacts, after createdAt:
  // Who made this version: archie, chat_edit or restore (see the versions sheet).
  origin: text("origin").notNull().default("archie"),
  // An Ask edit's one-line description.
  instruction: text("instruction"),

// cards, after messageId:
  // The current version; card_versions holds the history once the card has changed.
  version: integer("version").notNull().default(1),

// topicPrimers, after createdAt:
  origin: text("origin").notNull().default("archie"),
  instruction: text("instruction"),

// takeVersions, after createdAt:
  // owner for a save in the editor; chat_edit and restore otherwise.
  origin: text("origin").notNull().default("owner"),
```

and at the end of the file:

```ts
// A card's earlier questions and answers; the server writes versions 1 and 2 on a card's first change.
export const cardVersions = sqliteTable("card_versions", {
  id: text("id").primaryKey(),
  cardId: text("card_id").notNull(),
  version: integer("version").notNull(),
  question: text("question").notNull(),
  answer: text("answer").notNull(),
  origin: text("origin").notNull(),
  instruction: text("instruction"),
  createdAt: text("created_at").notNull(),
});

// Edits Ask proposed in a chat. The phone applies, undoes or discards one through the edit routes, never the outbox.
export const editProposals = sqliteTable("edit_proposals", {
  id: text("id").primaryKey(),
  conversationId: text("conversation_id").notNull(),
  messageId: text("message_id").notNull(),
  targetKind: text("target_kind").notNull(),
  targetId: text("target_id").notNull(),
  title: text("title").notNull(),
  description: text("description").notNull(),
  baseVersion: integer("base_version").notNull(),
  // JSON-encoded content in its edit shape (see edits/content.ts).
  before: text("before").notNull(),
  after: text("after").notNull(),
  status: text("status").notNull(),
  appliedVersion: integer("applied_version"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
});
```

- [ ] **Step 3: Generate the migration.** `cd app && npx drizzle-kit generate --name chat_edits`. **Read the SQL.** Expected: two `CREATE TABLE` (`card_versions`, `edit_proposals`) and six `ALTER TABLE … ADD` (`artifacts.origin`, `artifacts.instruction`, `cards.version`, `topic_primers.origin`, `topic_primers.instruction`, `take_versions.origin`), nothing else, in a file named `0013_chat_edits.sql`. If drizzle emits a `__new_<table>` rebuild instead, its `INSERT INTO __new_… SELECT … FROM …` must list every existing column of that table — fix it by hand. Then append:

```sql
--> statement-breakpoint
-- Card versions and Ask's edit proposals reach this phone only through a full re-pull.
UPDATE sync_state SET position = 0;
```

Confirm `app/drizzle/migrations.js` imports `m0013` and the journal has the `0013_chat_edits` entry.

- [ ] **Step 4: Pulled types.** In `app/src/sync/engine.ts`: add `// Absent when pulling from a server older than chat edits.` then `origin?: string; instruction?: string | null;` to `PulledArtifact` and `PulledTopicPrimer`, `origin?: string;` to `PulledTakeVersion`, `version?: number;` to `PulledCard`; add

```ts
export type PulledCardVersion = {
  id: string;
  card_id: string;
  version: number;
  question: string;
  answer: string;
  origin: string;
  instruction: string | null;
  created_at: string;
  change_seq: number;
};
export type PulledEditProposal = {
  id: string;
  conversation_id: string;
  message_id: string;
  target_kind: string;
  target_id: string;
  title: string;
  description: string;
  base_version: number;
  before: unknown;
  after: unknown;
  status: string;
  applied_version: number | null;
  created_at: string;
  updated_at: string;
  change_seq: number;
};
```

and to `PullPage.rows`: `// Absent when pulling from a server older than chat edits.` `card_versions?: PulledCardVersion[]; edit_proposals?: PulledEditProposal[];`.

- [ ] **Step 5: Write `app/src/edits/types.ts`:**

```ts
import type * as schema from "@/db/schema";
import type { PulledCardVersion, PulledEditProposal } from "@/sync/engine";

export type EditTargetKind = "summary" | "primer" | "topic_primer" | "take" | "card";
export type EditStatus = "proposed" | "applied" | "undone" | "discarded" | "stale" | "superseded";
export type VersionOrigin = "archie" | "owner" | "chat_edit" | "care" | "restore";

export type EditProposalRow = typeof schema.editProposals.$inferSelect;
export type CardVersionRow = typeof schema.cardVersions.$inferSelect;

// The `edit` event's data, snake_case as the server sends it.
export type EditProposalWire = {
  id: string;
  target_kind: EditTargetKind;
  target_id: string;
  title: string;
  description: string;
  base_version: number;
  before: unknown;
  after: unknown;
  status: EditStatus;
};

/** What the chat shows of a proposal, the same whether it came from the stream or from the phone's rows. */
export type ProposalView = {
  id: string;
  targetKind: EditTargetKind;
  targetId: string;
  title: string;
  description: string;
  baseVersion: number;
  before: unknown;
  after: unknown;
  status: EditStatus;
  appliedVersion: number | null;
};

const TARGET_KINDS = new Set<string>(["summary", "primer", "topic_primer", "take", "card"]);
const STATUSES = new Set<string>(["proposed", "applied", "undone", "discarded", "stale", "superseded"]);

export function isTargetKind(value: string): value is EditTargetKind {
  return TARGET_KINDS.has(value);
}

/** A stored proposal for the chat; a row of an unknown kind or status (a newer server) reads as null. */
export function viewOfRow(row: EditProposalRow): ProposalView | null {
  if (!isTargetKind(row.targetKind) || !STATUSES.has(row.status)) return null;
  return {
    id: row.id,
    targetKind: row.targetKind,
    targetId: row.targetId,
    title: row.title,
    description: row.description,
    baseVersion: row.baseVersion,
    before: parseJson(row.before),
    after: parseJson(row.after),
    status: row.status as EditStatus,
    appliedVersion: row.appliedVersion,
  };
}

export function viewOfWire(wire: EditProposalWire): ProposalView {
  return {
    id: wire.id,
    targetKind: wire.target_kind,
    targetId: wire.target_id,
    title: wire.title,
    description: wire.description,
    baseVersion: wire.base_version,
    before: wire.before,
    after: wire.after,
    status: wire.status,
    appliedVersion: null,
  };
}

/** The columns of a pulled (or just-returned) proposal, for an upsert. */
export function proposalValues(row: PulledEditProposal): Omit<EditProposalRow, "id"> {
  return {
    conversationId: row.conversation_id,
    messageId: row.message_id,
    targetKind: row.target_kind,
    targetId: row.target_id,
    title: row.title,
    description: row.description,
    baseVersion: row.base_version,
    before: JSON.stringify(row.before),
    after: JSON.stringify(row.after),
    status: row.status,
    appliedVersion: row.applied_version,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export function cardVersionValues(row: PulledCardVersion): Omit<CardVersionRow, "id"> {
  return {
    cardId: row.card_id,
    version: row.version,
    question: row.question,
    answer: row.answer,
    origin: row.origin,
    instruction: row.instruction,
    createdAt: row.created_at,
  };
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
```

- [ ] **Step 6: Store pulled rows.** In `app/src/sync/transport.ts::applyPage`: add `origin: artifact.origin ?? "archie", instruction: artifact.instruction ?? null` to the artifact `values`; `origin: primer.origin ?? "archie", instruction: primer.instruction ?? null` to the topic primer `values`; `origin: version.origin ?? "owner"` to the take version `values`; `version: card.version ?? 1` to the card `values`; and after the messages loop:

```ts
        for (const version of page.rows.card_versions ?? []) {
          const values = cardVersionValues(version);
          tx.insert(schema.cardVersions)
            .values({ id: version.id, ...values })
            .onConflictDoUpdate({ target: schema.cardVersions.id, set: values })
            .run();
        }

        // Proposals change only through the edit routes, whose answer is stored at once (edits/api.ts), so a pulled
        // row is never older than what the phone shows.
        for (const proposal of page.rows.edit_proposals ?? []) {
          const values = proposalValues(proposal);
          tx.insert(schema.editProposals)
            .values({ id: proposal.id, ...values })
            .onConflictDoUpdate({ target: schema.editProposals.id, set: values })
            .run();
        }
```

(import `cardVersionValues`, `proposalValues` from `@/edits/types`). In `app/src/auth/session.ts`'s sign-out wipe, add `tx.delete(schema.cardVersions).run();` and `tx.delete(schema.editProposals).run();` after `tx.delete(schema.messages).run();`.

- [ ] **Step 7: `ClientError.status`.** In `app/src/api/client.ts`:

```ts
// A 4xx other than 401: the server understood the request and refused it, so retrying it unchanged cannot help.
export class ClientError extends Error {
  constructor(
    message: string,
    readonly status: number | null = null,
  ) {
    super(message);
  }
}
```

and `if (!response.ok) throw new ClientError(\`${response.status} from ${path}\`, response.status);`.

- [ ] **Step 8: Write the failing content and versions tests.** `app/src/edits/content.test.ts`:

```ts
import { editLines, parseContent, summaryAsMarkdown, type SummaryShape } from "./content";

const SUMMARY: SummaryShape = {
  gist: "Index funds beat most stock pickers.",
  key_ideas: [
    { timestamp: null, idea: "They track an index." },
    { timestamp: "12:30", idea: "Low fees compound." },
  ],
  numbers: [],
};

describe("editLines", () => {
  it("lays a summary out as its sections, leaving out an empty one", () => {
    expect(editLines("summary", SUMMARY)).toEqual([
      "Gist",
      "Index funds beat most stock pickers.",
      "Key ideas",
      "• They track an index.",
      "• Low fees compound.",
    ]);
  });

  it("splits markdown into its non-blank lines and a card into question and answer", () => {
    expect(editLines("primer", { markdown: "## Rates\n\nThe Fed sets them.  \n\n- Short ones\n" })).toEqual([
      "## Rates",
      "The Fed sets them.",
      "- Short ones",
    ]);
    expect(editLines("card", { question: "What?", answer: "That." })).toEqual(["Question: What?", "Answer: That."]);
    expect(editLines("take", null)).toEqual([]);
  });
});

describe("parseContent", () => {
  it("accepts each kind's shape and rejects anything else", () => {
    expect(parseContent("summary", SUMMARY)).toEqual(SUMMARY);
    expect(parseContent("summary", { gist: "x" })).toBeNull();
    expect(parseContent("take", { markdown: "Body" })).toEqual({ markdown: "Body" });
    expect(parseContent("topic_primer", { text: "Body" })).toBeNull();
    expect(parseContent("card", { question: "Q?", answer: "A." })).toEqual({ question: "Q?", answer: "A." });
    expect(parseContent("card", "Q?")).toBeNull();
  });
});

it("renders a summary as markdown for the version preview", () => {
  expect(summaryAsMarkdown(SUMMARY)).toBe(
    "Index funds beat most stock pickers.\n\n## Key ideas\n\n1. They track an index.\n2. Low fees compound.",
  );
});
```

`app/src/edits/versions.test.ts`:

```ts
import { artifactEntries, cardEntries, originLabel, takeEntries } from "./versions";

const artifact = (version: number, isCurrent: number, origin: string, instruction: string | null = null) => ({
  id: `a${version}`,
  sourceId: "s1",
  kind: "primer",
  version,
  content: JSON.stringify({ markdown: `v${version}` }),
  isCurrent,
  createdAt: `2026-11-0${version}T00:00:00Z`,
  origin,
  instruction,
});

describe("version lists", () => {
  it("lists artifact versions newest first and marks the current one, even when it isn't the newest", () => {
    const entries = artifactEntries("primer", [
      artifact(1, 0, "archie"),
      artifact(2, 1, "chat_edit", "Drop the jargon"),
      artifact(3, 0, "archie"),
    ]);
    expect(entries.map((entry) => [entry.version, entry.current, entry.origin, entry.instruction])).toEqual([
      [3, false, "archie", null],
      [2, true, "chat_edit", "Drop the jargon"],
      [1, false, "archie", null],
    ]);
    expect(entries[1].content).toEqual({ markdown: "v2" });
  });

  it("gives a card with no history one current entry, and otherwise its rows", () => {
    const card = { id: "c1", question: "Q?", answer: "B.", version: 2, createdAt: "2026-11-01T00:00:00Z" };
    expect(cardEntries({ ...card, version: 1 }, [])).toEqual([
      {
        version: 1,
        createdAt: card.createdAt,
        origin: "archie",
        instruction: null,
        content: { question: "Q?", answer: "B." },
        current: true,
      },
    ]);
    const rows = [
      { id: "v1", cardId: "c1", version: 1, question: "Q?", answer: "A.", origin: "archie", instruction: null, createdAt: "x" },
      { id: "v2", cardId: "c1", version: 2, question: "Q?", answer: "B.", origin: "care", instruction: "Rates", createdAt: "y" },
    ];
    expect(cardEntries(card, rows).map((entry) => [entry.version, entry.current])).toEqual([
      [2, true],
      [1, false],
    ]);
  });

  it("marks a take's current version by its number and shows the raw text while cleaning", () => {
    const rows = [
      { id: "t1", takeId: "k", version: 1, body: null, rawBody: "raw", cleaned: 1, cleanFailed: 0, createdAt: "x", origin: "owner" },
      { id: "t2", takeId: "k", version: 2, body: "B", rawBody: "B", cleaned: 0, cleanFailed: 0, createdAt: "y", origin: "chat_edit" },
    ];
    const entries = takeEntries({ currentVersion: 2 }, rows);
    expect(entries.map((entry) => [entry.version, entry.current, entry.content])).toEqual([
      [2, true, { markdown: "B" }],
      [1, false, { markdown: "raw" }],
    ]);
  });

  it("labels each origin, and an unknown one as Archie", () => {
    expect(["archie", "owner", "chat_edit", "care", "restore", "later"].map(originLabel)).toEqual([
      "Archie",
      "You",
      "Edited in Ask",
      "Rewritten from your note",
      "Restored",
      "Archie",
    ]);
  });
});
```

Run `cd app && npx jest src/edits` → FAIL (modules missing).

- [ ] **Step 9: Write `app/src/edits/content.ts`:**

```ts
import type { EditTargetKind } from "./types";

export type SummaryShape = {
  gist: string;
  key_ideas: { timestamp: string | null; idea: string }[];
  numbers: { timestamp: string | null; fact: string }[];
};
export type MarkdownShape = { markdown: string };
export type CardShape = { question: string; answer: string };
export type EditContent = SummaryShape | MarkdownShape | CardShape;

/** A proposal's or version's content in its kind's shape; anything else (an older or newer shape) is null. */
export function parseContent(kind: EditTargetKind, value: unknown): EditContent | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (kind === "card") {
    return typeof record.question === "string" && typeof record.answer === "string"
      ? { question: record.question, answer: record.answer }
      : null;
  }
  if (kind !== "summary") return typeof record.markdown === "string" ? { markdown: record.markdown } : null;

  const ideas = Array.isArray(record.key_ideas) ? record.key_ideas : null;
  const numbers = Array.isArray(record.numbers) ? record.numbers : null;
  if (typeof record.gist !== "string" || !ideas || !numbers) return null;
  return {
    gist: record.gist,
    key_ideas: ideas
      .filter((item): item is { idea: string; timestamp?: unknown } => typeof item?.idea === "string")
      .map((item) => ({ idea: item.idea, timestamp: typeof item.timestamp === "string" ? item.timestamp : null })),
    numbers: numbers
      .filter((item): item is { fact: string; timestamp?: unknown } => typeof item?.fact === "string")
      .map((item) => ({ fact: item.fact, timestamp: typeof item.timestamp === "string" ? item.timestamp : null })),
  };
}

/** The content as the lines the diff compares: a summary by section, markdown by line, a card as Q and A. */
export function editLines(kind: EditTargetKind, content: EditContent | null): string[] {
  if (content === null) return [];
  if (kind === "card") {
    const card = content as CardShape;
    return [`Question: ${card.question}`, `Answer: ${card.answer}`];
  }
  if (kind !== "summary") {
    return (content as MarkdownShape).markdown
      .split("\n")
      .map((line) => line.trimEnd())
      .filter((line) => line.trim() !== "");
  }

  const summary = content as SummaryShape;
  const lines = ["Gist", summary.gist.trim()];
  if (summary.key_ideas.length > 0) lines.push("Key ideas", ...summary.key_ideas.map((item) => `• ${item.idea}`));
  if (summary.numbers.length > 0) lines.push("Rough numbers", ...summary.numbers.map((item) => `• ${item.fact}`));
  return lines;
}

/** A summary as markdown, for showing an earlier version read-only. */
export function summaryAsMarkdown(summary: SummaryShape): string {
  const parts = [summary.gist.trim()];
  if (summary.key_ideas.length > 0) {
    parts.push("## Key ideas", summary.key_ideas.map((item, index) => `${index + 1}. ${item.idea}`).join("\n"));
  }
  if (summary.numbers.length > 0) {
    parts.push("## Rough numbers", summary.numbers.map((item) => `- ${item.fact}`).join("\n"));
  }
  return parts.join("\n\n");
}
```

- [ ] **Step 10: Write `app/src/edits/versions.ts`:**

```ts
import type * as schema from "@/db/schema";

import { parseContent, type EditContent } from "./content";
import type { CardVersionRow, VersionOrigin } from "./types";

type ArtifactRow = typeof schema.artifacts.$inferSelect;
type TopicPrimerRow = typeof schema.topicPrimers.$inferSelect;
type TakeVersionRow = typeof schema.takeVersions.$inferSelect;
type CardLike = { question: string; answer: string; version: number; createdAt: string };

/** One version as the versions sheet lists it. */
export type VersionEntry = {
  version: number;
  createdAt: string;
  origin: VersionOrigin;
  instruction: string | null;
  content: EditContent | null;
  current: boolean;
};

export const ORIGIN_LABELS: Record<VersionOrigin, string> = {
  archie: "Archie",
  owner: "You",
  chat_edit: "Edited in Ask",
  care: "Rewritten from your note",
  restore: "Restored",
};

export function originLabel(origin: string): string {
  return ORIGIN_LABELS[origin as VersionOrigin] ?? ORIGIN_LABELS.archie;
}

/** One source's summary or primer versions; a summary's content is the `summary` object inside the artifact. */
export function artifactEntries(kind: "summary" | "primer", rows: ArtifactRow[]): VersionEntry[] {
  return newestFirst(
    rows.map((row) => {
      const content = parseJson(row.content) as Record<string, unknown> | null;
      return {
        version: row.version,
        createdAt: row.createdAt,
        origin: asOrigin(row.origin),
        instruction: row.instruction,
        content: parseContent(kind, kind === "summary" ? content?.summary : content),
        current: row.isCurrent === 1,
      };
    }),
  );
}

export function topicPrimerEntries(rows: TopicPrimerRow[]): VersionEntry[] {
  return newestFirst(
    rows.map((row) => ({
      version: row.version,
      createdAt: row.createdAt,
      origin: asOrigin(row.origin),
      instruction: row.instruction,
      content: parseContent("topic_primer", parseJson(row.content)),
      current: row.isCurrent === 1,
    })),
  );
}

/** A take's versions; one still being cleaned shows its raw text, as the take page does. */
export function takeEntries(take: { currentVersion: number }, rows: TakeVersionRow[]): VersionEntry[] {
  return newestFirst(
    rows.map((row) => ({
      version: row.version,
      createdAt: row.createdAt,
      origin: asOrigin(row.origin),
      instruction: null,
      content: { markdown: row.body ?? row.rawBody },
      current: row.version === take.currentVersion,
    })),
  );
}

/** A card's versions; one that never changed has no rows, so it is listed as its single current version. */
export function cardEntries(card: CardLike, rows: CardVersionRow[]): VersionEntry[] {
  if (rows.length === 0) {
    return [
      {
        version: card.version,
        createdAt: card.createdAt,
        origin: "archie",
        instruction: null,
        content: { question: card.question, answer: card.answer },
        current: true,
      },
    ];
  }
  return newestFirst(
    rows.map((row) => ({
      version: row.version,
      createdAt: row.createdAt,
      origin: asOrigin(row.origin),
      instruction: row.instruction,
      content: { question: row.question, answer: row.answer },
      current: row.version === card.version,
    })),
  );
}

function newestFirst(entries: VersionEntry[]): VersionEntry[] {
  return [...entries].sort((first, second) => second.version - first.version);
}

function asOrigin(origin: string): VersionOrigin {
  return origin in ORIGIN_LABELS ? (origin as VersionOrigin) : "archie";
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
```

- [ ] **Step 11: Write `app/src/edits/useTargetVersions.ts`:**

```ts
import { and, eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import type { EditTargetKind } from "./types";
import { artifactEntries, cardEntries, takeEntries, topicPrimerEntries, type VersionEntry } from "./versions";

// A key no row has, so a query for another kind of target reads nothing.
const NONE = "";

/** A target's versions, newest first, and its current version number (null until loaded, or when it is gone). */
export function useTargetVersions(
  kind: EditTargetKind | null,
  id: string | null,
): { current: number | null; entries: VersionEntry[] } {
  const artifactKind = kind === "summary" || kind === "primer" ? kind : null;
  const key = (wanted: boolean) => (wanted && id ? id : NONE);

  const { data: artifacts } = useLiveQuery(
    db
      .select()
      .from(schema.artifacts)
      .where(and(eq(schema.artifacts.sourceId, key(artifactKind !== null)), eq(schema.artifacts.kind, artifactKind ?? NONE))),
    [id, artifactKind],
  );
  const { data: primers } = useLiveQuery(
    db.select().from(schema.topicPrimers).where(eq(schema.topicPrimers.topicId, key(kind === "topic_primer"))),
    [id, kind],
  );
  const { data: takes } = useLiveQuery(
    db.select().from(schema.takes).where(eq(schema.takes.id, key(kind === "take"))),
    [id, kind],
  );
  const { data: takeVersions } = useLiveQuery(
    db.select().from(schema.takeVersions).where(eq(schema.takeVersions.takeId, key(kind === "take"))),
    [id, kind],
  );
  const { data: cards } = useLiveQuery(
    db.select().from(schema.cards).where(eq(schema.cards.id, key(kind === "card"))),
    [id, kind],
  );
  const { data: cardVersions } = useLiveQuery(
    db.select().from(schema.cardVersions).where(eq(schema.cardVersions.cardId, key(kind === "card"))),
    [id, kind],
  );

  return useMemo(() => {
    const entries = entriesFor({ kind, artifactKind, artifacts, primers, takes, takeVersions, cards, cardVersions });
    return { current: entries.find((entry) => entry.current)?.version ?? null, entries };
  }, [kind, artifactKind, artifacts, primers, takes, takeVersions, cards, cardVersions]);
}

function entriesFor(input: {
  kind: EditTargetKind | null;
  artifactKind: "summary" | "primer" | null;
  artifacts: (typeof schema.artifacts.$inferSelect)[];
  primers: (typeof schema.topicPrimers.$inferSelect)[];
  takes: (typeof schema.takes.$inferSelect)[];
  takeVersions: (typeof schema.takeVersions.$inferSelect)[];
  cards: (typeof schema.cards.$inferSelect)[];
  cardVersions: (typeof schema.cardVersions.$inferSelect)[];
}): VersionEntry[] {
  if (input.artifactKind) return artifactEntries(input.artifactKind, input.artifacts);
  if (input.kind === "topic_primer") return topicPrimerEntries(input.primers);
  if (input.kind === "take") {
    const take = input.takes[0];
    return take && take.deletedAt === null ? takeEntries(take, input.takeVersions) : [];
  }
  if (input.kind === "card") {
    const card = input.cards[0];
    return card && card.deletedAt === null ? cardEntries(card, input.cardVersions) : [];
  }
  return [];
}
```

(Check the `takes` table's column names in `schema.ts` — `currentVersion`, `deletedAt` — and adapt if they differ. A deleted source still has artifacts; the chat's stale check treats a missing target via the server's answer, which is enough.)

- [ ] **Step 12: Write `app/src/edits/api.ts`:**

```ts
import { apiFetch, ClientError } from "@/api/client";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import type { PulledEditProposal } from "@/sync/engine";

import { proposalValues, type EditTargetKind } from "./types";

export type EditAction = "apply" | "undo" | "discard";

/** Applies, undoes or discards a proposal; the server's answer is stored at once so the card updates before a pull. */
export async function sendEditAction(input: {
  proposalId: string;
  action: EditAction;
  sessionKey: string;
}): Promise<PulledEditProposal> {
  const row = (await apiFetch(`/ask/edits/${input.proposalId}/${input.action}`, {
    method: "POST",
    sessionKey: input.sessionKey,
  })) as PulledEditProposal;
  const values = proposalValues(row);
  db.insert(schema.editProposals)
    .values({ id: row.id, ...values })
    .onConflictDoUpdate({ target: schema.editProposals.id, set: values })
    .run();
  return row;
}

/** Saves an earlier version again as the newest; returns the new current version number. */
export async function restoreVersion(input: {
  targetKind: EditTargetKind;
  targetId: string;
  version: number;
  sessionKey: string;
}): Promise<number> {
  const body = (await apiFetch("/versions/restore", {
    method: "POST",
    sessionKey: input.sessionKey,
    body: { target_kind: input.targetKind, target_id: input.targetId, version: input.version },
  })) as { version: number };
  return Number(body.version);
}

/** A 409: the edit or the item changed since the phone last looked. */
export function isConflict(error: unknown): boolean {
  return error instanceof ClientError && error.status === 409;
}
```

- [ ] **Step 13: Sync tests.** In `app/src/sync/engine.test.ts`: add `"0013_chat_edits"` to the `it.each` list of migrations that reset the position; add a copy of the 0011 card-survival test for 0013 (run every migration before `0013_chat_edits`, insert the same card plus `conversation_id = NULL, message_id = NULL`, run 0013, expect `expect.objectContaining({ id: "c1", fsrs_state: "review", reps: 2, version: 1 })`); and:

```ts
  it("stores pulled card versions, edit proposals and version origins", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: {
        sources: [],
        artifacts: [pulledArtifact({ origin: "chat_edit", instruction: "Drop the jargon" })],
        cards: [pulledCard({ version: 2 })],
        card_versions: [
          { id: "cv1", card_id: "c1", version: 1, question: "Q?", answer: "A.", origin: "archie", instruction: null, created_at: "x", change_seq: 3 },
        ],
        edit_proposals: [
          {
            id: "p1",
            conversation_id: "k1",
            message_id: "m1",
            target_kind: "card",
            target_id: "c1",
            title: "Q?",
            description: "Say B",
            base_version: 1,
            before: { question: "Q?", answer: "A." },
            after: { question: "Q?", answer: "B." },
            status: "applied",
            applied_version: 2,
            created_at: "x",
            updated_at: "y",
            change_seq: 4,
          },
        ],
      },
      position: 4,
      more: false,
    });

    expect(db.select().from(schema.artifacts).get()).toEqual(
      expect.objectContaining({ origin: "chat_edit", instruction: "Drop the jargon" }),
    );
    expect(db.select().from(schema.cards).get()?.version).toBe(2);
    expect(db.select().from(schema.cardVersions).all()).toEqual([expect.objectContaining({ cardId: "c1", version: 1 })]);
    expect(db.select().from(schema.editProposals).get()).toEqual(
      expect.objectContaining({ status: "applied", appliedVersion: 2, after: JSON.stringify({ question: "Q?", answer: "B." }) }),
    );
  });
```

(`pulledArtifact` / `pulledCard` are the file's existing builders; check their signatures — `pulledArtifact` may take positional arguments before its overrides — and pass `{ origin, instruction }` / `{ version: 2 }` as their overrides.) If `app/src/auth/session.test.ts` lists the wiped tables, add `card_versions` and `edit_proposals` there.

- [ ] **Step 14: Run.** `cd app && npm run typecheck && npx jest` → PASS.

- [ ] **Step 15: Commit.**

```bash
git add app/src/db/schema.ts app/drizzle app/src/sync app/src/auth/session.ts app/src/api/client.ts app/src/edits
git commit -m "App: drizzle 0013, card versions and edit proposals synced, shared edit types and the edit API client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XcYDkHG569wyzZcbNoxSyL"
```

## Parallel-safe tasks

Each runs in its own worktree from the last foundation commit (`git gtr new chat-edits-e<N> --from-current --yes` inside the `chat-edits` worktree), with its own database `archie_test_e<N>`, and merges back into `chat-edits` when done. None consumes another parallel task's code.

### Task 4: API: apply, undo and discard an edit; restore a version  (tier: most capable)

**Files:**
- Create: `services/api/archie_api/edits/__init__.py`, `services/api/archie_api/edits/routes.py`, `services/api/tests/e2e/test_edits_e2e.py`
- Modify: `services/api/archie_api/main.py` (one `include_router` line)

**Interfaces:**
- Consumes (Tasks 1–2): `models.EditProposal`, `models.EditStatus`, `models.EditTarget`, `models.VersionOrigin`; `versions.resolve`, `versions.current`, `versions.write`, `versions.restore`; `schemas.EditProposalOut`.
- Produces: the four routes in Global Constraints (`POST /ask/edits/{proposal_id}/apply|undo|discard`, `POST /versions/restore`).
- Depends on: Tasks 1-3
- Review: yes (state machine over versions).

- [ ] **Step 1: Worktree and test DB.** Inside the `chat-edits` worktree: `git gtr new chat-edits-e4 --from-current --yes`, then work in the path `git gtr go chat-edits-e4` prints. `docker exec second-brain-postgres-1 createdb -U archie archie_test_e4` (ignore "already exists").

- [ ] **Step 2: Write the failing tests** `services/api/tests/e2e/test_edits_e2e.py`:

```python
"""Apply, undo and discard Ask's edit proposals, and restore versions, through the real API on seeded rows.

No model is called here: proposals are seeded as the Ask stream stores them (see test_ask_edit_e2e.py for that).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, pipeline, session, takes, versions
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

SUMMARY: dict[str, Any] = {
    "gist": "Index funds beat most stock pickers.",
    "key_ideas": [
        {"timestamp": None, "idea": "They track an index."},
        {"timestamp": None, "idea": "Low fees compound."},
    ],
    "numbers": [],
}
EDITED = {**SUMMARY, "key_ideas": SUMMARY["key_ideas"][:1]}


@dataclass(frozen=True)
class Seeded:
    """A whitelisted user's source with a summary, a card and a take, and a chat whose answer can hold proposals."""

    user_id: int
    source_id: uuid.UUID
    card_id: uuid.UUID
    take_id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID


def _user_id(authed: httpx.Client) -> int:
    return int(authed.get("/me").json()["user_id"])


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def _db(live_stack: LiveStack) -> sqlalchemy.orm.Session:
    return sqlalchemy.orm.Session(session.engine_for(live_stack.database_url))


def _seed(live_stack: LiveStack, *, user_id: int) -> Seeded:
    with _db(live_stack) as db:
        changes.lock_user_writes(db, user_id)
        url = f"https://example.com/{uuid.uuid4()}"
        source = models.Source(
            id=uuid.uuid4(), user_id=user_id, url=url, normalized_url=url, title="Index funds",
            kind=models.SourceKind.ARTICLE.value, state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(source)
        db.flush()
        pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY, content={"summary": SUMMARY, "cards": []},
            model="m", prompt_version="p",
        )  # fmt: skip
        card = models.Card(
            id=uuid.uuid4(), user_id=user_id, source_id=source.id, kind=models.CardKind.CONCEPT.value,
            question="What do fees do?", answer="They compound.", change_seq=changes.next_change_seq(),
        )  # fmt: skip
        take = models.Take(
            id=uuid.uuid4(), user_id=user_id, kind=models.TakeKind.OPINION.value, title="Rates", current_version=0,
            change_seq=changes.next_change_seq(),
        )  # fmt: skip
        conversation = models.Conversation(
            id=uuid.uuid4(), user_id=user_id, title="Edit", about_source_id=source.id, about_kind="source",
            change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add_all([card, take, conversation])
        db.flush()
        takes.add_version(
            db, take=take, version_id=uuid.uuid4(), body="Rates stay high.", raw_body="Rates stay high.",
            cleaned=False, origin=models.VersionOrigin.OWNER,
        )  # fmt: skip
        message = models.Message(
            id=uuid.uuid4(), user_id=user_id, conversation_id=conversation.id,
            role=models.MessageRole.ASSISTANT.value, text="Here's the edit.", segments=[], web_search=False,
            status=models.MessageStatus.COMPLETE.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(message)
        db.execute(sqlalchemy.delete(models.Job))
        db.commit()
        return Seeded(
            user_id=user_id, source_id=source.id, card_id=card.id, take_id=take.id,
            conversation_id=conversation.id, message_id=message.id,
        )  # fmt: skip


def _propose(
    live_stack: LiveStack,
    seeded: Seeded,
    *,
    kind: models.EditTarget,
    target_id: uuid.UUID,
    before: dict[str, Any],
    after: dict[str, Any],
    base_version: int = 1,
) -> str:
    """A stored proposal, as `_save` writes it at the end of an answer."""
    with _db(live_stack) as db:
        changes.lock_user_writes(db, seeded.user_id)
        proposal = models.EditProposal(
            id=uuid.uuid4(), user_id=seeded.user_id, conversation_id=seeded.conversation_id,
            message_id=seeded.message_id, target_kind=kind.value, target_id=target_id, title="Index funds",
            description="Drop the fees idea", base_version=base_version, before=before, after=after,
            status=models.EditStatus.PROPOSED.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(proposal)
        db.commit()
        return str(proposal.id)


def _current(live_stack: LiveStack, seeded: Seeded, kind: models.EditTarget, target_id: uuid.UUID) -> versions.Snapshot:
    with _db(live_stack) as db:
        target = versions.resolve(db, user_id=seeded.user_id, kind=kind, item_id=target_id)
        assert target is not None
        return versions.current(db, target=target)


def _jobs(live_stack: LiveStack) -> list[str]:
    with _db(live_stack) as db:
        return list(db.scalars(sqlalchemy.select(models.Job.kind).order_by(models.Job.id)))


@pytest.fixture
def authed(live_stack: LiveStack) -> httpx.Client:
    """A whitelisted user's client."""
    return live_stack.authed(live_stack.sign_in(is_whitelisted=True))


def test_apply_writes_the_edit_as_the_next_version_and_repeats_harmlessly(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Version 2 is the edit (origin chat_edit, the description as instruction); a second Apply changes nothing."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )

    first = authed.post(f"/ask/edits/{proposal_id}/apply")
    again = authed.post(f"/ask/edits/{proposal_id}/apply")

    assert first.status_code == 200 and again.status_code == 200
    assert (first.json()["status"], first.json()["applied_version"]) == ("applied", 2)
    assert again.json()["change_seq"] == first.json()["change_seq"]
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id) == versions.Snapshot(
        version=2, content=EDITED
    )
    current = next(row for row in _rows(authed)["artifacts"] if row["is_current"])
    assert (current["origin"], current["instruction"]) == ("chat_edit", "Drop the fees idea")
    assert _jobs(live_stack) == [models.JobKind.EMBED.value]


def test_apply_goes_stale_when_the_target_changed_or_is_gone(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A proposal made against version 1 of a summary now at 2 is stale; so is one for a deleted source."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    behind = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    newer = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY,
        after={**SUMMARY, "gist": "Other."},
    )  # fmt: skip
    authed.post(f"/ask/edits/{newer}/apply")

    assert authed.post(f"/ask/edits/{behind}/apply").json()["status"] == "stale"
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id).version == 2

    card_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.CARD, target_id=seeded.card_id,
        before={"question": "What do fees do?", "answer": "They compound."},
        after={"question": "What do fees do?", "answer": "They compound over decades."},
    )  # fmt: skip
    with _db(live_stack) as db:
        db.get_one(models.Card, seeded.card_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    assert authed.post(f"/ask/edits/{card_edit}/apply").json()["status"] == "stale"


def test_undo_restores_the_version_the_edit_was_made_against(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Undo makes version 3 a copy of version 1 (origin restore) and marks the edit undone; again is harmless."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    authed.post(f"/ask/edits/{proposal_id}/apply")

    undone = authed.post(f"/ask/edits/{proposal_id}/undo")

    assert undone.status_code == 200 and undone.json()["status"] == "undone"
    assert authed.post(f"/ask/edits/{proposal_id}/undo").status_code == 200
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id) == versions.Snapshot(
        version=3, content=SUMMARY
    )
    assert next(row for row in _rows(authed)["artifacts"] if row["is_current"])["origin"] == "restore"


def test_undo_is_refused_once_something_else_changed_the_target(live_stack: LiveStack, authed: httpx.Client) -> None:
    """After a restore moved the summary past the edit, Undo answers 409 "changed since" and writes nothing."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    authed.post(f"/ask/edits/{proposal_id}/apply")
    authed.post("/versions/restore", json={"target_kind": "summary", "target_id": str(seeded.source_id), "version": 1})

    refused = authed.post(f"/ask/edits/{proposal_id}/undo")

    assert (refused.status_code, refused.json()["detail"]) == (409, "changed since")
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id).version == 3


def test_discard_is_final_and_apply_after_it_is_refused(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Discard marks the edit discarded (twice is harmless); Apply and Undo then answer 409 naming the status."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )

    assert authed.post(f"/ask/edits/{proposal_id}/discard").json()["status"] == "discarded"
    assert authed.post(f"/ask/edits/{proposal_id}/discard").status_code == 200
    applied = authed.post(f"/ask/edits/{proposal_id}/apply")
    assert (applied.status_code, applied.json()["detail"]) == (409, "edit is discarded")
    assert authed.post(f"/ask/edits/{proposal_id}/undo").status_code == 409
    assert _current(live_stack, seeded, models.EditTarget.SUMMARY, seeded.source_id).version == 1


def test_card_and_take_edits_apply_with_their_side_effects(live_stack: LiveStack, authed: httpx.Client) -> None:
    """A card edit pulls card versions 1 and 2; a take edit is take version 2 and queues its cards."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    card_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.CARD, target_id=seeded.card_id,
        before={"question": "What do fees do?", "answer": "They compound."},
        after={"question": "What do fees do?", "answer": "They compound over decades."},
    )  # fmt: skip
    take_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.TAKE, target_id=seeded.take_id,
        before={"markdown": "Rates stay high."}, after={"markdown": "Rates stay high into 2027."},
    )  # fmt: skip

    assert authed.post(f"/ask/edits/{card_edit}/apply").json()["applied_version"] == 2
    assert authed.post(f"/ask/edits/{take_edit}/apply").json()["applied_version"] == 2

    rows = _rows(authed)
    assert [(row["version"], row["origin"]) for row in rows["card_versions"]] == [(1, "archie"), (2, "chat_edit")]
    [card] = rows["cards"]
    assert (card["version"], card["answer"]) == (2, "They compound over decades.")
    take_versions = sorted(rows["take_versions"], key=lambda row: row["version"])
    assert [(row["version"], row["origin"], row["body"]) for row in take_versions] == [
        (1, "owner", "Rates stay high."),
        (2, "chat_edit", "Rates stay high into 2027."),
    ]
    assert models.JobKind.TAKE_CARDS.value in _jobs(live_stack)


def test_restore_copies_a_version_and_refuses_the_current_one_or_a_missing_one(
    live_stack: LiveStack, authed: httpx.Client
) -> None:
    """Restoring version 1 of an edited card makes version 3; restoring the current one is 409, version 9 is 404."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    card_edit = _propose(
        live_stack, seeded, kind=models.EditTarget.CARD, target_id=seeded.card_id,
        before={"question": "What do fees do?", "answer": "They compound."},
        after={"question": "What do fees do?", "answer": "They compound over decades."},
    )  # fmt: skip
    authed.post(f"/ask/edits/{card_edit}/apply")
    body = {"target_kind": "card", "target_id": str(seeded.card_id)}

    restored = authed.post("/versions/restore", json={**body, "version": 1})
    current = authed.post("/versions/restore", json={**body, "version": 3})
    missing = authed.post("/versions/restore", json={**body, "version": 9})
    unknown = authed.post("/versions/restore", json={**body, "target_id": str(uuid.uuid4()), "version": 1})

    assert (restored.status_code, restored.json()) == (200, {"version": 3})
    assert (current.status_code, current.json()["detail"]) == (409, "already current")
    assert (missing.status_code, missing.json()["detail"]) == (404, "version not found")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "not found")
    [card] = _rows(authed)["cards"]
    assert (card["version"], card["answer"]) == (3, "They compound.")


def test_another_users_proposal_and_a_deleted_chats_are_not_found(live_stack: LiveStack, authed: httpx.Client) -> None:
    """Every edit route answers 404 for someone else's proposal, and for one whose chat was deleted."""
    seeded = _seed(live_stack, user_id=_user_id(authed))
    proposal_id = _propose(
        live_stack, seeded, kind=models.EditTarget.SUMMARY, target_id=seeded.source_id, before=SUMMARY, after=EDITED
    )
    stranger = live_stack.authed(live_stack.sign_in(apple_sub="stranger", is_whitelisted=True))

    for action in ("apply", "undo", "discard"):
        response = stranger.post(f"/ask/edits/{proposal_id}/{action}")
        assert (response.status_code, response.json()["detail"]) == (404, "edit not found")

    with _db(live_stack) as db:
        db.get_one(models.Conversation, seeded.conversation_id).deleted_at = sqlalchemy.func.now()
        db.commit()
    assert authed.post(f"/ask/edits/{proposal_id}/apply").status_code == 404
```

Run: `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e4 uv run pytest services/api/tests/e2e/test_edits_e2e.py -m postgres -v` → FAIL (404 for every route: they don't exist).

- [ ] **Step 3: Routes** `services/api/archie_api/edits/__init__.py` (empty, with a one-line docstring `"""Applying Ask's edits and restoring versions."""`) and `services/api/archie_api/edits/routes.py`:

```python
"""Apply, undo and discard an edit Ask proposed, and restore an earlier version of anything editable.

None of these calls a model, so each runs in one transaction under the user's write lock: read, check, write. Apply
writes the proposal's `after` as the target's next version only while the target is still at the version the edit
was proposed against; otherwise the proposal goes stale and nothing is written. Undo restores that version only while
the edit's own version is still current. Repeating a finished action returns the proposal unchanged.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import fastapi
import pydantic
import sqlalchemy
from archie_db import changes, models, versions
from sqlalchemy import orm

from archie_api import deps
from archie_api.sync import schemas

NO_EDIT = "edit not found"
CHANGED_SINCE = "changed since"
ALREADY_CURRENT = "already current"
NOT_FOUND = "not found"
NO_VERSION = "version not found"

router = fastapi.APIRouter(tags=["edits"])


class RestoreRequest(pydantic.BaseModel):
    """Which version of which target to save again as the newest."""

    target_kind: models.EditTarget
    target_id: uuid.UUID
    version: int = pydantic.Field(ge=1)


class RestoreResponse(pydantic.BaseModel):
    """The target's new current version (a copy of the one restored)."""

    version: int


@router.post("/ask/edits/{proposal_id}/apply")
def apply(
    proposal_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.EditProposalOut:
    """Write the edit as the target's next version, or mark it stale when the target moved on or is gone."""
    changes.lock_user_writes(db, user.id)
    proposal = _owned_proposal(db, user=user, proposal_id=proposal_id)
    if proposal.status == models.EditStatus.APPLIED:
        return schemas.EditProposalOut.model_validate(proposal)
    _require_status(proposal, models.EditStatus.PROPOSED)

    target = _live_target(db, user=user, proposal=proposal)
    if target is None or versions.current(db, target=target).version != proposal.base_version:
        _set_status(proposal, models.EditStatus.STALE)
        return _committed(db, proposal)

    proposal.applied_version = versions.write(
        db,
        target=target,
        content=proposal.after,
        origin=models.VersionOrigin.CHAT_EDIT,
        instruction=proposal.description,
        derived_from=proposal.base_version,
    )
    _set_status(proposal, models.EditStatus.APPLIED)
    return _committed(db, proposal)


@router.post("/ask/edits/{proposal_id}/undo")
def undo(
    proposal_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.EditProposalOut:
    """Restore the version the edit was made against, while the edit's own version is still current."""
    changes.lock_user_writes(db, user.id)
    proposal = _owned_proposal(db, user=user, proposal_id=proposal_id)
    if proposal.status == models.EditStatus.UNDONE:
        return schemas.EditProposalOut.model_validate(proposal)
    _require_status(proposal, models.EditStatus.APPLIED)

    target = _live_target(db, user=user, proposal=proposal)
    if target is None or versions.current(db, target=target).version != proposal.applied_version:
        raise fastapi.HTTPException(status_code=409, detail=CHANGED_SINCE)

    versions.restore(db, target=target, version=proposal.base_version)
    _set_status(proposal, models.EditStatus.UNDONE)
    return _committed(db, proposal)


@router.post("/ask/edits/{proposal_id}/discard")
def discard(
    proposal_id: uuid.UUID,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> schemas.EditProposalOut:
    """Set a proposed edit aside for good."""
    changes.lock_user_writes(db, user.id)
    proposal = _owned_proposal(db, user=user, proposal_id=proposal_id)
    if proposal.status == models.EditStatus.DISCARDED:
        return schemas.EditProposalOut.model_validate(proposal)
    _require_status(proposal, models.EditStatus.PROPOSED)

    _set_status(proposal, models.EditStatus.DISCARDED)
    return _committed(db, proposal)


@router.post("/versions/restore")
def restore(
    body: RestoreRequest,
    db: Annotated[orm.Session, fastapi.Depends(deps.get_db)],
    user: Annotated[models.User, fastapi.Depends(deps.current_user)],
) -> RestoreResponse:
    """Save an earlier version of a summary, primer, topic primer, take or card again as the newest one."""
    changes.lock_user_writes(db, user.id)
    target = versions.resolve(db, user_id=user.id, kind=body.target_kind, item_id=body.target_id)
    if target is None:
        raise fastapi.HTTPException(status_code=404, detail=NOT_FOUND)
    if versions.current(db, target=target).version == body.version:
        raise fastapi.HTTPException(status_code=409, detail=ALREADY_CURRENT)

    new_version = versions.restore(db, target=target, version=body.version)
    if new_version is None:
        raise fastapi.HTTPException(status_code=404, detail=NO_VERSION)
    db.commit()
    return RestoreResponse(version=new_version)


def _owned_proposal(db: orm.Session, *, user: models.User, proposal_id: uuid.UUID) -> models.EditProposal:
    """The user's proposal in a live chat, or 404."""
    proposal = db.get(models.EditProposal, proposal_id)
    conversation = db.get(models.Conversation, proposal.conversation_id) if proposal is not None else None
    if proposal is None or proposal.user_id != user.id or conversation is None or conversation.deleted_at is not None:
        raise fastapi.HTTPException(status_code=404, detail=NO_EDIT)
    return proposal


def _require_status(proposal: models.EditProposal, status: models.EditStatus) -> None:
    if proposal.status != status:
        raise fastapi.HTTPException(status_code=409, detail=f"edit is {proposal.status}")


def _live_target(db: orm.Session, *, user: models.User, proposal: models.EditProposal) -> versions.Target | None:
    return versions.resolve(
        db, user_id=user.id, kind=models.EditTarget(proposal.target_kind), item_id=proposal.target_id
    )


def _set_status(proposal: models.EditProposal, status: models.EditStatus) -> None:
    """Change the status with a fresh position, so phones pull the new state."""
    proposal.status = status.value
    proposal.updated_at = sqlalchemy.func.now()
    proposal.change_seq = changes.next_change_seq()


def _committed(db: orm.Session, proposal: models.EditProposal) -> schemas.EditProposalOut:
    db.commit()
    db.refresh(proposal)
    return schemas.EditProposalOut.model_validate(proposal)
```

In `services/api/archie_api/main.py` add `from archie_api.edits import routes as edits_routes` and `app.include_router(edits_routes.router)` next to the Ask routers.

- [ ] **Step 4: Run.** `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e4 uv run pytest services/api/tests/e2e/test_edits_e2e.py -m postgres -v` → PASS. Then `make lint` and the whole suite `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e4 uv run pytest -m "postgres or not postgres"` → PASS.

- [ ] **Step 5: Commit and merge back.**

```bash
git add services/api/archie_api/edits services/api/archie_api/main.py services/api/tests/e2e/test_edits_e2e.py
git commit -m "API: apply, undo and discard Ask's edits, and restore any version

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XcYDkHG569wyzZcbNoxSyL"
```

Then, in the `chat-edits` worktree: `git merge chat-edits-e4`.

### Task 5: API: Ask's editing tools, the `editing` / `edit` events, proposals saved with the answer  (tier: most capable)

**Files:**
- Create: `services/api/archie_api/ask/edit_tools.py`, `services/api/tests/test_edit_tools_units.py`, `services/api/tests/e2e/test_ask_edit_e2e.py`, cassettes `services/api/tests/e2e/cassettes/ask_edit_summary.yaml` and `ask_edit_card.yaml` (recorded)
- Modify: `services/api/archie_api/ask/answer.py`, `services/api/archie_api/ask/prompts.py`, `services/api/archie_api/ask/context.py`, `services/api/archie_api/ask/citations.py` (`_result_title`)

**Interfaces:**
- Consumes (Tasks 1–2): `models.EditProposal`, `models.EditTarget`, `models.EditStatus`; `versions.resolve`, `versions.current`, `versions.title`, `versions.Target`, `versions.MARKDOWN_KEY`/`QUESTION_KEY`/`ANSWER_KEY`; `search.any_terms`; `changes.next_change_seq`.
- Produces:
  - `edit_tools.TOOLS: list[dict[str, Any]]`, `edit_tools.TOOL_NAMES: frozenset[str]`, `edit_tools.ToolContext(user_id: int, conversation_id: uuid.UUID, pending: tuple[Proposal, ...])`, `edit_tools.Proposal` (`id, target, title, description, base_version, before, after`, `.to_event() -> dict`), `edit_tools.ToolOutcome(result: dict, proposal: Proposal | None)`, `edit_tools.run(engine, *, context, tool_use_id: str, name: str, tool_input: object) -> ToolOutcome`, `edit_tools.save_proposals(db, *, user_id, conversation_id, message_id, proposals) -> None`, `edit_tools.apply_replacements(text: str, *, replacements: Sequence[tuple[str, str]]) -> str`, `edit_tools.ToolInputError`.
  - `answer.EventName.EDITING = "editing"`, `answer.EventName.EDIT = "edit"`; `answer.MAX_ROUNDS = 6`, `answer.MAX_TOKENS = 8000`.
  - `context.HistoryMessage.notes: tuple[str, ...] = ()`, `context.citation_notes(segments: list[dict[str, Any]] | None) -> list[str]`, `context.proposal_note(proposal: models.EditProposal) -> str`.
- Depends on: Tasks 1-3
- Review: yes (the model loop, validation, the proposal state written with the answer).

- [ ] **Step 1: Worktree and test DB.** Inside the `chat-edits` worktree: `git gtr new chat-edits-e5 --from-current --yes`; work in `git gtr go chat-edits-e5`. `docker exec second-brain-postgres-1 createdb -U archie archie_test_e5` (ignore "already exists").

- [ ] **Step 2: Write the failing unit tests** `services/api/tests/test_edit_tools_units.py`:

```python
"""Editing tools' pure logic: find/replace application and the history lines that tell the model about edits."""

from __future__ import annotations

import pytest
from archie_api.ask import context, edit_tools
from archie_db import models


def test_replacements_apply_in_order_and_each_must_match_exactly_once() -> None:
    """A later find sees the earlier replacement; a missing or repeated find is an error naming it."""
    text = "## Rates\nThe Fed sets rates.\nBanks follow."

    assert edit_tools.apply_replacements(
        text, replacements=[("sets rates", "sets short-term rates"), ("short-term rates.\n", "short-term rates.\n\n")]
    ) == "## Rates\nThe Fed sets short-term rates.\n\nBanks follow."
    assert edit_tools.apply_replacements(text, replacements=[("\nBanks follow.", "")]) == "## Rates\nThe Fed sets rates."

    with pytest.raises(edit_tools.ToolInputError, match="isn't in the current text"):
        edit_tools.apply_replacements(text, replacements=[("The ECB", "x")])
    with pytest.raises(edit_tools.ToolInputError, match="appears 2 times"):
        edit_tools.apply_replacements(text, replacements=[("es", "x")])


def test_history_adds_the_cited_items_and_the_edits_after_an_answer() -> None:
    """The model sees which items an earlier answer cited and what became of the edits it proposed."""
    segments = [
        {
            "label": "library",
            "text": "Fees compound.",
            "citations": [
                {"kind": "library", "title": "Index funds", "source_id": "s1", "topic_primer_id": None, "take_id": None},
                {"kind": "library", "title": "Index funds", "source_id": "s1", "topic_primer_id": None, "take_id": None},
                {"kind": "web", "title": "Vanguard", "url": "https://vanguard.com"},
            ],
        }
    ]
    notes = context.citation_notes(segments)
    assert notes == ["[cited: Index funds — source s1]"]

    rows = [
        context.HistoryMessage(role=models.MessageRole.USER, text="Drop the fees idea", status=models.MessageStatus.COMPLETE),
        context.HistoryMessage(
            role=models.MessageRole.ASSISTANT,
            text="Here's the edit.",
            status=models.MessageStatus.COMPLETE,
            notes=("[edit proposed: Drop the fees idea — summary s1 — the owner applied it]",),
        ),
    ]
    assert context.history_messages(rows)[-1] == {
        "role": "assistant",
        "content": "Here's the edit.\n\n[edit proposed: Drop the fees idea — summary s1 — the owner applied it]",
    }
```

Run: `uv run pytest services/api/tests/test_edit_tools_units.py -v` → FAIL (`cannot import name 'edit_tools'`).

- [ ] **Step 3: Write `services/api/archie_api/ask/edit_tools.py`:**

```python
"""Ask's editing tools: read what can be edited, find cards, and propose edits the owner applies from the chat.

The model reads a target's exact current content with `read_item`, finds cards with `find_cards`, and proposes a
change with one of the three `propose_*` tools. A proposal changes nothing: it is validated here, shown to the owner
as an `edit` event, and stored with the answer by `save_proposals`; the owner's Apply goes through
`archie_api.edits.routes`. Each tool reads in its own short session between model rounds, so no transaction spans a
model call. A bad input goes back to the model as an error result it can fix.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pydantic
import sqlalchemy
import sqlalchemy.orm
from archie_db import changes, models, search, versions

from archie_api.sync import take_actions

READ_ITEM = "read_item"
FIND_CARDS = "find_cards"
PROPOSE_SUMMARY_EDIT = "propose_summary_edit"
PROPOSE_TEXT_EDIT = "propose_text_edit"
PROPOSE_CARD_EDIT = "propose_card_edit"
TOOL_NAMES = frozenset({READ_ITEM, FIND_CARDS, PROPOSE_SUMMARY_EDIT, PROPOSE_TEXT_EDIT, PROPOSE_CARD_EDIT})

MAX_FOUND_CARDS = 10
MAX_GIST_CHARACTERS = 2000
MAX_SUMMARY_ITEMS = 30
MAX_MARKDOWN_CHARACTERS = 60_000
MAX_DESCRIPTION_CHARACTERS = 300
MAX_REPLACEMENTS = 20
MAX_QUESTION_CHARACTERS = 500
MAX_ANSWER_CHARACTERS = 2000
PROPOSED = "shown to the owner with Apply and Discard; nothing has changed yet"
_CLIP_CHARACTERS = 80

_TEXT_KINDS = frozenset({models.EditTarget.PRIMER, models.EditTarget.TOPIC_PRIMER, models.EditTarget.TAKE})
_NULLABLE_STRING: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_DESCRIPTION: dict[str, Any] = {"type": "string", "description": "One short line telling the owner what changes."}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """A strict-mode object schema: every property required, nothing else allowed."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


READ_ITEM_TOOL: dict[str, Any] = {
    "name": READ_ITEM,
    "description": (
        "Read the exact current content of something the owner can edit: a source's summary or primer (id: the "
        "source id), a topic primer (id: a topic primer id or the topic id), one of the owner's takes (id: the take "
        "id) or a review card (id: the card id). Call it before proposing an edit and copy text from it exactly. "
        "`pending` is an edit you already proposed in this chat that the owner hasn't applied: build on it."
    ),
    "input_schema": _object(
        {"kind": {"type": "string", "enum": [kind.value for kind in models.EditTarget]}, "id": {"type": "string"}}
    ),
    "strict": True,
}
FIND_CARDS_TOOL: dict[str, Any] = {
    "name": FIND_CARDS,
    "description": (
        "Find the owner's review cards by words in their question or answer, by the item they came from, or both. "
        "Returns up to 10 cards with their ids."
    ),
    "input_schema": _object(
        {
            "query": {"type": "string", "description": "Words to look for; empty to list an item's cards."},
            "item": {
                "anyOf": [
                    _object(
                        {
                            "kind": {"type": "string", "enum": [kind.value for kind in models.SearchItemKind]},
                            "id": {"type": "string"},
                        }
                    ),
                    {"type": "null"},
                ]
            },
        }
    ),
    "strict": True,
}
PROPOSE_SUMMARY_EDIT_TOOL: dict[str, Any] = {
    "name": PROPOSE_SUMMARY_EDIT,
    "description": (
        "Propose a new version of a source's summary: the whole summary as it should read, with everything the owner "
        "didn't ask to change copied exactly, timestamps included. The owner sees a diff and taps Apply; nothing "
        "changes before that."
    ),
    "input_schema": _object(
        {
            "source_id": {"type": "string"},
            "description": _DESCRIPTION,
            "gist": {"type": "string"},
            "key_ideas": {"type": "array", "items": _object({"timestamp": _NULLABLE_STRING, "idea": {"type": "string"}})},
            "numbers": {"type": "array", "items": _object({"timestamp": _NULLABLE_STRING, "fact": {"type": "string"}})},
        }
    ),
    "strict": True,
}
PROPOSE_TEXT_EDIT_TOOL: dict[str, Any] = {
    "name": PROPOSE_TEXT_EDIT,
    "description": (
        "Propose an edit to a source's primer (id: the source id), a topic primer or one of the owner's takes, as "
        "find-and-replace pairs over its current markdown from read_item. Each find must be copied exactly and "
        "appear exactly once; an empty replace deletes it. The owner sees a diff and taps Apply; nothing changes "
        "before that."
    ),
    "input_schema": _object(
        {
            "kind": {"type": "string", "enum": [kind.value for kind in _TEXT_KINDS]},
            "id": {"type": "string"},
            "description": _DESCRIPTION,
            "replacements": {
                "type": "array",
                "items": _object({"find": {"type": "string"}, "replace": {"type": "string"}}),
            },
        }
    ),
    "strict": True,
}
PROPOSE_CARD_EDIT_TOOL: dict[str, Any] = {
    "name": PROPOSE_CARD_EDIT,
    "description": (
        "Propose a new question and answer for one of the owner's review cards (find it with find_cards). The card "
        "keeps its review schedule. The owner sees a diff and taps Apply; nothing changes before that."
    ),
    "input_schema": _object(
        {
            "card_id": {"type": "string"},
            "description": _DESCRIPTION,
            "question": {"type": "string"},
            "answer": {"type": "string"},
        }
    ),
    "strict": True,
}
TOOLS: list[dict[str, Any]] = [
    READ_ITEM_TOOL,
    FIND_CARDS_TOOL,
    PROPOSE_SUMMARY_EDIT_TOOL,
    PROPOSE_TEXT_EDIT_TOOL,
    PROPOSE_CARD_EDIT_TOOL,
]


class ToolInputError(Exception):
    """A tool input the model can fix; the message goes back to it as the tool's error result."""


@dataclass(frozen=True)
class Proposal:
    """A validated edit, kept until the answer is stored and shown to the owner at once as an `edit` event."""

    id: uuid.UUID
    target: versions.Target
    title: str
    description: str
    base_version: int
    before: dict[str, Any]
    after: dict[str, Any]

    def to_event(self) -> dict[str, Any]:
        """The `edit` event's data."""
        return {
            "id": str(self.id),
            "target_kind": self.target.kind.value,
            "target_id": str(self.target.id),
            "title": self.title,
            "description": self.description,
            "base_version": self.base_version,
            "before": self.before,
            "after": self.after,
            "status": models.EditStatus.PROPOSED.value,
        }


@dataclass(frozen=True)
class ToolContext:
    """Who is asking, in which chat, and the proposals this answer already made (newest last)."""

    user_id: int
    conversation_id: uuid.UUID
    pending: tuple[Proposal, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolOutcome:
    """A tool's result block for the model, and the proposal it made, if any."""

    result: dict[str, Any]
    proposal: Proposal | None = None


class _ItemIn(pydantic.BaseModel):
    kind: models.EditTarget
    id: uuid.UUID


class _CardOriginIn(pydantic.BaseModel):
    kind: models.SearchItemKind
    id: uuid.UUID


class _FindCardsIn(pydantic.BaseModel):
    query: str
    item: _CardOriginIn | None


class _KeyIdeaIn(pydantic.BaseModel):
    timestamp: str | None
    idea: str = pydantic.Field(min_length=1)


class _NumberIn(pydantic.BaseModel):
    timestamp: str | None
    fact: str = pydantic.Field(min_length=1)


class _SummaryEditIn(pydantic.BaseModel):
    source_id: uuid.UUID
    description: str = pydantic.Field(min_length=1, max_length=MAX_DESCRIPTION_CHARACTERS)
    gist: str = pydantic.Field(min_length=1, max_length=MAX_GIST_CHARACTERS)
    key_ideas: list[_KeyIdeaIn] = pydantic.Field(max_length=MAX_SUMMARY_ITEMS)
    numbers: list[_NumberIn] = pydantic.Field(max_length=MAX_SUMMARY_ITEMS)


class _ReplacementIn(pydantic.BaseModel):
    find: str = pydantic.Field(min_length=1)
    replace: str


class _TextEditIn(pydantic.BaseModel):
    kind: models.EditTarget
    id: uuid.UUID
    description: str = pydantic.Field(min_length=1, max_length=MAX_DESCRIPTION_CHARACTERS)
    replacements: list[_ReplacementIn] = pydantic.Field(min_length=1, max_length=MAX_REPLACEMENTS)


class _CardEditIn(pydantic.BaseModel):
    card_id: uuid.UUID
    description: str = pydantic.Field(min_length=1, max_length=MAX_DESCRIPTION_CHARACTERS)
    question: str = pydantic.Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    answer: str = pydantic.Field(min_length=1, max_length=MAX_ANSWER_CHARACTERS)


_Handled = tuple[dict[str, Any], Proposal | None]
_Handler = Callable[[sqlalchemy.orm.Session, ToolContext, object], _Handled]


def run(
    engine: sqlalchemy.Engine, *, context: ToolContext, tool_use_id: str, name: str, tool_input: object
) -> ToolOutcome:
    """Run one editing tool in its own read-only session; a bad input is an error result the model can act on."""
    handler = _HANDLERS[name]
    with sqlalchemy.orm.Session(engine) as db:
        try:
            payload, proposal = handler(db, context, tool_input)
        except (ToolInputError, pydantic.ValidationError) as error:
            return ToolOutcome(
                result={"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": _error_text(error)}
            )
    return ToolOutcome(
        result={"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(payload)}, proposal=proposal
    )


def save_proposals(
    db: sqlalchemy.orm.Session,
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    proposals: Sequence[Proposal],
) -> None:
    """Store the answer's proposals; each supersedes the chat's older still-proposed edits of the same target.

    The model was handed the pending edit to build on (`read_item`), so the newest proposal holds every change. The
    caller holds the user's write lock and has added the answer row.
    """
    for proposal in proposals:
        db.execute(
            sqlalchemy.update(models.EditProposal)
            .where(
                models.EditProposal.conversation_id == conversation_id,
                models.EditProposal.target_kind == proposal.target.kind.value,
                models.EditProposal.target_id == proposal.target.id,
                models.EditProposal.status == models.EditStatus.PROPOSED.value,
            )
            .values(
                status=models.EditStatus.SUPERSEDED.value,
                updated_at=sqlalchemy.func.now(),
                change_seq=changes.next_change_seq(),
            )
        )
        db.add(
            models.EditProposal(
                id=proposal.id,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                target_kind=proposal.target.kind.value,
                target_id=proposal.target.id,
                title=proposal.title,
                description=proposal.description,
                base_version=proposal.base_version,
                before=proposal.before,
                after=proposal.after,
                status=models.EditStatus.PROPOSED.value,
                change_seq=changes.next_change_seq(),
            )
        )
        db.flush()


def apply_replacements(text: str, *, replacements: Sequence[tuple[str, str]]) -> str:
    """Apply each (find, replace) in order; each find must occur exactly once in the text as it stands by then."""
    edited = text
    for find, replace in replacements:
        count = edited.count(find)
        if count == 0:
            raise ToolInputError(f'"{_clip(find)}" isn\'t in the current text; call read_item and copy it exactly.')
        if count > 1:
            raise ToolInputError(f'"{_clip(find)}" appears {count} times; include more of the text around it.')
        edited = edited.replace(find, replace, 1)
    return edited


def _read_item(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _ItemIn.model_validate(tool_input)
    target = _resolve(db, context=context, kind=parsed.kind, item_id=parsed.id)
    snapshot = versions.current(db, target=target)
    payload = {
        "kind": target.kind.value,
        "id": str(target.id),
        "title": versions.title(db, target=target),
        "version": snapshot.version,
        "content": snapshot.content,
        "pending": _pending_after(db, context=context, target=target),
    }
    return payload, None


def _find_cards(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _FindCardsIn.model_validate(tool_input)
    words = search.any_terms(parsed.query)
    if not words and parsed.item is None:
        raise ToolInputError("Give some words to look for, an item, or both.")

    criteria = [models.Card.user_id == context.user_id, models.Card.deleted_at.is_(None)]
    if parsed.item is not None:
        criteria.append(_card_origin(db, item=parsed.item))
    statement = sqlalchemy.select(models.Card).where(*criteria)
    if words:
        # A user has hundreds of cards, not millions: ranking them on the fly needs no index.
        document = sqlalchemy.func.to_tsvector("english", models.Card.question + " " + models.Card.answer)
        query = sqlalchemy.func.websearch_to_tsquery("english", words)
        statement = statement.where(document.op("@@")(query)).order_by(
            sqlalchemy.func.ts_rank_cd(document, query).desc(), models.Card.created_at
        )
    else:
        statement = statement.order_by(models.Card.created_at)

    cards = db.scalars(statement.limit(MAX_FOUND_CARDS)).all()
    return {"cards": [{"id": str(card.id), "question": card.question, "answer": card.answer} for card in cards]}, None


def _propose_summary_edit(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _SummaryEditIn.model_validate(tool_input)
    target = _resolve(db, context=context, kind=models.EditTarget.SUMMARY, item_id=parsed.source_id)
    after = {
        "gist": parsed.gist.strip(),
        "key_ideas": [{"timestamp": item.timestamp, "idea": item.idea.strip()} for item in parsed.key_ideas],
        "numbers": [{"timestamp": item.timestamp, "fact": item.fact.strip()} for item in parsed.numbers],
    }
    return _proposal(db, target=target, description=parsed.description, after=after)


def _propose_text_edit(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _TextEditIn.model_validate(tool_input)
    if parsed.kind not in _TEXT_KINDS:
        raise ToolInputError("propose_text_edit edits a primer, a topic primer or a take.")
    target = _resolve(db, context=context, kind=parsed.kind, item_id=parsed.id)

    # A follow-up edit builds on the chat's pending proposal for the same target, which it then supersedes.
    base = _pending_after(db, context=context, target=target) or versions.current(db, target=target).content
    pairs = [(replacement.find, replacement.replace) for replacement in parsed.replacements]
    markdown = apply_replacements(base[versions.MARKDOWN_KEY], replacements=pairs).strip()
    limit = take_actions.MAX_TAKE_BODY_LENGTH if target.kind == models.EditTarget.TAKE else MAX_MARKDOWN_CHARACTERS
    if not markdown:
        raise ToolInputError("The edit would leave it empty.")
    if len(markdown) > limit:
        raise ToolInputError(f"The edited text is longer than {limit} characters.")
    return _proposal(db, target=target, description=parsed.description, after={versions.MARKDOWN_KEY: markdown})


def _propose_card_edit(db: sqlalchemy.orm.Session, context: ToolContext, tool_input: object) -> _Handled:
    parsed = _CardEditIn.model_validate(tool_input)
    target = _resolve(db, context=context, kind=models.EditTarget.CARD, item_id=parsed.card_id)
    after = {versions.QUESTION_KEY: parsed.question.strip(), versions.ANSWER_KEY: parsed.answer.strip()}
    return _proposal(db, target=target, description=parsed.description, after=after)


_HANDLERS: dict[str, _Handler] = {
    READ_ITEM: _read_item,
    FIND_CARDS: _find_cards,
    PROPOSE_SUMMARY_EDIT: _propose_summary_edit,
    PROPOSE_TEXT_EDIT: _propose_text_edit,
    PROPOSE_CARD_EDIT: _propose_card_edit,
}


def _resolve(
    db: sqlalchemy.orm.Session, *, context: ToolContext, kind: models.EditTarget, item_id: uuid.UUID
) -> versions.Target:
    target = versions.resolve(db, user_id=context.user_id, kind=kind, item_id=item_id)
    if target is None:
        raise ToolInputError(f"There is no {kind.value} with id {item_id} that the owner can edit.")
    return target


def _proposal(
    db: sqlalchemy.orm.Session, *, target: versions.Target, description: str, after: dict[str, Any]
) -> _Handled:
    snapshot = versions.current(db, target=target)
    if after == snapshot.content:
        raise ToolInputError("That is exactly what it says now; change only what the owner asked for.")

    proposal = Proposal(
        id=uuid.uuid4(),
        target=target,
        title=versions.title(db, target=target),
        description=description.strip(),
        base_version=snapshot.version,
        before=snapshot.content,
        after=after,
    )
    return {"proposal_id": str(proposal.id), "status": PROPOSED}, proposal


def _pending_after(
    db: sqlalchemy.orm.Session, *, context: ToolContext, target: versions.Target
) -> dict[str, Any] | None:
    """The newest still-proposed edit of `target` in this chat: from this answer first, else from earlier ones."""
    for proposal in reversed(context.pending):
        if proposal.target == target:
            return proposal.after
    stored = db.scalars(
        sqlalchemy.select(models.EditProposal)
        .where(
            models.EditProposal.conversation_id == context.conversation_id,
            models.EditProposal.target_kind == target.kind.value,
            models.EditProposal.target_id == target.id,
            models.EditProposal.status == models.EditStatus.PROPOSED.value,
        )
        .order_by(models.EditProposal.created_at.desc())
        .limit(1)
    ).first()
    return stored.after if stored is not None else None


def _card_origin(db: sqlalchemy.orm.Session, *, item: _CardOriginIn) -> sqlalchemy.ColumnElement[bool]:
    if item.kind == models.SearchItemKind.SOURCE:
        return models.Card.source_id == item.id
    if item.kind == models.SearchItemKind.TAKE:
        return models.Card.take_id == item.id

    # Foundation cards belong to one primer version; any version (or the topic itself) names them all.
    primer = db.get(models.TopicPrimer, item.id)
    topic_id = primer.topic_id if primer is not None else item.id
    versions_of_topic = sqlalchemy.select(models.TopicPrimer.id).where(models.TopicPrimer.topic_id == topic_id)
    return models.Card.topic_primer_id.in_(versions_of_topic)


def _error_text(error: ToolInputError | pydantic.ValidationError) -> str:
    if isinstance(error, ToolInputError):
        return str(error)
    problems = [f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}" for problem in error.errors()]
    return "Invalid input: " + "; ".join(problems[:3])


def _clip(text: str) -> str:
    return text if len(text) <= _CLIP_CHARACTERS else f"{text[:_CLIP_CHARACTERS]}…"
```

- [ ] **Step 4: History lines and ids in the about block** (`services/api/archie_api/ask/context.py`). Add `notes: tuple[str, ...] = ()` as the last field of `HistoryMessage`. Replace `history` and the assistant half of `history_messages`:

```python
_EDIT_STATUS_NOTES: dict[models.EditStatus, str] = {
    models.EditStatus.PROPOSED: "waiting for the owner to apply it",
    models.EditStatus.APPLIED: "the owner applied it",
    models.EditStatus.UNDONE: "the owner applied it, then undid it",
    models.EditStatus.DISCARDED: "the owner discarded it",
    models.EditStatus.STALE: "it went stale: the item changed before it was applied",
    models.EditStatus.SUPERSEDED: "replaced by a later proposal",
}
_CITED_ITEM_KEYS = (("source", "source_id"), ("topic_primer", "topic_primer_id"), ("take", "take_id"))


def history(db: orm.Session, *, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    """The conversation's earlier finished exchanges as Messages API turns, oldest first.

    Each answer is followed by lines naming the items it cited and the edits it proposed (with what became of them),
    so a follow-up like "and fix that card too" can find its target.
    """
    stored = db.scalars(
        sqlalchemy.select(models.Message)
        .where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at, models.Message.id)
    ).all()
    proposals = db.scalars(
        sqlalchemy.select(models.EditProposal)
        .where(models.EditProposal.conversation_id == conversation_id)
        .order_by(models.EditProposal.created_at)
    ).all()
    edit_notes: dict[uuid.UUID, list[str]] = {}
    for proposal in proposals:
        edit_notes.setdefault(proposal.message_id, []).append(proposal_note(proposal))

    return history_messages(
        [
            HistoryMessage(
                role=models.MessageRole(row.role),
                text=row.text,
                status=models.MessageStatus(row.status),
                notes=(*citation_notes(row.segments), *edit_notes.get(row.id, [])),
            )
            for row in stored
        ]
    )


def citation_notes(segments: list[dict[str, Any]] | None) -> list[str]:
    """One `[cited: title — kind id]` line per library item an answer cited, in order, each once."""
    cited = [
        citation
        for segment in segments or []
        for citation in segment.get("citations", [])
        if citation.get("kind") == "library"
    ]
    tagged = (f"[cited: {citation['title']} — {tag}]" for citation in cited if (tag := _item_tag(citation)))
    return list(dict.fromkeys(tagged))


def proposal_note(proposal: models.EditProposal) -> str:
    """A `[edit proposed: …]` line: what the edit does, its target, and what the owner did with it."""
    status = _EDIT_STATUS_NOTES[models.EditStatus(proposal.status)]
    return f"[edit proposed: {proposal.description} — {proposal.target_kind} {proposal.target_id} — {status}]"


def _item_tag(citation: dict[str, Any]) -> str | None:
    return next((f"{kind} {citation[key]}" for kind, key in _CITED_ITEM_KEYS if citation.get(key)), None)
```

In `history_messages`, the appended assistant turn becomes `{"role": "assistant", "content": "\n\n".join([answer.text, *answer.notes])}`.

In `about_text` / `_source_text`, add the ids the model edits by: after the first line of `_source_text` add `lines.append(f"Source id: {source.id} (its summary and primer are editable)")`; the topic primer branch returns `f"Topic primer: {topic.name} (topic primer id {primer.id})\n\n{…}"`; the take branch returns `f"The owner's own {…}: {take.title} (take id {take.id})\n\n{body}"`.

- [ ] **Step 5: Item tags on search results** (`services/api/archie_api/ask/citations.py`). `_result_title` returns its current string with ` [<kind> <id>]` appended:

```python
def _result_title(hit: search.ChunkHit) -> str:
    """The passage's item and where in it the passage sits, ending with the item's tag for edits ([source <id>])."""
    tag = f"[{hit.item.kind.value} {hit.item.id}]"
    if hit.owner_kind == models.ChunkOwner.SOURCE_TEXT and hit.start_seconds is not None:
        minutes, seconds = divmod(int(hit.start_seconds), 60)
        return f"{hit.title} (at {minutes}:{seconds:02d}) {tag}"
    name = _OWNER_NAMES.get(hit.owner_kind)
    return f"{hit.title} ({name}) {tag}" if name else f"{hit.title} {tag}"
```

(Citation chips use `ChunkHit.title`, not this, so the phone never sees the tag.)

- [ ] **Step 6: The prompt** (`services/api/archie_api/ask/prompts.py`). Rename the existing `ASK_SYSTEM` string to `_ANSWER_RULES` (unchanged), and add:

```python
EDIT_RULES = """Editing the owner's things:
- You can propose edits to a source's summary or primer, a topic primer, one of the owner's takes, or a review \
card, but only when the owner asks for a change. Use propose_summary_edit, propose_text_edit or propose_card_edit. \
Nothing changes until the owner taps Apply, so never say the edit is done.
- Find the id first: the about item below names its ids, search results end with [kind id] tags, earlier answers \
list the items they cited, and find_cards finds cards. You don't need to search the library for an edit when you \
already have the id.
- Read the current content with read_item first and change only what the owner asked for; copy everything else \
exactly, timestamps included. If read_item shows a pending edit, build on it: your new proposal replaces it.
- When an edit removes or changes a fact that one of the item's cards asks about, find that item's cards and \
propose a matching card edit too.
- A take is the owner's own words: change only what they asked, and never add claims of your own.
- After proposing, say in one short sentence what will change. Don't repeat the new text."""

# The answer rules come first, so every chat's prompt keeps its first 60 characters (the cassette key).
ASK_SYSTEM = f"{_ANSWER_RULES}\n\n{EDIT_RULES}"
```

Update the module docstring to "Ask's system prompt and tools. The fixed answer rules come first (so every chat's prompt shares its first 60 characters), then the editing rules."

- [ ] **Step 7: The loop** (`services/api/archie_api/ask/answer.py`):
  - `MAX_ROUNDS = 6` and `MAX_TOKENS = 8000` (a comment above them: "Room for read, propose a summary edit and its card edit, then answer.").
  - `EventName` gains `EDITING = "editing"` and `EDIT = "edit"`; add both to the module docstring's list of events.
  - `_Progress` gains `proposals: list[edit_tools.Proposal] = field(default_factory=list)`.
  - In `_round`, `tools=[prompts.SEARCH_LIBRARY_TOOL, prompts.WEB_SEARCH_TOOL, *edit_tools.TOOLS]`.
  - In `_events_of`, the `content_block_start` branch becomes:

```python
    # A tool call, a search result or thinking ends the paragraph before it.
    if stream_event.type == "content_block_start" and stream_event.content_block.type != "text":
        yield from _blocks_of(progress.paragraphs.close(), progress=progress)
        block = stream_event.content_block
        if block.type == "tool_use" and block.name in edit_tools.TOOL_NAMES:
            yield Event(name=EventName.EDITING, data={"target_kind": None})
        return
```

  - In `_run`, replace the `results = [...]` comprehension with:

```python
        results = []
        for tool_use in tool_uses:
            result = yield from _run_tool(
                engine, request=request, tool_use=tool_use, passages=passages, progress=progress
            )
            results.append(result)
        messages.append({"role": "user", "content": results})
```

  and add:

```python
def _run_tool(
    engine: sqlalchemy.Engine,
    *,
    request: AnswerRequest,
    tool_use: anthropic.types.ToolUseBlock,
    passages: dict[str, search.ChunkHit],
    progress: _Progress,
) -> Generator[Event, None, dict[str, Any]]:
    """One tool call's result block; a proposal is kept for the save and shown at once as an `edit` event."""
    if tool_use.name not in edit_tools.TOOL_NAMES:
        return _search_library(engine, request=request, tool_use=tool_use, passages=passages)

    context = edit_tools.ToolContext(
        user_id=request.user_id, conversation_id=request.conversation_id, pending=tuple(progress.proposals)
    )
    outcome = edit_tools.run(
        engine, context=context, tool_use_id=tool_use.id, name=tool_use.name, tool_input=tool_use.input
    )
    if outcome.proposal is not None:
        progress.proposals.append(outcome.proposal)
        yield Event(name=EventName.EDIT, data=outcome.proposal.to_event())
    return outcome.result
```

  - In `_save`, after `db.add(models.Message(...))` add:

```python
        db.flush()
        # A failed answer keeps its proposals too: each is checked against its target again on Apply.
        edit_tools.save_proposals(
            db,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            message_id=message_id,
            proposals=progress.proposals,
        )
```

  - Import `edit_tools` with the other `archie_api.ask` modules.

- [ ] **Step 8: Run the unit tests and the existing Ask suite.** `uv run pytest services/api/tests/test_edit_tools_units.py services/api/tests/test_ask_units.py -v` → PASS. `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e5 uv run pytest services/api/tests/e2e/test_ask_e2e.py services/api/tests/e2e/test_ask_cards_e2e.py -m postgres -v` → PASS (the old cassettes still replay: the system prompt's first 60 characters are unchanged, and the extra tools only change the request body).

- [ ] **Step 9: Write the tool tests that need Postgres but no model**, at the top of `services/api/tests/e2e/test_ask_edit_e2e.py`:

```python
"""Ask's editing tools end to end: recorded answers that propose a summary edit and a card edit, plus the tools'
validation and supersede rules on seeded rows (no model).

Anthropic is replayed from recorded real responses, round by round (`allow_playback_repeats=False`). Re-record a
cassette by deleting it and running `uv run pytest services/api/tests/e2e/test_ask_edit_e2e.py --record-mode=once -m
postgres` with TEST_DATABASE_URL set (a few cents of Sonnet 5.5; needs ANTHROPIC_API_KEY).
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
from archie_api.ask import edit_tools
from archie_db import changes, models, pipeline, session
from archie_testing import recording
from archie_testing.harness import LiveStack

pytestmark = pytest.mark.postgres

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"
SUMMARY: dict[str, Any] = {
    "gist": "Index funds beat most stock pickers because they cost less and don't try to time the market.",
    "key_ideas": [
        {"timestamp": None, "idea": "An index fund buys every stock in an index instead of picking winners."},
        {"timestamp": None, "idea": "Low fees compound into large differences over decades."},
        {"timestamp": None, "idea": "Most active managers trail their index after fees."},
    ],
    "numbers": [{"timestamp": None, "fact": "~90% of US large-cap funds trailed the S&P 500 over 15 years."}],
}
PASSAGE = "Index funds buy every stock in the index. Their low fees compound into large differences over decades."
FEES_QUESTION = "What do low fees do over decades?"
FEES_ANSWER = "They compound into large differences."


@pytest.fixture(autouse=True)
def recording_api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic key while recording, a placeholder on replay (no OpenAI key: keyword search in the tool)."""
    recording.use_recording_api_key(request, monkeypatch)


def _replay(request: pytest.FixtureRequest, cassette: str) -> Any:
    recorder = recording.vcr_for(request, cassette_dir=CASSETTE_DIR)
    recorder.ignore_localhost = True
    return recorder.use_cassette(f"{cassette}.yaml", allow_playback_repeats=False)


def _user_id(authed: httpx.Client) -> int:
    return int(authed.get("/me").json()["user_id"])


def _rows(authed: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = authed.get("/sync/pull", params={"since": 0}).json()["rows"]
    return rows


def _ask(authed: httpx.Client, conversation_id: str, text: str, about: dict[str, str]) -> list[tuple[str, dict[str, Any]]]:
    payload = {"user_message_id": str(uuid.uuid4()), "text": text, "web_search": False, "about": about}
    with authed.stream("POST", f"/ask/conversations/{conversation_id}/messages", json=payload, timeout=180) as response:
        assert response.status_code == 200, response.read()
        raw = "".join(response.iter_text())
    events = []
    for chunk in raw.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _seed_source(live_stack: LiveStack, *, user_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    """An index-funds article with its summary, one indexed passage and one card; returns the source and card ids."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        url = "https://example.com/index-funds"
        source = models.Source(
            id=uuid.uuid4(), user_id=user_id, url=url, normalized_url=url, title="How index funds work",
            kind=models.SourceKind.ARTICLE.value, state=models.SourceState.CONSUMED.value,
            intent=models.SourceIntent.FINISHED.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(source)
        db.flush()
        pipeline.write_artifact(
            db, source=source, kind=models.ArtifactKind.SUMMARY,
            content={"summary": SUMMARY, "domain": "Finance", "cards": []}, model="m", prompt_version="p",
        )  # fmt: skip
        db.add(
            models.Chunk(
                user_id=user_id, source_id=source.id, owner_kind=models.ChunkOwner.SOURCE_TEXT.value, chunk_index=0,
                text=PASSAGE,
            )
        )  # fmt: skip
        card = models.Card(
            id=uuid.uuid4(), user_id=user_id, source_id=source.id, kind=models.CardKind.MECHANISM.value,
            question=FEES_QUESTION, answer=FEES_ANSWER, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(card)
        db.commit()
        ids = (source.id, card.id)
    engine.dispose()
    return ids


def _seed_chat(live_stack: LiveStack, *, user_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A chat with one stored answer; returns the chat and answer ids."""
    engine = session.engine_for(live_stack.database_url)
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        conversation = models.Conversation(
            id=uuid.uuid4(), user_id=user_id, title="Edit", change_seq=changes.next_change_seq()
        )
        db.add(conversation)
        db.flush()
        message = models.Message(
            id=uuid.uuid4(), user_id=user_id, conversation_id=conversation.id,
            role=models.MessageRole.ASSISTANT.value, text="Done.", segments=[], web_search=False,
            status=models.MessageStatus.COMPLETE.value, change_seq=changes.next_change_seq(),
        )  # fmt: skip
        db.add(message)
        db.commit()
        ids = (conversation.id, message.id)
    engine.dispose()
    return ids


def test_text_edits_must_match_and_a_new_proposal_supersedes_the_pending_one(
    live_stack: LiveStack,
) -> None:
    """A missing find is an error result; a card proposal stored twice leaves only the newer one proposed; read_item
    then shows the pending edit."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    user_id = _user_id(authed)
    _, card_id = _seed_source(live_stack, user_id=user_id)
    conversation_id, message_id = _seed_chat(live_stack, user_id=user_id)
    engine = session.engine_for(live_stack.database_url)
    context = edit_tools.ToolContext(user_id=user_id, conversation_id=conversation_id)

    unknown = edit_tools.run(
        engine, context=context, tool_use_id="t1", name=edit_tools.PROPOSE_TEXT_EDIT,
        tool_input={"kind": "take", "id": str(uuid.uuid4()), "description": "x", "replacements": [{"find": "a", "replace": "b"}]},
    )  # fmt: skip
    same = edit_tools.run(
        engine, context=context, tool_use_id="t2", name=edit_tools.PROPOSE_CARD_EDIT,
        tool_input={"card_id": str(card_id), "description": "x", "question": FEES_QUESTION, "answer": FEES_ANSWER},
    )  # fmt: skip
    assert unknown.result["is_error"] and "that the owner can edit" in unknown.result["content"]
    assert same.result["is_error"] and "exactly what it says now" in same.result["content"]

    proposals = [
        edit_tools.run(
            engine, context=context, tool_use_id=f"p{index}", name=edit_tools.PROPOSE_CARD_EDIT,
            tool_input={"card_id": str(card_id), "description": "Longer", "question": FEES_QUESTION, "answer": answer},
        ).proposal
        for index, answer in enumerate(["They compound.", "They compound over decades."])
    ]  # fmt: skip
    with sqlalchemy.orm.Session(engine) as db:
        changes.lock_user_writes(db, user_id)
        edit_tools.save_proposals(
            db, user_id=user_id, conversation_id=conversation_id, message_id=message_id,
            proposals=[proposal for proposal in proposals if proposal is not None],
        )  # fmt: skip
        db.commit()

    statuses = [row["status"] for row in sorted(_rows(authed)["edit_proposals"], key=lambda row: row["created_at"])]
    assert sorted(statuses) == ["proposed", "superseded"]
    read = edit_tools.run(
        engine, context=context, tool_use_id="r1", name=edit_tools.READ_ITEM, tool_input={"kind": "card", "id": str(card_id)}
    )  # fmt: skip
    assert json.loads(read.result["content"])["pending"] == {"question": FEES_QUESTION, "answer": "They compound over decades."}
    engine.dispose()
```

Run: `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e5 uv run pytest services/api/tests/e2e/test_ask_edit_e2e.py -m postgres -v` → PASS.

- [ ] **Step 10: The recorded answers.** Append:

```python
def test_asking_to_drop_a_key_idea_proposes_a_summary_edit_and_changes_nothing(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """read_item then propose_summary_edit: an `edit` event and a stored proposal with one key idea fewer."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id, _ = _seed_source(live_stack, user_id=_user_id(authed))

    with _replay(request, "ask_edit_summary"):
        events = _ask(
            authed,
            str(uuid.uuid4()),
            "Please remove the key idea about fees compounding from the summary.",
            about={"kind": "source", "id": str(source_id)},
        )

    names = [name for name, _ in events]
    assert "editing" in names and names[-1] == "done"
    [edit] = [data for name, data in events if name == "edit"]
    assert (edit["target_kind"], edit["target_id"], edit["base_version"], edit["status"]) == (
        "summary",
        str(source_id),
        1,
        "proposed",
    )
    assert edit["before"] == SUMMARY
    ideas = [item["idea"] for item in edit["after"]["key_ideas"]]
    assert len(ideas) == 2 and not any("fees compound" in idea.lower() for idea in ideas)
    assert edit["after"]["gist"] == SUMMARY["gist"] and edit["after"]["numbers"] == SUMMARY["numbers"]

    rows = _rows(authed)
    [proposal] = rows["edit_proposals"]
    assert (proposal["id"], proposal["status"], proposal["message_id"]) == (
        edit["id"],
        "proposed",
        events[-1][1]["message_id"],
    )
    [current] = [row for row in rows["artifacts"] if row["is_current"]]
    assert current["version"] == 1


def test_asking_to_fix_a_card_finds_it_and_proposes_a_card_edit(
    live_stack: LiveStack, request: pytest.FixtureRequest
) -> None:
    """find_cards then propose_card_edit: the edit targets the seeded card and carries the owner's new answer."""
    authed = live_stack.authed(live_stack.sign_in(is_whitelisted=True))
    source_id, card_id = _seed_source(live_stack, user_id=_user_id(authed))

    with _replay(request, "ask_edit_card"):
        events = _ask(
            authed,
            str(uuid.uuid4()),
            "Change my card about low fees so its answer says a 1% fee can eat about a quarter of your savings "
            "over 40 years.",
            about={"kind": "source", "id": str(source_id)},
        )

    [edit] = [data for name, data in events if name == "edit"]
    assert (edit["target_kind"], edit["target_id"]) == ("card", str(card_id))
    assert edit["before"] == {"question": FEES_QUESTION, "answer": FEES_ANSWER}
    assert "quarter" in edit["after"]["answer"].lower()
    assert events[-1][0] == "done"
```

Record both (Global Constraints: delete nothing — they don't exist yet — and run `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e5 uv run pytest services/api/tests/e2e/test_ask_edit_e2e.py --record-mode=once -m postgres -k "asking_to"`). If the model's first recording doesn't use the tools as asked (e.g. it searches first), keep it as long as the assertions hold; if an assertion fails because the model did something reasonable but different (another wording), loosen only that assertion and say why in a comment. Then check the cassettes hold no secrets (Global Constraints `rg`), and run the file again in replay → PASS.

- [ ] **Step 11: Full suite and lint.** `make lint`; `TEST_DATABASE_URL=postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test_e5 uv run pytest -m "postgres or not postgres"` → PASS.

- [ ] **Step 12: Commit and merge back.**

```bash
git add services/api/archie_api/ask services/api/tests/test_edit_tools_units.py services/api/tests/e2e/test_ask_edit_e2e.py services/api/tests/e2e/cassettes/ask_edit_summary.yaml services/api/tests/e2e/cassettes/ask_edit_card.yaml
git commit -m "Ask: read, find and propose edits to summaries, primers, topic primers, takes and cards

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XcYDkHG569wyzZcbNoxSyL"
```

Then, in the `chat-edits` worktree: `git merge chat-edits-e5`.

