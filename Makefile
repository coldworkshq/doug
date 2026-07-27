.PHONY: dev api-dev web-dev test lint build docker

# Run both services for local dev (API :8000, web :3000).
dev:
	(cd api && uv run uvicorn magpie.api:app --reload) & \
	(cd web && npm run dev) & \
	wait

api-dev:
	cd api && uv run uvicorn magpie.api:app --reload

web-dev:
	cd web && npm run dev

test:
	cd api && uv run pytest

lint:
	cd api && uv run ruff check .
	cd web && npm run lint

build:
	cd web && npm run build

docker:
	docker build -t magpie-api ./api
	docker build -t magpie-web ./web
