# Architecture: The Outcome Loop

**Companion to:** `design-lock.md` (why each box won), `build-plan.md` (the file:line seams). This is the shape.

Legend — every box is labeled with its state, and the labels are load-bearing:
`[live]` deployed today · `[v1]` this build · `[v1.5]` gated on adjudicated data · `[later]` has a named trigger, not a date.

## System

```
                    ┌──────────────────────────────────────────────────┐
                    │                      GITHUB                      │
                    │    PRs · merges · native reviews · git history   │
                    │    App: dougs-review — installation = tenant     │
                    └─────────┬─────────────────────────▲──────────────┘
                              │                         │
        webhooks (HMAC,       │                         │   THE CUSTOMER SURFACE [v1]
        sha256-pinned) [live] │                         │   one neutral check run "Doug":
          pull_request        │                         │   verdict + receipt content
          pull_request_review │ [v1]                    │   N adjudicated · M pending
          closed && merged ───┼── starts the clock [v1] │   deep reads: 143/200
          installation ───────┼── mints tenant token    │   (never blocks, never comments)
                              ▼                         │
                    ┌─────────────────────────────────────────────────┐
                    │            doug-api · Cloud Run [live]          │
                    │                                                 │
                    │  webhook: verify → enqueue → 202          [v1]  │
                    │    never reviews inline; a merge never          │
                    │    buys a read; redelivery deduped by           │
                    │    UNIQUE(inst, repo, pr, sha) job keys         │
                    │  worker: drain review_jobs                [v1]  │
                    │    FOR UPDATE SKIP LOCKED →                     │
                    │    fetch PR + diff → deep read → verdict        │
                    │  third-party ingest:                      [v1]  │
                    │    pull_request_review → verdict rows           │
                    │    (source='review:<login>', no model call)     │
                    │  api: /v1/queue · /v1/prs/:n/receipt      [v1]  │
                    │    scoped by per-installation token             │
                    └───────┬──────────────────────┬──────────────────┘
                            │                      │
              deep read     │                      │  verdicts · findings · reads
              frozen prompt │                      │  deviations · review_jobs
              spend-capped  ▼                      ▼  outcome_jobs
                    ┌──────────────┐   ┌─────────────────────────────────────┐
                    │    CLAUDE    │   │  doug-ledger · Cloud SQL PG [live]  │
                    │  Anthropic   │   │                                     │
                    │  API today,  │   │  THE PRODUCT IS THIS JOIN:          │
                    │  Vertex is a │   │    verdicts ⋈ outcomes              │
                    │  procurement │   │  keyed on installation/repo IDs,    │
                    │  option      │   │  repo strings display-only    [v1]  │
                    └──────────────┘   │  due_at = the ONLY 14/60-day clock  │
                                       │  denominator = outcome_jobs done    │
                                       └────────▲───────────────┬────────────┘
                                                │               │
                                       outcomes │               │ jobs where
                                       (append- │               │ due_at <= now()
                                       only     │               ▼
                                       events)  │  ┌─────────────────────────────────┐
                    Cloud Scheduler ────────────┴─►│ doug-adjudicator ·              │
                    (daily) [v1]                   │ Cloud Run Job, 2Gi        [v1]  │
                                                   │                                 │
                                                   │ treeless clone → git_labels     │
                                                   │ revert map (the SAME detector   │
                                                   │ the backtest validated) →       │
                                                   │ adjudicate (pure fn) →          │
                                                   │ revert (evidence shas) ·        │
                                                   │ clean (default branch only) ·   │
                                                   │ censored (all else)             │
                                                   └─────────────────────────────────┘

  ┌───────────────────────────────┐    ┌──────────────────────────────────────────┐
  │  doug-web · Cloud Run [live]  │    │  doug-mcp · Cloud Run            [v1.5]  │
  │                               │    │  GATED: ships only when it can answer    │
  │  landing page                 │    │  (adjudicated rows ≥ min-n)              │
  │  public Doug-on-Doug          │    │                                          │
  │  scoreboard (dogfood    [v1]  │    │  same image as doug-api, own service     │
  │  proof — deliberately         │    │  (trust boundary: third-party agents;    │
  │  public, no auth)             │    │  traffic isolated from the 10s webhook   │
  └───────────────▲───────────────┘    │  deadline)                               │
                  │ reads ledger       │                                          │
                  │ (server-side)      │  doug.check → adjudicated history with   │
                                       │  citations, n + provenance inside the    │
  ┌───────────────────────────────┐    │  sentence · AGENTS.md fragment export    │
  │  tenant dashboard    [later]  │    │  (the CUSTOMER commits it — Doug never   │
  │  WorkOS AuthKit, tenancy      │    │  writes to a repo)                       │
  │  spec steps 3-4; trigger:     │    └──────────────────▲───────────────────────┘
  │  >3 tenants or first ask      │                       │ per-installation token
  └───────────────────────────────┘         coding agents, before they type
```

