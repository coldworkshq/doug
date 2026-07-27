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
