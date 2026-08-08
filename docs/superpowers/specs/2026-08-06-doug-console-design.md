# doug-console — operator console design

**Date:** 2026-08-06
**Status:** design approved, implementation not started
**Branch:** `console-design`

## Problem

Doug is being dogfooded daily and its operator cannot answer four questions
from any surface it ships:

1. **What did Doug actually do with this PR?** The `review_jobs` row, the
   read coverage, the tier that produced the score, the model and prompt
   hash, the check run, the outcome clock — none of it is rendered anywhere.
   Answering requires a psql session.
2. **What is happening per repo?** `latest_reviews` selects `verdicts.repo`,
   but the `QueueItem` wire model drops it and `PRMetadata` has no repo
   field. Scoping happens server-side through the `DOUG_QUEUE_REPO`
   environment variable: one repo, or every repo mixed together with no way
   to tell them apart. Doug now has two real installations (`drewjst`
   150424894, `lemahq` 151500529) and the UI knows about neither.
3. **What are the metrics?** `reads` (coverage), `review_jobs` (throughput,
   failures), `verdicts.tier`/`model`/`prompt_hash`, `outcomes`,
   `installations` — all populated, none served, none rendered.
4. **Is Doug improving?** `docs/findings-log.jsonl` holds 25 adjudicated
   rows and is read by nothing but a CLI.

A secondary problem, found while grounding this design: `doug-web` is
deployed `--allow-unauthenticated` (`api/deploy/gcp.sh:266`) while holding
the unscoped operator credential `DOUG_API_TOKEN` as a secret. The only
thing bounding what that public service will render is
`DOUG_QUEUE_REPO=drewjst/doug` — a public repo. A console spanning both
installations cannot ship on that URL, and the existing arrangement is one
environment-variable typo away from serving the whole ledger.

## Non-goals

- **The M6 tenant dashboard.** That track is gated on ">3 tenants or first
  tenant ask" and needs WorkOS login. Neither trigger has fired. This
  console is operator-only and adds no authentication code. Tenant scoping
  is a filter here; when M6 fires, that filter becomes an auth boundary
  rather than a rewrite.
- **Any change to the reader prompt.** ADR-0002 froze it. This design reads
  `prompt_hash`; it never writes one.
- **New capture for tenant-repo finding disposition.** See "Fixed" under
  Evidence — the gap is named and rendered, not filled.

## Decision 1 — two services, split by audience

### `doug-web` (stays public)

Keeps `/` and `/queue`. The public queue is **not** moved into the console:
Doug reviewing Doug in the open is ADR-0008's whole point, the landing
page's two primary CTAs target it, and it is a brand asset. It stays pinned
to the showcase repo, which is what `DOUG_QUEUE_REPO` already enforces.

It stops holding the operator token. A new unauthenticated
`GET /v1/showcase/queue` serves only the repo named by `DOUG_SHOWCASE_REPO`
on the API side, and `--set-secrets DOUG_API_TOKEN=...` comes off the web
service. The bound then lives in the API, deliberately public by design,
instead of in a deployment flag on an internet-facing service.

