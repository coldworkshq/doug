.PHONY: dev api-dev web-dev console-dev test lint build docker

# Run both services for local dev (API :8000, web :3000).
dev:
	(cd api && uv run uvicorn doug.api:app --reload) & \
	(cd web && npm run dev) & \
	wait

api-dev:
	cd api && uv run uvicorn doug.api:app --reload

web-dev:
	cd web && npm run dev

console-dev:
	cd console && npm run dev

test:
	cd api && uv run pytest
	cd console && npm test

lint:
	cd api && uv run ruff check .
	cd web && npm run lint
	cd console && npm run lint

build:
	cd web && npm run build
	cd console && npm run build

docker:
	docker build -t doug-api ./api
	docker build -t doug-web ./web
	docker build -t doug-console ./console
