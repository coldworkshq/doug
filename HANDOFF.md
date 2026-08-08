# HANDOFF — doug

State:    spec — console Phase 2a (health strip + failure surface) design is
          written and committed. Not yet planned, no code.
          Worktree `.claude/worktrees/console-next`, branch
          `worktree-console-next`, based on main `91b5e8b` (= origin/main,
          #69). No open PRs at branch time. Console baseline verified green:
          58/58 `node --test` in console/.
          THIS FILE COVERS THE CONSOLE LANE ONLY. The authoritative M3
          tracker is repo/HANDOFF.md + docs/design/outcome-loop/ROADMAP.md.
          M3 Task 7 (production 60-day catch-up) is untouched by this lane
          and remains the critical path there.

Next:     Invoke writing-plans against
          docs/superpowers/specs/2026-08-07-console-health-failure-surface-design.md
          and produce the TDD task plan. Andrew is reviewing the spec first.

Blockers: none.

Decisions this session:
- Next console iteration = health strip + failure surface (Phase 2a) — Andrew
  picked it over Evidence, Phase 4 token exposure, and render-test/master-
  detail debt. Timely: the M3 adjudicator's first real due clock is ~Aug 16
  and that lane is invisible today — rejected: the other three, deferred not
  dropped.
- Health strip + separate /jobs page; Runs stays verdict-keyed — rejected:
  flipping the spine to job-keyed (score/band/coverage/findings go null on
  every non-done row, which is the exact "UI claiming to know something it
  does not" class that produced 12 of Phase 1's defects); strip-only (no
  drill-down, still reach for psql); failure band above Runs (no home for the
  outcome lane).
- Read-only, no requeue — rejected: mutation (fencing contract vs live
  claims + idempotency + first console write path ~doubles the build);
  copyable remediation commands (doc-drift risk).
- Two endpoints /v1/health (aggregates only) + /v1/jobs (rows only) —
  rejected: one combined endpoint (strip pays row cost every page load, rows
  get no independent pagination, a slow row query blanks the strip that
  exists to say something is wrong); a job-keyed view mode on /v1/runs (the
  merged table in API costume).
- Strip is GLOBAL, never scoped; /jobs is scoped like Runs — a scope filter
  that can hide a fire in another tenant is an anti-feature on this surface.
  Dissolves the strip-vs-table disagreement instead of documenting it.
- 26h adjudicator grace + 15min pending threshold live in lib/health.ts as
  named tested constants, NOT in the API — both are statements about
  schedules/kick frequency, not about stored values. The strip states each
  assumption in words so it stays falsifiable.

VERIFICATION FINDINGS (Andrew asked for a check before committing; these
          five came out of reading ingest.py / outcome_queue.py / worker.py
          and TWO were defects in the design as presented — do not re-derive):
- `ingest.fail()` below cap sets `enqueued_at = now` (deliberate: retry goes
  to the BACK of the queue instead of burning all 3 attempts in one pass).
  So MIN(enqueued_at) WHERE status='pending' reports a twice-failed job as
  FRESH — blind to exactly the jobs in trouble. Fix: oldest_pending_at is
  restricted to attempts=0; retrying rows get their own oldest_retry_at.
  Never blend them back into one MIN.
- `ingest.complete()` takes verdict_id: int | None — "a skipped PR is
  finished, not failed". So `done` splits into done-with-verdict and
  done-skipped, BOTH green. Unlinkable != unhealthy. Third silent outcome:
  Doug ran, declined, left no trace in the console.
- THE LANES HAVE DIFFERENT CONSTANTS. ingest: STALL_LEASE_SECONDS=900,
  max_attempts=3. outcome_queue: STALL_LEASE_SECONDS=7200, MAX_ATTEMPTS=10.
  A single top-level stall_lease_seconds would flag a healthy 20-min outcome
  claim as stalled and render attempts as 4/3 on a lane whose cap is 10.
  Both constants go PER LANE in the payload.
- `outcome_queue._fail_job()` does NOT touch due_at on retry, so a retrying
  outcome job stays correctly overdue. The lane asymmetry is real and
  grounded — only the review lane has the enqueued_at reset problem.
- No existing audit/status CLI to mirror (only findings_log + review have
  argparse entrypoints). `worker.drain()` does call `ingest.reclaim_stalled()`
  before its first claim, which is what makes the AMBER self-heal
  classification true rather than hopeful.

GROUNDING FACTS (cost real time to find):
- The health strip ALREADY EXISTS in console/components/shell.tsx as a
  ghosted placeholder — cells `running · pending · failed 24h · clocks due`,
  every value an em dash, no hue, with a comment reserving that layout for
  Phase 2. Four cells cannot carry the honest picture; spec keeps the visual
  treatment and widens the cell set to six.
- `Shell`'s `active` prop is a single-member union `"runs"` — adding /jobs
  widens it to `"runs" | "jobs"`. Nav has ghosted Repos/Evidence tabs, no
  Jobs tab.
- api.py has ONLY /v1/runs and /v1/runs/{id} for the console. /v1/repos,
  /v1/health, /v1/evidence/*, /v1/showcase/queue do NOT exist.
- Zero page-level tests in console/ — lib/*.test.mjs covers pure transforms
  only. This spec routes AROUND that debt (all lying-risk in a pure
  lib/health.ts) rather than closing it; render-test infra stays its own item.
- Three partial indexes from migration 3 already serve most health
  aggregates. Two honest caveats recorded in the spec: adding attempts=0 to
  the pending predicate makes it no longer index-only, and
  `outcome_jobs.status` has NO index at all (review_jobs.status does), so the
  outcome failed-count seq-scans.
- The Phase 1 design doc overclaims on TWO points, corrected by this spec:
  its /v1/health lists `installations.reconciled_at` (column does not exist —
  MT3/migration 8, unstarted), and its Phase 2 row bundles the health strip
  with /v1/repos (now split: 2a = health/failures, 2b = repos).
- STALE NOTE CLEARED: the workspace HANDOFF warns that
  docs/design/session-lane/design.md is untracked and at risk. It is
  COMMITTED on branch `read-budget-routing`. Nothing is at risk.

Pointers: branch `worktree-console-next` @ worktree
          `.claude/worktrees/console-next`
          · spec: docs/superpowers/specs/
            2026-08-07-console-health-failure-surface-design.md
          · Phase 1 design being corrected: docs/superpowers/specs/
            2026-08-06-doug-console-design.md
          · code read for verification: api/doug/ingest.py (fail/complete/
            supersede/reclaim_stalled), api/doug/outcome_queue.py
            (_fail_job/claim_repository, MAX_ATTEMPTS, STALL_LEASE_SECONDS),
            api/doug/worker.py (drain), api/doug/migrations.py (migration 3
            partial indexes), console/components/shell.tsx (ghosted strip)
