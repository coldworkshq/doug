# HANDOFF — doug

*** NEW LANE — MARKETING SITE HEADER + HOSTED /docs (2026-08-11/12). Separate
    from both lanes below (console, and the WorkOS front-door auth lane) —
    touches only web/, cosmetic + one new public route tree, no API/auth
    changes. NOTE: the front-door lane's top-of-file status right below this
    (PHASE 0 IN REVIEW, Phase 1 gated) reads stale against what's actually on
    main today — web/app/dashboard, /install/*, /auth/* all already exist and
    PR #90 ("dashboard honesty") is in recent git log — so that section
    predates several merges. Not reconciled here; out of scope for this lane,
    flagging so it isn't trusted at face value.
    State: REVIEW. Built and fully verified (web: tsc clean, `npm run lint`
    clean, `npm test` 72/72 — was 62, +10 new (lib/docs-nav.test.mjs) —
    `npm run build` green, all 11 /docs routes prerender static). Branched,
    committed (6351658), pushed, PR #101 open: github.com/drewjst/doug/pull/101.
    Remember ADR-0009 (merge-to-main deploys) before merging.
    Next: Andrew reviews PR #101. Nothing else blocks it.
    Decisions this session:
    - Extracted the landing page's inline nav into components/site-header.tsx,
      reused as-is on /docs; left /queue and /dashboard alone — both already
      have deliberately different chrome (forced-dark live-badge nav; signed-
      in "forensic ledger" shell) and this component would be the wrong fit —
      rejected: one universal header everywhere.
    - Header is `sticky top-4`, not `fixed` — reads as floating from the first
      frame (sticky enforces the top-4 gap immediately when the element sits
      at the very top of a scrollable area, not only once you've scrolled past
      it) with zero layout-shift risk and no scroll-listener JS — rejected: a
      fixed header with manual top-padding compensation on every page below it.
    - Sign in is the one filled/colored control in the bar; Docs/Queue/GitHub
      and the theme toggle stay low-contrast text until hover — separates it
      by visual weight, not just position — rejected: an outline-only Sign in
      (didn't read as a real CTA next to plain links) and a second solid-black
      pill (competed with the hero's own Get started).
    - /docs is real per-route pages (`/docs/quickstart`, `/docs/cli`, …), not
      a port of the gh-pages site's single-scroll-page-plus-anchors trick —
      matches how Stripe's own docs actually route, gives every topic a real
      shareable URL. One nav tree (lib/docs-nav.ts, tested) drives the
      sidebar, prev/next pager, and the sidebar's title-only filter (matches
      the old site's filter contract exactly — it never indexed body content
      either).
    - Docs content lives as hand-authored TSX + a small shared component kit
      (components/docs/: badge, callout, code-block, params-table, prose,
      docs-two-col, docs-sidebar, docs-pager) — matches this app's existing
      convention (page.tsx already hand-writes its copy as typed consts, no
      CMS/MDX anywhere in web/) — rejected: adding an MDX pipeline for eleven
      pages.
    - Kept Doug's existing tokens/fonts throughout (Bricolage/Geist/Geist
      Mono, panel/glass, the iridescent accent, the dot-grid atmosphere) for
      the "Stripe feel" — it's the STRUCTURE (dense grouped sidebar, sticky
      code-rail beside prose, status badges) that's Stripe-shaped, not the
      palette — rejected: reskinning toward Stripe's actual indigo/white.
      Added one new token, --warn (light #9a6b12 / dark #efa167), for the
      Preview status badge; Available reuses --clear, Planned reuses --sheen
      (its gh-pages value, #5b6470, is already --sheen's exact light value).
    - Code-rail is always-dark regardless of site theme (globals.css
      .code-rail/.code-rail-head, new) — same reasoning already on record for
      .glass: it's a fixed terminal surface, not something that should go
      pale in light mode.
    - Mobile: sidebar falls out of the two-column grid below `lg` and renders
      inline above the article instead of `display:none` — the gh-pages
      source hides it below 900px with, by its own admission, no replacement
      at all. Small, free improvement over the source rather than a faithful
      port of that specific gap.
    - StatusDot renders nothing for a page with no status (Introduction,
      Changelog) even though the gh-pages source gave every sidebar row a dot
      including those two — a stray signal this codebase's own standing rule
      ("don't show a signal you can't back up") argues for dropping, not
      porting. Everything else content-wise is a faithful, numbers-exact port
      — verified against the real gh-pages HTML (saved to scratchpad, not
      this repo), not a paraphrase.
    - Ported /llms.txt too (web/public/llms.txt, static) since it was a real
      linked feature on the source site (its docs topbar fetches and copies
      it), not just styling — "just like our docs" included it. Fixed the
      two hostname-dependent lines (site has no stable custom domain yet per
      the front-door spec's Phase 3 note) to relative /docs; left everything
      else, including the CLI examples' github.com/drewjst/doug clone URL,
      unchanged. Did NOT port the old site's "Copy for LLM" clipboard button,
      only a plain link — smaller surface, same core feature.
    - INCIDENTAL FIX, found via the Next.js dev overlay while visually
      verifying, not asked for: components/theme-toggle.tsx's mount-guard
      comment claimed "resolvedTheme is undefined on the server and on the
      first client render alike" — true only for a visitor with no stored
      preference. A returning dark-mode visitor hits a REAL hydration error
      on every fresh page load (next-themes resolves to "dark" client-side
      before this component's own effect could run; <html> is protected by
      suppressHydrationWarning in layout.tsx, this button wasn't). Pre-
      existing, not caused by this lane, but this lane is what turns a single
      page carrying the toggle into eleven, so fixed it now rather than
      shipping eleven pages that reproduce a known bug more often. Fixed with
      useSyncExternalStore (getServerSnapshot=false, client=true), not
      useEffect+setState — this repo's eslint (react-hooks/set-state-in-
      effect) rejects the classic mounted-flag pattern; confirmed lint-clean.
    Pointers: branch `landing-header-and-docs` @ 6351658, PR #101. New:
    web/components/site-header.tsx, web/components/docs/*, web/lib/docs-nav.ts
    (+.test.mjs), web/app/docs/** (11 routes), web/public/llms.txt. Modified:
    web/app/page.tsx (nav extraction), web/app/globals.css (+--warn,
    +.code-rail/-head), web/components/theme-toggle.tsx (hydration fix). ***

*** NEW LANE — FRONT DOOR (2026-08-08/09). Separate from the console work
    described below, which is unchanged and still accurate.
    Design: docs/superpowers/specs/2026-08-08-front-door-design.md
    Roadmap: docs/design/outcome-loop/ROADMAP.md § M6 (tenant dashboard, pulled
    forward ahead of its trigger — the note under the table explains why).
    PHASE 0 IS BUILT AND IN REVIEW: PR #75, branch `front-door-design`,
    worktree repo/.worktrees/front-door. It takes DOUG_API_TOKEN off doug-web
    by BOTH routes (deploy flag + Secret Manager binding) and gives the public
    pages an unauthenticated GET /v1/showcase/queue pinned by a new
    DOUG_SHOWCASE_REPO. 925 pytest · ruff clean · bash -n clean · web 4/4.
    THREE THINGS TO KNOW BEFORE MERGING #75:
    1. deploy.yml's `web` job is `needs: changes` ONLY, not `needs: api`
       (:82-83 vs :147-148), so api and web deploy IN PARALLEL. This PR changes
       both. If web wins, the public pages hit a showcase route the live api
       does not serve yet and fall back to the labelled fixture until api lands.
       Transient and self-healing; one-line fix is `needs: [changes, api]`.
    2. The endpoint filters on `verdicts.repo`, a DISPLAY-ONLY string, on an
       unauthenticated surface. MT4 says authorization keys on github_repo_id.
       The PR did not introduce string-keying (/v1/queue?repo= already did) but
       it moves it onto a public surface. Follow-up, not a blocker.
    3. Nothing smoke-tests /v1/showcase/queue; promote_if_healthy smokes `/`
       which returns 200 whether the page rendered live rows or the fixture.
    STILL OWED TO ANDREW, needs prod gcloud: the compute-SA revocation now
    written up at docs/OPERATIONS.md § "Service identities". Removing the token
    from doug-web did NOT close it.
    NEXT: Phase 1, gated on proving that WorkOS's GitHub-App token is a
    user-to-server token GET /user/installations answers for. One live call. ***

State:    console Phase 2a (health strip + failure surface) is BUILT. All
          seven plan tasks are complete, plus a whole-branch review fix wave
          (three Important + several Minor findings the cross-task view
          surfaced, applied together — see Decisions below). Worktree
          `.claude/worktrees/console-next`, branch `worktree-console-next`,
          16 commits over main `91b5e8b` (= origin/main, #69). No open PR
          yet.
          Ships two endpoints (`GET /v1/health`, `GET /v1/jobs`), the health
          strip (`components/health-strip.tsx` + `lib/health.ts`'s pure
          classifier) wired into `shell.tsx` on every page, and the `/jobs`
          failure list (`app/jobs/page.tsx` + `components/jobs-table.tsx`),
          scoped like Runs with an unhealthy/all toggle.
          Verified green: api `uv run pytest` 853 passing, `ruff check .`
          clean; console `npm test` 70 passing (69 plus one test added in
          the fix wave, pinning `getJobs`'s `installationId=0` guard),
          `npm run lint` clean, `npm run build` green.
          THIS FILE COVERS THE CONSOLE LANE ONLY. The authoritative M3
          tracker is repo/HANDOFF.md + docs/design/outcome-loop/ROADMAP.md.
          M3 Task 7 (production 60-day catch-up) is untouched by this lane
          and remains the critical path there.

Next:     Open the PR for `worktree-console-next` against main. Nothing else
          is planned or blocked on this lane.

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

FIVE DEFECTS IN THE PLAN, found DURING execution, all fixed. Recorded because
          each one is a trap the next plan in this repo could repeat:
- Brief's `_db_now` would have been a FOURTH identical copy (ingest,
  outcome_queue, outcome_backfill already had one each). All three already
  import store, so store was the only home with no cycle. Consolidated
  instead; proven a pure move (those three suites unchanged at 66).
- Brief's job_rows compared Python-side naive sqlite timestamps against aware
  now/cutoff -> TypeError. Fixed with the house `_as_utc`. Every other
  lease comparison in the repo does it in SQL, which is why nothing hit it
  before.
- Brief's `ageMs` used raw `Date.parse`. `console/lib/runs.ts:141` exports
  `parseUtc` precisely because zoneless timestamps parse as LOCAL per
  ECMA-262 (7-hour shift; its docstring carries a repro). The decisive
  argument is NOT sqlite-vs-Postgres — it is that a SECOND parser makes
  rendered ages and computed verdicts disagree with no error anywhere.
- Brief built the /jobs view-toggle links by spreading optional searchParams
  into URLSearchParams, which stringifies undefined:
  `?repo=undefined&view=all`. That filters to a repo literally named
  "undefined" and renders an empty list reading as "nothing is wrong".
- Brief's caps fell back to literal 0 when getHealth() failed, rendering
  attempts as "2/0" — a real-looking cap. Reachable WITHOUT the page
  failing, because getHealth() runs twice per /jobs load and AbortSignal
  opts both out of Next fetch memoization. Now `number | null` + explicit
  "cap unknown".
- A SIXTH was caught only by the whole-branch review, because it lived in the
  interaction between two tasks' files and neither task's review could see
  it: `next_due_at` could never render. It is defined server-side as
  MIN(due_at) WHERE due_at >= now, so it is always in the future, and the
  strip's `age()` helper discarded negative deltas. The clocks cell showed
  its count and nothing else, permanently. Fixed with a forward-looking
  `dueIn()`; the negative guard stays for the backward-looking cells.

DELIBERATELY NOT DONE (triaged ship-as-is at final review):
- Console has NO component/render test infrastructure. This plan routed
  around it by keeping all lying-risk in the pure, tested lib/health.ts
  rather than closing it. The spec's testing section is NOT fully satisfied:
  "attempts never render against the wrong lane's cap" has no test, only a
  construction that makes it hard to get wrong. Render-test infra remains
  its own Phase 2 item and this is the first assertion to add.
- /v1/health is fetched twice per /jobs load and every page awaits it
  sequentially (Shell renders after the page's own await). Latency only, no
  wrong data. React.cache + a Suspense boundary with a GHOSTED (never
  "clear") fallback is the fix.

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


---

# M3 LANE — preserved verbatim from main @91b5e8b

Unchanged by the console-next branch. This branch touches docs/superpowers/
specs/ only; nothing below was re-verified in this session.

---

# HANDOFF — doug

State:    M3 ACTIVE. The last verified deployed production commit is `fa1e323`
          (#65). The implementation-PR base snapshot verified on 2026-08-07 is
          `99011b7`; it includes #67's `/compare` and dual-run comparison
          retirement plus #68's console run forensics. This is a repository-base
          snapshot, not a production deployment claim. M3 is not deployed. Task 7
          must re-verify the serving production revision before either those base
          changes or the M3 branch is marked live.
          M3 item 1 (`adjudicate.py`) and the v7 draft pre-registration are merged
          (#59–#61). On implementation branch `m3-60-day-backfill`, the permanent
          atomic 14/60 merge write, guarded one-time catch-up CLI, deploy-time
          lock guard, exact production runbook, and `LOCKED v8` document are
          built. None of those branch changes has been deployed or run; the
          production catch-up and v8 lock hash are not live.
          M3 item 2 remains LIVE: #64 shipped migration 007, the
          repository-batched `doug-adjudicator` Cloud Run Job (2Gi), crash leases
          + generation fencing, ten daily attempts, append-only merge-SHA
          outcomes, persisted read coverage, and the separate Scheduler identity;
          #65 fixed the first deploy's `gcloud --args` parse failure and IAM
          propagation wait. `doug-adjudicator-daily` is enabled for 03:00 UTC
          with zero Scheduler retry attempts. The Job uses the exact API image
          and the intended runtime SA, one task, zero platform retries and a
          3600-second timeout. First execution `doug-adjudicator-nvwqn` completed
          successfully on 2026-08-07 with `repositories=0`, `done=0`,
          `retried=0`, `failed_repositories=0`, and `reclaimed=0`. The
          session-independent future-row audit and the done-job identity audit
          both returned zero rows.
          The console Phase 1 and web service-account cutover are live. The
          grouping/facets/sorting slice (#63) is merged but still needs the
          manual console redeploy that service deliberately requires.
Next:     1) Merge `m3-60-day-backfill`, then execute Task 7 exactly from
          `docs/design/outcome-loop/60-day-backfill-runbook.md`: deploy and pin
          the v8 hash, dry-run, pause, prove execution quiescence, apply + verify
          the manifest, spool the pre-Job SQL audit, execute one manual Job,
          capture its execution resource, execution-scoped logs and DrainSummary,
          spool the post-Job SQL audit, run the final CLI audit, and resume. Keep
          the named dry-run, apply, manifest, quiescence, SQL, execution, log,
          summary, and Scheduler paths for the closure PR. Do not mark the
          production catch-up complete without that receipt. Then finish M3 in
          separate PRs: receipts; check-run counters/meter; public Doug-on-Doug
          scoreboard.
          2) Watch the next scheduled 03:00 UTC execution and the first real
          due-row execution. The first known due clock is currently Aug 16;
          that run, not the no-op smoke, exercises GitHub clone + adjudication.
          3) Independently, redeploy #63 with
          `PROJECT=doug-prod0 REGION=us-central1 bash deploy/gcp.sh console`.

          Audit lesson: Cloud SQL Studio does not guarantee that consecutive
          submissions reuse one PostgreSQL backend, so TEMP tables can vanish
          between the pre-run snapshot and post-run query. For cross-command
          audits, use one persistent `psql` session or export a durable
          pre-state. The first-ever no-op was recoverably checked without the
          lost TEMP table: its execution summary reported zero repositories
          and zero reclaimed claims, and this session-independent query also
          returned zero rows:

             SELECT id, status, attempts, claim_generation, due_at,
                    started_at, finished_at, error
             FROM outcome_jobs
             WHERE due_at > TIMESTAMPTZ '2026-08-07 13:49:46.420106+00'
               AND (status <> 'pending' OR attempts <> 0
                    OR claim_generation <> 0 OR started_at IS NOT NULL
                    OR finished_at IS NOT NULL OR error IS NOT NULL);

          The complete-identity audit also returned zero rows:

             SELECT j.id, count(o.id) AS matching_outcomes
             FROM outcome_jobs j
             LEFT JOIN outcomes o
               ON o.installation_id = j.installation_id
              AND o.github_repo_id = j.github_repo_id
              AND o.pr_number = j.pr_number
              AND o.merge_commit_sha = j.merge_commit_sha
              AND o.window_days = j.window_days
             WHERE j.status = 'done'
             GROUP BY j.id
             HAVING count(o.id) <> 1;

Rulings:  All five settled in #61. Tenant repos are in by default by name
          with prospective opt-out; the lower window bound is
          `TOLERANCE_DAYS = 1`; decidability is two-sided; quarterly cadence
          is a floor; adjudication `max_attempts = 10`. The Job cadence is
          daily, so the ceiling buys ten calendar-day opportunities. Platform
          retries are zero: one scheduled trigger spends at most one attempt.
Blockers: Job/Scheduler has none. Code, runbook, and lock are built on the
          implementation branch; publication remains blocked on merge plus the
          Task 7 production catch-up. Neither catch-up nor the v8 lock hash is
          live.
Pointers: ROADMAP M3 · REVIEWING.md · `docs/design/outcome-loop/
          publication-preregistration.md` (`LOCKED v8` on the implementation
          branch) · `docs/design/outcome-loop/60-day-backfill-runbook.md` ·
          `docs/superpowers/plans/2026-08-06-m3-adjudicator-job-scheduler.md`.

---

State (historical, still useful below): M0 CLOSED. TASK 10 IS DONE: the App
          path is LIVE and verified in production on drewjst/doug (neutral
          check run, "Cleared · risk 0.02 · diff read", on PR #33 — tier in
          the title, so it was a real read and not a deterministic fallback).
          M1 code is complete except TASK 9, which is now the last M1 task.
          ONE PR PER TASK (Andrew's call, 2026-08-01: more Doug verdicts +
          smaller diffs Doug can actually read whole). Merged to main: Tasks
          1-2 (#18), 3 (#19), 4 (#20), 5 (#23), 7a Steps 1-3 (#24, + the #26
          cooloff fix), 8 (#22, ADR-0010), 6 (#27, the webhook rewrite),
          7b (#28, startup sweep + the review-state casing fix — which
          CLOSES Task 7), #29 (the late #24 re-review), 10 (#32, code) with
          the operator cutover run 2026-08-01, and #34 (m1-cutover-done).

          #34 (m1-cutover-done) was not a plan task. The cutover
          exposed that worker.process_job wrote NOTHING to the log on any
          successful outcome, so "the review ran" and "the job was never
          claimed" were indistinguishable — answering "did that review
          actually run?" took four tool calls, a dashboard fetch and a
          browser screenshot. It adds one line per outcome, and the fresh
          review and the idempotent replay are worded so they can never be
          confused: only the fresh one says "paid read", because only it
          bought one. See the decision below for why that distinction is
          the change rather than a detail of it.
Next:     A SOAK on the live App path, then M1 Task 9. Task 9 (retire the
          CI token path: delete .github/workflows/doug-review.yml and
          /v1/review) is unblocked and code-ready, and is deliberately NOT
          the next thing anyone does. Andrew's
          call, 2026-08-02: the CI path and the App path run in PARALLEL
          until the App path has been watched against an independent
          reviewer, because Task 9 deletes that reviewer. Exit criteria are
          counted in PRs, not days — see the soak decision below, which
          also carries the reason and the concurrent UI work reading the
          same rows. That decision supersedes nothing about the 10-then-9
          resequencing; it adds a gate in front of the 9.
          Rebase vs. merged #15 still to be done deliberately. AFTER the
          soak and Task 9, M1's exit gate is checkable end to end.

          SOAK TALLY as of 2026-08-02 ~15:30Z (counted from the prod logs;
          nothing was counting it before, so re-count rather than trust this
          if much time has passed). Source: `gcloud run services logs read
          doug-api --region us-central1 --project doug-prod0 | grep
          "doug: reviewed"`.
          1. MULTIPLE PUSHES — MET, twice: #37 (78649827, bc0968a5) and #38
             (1294e160, bee606e2) each scored at two head SHAs.
          2. COLD START, sweep enqueues >0 — NOT MET, and it will NOT be met
             by waiting. Every reconcile line in the window says "enqueued 0
             job(s)". The webhook path drains jobs promptly, so at any boot
             there is nothing pending for the sweep to find. The criterion
             asks the backstop to prove itself, and passive soaking cannot
             create the condition it needs. ANDREW RULED 2026-08-02: FORCE
             THE CONDITION, rather than rewrite the criterion or drop it —
             it was written to test an untested claim, so weakening it to
             pass would defeat its purpose. Procedure agreed, NOT YET RUN
             and deliberately not run unattended, because step 1 is a
             deliberate production degradation: (1) stop deliveries reaching
             the queue, (2) push to an open PR so no job is enqueued, (3)
             let the service cold-start, (4) expect "doug: reconcile
             enqueued 1 job(s)" plus a check run for that SHA. Costs one
             paid read. Run this WITH Andrew, not for him.
          3. MERGE writes an outcome_jobs row — UNVERIFIED. #35/#36/#37 all
             merged 2026-08-02 and no log line covers this path, so it needs
             a ledger read, not a grep. Cheapest honest check available.
          4. ~10 CHECK RUNS none missing — 7/10. Reviews: #30@afee4cac,
             #35@5c59fe84, #36@36606df3, #37 ×2, #38 ×2. No gaps: every PR
             that saw a push since the line existed produced one. Note the
             count only starts at #34's merge (06:22Z), because the
             "reviewed" line did not exist before it.

          M2 SAFETY WORK IS NOW MOSTLY DONE, out of order and deliberately,
          because the cutover changed the risk: paid reads are now triggered
          by webhook deliveries — PR activity Doug does not control — rather
          than by our own CI. Merged: #35 (/v1/score/read was unauthenticated
          AND paid on a public --allow-unauthenticated service; now gated)
          and #37 (MERGED 2026-08-02T07:26Z, a8cc396, main's HEAD): the spend
          cap wired to every paid call site, plus per-read cost capture.
          Spend is now bounded AND measured — the cost lines are live in
          production, confirmed on the serving revision from 15:16Z.

          The remaining M2 items, in the order I would do them:
          0. NEW, FOUND 2026-08-02 BY READING #37's OWN COST LINES — the
             intent read's per-installation flag DOES NOT EXIST. design-lock
             .md:62 (red-team mitigation "overclaim #4 = scope #1") commits
             to "per-installation flag, default OFF, ON for the dogfood
             install; labeled experimental; stays off until the pre-
             registered positive control passes." What is actually in the
             code is a PROCESS-WIDE env var: intent.enabled() is
             `os.environ.get("DOUG_INTENT") == "1"` (api/doug/intent.py:73,
             duplicated at api/doug/reader.py:527), consulted once in
             review.read_intent (api/doug/review.py:307) and never per
             installation. It is ON in production — the kind=intent lines
             prove it. Harmless at one installation; the moment there is a
             second, that tenant gets the experimental read, charged to
             THEIR ceiling, with no per-tenant off switch. M2's exit gate is
             "safe to point at strangers", so this belongs in M2 and is not
             on the roadmap's M2 list at all. NOT a live incident: install
             visibility is still "Only on this account".
             BUILT — PR #39 OPEN (branch intent-per-installation-flag; 500
             passed, was 492; ruff clean; 6 mutations caught). Doug reviewed
             it: FLAGGED 0.32 vs 0.30, and its 90% PARTIAL READ was caused by
             a stray file this branch should never have carried (see the
             git-add note below). Findings answered in a PR comment — 2
             fixed (canonical scope parsing; the deploy test now pins "and
             nobody else" instead of unpacking one line), 1 disproved
             (reader.intent_enabled had no caller anywhere), 1 already
             disclosed (config drift until gcp.sh runs). Andrew ruled ENV
             ALLOWLIST over an installations column — no migration, no
             collision with 005, right size for one install; it becomes a
             column when item 3's dispense work opens that table anyway.
             Shape: intent.enabled_for(installation_id) over
             DOUG_INTENT_INSTALLATIONS, with the id derived from the SAME
             scope string the spend cap charges (reader.installation_from_
             scope), so payer and opted-in party cannot drift. Untenanted
             callers → None → no intent read, which also halves the soak's
             intent spend. gcp.sh switched to the allowlist and PINNED by a
             test, because silent-off is the safe direction and therefore
             the easy one to ship by accident.
             NOT YET DEPLOYED — until gcp.sh runs, prod still has the old
             DOUG_INTENT=1 and the fix is source-only.
             Cost context, first real numbers Doug has ever had: on #38 each
             push bought FOUR reads, because the soak dual-runs both paths —
             risk and intent, each on scope=installation:150424894 and again
             on scope=untenanted. The intent read is the LARGER of the two
             (in=16601/out=1305 vs in=14031/out=925), so the unvalidated
             feature is over half the input tokens per PR. Cross-reference
             the derangement check below: intent findings are UNBELIEVED and
             a positive control is still unrun.
          1. Migration 005 — DONE (#43). UNIQUE App-path verdict identity.
          2. doug-web's own service account — CODE DONE (#44). Ops cutover
             may remain: first `gcp.sh web` as `doug-web-sa`, then revoke
             default compute SA’s leftover `doug-api-token` accessor.
          3. Per-installation scoped reads + token dispense. This is the
             one that actually gates real tenants, and it is untouched.
          4. Bot-author exclusion — RE-SCOPE THIS BEFORE BUILDING IT. The
             roadmap wants bot-authored PRs excluded from deep reads to
             save money, but Doug's thesis is AI-review routing and the
             agentic-trust surface, so those are the PRs it exists to
             grade. api.py already says as much for the reviewer lane
             ("grading bot reviewers is the point of the lane"). Probably
             metering, not exclusion. Andrew has not ruled on it.

          What the cutover actually put in production, verified on the
          serving revision: doug-api runs as its OWN service account
          doug-api-sa (not the default compute SA, which holds
          roles/editor on doug-prod0); DOUG_GITHUB_APP_ID and
          GITHUB_APP_PRIVATE_KEY are both in --set-secrets, so
          app_auth.enabled() is TRUE in prod for the first time;
          --no-cpu-throttling is set, without which the background drain
          is suspended the moment its request returns; and Task 7b's
          startup sweep runs at boot, which needs both of those at once.
          doug-web SA code is on main (#44); confirm the serving web
          revision identity after the next web deploy.
Blockers: NONE. Both Andrew-only items closed 2026-08-02 and verified:
          - "Pull request review" event subscription ENABLED (Andrew
            confirmed). The tier='external' grader lane can now receive.
            Nothing has exercised it yet in production — the first
            third-party review on a PR is what proves it, and no log line
            fires when it works, only when the state is unrecognized.
          - Anthropic key rotation CLOSED: v2 live, v1 DISABLED in Secret
            Manager (verified `state: disabled`), local plaintext file
            deleted. Every secret binding is `version=latest` — verified
            on the serving revision — so disabling v1 was safe. NOTE that
            `latest` means a future v3 is picked up silently; nothing pins
            a version anywhere.

          Standing hazard, not a blocker: GitHub's REST quota is 5,000/hr
          and is SHARED across every concurrent session and agent. It was
          exhausted twice on 2026-08-02. Prefer `gcloud run services logs
          read doug-api` over `gh` for anything the logs can answer —
          since #34 and #37 they answer most of it.

Execution model (do not rediscover this):
- One PR per task. Doug reviews each (ADR-0008); read its findings, but
  VERIFY before fixing or dismissing — roughly half are disproved by files
  outside the diff. See docs/REVIEWING.md, which is the accumulated
  lessons from ~20 findings across two review layers.
- Per task: fresh implementer subagent from an extracted brief, then an
  INDEPENDENT reviewer, then a fix round, then a scoped re-review. Do not
  let the implementer grade its own work, and do not fix findings in the
  controller session.
- Extract a brief with sed from the plan; never make a subagent read all
  4591 lines. Task line ranges: T6 2638-3395, T7 3396-3716 (Step 4 starts
  at 3267 of that slice), T9 4025-4244, T10 4245-4591.

Standing rules this branch learned the hard way:
- NEVER `git add -A` at this repo's root. The main worktree carries other
  sessions' UNTRACKED files — .claude/worktrees/ holds six live branches —
  and a repo-wide add swept a landing-theme design spec into #39. It cost a
  commit to undo and it degraded Doug's review of that PR to a 90% partial
  read, cut inside the stray itself. Stage explicit paths. Undo with
  `git rm --cached` so the other session's on-disk copy survives.
- Doug's deviation stream is UNBELIEVED by policy (failed derangement check)
  and has now flagged the real defect TWICE on the same subject: arms.json:187
  had already caught the DOUG_INTENT=1 service-wide deviation that #39 fixes,
  and the #39 review's beyond-ticket finding is what caught the stray file.
  This is NOT validation — a failed derangement check validates nothing in
  either direction — but it is the concrete argument for scheduling the
  positive control instead of leaving the tier disbelieved indefinitely.
- A docstring asserting a durability/ordering/concurrency property must be
  TRUE. Eight separate findings here were comments promising guarantees
  the code did not make. If nothing enforces the claim, the comment is the
  bug.
- Plan INTENT governs over the plan's literal code sample. Several samples
  violated constraints the same plan states in prose. Fix it, and record
  the ruling in the PR body rather than applying it silently.
- A test that cannot fail when its named behavior regresses is an
  Important finding. Two shipped tests here were vacuous; both were caught
  by mutation, not by reading.

Key facts for the executor:
- App: dougs-review, App ID 4450932, installation 150424894 on drewjst
  (User, selected: doug only). Perms checks:write/contents:read/
  pull_requests:read/metadata:read; events: pull_request. Private key in
  Secret Manager doug-github-app-key — Task 10 SETTLED the custody
  question: it is granted to the dedicated doug-api-sa, not to the default
  compute SA. Webhook secret doug-webhook-secret v2 (v1 has a trailing
  newline; bound as :latest, which IS v2 — this file once claimed it was
  pinned to :2 and that was never true). Webhook verified end-to-end in
  prod: ping + installation events 202 with valid signatures. Deliveries
  no longer verify-and-discard — Task 6 (#27) dispatches them, and since
  the 2026-08-01 cutover that is what production is actually running: the
  discarding revision is gone.
- Install visibility is "Only on this account" — flip to "Any account"
  before installing on lemahq/lema (Task 10 cutover).
- Carried forward for the doug-web SA follow-on, verified during Task 10's
  scoping and still true of doug-web: the default compute SA holds
  roles/editor on doug-prod0, and roles/editor does NOT include
  secretmanager.versions.access. So the explicit secretAccessor bindings in
  api/deploy/gcp.sh:88-98 are LOAD-BEARING, not belt-and-braces, and the
  gcp.sh:84-87 comment saying so is accurate as written. Do not "simplify"
  those bindings away on the assumption editor covers them.
- The plan was built by 3 drafting agents on locked interfaces, reviewed by
  2 adversarial verifiers (both verify by execution), 3 blockers + 5 majors
  fixed. Deepest invariants (do not "tidy" these away): enqueue REVIVES
  failed/superseded rows in place with a STABLE id; drain's seen-set bounds
  both retry burn and the force-push supersede/revive ping-pong; the
  no-ledger 503 is scoped to the three handled webhook events only.
- Derangement check (2026-07-31): BAR FAILED and the instrument is invalid
  for constraint-style records — validates nothing either way. Deviation
  findings stay UNBELIEVED; check-run copy must keep the "unvalidated"
  label. Positive-control experiment needed before further intent-stream
  investment. Full analysis: workspace/research/phase1-entry-preregistration.md
  (workspace/ is untracked — lives only on Andrew's machine).

Decisions this session (2026-08-01/02, cutover + the logging it exposed):
- TASK 9 WAITS FOR A SOAK (Andrew, 2026-08-02). The CI path and the App
  path run in parallel on purpose, so the new path can be compared against
  an INDEPENDENT reviewer before the old one is deleted. The reason is the
  App path's characteristic failure mode: SILENCE. Nothing turns red, no
  job fails, no alert fires — the check run simply never appears, and an
  absent check run looks exactly like a PR nobody pushed to. The CI job
  summary is the second, independently-triggered observer that would make
  that visible, and Task 9 is what deletes it, so it goes last.
  Note this is a different claim from the logging work above: that logging
  makes a review the operator ASKS about answerable in one grep. It cannot
  reveal a review that was never triggered, because the missing line and
  the un-triggered job are the same absence. Only a second path scoring
  the same PR can.
  EXIT CRITERIA — counted in PRs, not days. All four:
  1. a PR with MULTIPLE PUSHES (exercises supersede + re-enqueue),
  2. a COLD START whose startup sweep enqueues >0 jobs — it has only ever
     logged 0 in production, so the backstop has never actually done
     anything and is currently an untested claim, not a verified one,
  3. a MERGE that writes an outcome_jobs row,
  4. ~10 CHECK RUNS with none missing.
- A SECOND SESSION is concurrently building the dual-run comparison UI in
  web/, on branch dashboard-dual-run. It owns web/**, api/tests/test_api.py
  and api/tests/test_store.py, and appends only in api/doug/api.py and
  api/doug/store.py. What makes the comparison possible, and is NOT obvious
  from the schema: both current App and CI paths write head_sha as shared
  commit identity for idempotency. App alone also writes installation_id and
  github_repo_id. Current CI therefore has both App ids NULL and head_sha
  populated; legacy CI rows may have all three NULL. The comparison separates
  paths by the App id pair after the store predicate qualifies a row, and
  excludes either one-id shape, both App ids without a head SHA, and
  tier='external'. `/v1/review` replay is scoped to the same null App-id pair,
  so an App verdict cannot suppress the independent CI measurement. A legacy
  row with no head remains visible as neutral, unpairable evidence; it cannot
  establish that either path is missing.
- A FRESH REVIEW AND AN IDEMPOTENT REPLAY MUST NOT LOG ALIKE. They agree on
  every field either line could carry — repo, PR, head SHA, tier, band,
  score, verdict id — and differ in exactly one thing: the fresh one bought
  a model read and the replay re-rendered a row already in the ledger. So
  the difference has to live in the WORDING or it does not exist: one line
  covering both would make spend unauditable from the logs, with an
  operator counting reviews counting replays that cost nothing. Only the
  fresh line says "paid read" — rejected: a single "job N complete" line,
  which is what "add a success log" naturally produces and is worse than
  the silence it replaces.
- The fresh line is emitted BEFORE ingest.complete, not after. By that
  point the read is paid for and the verdict durable, and complete()
  raising is the one failure that re-pends a job in exactly that state — it
  must not be able to erase the record of what the attempt cost. It is
  still not a complete spend ledger (a read dying before save_review
  commits leaves only drain's failure line) and the code says so rather
  than claiming a guarantee it does not make.
- Key rotation CLOSED and verified rather than trusted: the plaintext
  api/.backtest-cache/llm-probe/api-key is gone (whole llm-probe/ directory
  with it) and doug-anthropic-key has a v2 created 2026-08-02. The "v1 still
  enabled" loose end this line used to carry is CLOSED — v1 is disabled and
  verified; see Blockers, which is the current record.
- ROADMAP's Task 10/Task 9 item SPLIT into two boxes. One box covering two
  tasks cannot record that one is done and the other is not — rejected:
  ticking the combined line, which would have read as Task 9 being done.

Decisions this session (2026-08-01, M1 Tasks 6–7b):
- Task 9 RESEQUENCED AFTER Task 10 (Andrew, 2026-08-01): Task 9 deletes
  .github/workflows/doug-review.yml, which is the surface producing Doug's
  reviews on this repo today. Deleting it before the App's check run is
  verified working in production would leave every PR — including the ones
  fixing that — reviewed by nothing, with no fallback to roll back to —
  rejected: the plan's 9-then-10 order.
- Task 7b tested the lifespan wiring the brief shipped untested. The brief's
  own note ("both guards are off in tests, so TestClient never spawns the
  thread") describes the gap rather than justifying it; the tests patch
  app_auth.enabled/store.enabled instead of the env behind them, and the
  thread is named so "no thread was started" is assertable rather than a
  race — rejected: shipping Step 4 with the coverage the brief specified.

Decisions this session (2026-08-01, M1 Tasks 1–2):
- outcome_jobs is a store.metadata table, NOT a migration (Global
  Constraint: new tables via create_all; migrations are for columns on
  existing prod tables) — rejected: ROADMAP's literal "migration 002"
  framing for the table.
- installation.created token mint SKIPPED: hash-only storage makes an
  install-time mint unrecoverable dead weight; M2's dispense endpoint
  mints and writes installations.token_hash (column landed in Task 2) —
  rejected: minting a token nobody can ever read back.
- verdicts.source widened to String(64) ('review:<login>' needs 46) —
  rejected: plan's String(20).
- Two plan-mandated defects fixed against the plan's literal code because
  the plan's own stated invariants condemned them: apply()'s version
  insert now swallows the duplicate-version race (docstring: "already
  done is satisfied, not failed"); drift test now pins BOTH directions
  (baseline + migrations == metadata) — rejected: shipping the plan's
  verbatim body over its intent.
- pull_request_review ingest design (for Task 6): tier='external',
  band cleared/flagged from review state, dedup on (inst, repo, pr,
  source, head_sha, scored_at); latest_reviews/find_review must exclude
  tier='external'. GitHub App needs the "Pull request review" event
  subscription — MANUAL step, Task 10 cutover checklist.

Decisions this session (2026-07-31/08-01, M0 pass):
- workflow-summary-test-fidelity: DROPPED, branch deleted (local + remote).
  Its only real content vs main was a test regex fix, already byte-identical
  on main; the branch's sole diff was a stale HANDOFF.md snapshot —
  rejected: merging it (nothing to merge).
- PR #15 was already merged upstream before this session acted on it
  (by a concurrent session); local main fast-forwarded, no rebase needed.
- Intent-stream posture (per-installation flag, default OFF for tenants,
  ON for dogfood, experimental label) needed no new decision — confirmed
  already written into design-lock.md:62 — rejected: re-deciding it.
- Key rotation at api/.backtest-cache/llm-probe/api-key deferred by Andrew
  this session (needs Anthropic console access) — rejected: deleting the
  file without rotating first (would just lose the credential, not retire
  it).

Prior decisions this session (2026-07-31/08-01, step-2 plan):
- Step-2 plan pushed straight to main (Andrew's instruction, sole session);
  execution returns to PRs. — rejected: PRing the plan doc (explicitly
  overridden by Andrew).
- ADR-0003 will be superseded by ADR-0010 (neutral check run) in the same
  commit as the check-run code; ADR-0007 and ADR-0008 get prose corrections
  only (their decisions stand, their surface references die with CI).
- Anthropic key rotation staged create-then-revoke-after-verify (Task 10)
  so the live reader never breaks between rotation and deploy.

Pointers:
- Plan: docs/superpowers/plans/2026-07-31-step-2-github-app-webhook-ingest.md
  (commits d51eec8..94f87e9+). Spec: docs/superpowers/specs/
  2026-07-30-github-app-tenancy-dashboard-design.md (lema mentions
  clarified 2026-08-01).
- Roadmap: docs/design/outcome-loop/ROADMAP.md — the tracking document,
  M0 through M6.
- Full session state: ../HANDOFF.md on Andrew's machine (project root,
  above this repo) is the richer, hook-maintained handoff.
- PR #16 open: docs/outcome-loop-design-lock (design docs + landing-page
  section + .env.example MAGPIE_*→DOUG_* fix).
- stash@{0} (queue-polish era): dashboard repoint + the lost step-1 plan
  file. Both obsolete (repoint shipped via deploy config; plan content
  landed in #14) — drop deliberately when convenient.
- Carried forward: reader-feedback items 3 & 4 (invariant-vs-mechanism;
  severity = impact × confidence) need a frozen v2 prompt + validation run —
  credits now exist, still unscheduled. lema#643 had FOUR reader findings
  (reader:brittle-test-assertion, low, unscored) — evidence the reader
  reads tests it is given.