Not in the picture on purpose (all killed in `design-lock.md` until Postgres is measurably
the bottleneck): AlloyDB, BigQuery, Pub/Sub, Cloud Tasks, Agent Runtime, A2A, a rate limiter.

## The loop — one PR's life

```
  opened ─► scored ────────────► merged ──────────► due ─────────────► adjudicated
            │                    │                  │                  │
            verdict row +        outcome_jobs row   day 14 (and 60):   reverted (sha in
            receipt (dated,      per window;        adjudicator        receipt) · survived
            immutable, prompt-   due_at = clock     claims the job     the window ·
            hash + prereg-hash)  starts             (SKIP LOCKED)      censored (honest)
            │                                                          │
            third-party reviews on the same PR ─► verdict rows ────────┤ same clock
                                                                       ▼
                                              scoreboard counters tick (monotone, dated)
                                              ─► published on the pre-committed date,
                                                 good or bad: cleared-band miss rate
                                                 vs the repo's own historical base
```

## Where to split — services, repos, projects

Principles first, because every split has a bill attached:

- **Split a service** on a trust boundary, a failure-isolation need, or a divergent resource
  profile. Never for tidiness — every service is another deploy, another auth surface,
  another thing the 10s webhook deadline can queue behind.
- **Split a repo** on license, data classification, or consumer — never while a shared seam
  is load-bearing. Two seams are load-bearing here and pin the monorepo: the backtest
  replays the *live* `score()` (the whole evidence chain), and doug-mcp/doug-adjudicator
  run the *same image* as doug-api so the pattern math and the revert detector can never
  fork from what was validated.
- **Split a GCP project** on blast radius and data classification, not org-chart aesthetics.
- **One database** until a Postgres table is measurably the bottleneck; pgvector in the same
  DB if semantic retrieval ever earns entry. A second *store* only ever appears for a
  different data classification, not for scale.

What that yields, concretely:

| Unit | Split | When (the trigger) | Why not sooner |
|---|---|---|---|
| doug-api / doug-web | 2 services, one repo | already done | path-filtered deploys already give independent ship cadence |
| doug-adjudicator | Job, same image, same repo | v1 | 2Gi clones + long runs don't fit a 512Mi request-serving service; but its detector must be the api's own `git_labels` |
| review worker | own Cloud Run worker pool | sustained review_jobs depth, or webhook p99 approaching GitHub's ~10s | the in-service drain is fine at design-partner volume; a premature pool doubles deploy surface |
| doug-mcp | own service, same image, same repo | v1.5 ship (adjudicated rows ≥ min-n) | third-party agent clients are a different trust boundary and must never queue in front of ingest — but same repo forever: identical pattern math is the point |
| staging project | second GCP project | tenant #2, or the first deploy-caused incident | gated-traffic deploys (candidate → smoke → promote) cover one-tenant blast radius; ADR-0009's trigger is recorded, not dodged |
| tenant dashboard | stays in doug-web | steps 3-4 (WorkOS), >3 tenants or first ask | it's a consumer of the same API; no boundary changes |
| **public garden** | **own repo + own GCP project + own store** | its own design pass, after the private garden earns the word "pattern" | this is the one *true* repo split: a cross-tenant, permissively-licensed public corpus with attribution machinery is a different data classification and legal posture — it must be structurally incapable of touching the tenant ledger (research rationales quote customer source; the lock bans filtering them outward) |
| OSS artifacts (CLI, GitHub Action, MCP client helper) | own repo(s) | the day one ships under Apache/MIT for distribution | FSL-1.1 core and permissive client artifacts shouldn't share a license boundary; until then the CLI lives in `api/` |
| marketing site | gh-pages branch (today) | own repo only if non-engineers need write access | it's copy, not code |

The through-line: **almost everything stays together, and the exceptions are boundaries of
trust or law, not of code size.** The monorepo is not a phase — it is what keeps the published
number and the validated instrument provably the same thing.
