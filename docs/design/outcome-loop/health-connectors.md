# Repo health narrative + observability connector contract

**Status:** captured 2026-08-01 — explanatory / future lane. **Not** a v1 commitment.
**Does not reopen** design-lock or A1. Extends the outcome loop with *inbound*
runtime signals; does not create an observability product.
**Mirror (backup):** `workspace/research/health-connectors.md` — keep in sync if edited.
**Related:** `workspace/IDEAS.md` § 2026-08-01 · [`distillation-shape.md`](distillation-shape.md) ·
THESIS §5/§11 · `experience.md` scoreboard honesty.

---

## Product role (one sentence)

Doug stays a **code/repo health instrument**: whether the change stream is getting
safer or riskier, **why**, and **what happened** — using git outcomes first, and
optional connectors to Datadog / Grafana / Sentry as *label enrichment*, never as
a metrics platform.

**Non-goal:** become Datadog (dashboards, alerting, APM, log search).

---

## The health narrative

Buyer question (Act II+):

> Is this repo getting better or worse under agent load — and what drove the change?

```
  ┌─────────────────────────────────────────────────────────────────┐
  │  REPO HEALTH (window: 14d / 60d / quarter)                      │
  │                                                                 │
  │  code side (always)          runtime side (if connector on)     │
  │  ─────────────────           ──────────────────────────────     │
  │  cleared-band miss rate      regressions joined to PRs/deploys  │
  │  flagged capture / density   pages / SLO burns with PR links    │
  │  top rule / path drivers     "cleared but paged" audit hits     │
  │  agent vs human split        deploy markers ↔ merge shas        │
  │                                                                 │
  │  Narrative (example):                                           │
  │  "Cleared-band density 0.80× → 0.55× base over 6 weeks.         │
  │   Drivers: fewer auth-path PRs without tests; migration+boundary│
  │   rule promoted. Runtime: checkout error-rate stable; 1 cleared │
  │   PR linked to Sentry issue-group (audit sample)."              │
  └─────────────────────────────────────────────────────────────────┘
```

Honesty rules (same as scoreboard):
- Numbers appear with **n** and window, or not at all.
- Runtime joins are a **separate instrument** from git-revert adjudication —
  never silently averaged into the published miss rate until a pre-registered
  promotion bar says they may.
- Empty connector = git-only narrative; never invent runtime causality.
- Narrative bullets are generated from **structured fields**; no free-form LLM
  as source of truth.

### Where it shows up (UX)

| Surface | Role |
|---|---|
| Public / dogfood scoreboard | Add a “health” strip under calibration counters — code rates always; runtime line only if connector on |
| `GET /v1/repos/{id}/health` | Machine form of `repo_health` (below); same honesty fields |
| Check run | **Does not** grow a health essay — stays verdict + receipt; maybe one optional “health ↓ this window” link later |
| Garden / underwriter | Consumers of joined labels — not the primary UX |

---

## System shape — inbound only

```
  Datadog / Grafana / Sentry / (later: pager)
           │
           │  thin connector (OAuth / API token, per installation)
           │  pulls: deploy markers, incident/monitor fires,
           │         issue↔release/PR links, service tags
           │  never: full metric warehouse, alert routing, viz
           ▼
  ┌─────────────────────────────────────┐
  │  doug-ledger                        │
  │  runtime_events (append-only)       │
  │    installation_id, source,         │
  │    occurred_at, kind,               │
  │    deploy_sha | pr_number?,         │
  │    service?, severity?,             │
  │    external_id, raw_ref             │
  │                                     │
  │  join: runtime_events ⋈             │
  │        verdicts / outcome_jobs      │
  │        (by sha / pr / release)      │
  └──────────────────┬──────────────────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
   health panel   richer      garden /
   (narrative)    labels      underwriter
```

---

## Connector contract (v0)

### Shared invariants

1. **Pull, don't host.** Store joins and event *pointers*, not time-series.
2. **Per-installation opt-in.** Default off. Dogfood may enable early.
3. **Least privilege.** Read-only scopes; no write to monitors/dashboards.
4. **Join keys (preferred order):** `git sha` → `PR number` → `release/version`
   → time-window heuristic (last resort; labeled `join_confidence=low`).
5. **Tenant boundary.** Runtime payloads never enter the pooled public garden as
   source; only structural observations may raise support counts (§5 spirit).
6. **Failure mode.** Connector down → git-only narrative; check runs and
   published miss rate unaffected.

### Per source

| Source | Ingest | Refuse |
|---|---|---|
| **Sentry** | issue groups linked to release/PR; regression markers; culprit commit | issue triage UI, stack warehouse |
| **Datadog** | deploy events, monitor alerts that fired, service↔repo tag map | metrics browser, logs, alert mgmt |
| **Grafana** | annotations / OnCall links / deploy markers | dashboards, Explore, hosting Loki/Tempo |

### Event kinds (canonical)

```
deploy_marker      — sha or version → env X at t
monitor_fire       — alert/monitor id fired; optional service
incident_open      — incident started
incident_resolve   — closed; duration optional
error_regression   — issue-group rate spike vs baseline (vendor-defined)
```

### `repo_health` record

```
repo_health(
  installation_id, repo_id, window_start, window_end,
  code: {
    cleared_miss_rate, n_cleared, n_flagged,
    density_vs_base, top_drivers[]
  },
  runtime: {                         -- null if no connector
    n_events_joined, n_cleared_but_paged,
    top_joined_services[],
    instrument: "runtime_v0"
  },
  narrative_bullets[]                -- from structured fields only
)
```

---

## Recommended defaults on open questions

Capture decisions for when this is scoped — not binding until a design pass.

| Question | Recommendation | Why |
|---|---|---|
| service↔repo map | Prefer explicit tag `doug.repo=owner/name` (Datadog) / Sentry project link; fallback CODEOWNERS path → service only as `join_confidence=low` | Tags are auditable; heuristics lie |
| “cleared but paged” | First-class **runtime outcome label**, separate column/stream — not a fourth git adjudication state | Keeps miss-rate instrument clean |
| Retention | Keep pointers + join keys 400 days; drop payloads/refs after 90d unless joined to an adjudicated miss | Cost + least data |
| Env filter | **prod-only** default; staging opt-in per connector | Staging noise destroys trust |

---

## Downstream consumers (gated)

| Consumer | Use | Gate |
|---|---|---|
| Health / scoreboard | better/worse + why | git loop live; runtime optional |
| Outcome labels | slow burns git missed | pre-register precision bar before mixing |
| Pattern garden | “fewer pages” evidence tier | survival/outcome bars first (probe #1 FAIL 2026-08-01 — garden still locked) |
| Underwriter shadow | loss ratio × severity | ≥2 quarters adjudicated (IDEAS) |

---

## Sequencing

1. **Now:** git outcome loop (ROADMAP M1–M3). No connector engineering.
2. **After prospective counters:** dogfood **Sentry** connector only (closest to code).
3. **Partner ask or measured slow-burn gap:** Datadog / Grafana deploy + monitor fires.
4. **Never in v1 copy:** “Doug is your observability layer.”

---

## Links

- IDEAS: `workspace/IDEAS.md` § 2026-08-01
- Distillation / MATCH: [`distillation-shape.md`](distillation-shape.md)
- Scoreboard: `experience.md`, `product-spec.md`
