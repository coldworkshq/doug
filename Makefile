.PHONY: dev api-dev web-dev console-dev test lint build docker

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

build:
	npm run build --workspace=web
	npm run build --workspace=console

# Node images must be built from the repo root — the Dockerfiles expect the
# workspace lockfile and both package.json manifests.
docker:
	docker build -t doug-api ./api
	docker build -t doug-web -f web/Dockerfile .
	docker build -t doug-console -f console/Dockerfile .
