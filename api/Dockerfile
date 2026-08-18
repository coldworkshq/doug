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
# git is a RUNTIME dependency of this image, not a build tool. The API
# service never shells out, but doug-adjudicator runs `python -m
# doug.outcome_worker` from this very image and its drain path calls
# git_labels.clone_treeless -> `git clone --filter=tree:0` / `git fetch` /
# `git log`. Without it the Job dies with FileNotFoundError: 'git' the first
# time a repository has due work — which is exactly what happened on
# 2026-08-18, because every execution before that one had nothing due and
# returned before reaching the clone.
# Unpinned against the pinned base on purpose: pinning a Debian package
# version here rots into an unbuildable image at the next point release, and
# git moving within trixie is a smaller risk than an image that cannot be
# rebuilt during an incident.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
# Cloud Run injects PORT; default matches its convention.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn doug.api:app --host 0.0.0.0 --port ${PORT}"]
