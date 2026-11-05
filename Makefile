UV := $(shell which uv)
UV_RUN := $(UV) run

# The Python members of the workspace — everything mypy and pytest should see.
PY_TARGETS := packages services

# Fail early with a friendly pointer if uv isn't installed.
define check_uv
	@if [ -z "$(UV)" ]; then \
		echo "ERROR: uv is not installed or not in PATH."; \
		echo "Install it from: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	fi
endef

###################################################
##            Setup and Formatting               ##
###################################################

install:
	$(check_uv)
	$(UV) sync

check:
	@$(UV_RUN) ruff check .
	@$(UV_RUN) ruff format --check --diff .

check-types:
	@$(UV_RUN) mypy $(PY_TARGETS)

format:
	@$(UV_RUN) ruff check --fix .
	@$(UV_RUN) ruff format .

lint: check check-types

tidy: format lint

###################################################
##                   Tests                       ##
###################################################

test:
	@$(UV_RUN) pytest -vv --color=yes

LOCAL_DATABASE_URL := postgresql+psycopg://archie:archie@127.0.0.1:5434/archie
LOCAL_TEST_DATABASE_URL := postgresql+psycopg://archie:archie@127.0.0.1:5434/archie_test

# Start local Postgres (development + test databases) and wait until it accepts connections.
db-up:
	@docker compose up -d --wait postgres

db-down:
	@docker compose down

# Run only the Postgres-backed tests against the local test database.
test-db: db-up
	@TEST_DATABASE_URL=$(LOCAL_TEST_DATABASE_URL) $(UV_RUN) pytest -vv --color=yes -m postgres

# List every remaining scaffold marker, or report a clean tree.
scaffold:
	@grep -rn "SCAFFOLD" packages services conftest.py 2>/dev/null || echo "✓ no scaffold markers left"

###################################################
##               Local Execution                 ##
###################################################

# Apply migrations to the local development database.
migrate-local: db-up
	@DATABASE_URL=$(LOCAL_DATABASE_URL) $(UV_RUN) archie-db upgrade

# The API on :8000 against the local development database, in dev mode (test routes on).
start-api-local: migrate-local
	@DATABASE_URL=$(LOCAL_DATABASE_URL) ARCHIE_ENV=dev $(UV_RUN) uvicorn archie_api.main:app --host 0.0.0.0 --port 8000 --reload

start-worker-local: migrate-local
	@DATABASE_URL=$(LOCAL_DATABASE_URL) ARCHIE_ENV=dev $(UV_RUN) archie-worker

# Both processes, as the container runs them (Ctrl-C stops both).
start-local: migrate-local
	@DATABASE_URL=$(LOCAL_DATABASE_URL) ARCHIE_ENV=dev $(UV_RUN) archie-launch

###################################################
##                   Maestro                     ##
###################################################

# Maestro drives the debug app on the booted simulator; see maestro/README.md for the setup.
MAESTRO_PATH := /opt/homebrew/opt/openjdk@17/bin:$(HOME)/.maestro/bin:$(PATH)

# Empty the local development database's synced data so a flow never sees leftovers from an earlier run.
reset-local-data: db-up
	@docker compose exec -T postgres psql -q -U archie archie -c "TRUNCATE applied_actions, jobs, briefs, topic_primers, topics, sources, sessions, users RESTART IDENTITY CASCADE"

# The flows that only need a running backend (`make start-local` in another terminal).
# source_page and today_primer call Anthropic for real, so a run spends a few cents.
maestro: reset-local-data
	@PATH="$(MAESTRO_PATH)" maestro test maestro/add_link.yaml maestro/sign_out.yaml maestro/source_page.yaml maestro/library_queue.yaml maestro/library_search.yaml maestro/topics.yaml maestro/finish_item.yaml maestro/topic_picker.yaml maestro/today_primer.yaml

# The podcast flow resolves and summarizes a real episode, so it spends real API credits; run it on purpose.
maestro-podcast: reset-local-data
	@PATH="$(MAESTRO_PATH)" maestro test maestro/add_podcast.yaml

# Delivers a newsletter through the ingest endpoint (needs INGEST_SECRET and the owner's keys in .env; a few cents).
maestro-newsletter: reset-local-data
	@maestro/run_newsletter.sh

# Delivers a news newsletter and an essay, then reads the brief (needs INGEST_SECRET and the owner's keys in .env; a few cents).
maestro-brief: reset-local-data
	@maestro/run_brief.sh

# Starts and stops the backend itself, to take the phone offline mid-flow.
maestro-offline: reset-local-data
	@maestro/run_offline.sh

.PHONY: install check check-types format lint tidy test db-up db-down test-db scaffold migrate-local reset-local-data start-api-local start-worker-local start-local maestro maestro-podcast maestro-newsletter maestro-brief maestro-offline
