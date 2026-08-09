<h1 align="center">Doug</h1>

<p align="center"><em>62 open. 5 need you.</em></p>

---

Most pull requests don't need a human. Doug works out which ones do.

Every AI code reviewer on the market runs a language model over every diff. That makes their cost scale with the exact thing coding agents are inflating, and it still leaves a person reading bot comments on 100% of pull requests. Doug inverts it: cheap deterministic analysis scores every PR, most are cleared, and only the small fraction that carries real risk gets a deep look.

Doug is a Saint Bernard. The breed has had one job for three centuries: find the traveler buried in the snow, and bring help. That's the product — find the pull request that's in trouble, and bring a human. Doug doesn't dig you out himself, and he doesn't bark at every hiker on the trail.

## Three rules

**Route, never block.** The PR proceeds either way. Doug only decides who has to look. Tools that block get disabled.

**Never write code, never open a PR.** The moment it authors, it owns the authorship.

**Publish the miss rate.** Every quarter, including the incidents that came from PRs it cleared. A gate that never publishes its errors is a marketing claim; one that does can survive being wrong.

## What it looks at

Routing is deterministic — no model invocation, fractions of a cent per PR:

- Boundary crossings against a declared or harvested architecture
- Schema migrations landing in the same diff as a boundary or auth change
- Dependency major bumps where the tests mock the dependency (green CI is anti-signal here)
- Approval latency relative to diff size
- Test delta disproportionate to the change
- Cross-repo blast radius from the org lockfile and config graph
- Authorship (agent or human) against how recently a human touched the module

Diff size is deliberately de-weighted. It predicts poorly once the rest are controlled for.

## Repo layout

- `api/` — Python 3.14 + FastAPI, managed with uv. The routing core: `doug/features.py` (PR metadata → feature vector, pure) and `doug/scoring.py` (features → verdict, as named weighted rules). `GET /v1/queue` serves a scored demo queue; `POST /webhooks/github` is an HMAC-verified stub until the Live Gate phase.
- `web/` — Next.js 16 + Tailwind 4 + shadcn/ui. Landing page and `/queue`, the scored review queue. Reads the live API when it's up, falls back to a bundled fixture when it isn't.
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
```

## Status

**Pre-build.** The scoring rules exist and are tested, but they encode priors, not measurements — no backtest has validated the weights yet.

The whole idea rests on one claim: that a small set of cheaply-computable structural features captures a disproportionate share of bad changes. If flagging 10% of PRs catches 40% of the trouble instead of 70%, this is an expensive random sampler and it should be abandoned.

That's testable on public data before a service exists — reconstruct the features over historical PRs, label defect-inducing changes via revert anchors, and plot capture rate against flag rate. That measurement comes first. The first shippable thing after it is a CLI that replays your last 90 days and shows you which PRs it would have flagged, overlaid with the reverts you actually had.

## License

[FSL-1.1-ALv2](LICENSE.md) — Functional Source License. Read it, run it internally, modify it, learn from it. The one thing you can't do is ship it as a competing commercial product or service. It converts to Apache-2.0 automatically two years after each version is published.

Source-available rather than open source, and deliberately so: the point is freedom without free-riding, not enclosure.
