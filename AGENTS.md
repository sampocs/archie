# Archie

Archie is a personal "second brain": it turns the podcasts, articles, videos and newsletters a user
shares into summaries, primers and spaced-repetition cards, on an iPhone app that works offline.
This repo holds the Python backend (a uv workspace: `packages/` libraries, `services/` deployables:
the FastAPI `api` and the background `worker`), the Expo app in `app/`, Maestro flows in `maestro/`,
and product/engineering docs in `docs/`. `spikes/` is reference-only throwaway code.

Product behavior lives in `docs/superpowers/specs/2026-10-26-product-scope.md` (the single source of
truth); how it's built lives in `docs/superpowers/specs/2026-11-02-backend-architecture-design.md`.

## Commands

- `make install` — `uv sync` the workspace
- `make lint` — ruff check, ruff format check, mypy; `make format` fixes; `make tidy` does both
- `make test` — all Python tests (Postgres tests skip without a database)
- `make db-up` / `make db-down` — local Postgres + pgvector on `127.0.0.1:5434` (dbs `archie`, `archie_test`)
- `make test-db` — only the Postgres-backed tests, against `archie_test`
- `make start-api-local` / `make start-worker-local` — run against the local dev database
- `make migrate-local` — apply migrations to the local dev database
- `make start-local` — API + worker together, as the container runs them
- `make reset-local-data` — empty the local dev database's synced data
- `make maestro` / `make maestro-offline` — Maestro flows on the booted simulator (see `maestro/README.md`); `make maestro-podcast` runs the podcast flow, which spends real API credits
- `cd app && npm test` / `npm run typecheck` — app jest suite / `tsc --noEmit`
- Re-recording a cassette: delete it, then `uv run pytest <test file> --record-mode=once -m postgres` with
  `TEST_DATABASE_URL` set (as `make test-db` does). Anthropic cassettes cost a few cents and need `ANTHROPIC_API_KEY`
  in the repo-root `.env` (transcription cassettes also read `GROQ_API_KEY` and `OPENAI_API_KEY`); only
  `archie_testing.recording.use_recording_api_key` reads them, and only in record mode
  (every normal run strips it and refuses the network). Recorded keys and account ids are filtered out.
- `make scaffold` — list remaining scaffold markers
- `scripts/install_ios.sh [api-url]` — Release build against the Railway API, installed on the connected iPhone
- Deploys: Railway project `archie`, declared in `.railway/railway.ts`. Pushes deploy after CI passes; `railway config plan` / `apply` change infrastructure (see `docs/deploy.md`)

## Testing

E2E first. Write a unit test only for logic that could plausibly be wrong — never a test that restates a
constant or checks that a thin function calls another. Outside services are replayed from recorded real
responses (pytest-recording cassettes), never hand-made mocks of their bodies. Tests can't reach the
network or read `.env` (root `conftest.py`); Postgres tests are marked `@pytest.mark.postgres`.

## Python house style

- Module-qualified imports: `import archie_db.session` then `session.engine_for(...)`. Classes,
  decorators and `typing.*` may be imported by name.
- Annotate everything; `X | None`, never `Optional`; `Decimal` for money.
- Guard clauses over nesting; a main function reads like a table of contents.
- `StrEnum` or constants instead of magic strings.
- Dataclasses instead of tuples of more than two elements or dicts with caller-visible keys.
- Named parameters for calls with more than one argument (db/session positionals excepted).
- Public classes and functions get docstrings (ruff `D`); comments explain *why*, not *what*.
- Blank-line paragraphs in any function past ~8 lines.
- Explicit checks over try/except; never catch generic `Exception` without a reason.
- Secrets come from the environment only. Never print secrets or `.env` values.

## Scaffold convention

The repo was seeded with exemplar code whose job is to set the conventions above. Files headed
`# SCAFFOLD(exemplar):` exist only to show style; inline `# SCAFFOLD:` marks a stub inside a real file.
Each marker says what replaces it. `make scaffold` lists what's left. **When real code lands in an
area, delete the exemplar files and stubs it supersedes in the same PR** — match their style, then
remove them. Never build real logic on top of a marked file. Unmarked code (tooling, config, logging,
DB session, migrations) is real foundation and stays.

## Worktree policy

When starting new changes from `main` in a **local Claude Code or Codex session**, always make them in a
worktree — `git gtr new <branch> --yes` — never on a branch created in place, so the main checkout stays
on `main`. Every other harness (Cursor, OpenCode, Conductor, cloud sessions) manages its own isolation, so
branch in place in the directory you were handed. If you're already on a feature branch (or in its
worktree), keep working there.
