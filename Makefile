.PHONY: dev api-dev web-dev console-dev test lint build docker

# Run both services for local dev (API :8000, web :3000).
dev:
	(cd api && uv run uvicorn doug.api:app --reload) & \
	npm run dev --workspace=web & \
	wait

api-dev:
	cd api && uv run uvicorn doug.api:app --reload

web-dev:
	npm run dev --workspace=web

console-dev:
	npm run dev --workspace=console

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
