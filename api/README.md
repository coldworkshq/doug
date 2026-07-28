# magpie-api

Deterministic routing service. No model reads a diff unless the score says it should.

```sh
uv sync                 # install (pins Python 3.14 via uv)
uv run uvicorn magpie.api:app --reload   # http://localhost:8000
uv run pytest           # tests
uv run ruff check .     # lint
```

## Endpoints

| Route | What |
|---|---|
| `GET /healthz` | liveness |
| `POST /v1/score` | PR metadata in, verdict out (score, band, reasons) |
| `GET /v1/queue` | scored demo queue from fixtures, riskiest first; `?threshold=` to move the line |
| `POST /webhooks/github` | HMAC-verified receiver; parses nothing yet (Phase 2) |

## Layout

- `magpie/features.py` — PR metadata → feature vector. Pure, no I/O. The backtest CLI and the webhook both call this; keep it that way.
- `magpie/scoring.py` — features → verdict, as legible weighted rules.
- `magpie/fixtures/queue.json` — demo queue used by `/v1/queue` until the Live Gate exists.

Env: `MAGPIE_THRESHOLD` (default 0.62), `GITHUB_WEBHOOK_SECRET`, `MAGPIE_CORS_ORIGINS`.

## Backtest (Phase 0)

```sh
uv run magpie-backtest owner/repo --limit 500 --before 2026-06-15
```

**Labels (default: `--labels git`)** come from a treeless clone
(`git clone --filter=tree:0`) — squash-merge subjects embed PR numbers,
so revert commits resolve to original PRs across *all* history at zero
API cost. The scored set is a contiguous harvest window (no
outcome-dependent injection — that would bias capture@10%). Widen
`--limit` to raise defect n. `--labels api|both` keeps the search-API path.

**Features** are still harvested over the REST API (3 calls/PR, cached
in `.backtest-cache/`). The replay uses the same extract/score path the
webhook will. Report: capture curve vs size-only and random, plus
per-rule precision.

`--before` matters: young PRs haven't had time to be reverted, so
sampling the newest history deflates the defect rate (right-censoring).
Auth comes from `--token`, `GITHUB_TOKEN`, or `gh auth token`.
