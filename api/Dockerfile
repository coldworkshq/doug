FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
# No BuildKit cache mounts — Cloud Build's default docker builder lacks them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev
COPY . .
RUN uv sync --locked --no-dev

FROM python:3.14-slim-trixie
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
# Cloud Run injects PORT; default matches its convention.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn doug.api:app --host 0.0.0.0 --port ${PORT}"]
