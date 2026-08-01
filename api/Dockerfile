# Bases pinned by manifest-list digest: this image is built during the prod
# deploy itself, so a floating tag would mean an upstream Debian/uv bump
# lands unreviewed, mid-merge, in prod. Refresh deliberately by updating the
# digest (docker buildx imagetools inspect <image:tag> prints it).
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:dfe4069fefc02ee4d6097c26f31d0784df09c9b6242fb4a25ad31fbae74ec6aa AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
# No BuildKit cache mounts — Cloud Build's default docker builder lacks them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev
COPY . .
RUN uv sync --locked --no-dev

FROM python:3.14-slim-trixie@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
# Cloud Run injects PORT; default matches its convention.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn doug.api:app --host 0.0.0.0 --port ${PORT}"]
