<h1 align="center">Doug</h1>

<p align="center"><em>Most pull requests don't need a human.</em></p>

---

Doug works out which ones do.

Every AI code reviewer on the market runs a language model over every diff. That makes their cost scale with the exact thing coding agents are inflating, and it still leaves a person reading bot comments on 100% of pull requests. Doug inverts the *attention*: most PRs clear, and only the small fraction that carries real risk gets a human. When the reader is on, that routing verdict still comes from an LLM reading the diff — the deterministic rules are the labeled fallback, not a claim that production is model-free.

Doug is a Saint Bernard. The breed has had one job for three centuries: find the traveler buried in the snow, and bring help. That's the product — find the pull request that's in trouble, and bring a human. Doug doesn't dig you out himself, and he doesn't bark at every hiker on the trail.

## Three rules

**Route, never block.** The PR proceeds either way. Doug only decides who has to look. Tools that block get disabled.

**Never write code, never open a PR.** The moment it authors, it owns the authorship.

**Publish the miss rate.** Every quarter, including the incidents that came from PRs it cleared. A gate that never publishes its errors is a marketing claim; one that does can survive being wrong. The scoreboard is live; the miss-rate number is not yet — `miss_rate` stays null until enough adjudications exist.

## What it looks at

Live scoring (production sets `DOUG_READER=1`) is an LLM diff-read, unless a repository turns its deep read off on `/dashboard/settings` — that setting narrows, never widens. The deterministic fallback looks at cheap structural signals, including:

- Sensitive paths (auth, billing, security) and schema migrations in the same diff
- Runtime dependency bumps with no test delta
- Fast single-reviewer approval on a large diff
- Sizeable changes with no test files touched
- Bot / agent authorship
- Static hotspot path segments (historically high-revert areas)

Diff size is deliberately de-weighted. It predicts poorly once the rest are controlled for. Rolling-window hotspot *learning* and several shape rules exist in the backtest CLI only, not in the live App path.

## Repo layout

- `api/` — Python 3.14 + FastAPI, managed with uv. `doug/reader.py` (LLM scoring when enabled), `doug/worker.py` (drain + check run), `doug/check_run.py`, `doug/features.py` + `doug/scoring.py` (deterministic fallback). `POST /webhooks/github` verifies, records, and enqueues a review job, then 202s. `GET /v1/queue` is the token-gated ledger queue; `GET /v1/showcase/queue` and `GET /v1/showcase/scoreboard` are the public dogfood surfaces.
- `web/` — Next.js 16 + Tailwind 4 + shadcn/ui. Landing, `/queue`, `/docs`, `/scoreboard`, WorkOS sign-in, and the signed-in `/dashboard` (ledger, repositories, and `/dashboard/settings` — flag line, PR comment, deep read, per repository). Public pages fetch `/v1/showcase/*` when the API is up, and fall back to a bundled fixture when it isn't.
- `console/` — Operator console (Next.js). Shares the root npm workspaces lockfile with `web/`.

```sh
make dev    # API on :8000, web on :3000
make test   # API + Node workspace tests
make lint   # ruff + eslint
npm ci      # install web + console from the root lockfile
```

Services ship Dockerfiles built for Cloud Run (respect `PORT`, scale to zero). The API still uses an app-dir build context; Node apps must be built from the monorepo root because of npm workspaces:

```sh
gcloud run deploy doug-api --source api
docker build -f web/Dockerfile -t doug-web .
docker build -f console/Dockerfile -t doug-console .
# Prod path: api/deploy/gcp.sh web|console builds via Cloud Build, then
# gcloud run deploy --image …
#
# Before the first Node image deploy, create the Artifact Registry repo
# (or re-run setup): PROJECT=doug-prod0 ./api/deploy/gcp.sh setup
#
# console is IAM-gated and not in CI — after a root lockfile / Dockerfile
# change, rebuild it with: PROJECT=doug-prod0 ./api/deploy/gcp.sh console
```

## Status

**Early preview, dogfooding on this repository.** Doug runs as a GitHub App (`dougs-review`): webhook ingest, a durable worker, a neutral check run on every PR (ADR-0010). Merge to `main` deploys API + web (ADR-0009). It is not a self-serve product for other orgs yet.

The LLM reader is the scoring path when enabled (ADR-0004). The 2026-07 probe's AUC 0.69 / 0.67 is that probe, not a measurement of the shipped 100k-char reader (ADR-0012). Deterministic rule weights remain priors.

**Not yet:** outside installs, first published miss rate, Pattern Garden MCP server.

The self-serve measurement tool is still `doug-backtest`: replay a public repo's merged history, label defect-inducing changes via revert anchors, and plot capture against a size-only baseline.

## License

[FSL-1.1-ALv2](LICENSE.md) — Functional Source License. Read it, run it internally, modify it, learn from it. The one thing you can't do is ship it as a competing commercial product or service. It converts to Apache-2.0 automatically two years after each version is published.

Source-available rather than open source, and deliberately so: the point is freedom without free-riding, not enclosure.
