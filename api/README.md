# doug-api

Routing service. LLM diff-reader when `DOUG_READER=1`; deterministic fallback otherwise.

```sh
uv sync                 # install (pins Python 3.14 via uv)
uv run uvicorn doug.api:app --reload   # http://localhost:8000
uv run pytest           # tests
uv run ruff check .     # lint
```

## Endpoints

| Route | What |
|---|---|
| `GET /healthz` | liveness |
| `GET /healthz/queues` | per-lane oldest-pending-age contradiction as a status code — 200 inside the bars, 503 outside; unauthenticated, so an uptime check can watch it from outside the process (#121) |
| `POST /v1/score` | PR metadata in, verdict out (score, band, reasons); pure, no read |
| `POST /v1/score/read` | reader-tier scoring (LLM diff-read when enabled, deterministic fallback otherwise); token-gated, spends money |
| `GET /v1/queue` | review queue — operator token sees everything, a dispensed tenant token sees only its installation |
| `GET /v1/showcase/queue` | the dogfood repo's open PRs, scored; unauthenticated, pinned to `DOUG_SHOWCASE_REPO` and never to a caller's `?repo=` |
| `GET /v1/showcase/scoreboard` | the same repo's publication counters — adjudicated, pending, first due, deep-read meter; `miss_rate` is always null here |
| `GET /v1/prs/{pr_number}/receipt` | one PR's evidentiary record (verdict + governing verdict per merge + findings + adjudication, when it exists); operator-unscoped or tenant token carrying `receipt:read` |
| `GET /v1/runs` | verdict history for the operator console; operator-only |
| `GET /v1/runs/{verdict_id}` | one run end to end; operator-only |
| `POST /v1/installations/token` | mint a tenant API key, proving authority through the caller's own GitHub credential; public, append-only |
| `GET /v1/installations/tokens` | masked key inventory for an installation; org-admin/account-owner GitHub proof required |
| `DELETE /v1/installations/token/{token_id}` | soft-revoke one key; GitHub proof must cover the key's selection |
| `GET /v1/patterns` | per-pattern precision from the findings × outcomes join; operator-only |
| `POST /webhooks/github` | HMAC-verified GitHub webhook receiver; verifies, records and enqueues a review job, then 202s — never reviews inline |

## Layout

- `doug/features.py` — PR metadata → feature vector. Pure, no I/O. The backtest CLI and the deterministic fallback both call this; keep it that way.
- `doug/scoring.py` — features → verdict, as legible weighted rules.
- `doug/fixtures/queue.json` — bundled fixture used by `/v1/queue` and the showcase when the ledger is not configured.

Env, for local dev: `DOUG_THRESHOLD` (default 0.62), `GITHUB_WEBHOOK_SECRET`,
`DOUG_CORS_ORIGINS` — the three in `.env.example`.

The rest of the surface is ~30 vars; these are the ones that change what Doug
*does*, and each is off unless set, so an unset deploy is the quiet one:

| Var | Effect when set |
|---|---|
| `DOUG_READER=1` | the LLM diff-read becomes the scoring path (ADR-0004). Production sets it; a repository can still turn its own deep read off. |
| `DOUG_READER_THRESHOLD` | reader risk points at which Doug asks for a human (default 30). A per-repository setting overrides it (ADR-0013, ADR-0019). |
| `DOUG_VERIFY_INSTALLATIONS` | comma-separated installation IDs that get grounding. An allowlist, not a boolean — unset enables nobody, never everybody (ADR-0017). |
| `DOUG_INTENT_INSTALLATIONS` | same shape, for the experimental intent stream. |
| `DOUG_ATTRIBUTION=1` | runs the post-read hunk-attribution pass (ADR-0015). |
| `DOUG_SHOWCASE_REPO` | the one repo the unauthenticated `/v1/showcase/*` routes serve. Unset ⇒ those routes 404. |

`DOUG_EXAMPLE_PACK_*` gate the evidence lane and are documented in
[`../docs/EXAMPLE_PACK.md`](../docs/EXAMPLE_PACK.md) and the runbook.

## Backtest (Phase 0)

```sh
uv run doug-backtest owner/repo --limit 500 --before 2026-06-15
```

**Labels (default: `--labels git`)** come from a treeless clone
(`git clone --filter=tree:0`) — squash-merge subjects embed PR numbers,
so revert commits resolve to original PRs across *all* history at zero
API cost. The scored set is a contiguous harvest window (no
outcome-dependent injection — that would bias capture@10%). Widen
`--limit` to raise defect n. `--labels api|both` keeps the search-API path.

**Features** are still harvested over the REST API (3 calls/PR, cached
in `.backtest-cache/`). The replay uses the deterministic extract/score
path — the live App's fallback when the reader is off or fails. Report:
capture curve vs size-only and random, plus
per-rule precision.

`--before` matters: young PRs haven't had time to be reverted, so
sampling the newest history deflates the defect rate (right-censoring).
Auth comes from `--token`, `GITHUB_TOKEN`, or `gh auth token`.