`/compare` is deleted. It renders app-path versus CI-path dual runs, and
roadmap Task 9 (PR #54) retires the CI review path, which makes the page
meaningless. The deletion should ride with that merge.

### `doug-console` (new)

A new Cloud Run service, `--no-allow-unauthenticated`, IAM-bound to the
operator, with its own service account. Reached through
`gcloud run services proxy` or an authenticated browser session.

It is a **separate Next application** under `repo/console/`, not new routes
in `repo/web/`. Serving a public surface and a gated surface from one build
means a single environment variable separates them, which is the same
failure mode this design exists to close. The cost is duplicating six
generated shadcn primitives and the theme tokens; the benefit is that the
blast radius of a console bug cannot reach the public site.

## Decision 2 — run-first information architecture

The review is the primary object. Repo and tenant are a global filter
present in the chrome on every page, not a section — with two installations
a repo-first top level would be nearly empty and would put two clicks in
front of the forensic view, which is the acute pain.

### Chrome (persistent)

Brand, tenant/repo switcher, health strip. The switcher drives every page
through URL parameters so any view is bookmarkable and shareable. Health is
a strip rather than a page because it is wanted ambiently, not visited.

### `/` — Runs

A dense table of verdict **history**: score, repo/PR and title, tier, read
coverage percentage (marked when under threshold), findings by severity,
outcome state, age, job status. Filters on tenant, repo, band, tier,
`coverage<X`, and has-error; all filter state lives in the URL.

This is history, not `latest_reviews`. That function returns one row per
`(repo, pr)`; a PR scored three times across three pushes is three runs and
all three must be visible.

### `/runs/[verdict_id]` — run forensics

The core deliverable. Eight blocks:

1. **Header** — repo/PR, score, band, threshold, `scored_at`, and a
   `source` badge (`live` / `replay` / `research`).
2. **Timeline** — webhook received → `review_jobs` enqueued, started,
   finished, with `attempts`, `claim_generation`, and `error` → read →
   verdict written → check run posted → outcome jobs scheduled. Real
   timestamps and durations.
3. **What the reader was given** — `files_sent` over `changed_files`,
   `sent_chars` over `diff_chars`, `file_cut` (the file where the budget
   ran out), `files_unseen`, and `files_dropped` (binary or oversize, which
   never had a chance to be read at all), each with its share of the diff.

   **Unseen files are not marked "sensitive."** The obvious move is to flag
   `files_unseen` entries that `features._is_sensitive` classifies as
   sensitive. The read-budget-routing spec (2026-08-06) measured that
   predicate against the exact PRs that motivated this work and found it
   fires on **zero** of them — `tenancy.py`, `keyformat.py` and
   `migrations.py` are all `sensitive=False`, because `_SENSITIVE_NAME_RE`
   matches `secret|auth|authn|authz|rbac|oauth|credential|token` and none of
   those names contain one. Marking on a predicate that is inert on the
   motivating case would decorate the page with a signal that does not fire
   when it matters. Once `read_order()` lands and the API can report the
   tier it assigned each file (code / tests / prose), the ruler marks by
   that instead — a classification the routing actually uses.

   This block is what makes the live
   read-budget defect legible: three consecutive reviews of the tenancy
   work never read `tenancy.py` at 17–19% coverage, cut by file order.
4. **The read** — tier, model, `risk_score`, rationale, and `prompt_hash`
   checked against the frozen ADR-0002 hash.
5. **Findings** — rule, label, severity or weight, file. Reader findings
   render distinctly from deterministic rules; reader findings always carry
   weight 0 and a severity, deterministic rules carry a weight and no
   severity.
6. **Deviations** — a separate stream per ADR-0007, never blended into
   findings. Rows with `kind="none"` are the "read happened, found nothing"
   storage marker and are never displayed.
7. **Outcome** — the 14-day and 60-day clocks with their dates, and the
   graded result once it lands.
8. **Disposition** — `verdict` (real / disproved / adjacent), `changed`,
   and `settled_by`, joined from `findings-log.jsonl` where a row exists
   for that PR and rule.

### `/repos`

Rows grouped by installation. Per repo: review count, flag rate, tier mix,
median coverage, outcome tally, last review, installation state
(active / suspended / deleted), and repo state (active / removed). Clicking
a repo opens Runs filtered to it.

### `/evidence`

Four panels, each carrying its own N and provenance:

- **Judgment** — findings-log rates by layer (`doug` / `agent-reviewer`)
  and by rule. Prospective rows only; backfill rows are quarantined from
  every rate, exactly as `findings_log` already enforces.
- **Coverage** — read-percentage distribution, count under 30%,
  most-frequently-unseen paths, `file_cut` frequency by file. This is the
  evidence base for read-budget routing.
- **Outcomes** — verdicts graded at 14 and 60 days, with N and censoring
  rate. Near zero today, and rendered as such.
- **Fixed** — the `changed` field from findings-log, which answers "did the
  finding get fixed" for `drewjst/doug`. For tenant repos nothing links a
  finding to a merge, so this panel renders an explicit "no capture yet"
  naming what would be required. It never renders a zero.

## Decision 3 — API surface

Operator-token only, behind the existing `_operator_only` gate that
`/v1/comparisons` uses:

| Endpoint | Notes |
|---|---|
| `GET /v1/runs` | Paginated verdict history with `repo`, `installation_id`, `tier`, coverage summary, finding counts, outcome state. New query — `latest_reviews` is the wrong shape and drops `repo`. |
| `GET /v1/runs/{verdict_id}` | `find_verdict_by_id` + `_verdict_bundle`, plus the fields that bundle currently omits: `model`, `prompt_hash`, `risk_score`, `rationale`, `scored_at`, `source`, `head_sha`, `repo`, `installation_id`. Plus the `review_jobs` row and the `outcome_jobs` / `outcomes` rows. |
| `GET /v1/repos` | `installations` ⋈ `installation_repos` ⋈ per-repo verdict rollups. |
| `GET /v1/health` | Job counts by status, oldest pending age, 24-hour failures, outcome clocks due. (AMENDED 2026-08-07: the original row also listed per-installation `reconciled_at`. That column does not exist — it is MT3 / migration 8, unstarted — so it was never buildable as written. See `2026-08-07-console-health-failure-surface-design.md`.) |
| `GET /v1/evidence/findings-log` | `findings_log.rates()` over the JSONL, served rather than imported at build time because it changes with every PR. |
| `GET /v1/evidence/coverage` | Read-percentage distribution, unseen-path frequency, `file_cut` frequency. |

Public and unauthenticated: `GET /v1/showcase/queue`, serving only the repo
named by `DOUG_SHOWCASE_REPO`, returning 404 when that variable is unset.

`_verdict_bundle` (`api/doug/store.py:1054`) already assembles findings,
deviations, and coverage for one verdict, so the forensic endpoint is
mostly composition rather than new SQL.

**Coverage denominator:** `files_sent` is divided by `pr_meta.changed_files`
— GitHub's own changed-file count — never by `len(files)`. `files` is the
paginated list actually fetched and can be short of the true count, which
would silently inflate every coverage figure on exactly the large PRs where
coverage matters most. `changed_files` is `None` on rows predating its
capture; those render as "denominator unknown", not as 100%.

## Decision 4 — honesty rules

These are load-bearing behavior, not presentation preferences.

1. **The console never falls back to a fixture.** doug-web's fixture
   fallback is correct for a marketing page that must survive an API
   outage. On an operator console, invented data is strictly worse than an
   error: the whole purpose is to answer "what did Doug do", and a
   plausible wrong answer defeats it. API unreachable renders an explicit
   failure state.
2. **No rate without its denominator.** Every rate carries N.
3. **Empty is not zero.** "No outcomes graded yet" and "0% miss rate" must
   be visually distinct and can never be confused.
4. **The `verdicts.source` quarantine holds in the UI.** `replay` and
   `research` rows are excluded from every rate and badged wherever shown.
5. **`prompt_hash` drift is surfaced.** Historical App-path reader verdicts
   carry NULL because the worker path never stamped it. Those render as
   "unstamped", never as a match.

## Decision 5 — visual direction

Light-first, on the existing brand tokens: paper `#fcfcfa`, `--iridescent
#d1571e`, `--flag #c93a2b`, `--clear #177a50`, `--sheen #5b6470`,
Bricolage for headings, mono for all data. The `.dark` block stays
available. `.glass` does not come to the console — it is a dark-only
treatment, and it is why `/queue` currently reads as off-brand against the
light landing page.

The console needs a denser scale than the marketing site: tabular-figure
mono numerals, roughly 34px rows, tighter radius, hairline borders, and the
accent orange used sparingly as emphasis rather than as chrome.

**Palette constraint.** Red carries two unrelated meanings in this console:
"this PR needs a human" (band) and "Doug itself failed" (job error, hash
drift, missed revert). These must never be distinguishable by color alone —
each needs an icon or a label carrying the same information. Coverage is a
continuous quantity and is not forced onto the flag/clear pair. The
`dataviz` skill governs the palette and chart specifications; `recharts`
and `components/ui/chart.tsx` already exist and are reused.

## Decision 6 — phasing

Each phase is independently shippable and independently useful, and **each
phase gets its own implementation plan**. This document is the design for
all four; it is not scoped as a single plan.

| Phase | Ships | Closes |
|---|---|---|
| 1 | `/v1/runs`, `/v1/runs/{id}`, console shell, Runs list, run forensics | "I can't understand the run" |
| 2a | `/v1/health`, `/v1/jobs`, health strip, Jobs page | "is it healthy", "is Doug failing on anything" |
| 2b | `/v1/repos`, Repos page | "per repos" |
| 3 | `/v1/evidence/*`, Evidence page | "see improvements", all four tracks |
| 4 | `/v1/showcase/queue`, doug-web token removal, light-theme the public queue, delete `/compare` | the public-service token exposure |

Phase 1 alone answers the acute complaint. Phase 4 is small and may be
resequenced first if the token exposure is judged more urgent than the
ergonomics; its `/compare` deletion should ride with PR #54 regardless.

## Testing

The console's pure transforms are tested with the existing
`lib/*.test.mjs` pattern (`node --test`). API additions join the existing
pytest suite.

Tests encode why the behavior matters, not just what it does:

- A `replay` or `research` row leaking into a prospective rate fails a test.
- Coverage computed from `len(files)` rather than `changed_files` fails a
  test, with a fixture whose `files` list is deliberately shorter than
  `changed_files`.
- A `changed_files` of `None` rendering as a percentage rather than
  "denominator unknown" fails a test.
- The console rendering any number while the API is unreachable fails a
  test.
- A backfill findings-log row counted in a published rate fails a test.
- A `deviations` row with `kind="none"` appearing in the rendered
  deviation list fails a test.

## Open questions

None blocking implementation. Two items are noted for the plan rather than
the design:

- Whether Phase 4 is resequenced ahead of Phase 1 is an operator call on
  urgency, not a design dependency; the phases do not share code.
- The `prompt_hash` backfill for historical App-path verdicts (ADR-0002
  froze the prompt, so the era hash is knowable) is tracked on PR #54 and
  is not part of this work. Until it runs, those rows render "unstamped".
