.PHONY: dev api-dev web-dev console-dev test lint check typecheck typecheck-baseline ratchets ruff-debt build docker

# `api/.env` for the Python service, if you have one. Nothing in `api/` reads a
# dotenv file on its own — `uv run` ignores `.env` unless it is named — so this
# is what makes one work, and `uv run --env-file` ERRORS on a file that does
# not exist, which is why it stays empty until you create one. `web/` and
# `console/` are Next.js and load the repo-root `.env` themselves.
API_ENV_FILE := $(if $(wildcard api/.env),--env-file .env,)

# Run both services for local dev (API :8000, web :3000).
dev:
	(cd api && uv run $(API_ENV_FILE) uvicorn doug.api:app --reload) & \
	npm run dev --workspace=web & \
	wait

api-dev:
	cd api && uv run $(API_ENV_FILE) uvicorn doug.api:app --reload

web-dev:
	npm run dev --workspace=web

console-dev:
	npm run dev --workspace=console

# Deliberately WITHOUT $(API_ENV_FILE). A dotenv holding DOUG_TRACING=1 and a
# real key pair would otherwise put a span into a real Langfuse project for
# every reader test — hundreds of fixtures and synthetic PRs mixed in with the
# reviews someone is trying to read, and silently, because the tests still
# pass. api/tests/conftest.py clears the switch as well, so the suite is safe
# either way; this line is the half that keeps a test run from needing to be.
test:
	cd api && uv run pytest
	npm test --workspace=console
	npm test --workspace=web

lint:
	cd api && uv run ruff check .
	npm run lint --workspace=web
	npm run lint --workspace=console

# The static gate for api/: no database, seconds. CI and the Stop hook in
# .claude/settings.json run exactly this. typecheck runs before ratchets
# because basedpyright rewrites a baseline it can shrink, and ratchets fails
# until the smaller baseline is committed.
check:
	cd api && uv run ruff format --check .
	cd api && uv run ruff check .
	$(MAKE) typecheck
	cd api && uv lock --check
	$(MAKE) ratchets

# basedpyright in standard mode against api/.basedpyright/baseline.json, the
# errors that predate the gate. A new error fails; a fixed one shrinks the file.
typecheck:
	cd api && uv run basedpyright

# Records today's errors as the baseline. Only for adopting a stricter mode or
# rule: the ratchet refuses a baseline that grew past the merge base.
typecheck-baseline:
	cd api && (uv run basedpyright --writebaseline > /dev/null || true) && uv run basedpyright

# Shrink-only ruff debt and type baseline. CI passes RATCHETS_FLAGS=--require-base.
ratchets:
	cd api && uv run python ../.github/scripts/check_ratchets.py $(RATCHETS_FLAGS)

# Rewrites the ruff debt table to what fires today. Run it after paying debt down.
ruff-debt:
	cd api && uv run python ../.github/scripts/check_ratchets.py --write-ruff-debt

build:
	npm run build --workspace=web
	npm run build --workspace=console

# Node images must be built from the repo root — the Dockerfiles expect the
# workspace lockfile and both package.json manifests.
docker:
	docker build -t doug-api ./api
	docker build -t doug-web -f web/Dockerfile .
	docker build -t doug-console -f console/Dockerfile .
