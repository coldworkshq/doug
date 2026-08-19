# HANDOFF — doug

State:    **LOOP LIVE + EXIT-GATE AUDIT PASSED (18/18), and the audit found
          a live defect in `/v1/patterns`.**

Next:     1. ~~Fix `precision.fold`~~ DONE — PR open, see below. With it,
             `/v1/patterns` for drewjst/doug becomes `prs: 16, defects: 0,
             base_rate: 0.0`: honest, and correctly uninformative. Sixteen
             observations with zero defects cannot say which patterns
             predict defects. The pattern display has nothing to show YET —
             that is the finding, not a blocker.
          2. **2026-08-21: the first real detector test.** PR #68 merged to
             main 2026-08-07 and was reverted by #70 the same day. Its 14d
             adjudication is `pending`, due 2026-08-21. It is the only PR in
             the repo's history with a revert against it, so it MUST come
             back `kind=revert`. If it returns `clean`, the detector is
             broken and M3 says stop.
          3. The liveness item (roadmap M3, unbuilt). Zero alert policies
             still exist in doug-prod0.
          4. Then MT3, then M4's interviews.

Blockers: none.

## THE AUDIT — M3's exit gate, done 2026-08-18

Gate: "100% agreement vs. a manual `git log` audit (any disagreement =
detector bug = stop)". **18/18 agree.**

  16 clean (PRs 28-32, 34-39, 41-45) — the ONLY revert in the entire repo
     history since 2026-08-01 is `#70 Revert "...(#68)"` on 2026-08-07, and
     #68 is not in this batch (its window is still pending). So no PR
     labelled clean has a revert against it.
  2 censored (PRs 40, 46) — both merged to `gh-pages`, `censor_reason:
     base_ref`, `default_branch: main`. Independently checkable from the
     receipt's own base_ref. This is the roadmap's rule working: "merge to
     non-default branch -> censored, never clean".
  Denominator complete — the one gap in an otherwise contiguous 28-46 run
     is #33, which has `merges: 0`. Never merged, correctly not at risk.
     (This is the check MT3 exists to protect: a missing job would look
     identical to a clean sweep.)

Method: receipts via `GET /v1/prs/{n}/receipt` with the operator token, swept
over PRs 10-60; revert evidence read from `git log origin/main` by subject,
NOT from `git_labels` (using the detector to audit the detector is circular).

## THE DEFECT THE AUDIT FOUND — `/v1/patterns` counts censored as defect

`precision.py:50`:

    is_defect[key] = is_defect.get(key, False) or r["kind"] != "clean"

The Outcome enum is REVERT / CLEAN / CENSORED. A censored row is a
NON-OBSERVATION — the PR left the risk set — but it is `!= "clean"`, so it
lands in the numerator as a defect.

Live impact right now: `/v1/patterns?repo=drewjst/doug` returns
`prs: 18, defects: 2, base_rate: 0.111`. The true observed defect count is
**0 of 16**; 100% of the reported "defects" are non-observations, and the
honest denominator is 16, not 18. Every precision, lift and `clears_base`
value it publishes is computed against that manufactured base rate.

Same defect class as #93 ("a censored outcome is a non-observation, not a
miss") — fixed in the console then, not here. `precision.fold` is the ONLY
consumer of `kind != "clean"` in the package, so the blast radius is
`/v1/patterns` and nothing else.

FIXED on `fix/censored-is-not-a-defect`. The semantics were not a judgement
call — prereg §3 already rules it: `N_at_risk = N_done - censored`, and it
names and rejects the alternative ("counting censored as misses ... a
censoring rate wearing a miss rate's name"). So censored leaves BOTH the
numerator and the denominator. A censored row in one window does not
unobserve another (`outcomes` carries `window_days`). Kept as `!= CLEAN`
rather than `== REVERT` on purpose: a kind added to the enum later surfaces
as a defect (loud) instead of dissolving into clean (flattering), and
`test_fold_classifies_every_outcome_kind_the_adjudicator_can_write` fails
until someone gives the new kind a decision.

## What the three defects had in common — worth keeping

Every one was invisible because **the drain path had never executed against
real work in production**. Twelve green Job executions carried no evidence
about any of it; `docker build api` built an image it never ran; and the
public surface rendered `adjudicated 0`, the honest empty state, pixel-
identical to the broken one. Each fix exposed the next defect rather than
causing it. The general lesson is in the roadmap's M3 liveness item: a green
check over a code path that cannot run is not evidence, and "empty is the
product" only holds while empty-because-broken is a different, louder thing.

## THE LEASE — why re-running early "succeeded" and did nothing (RESOLVED)

The 14:20Z crash died AFTER `claim_repository`, so those rows sit at
`status='running'`. `drain()` opens with `reclaim_stalled()`, which only
returns rows older than `STALL_LEASE_SECONDS = 7200`, and
`due_repositories()` selects `status == 'pending'` only. The claim landed at
~14:22:40Z (the traceback is 14:22:44Z), so the lease clears at ~16:22:40Z and
9:25 AM PDT carries a margin. Every execution before then finds nothing due
and exits 0 — exactly what
`-m7vmr` (14:27Z, "Execution completed successfully") did. Scoreboard right
after it: `adjudicated 0 · pending 170`. The lease RESETS on each crash: if
the next run dies mid-way, add another two hours.

## CORRECTION — I was wrong about the deploy trap, and it spread

The "merging does not deploy the adjudicator" claim in commit 86807ee, PR
#113's body, this file, and the ROADMAP is **FALSE**. `deploy()` in `gcp.sh`
calls `adjudicator` and `reconcile_job` at its end, and `deploy.yml:132` says
so: "then refreshes doug-adjudicator from the promoted image". Proven: after
#113 merged, API and Job both moved to `@sha256:d12a4f4c` with no manual step.
Origin of the error: a `grep | head -20` that truncated before those lines,
plus reading gcp.sh's header ("`deploy` and `web` are what CI runs") as the
full list of what deploy does.

**It propagated.** main's HANDOFF carried it forward as its step 1 ("Run
`gcp.sh adjudicator` BY HAND ... merging #113 did not deploy the
adjudicator"), so a second session was about to act on my wrong claim. Fixed
here, struck through in the ROADMAP (#116), and corrected on #113 itself:
https://github.com/drewjst/doug/pull/113#issuecomment-5329880253

What survives: `doug-outcome-reconciler` still has ZERO executions and Cloud
Scheduler still holds only `doug-adjudicator-daily`. That was about the
scheduler, and `deploy` does not create schedulers.

## THE SECOND DEFECT — 2026-08-18, verified in prod (fix = #116)

    doug-adjudicator-hvdfn  14:20Z  exit 1
      File "/app/doug/backtest/git_labels.py", line 112, in clone_treeless
        subprocess.run([...])
      FileNotFoundError: [Errno 2] No such file or directory: 'git'

- Final stage is `python:3.14-slim-trixie`, copies only `/app`, installs
  nothing. The Job runs `python -m doug.outcome_worker` from that image.
- `git` is the ONLY missing binary: the import closure of `outcome_worker`
  reaches `backtest.git_labels` (git clone/fetch/log) and never `harvest`
  (the only `gh` caller). `_git_auth_env` injects `GIT_CONFIG_*` — no
  credential helper, no netrc, nothing else needed.
- Hidden by the SAME structural fact as the client bug, third time running:
  the drain path had never executed against real work, so twelve green Job
  executions carried no evidence about any of it.
- `docker build api` in CI never ran the image it built. #116 makes it run
  `git --version` against the built image.

## Dashboard redesign — PR #114 (MERGED as 8e1d774)

04df04a shell + census · 262f8e7 Repositories view · 3461657 the doc ·
03af44a the three review findings, fixed.

REVIEW ROUND, dispositioned in docs/reviews/2026-08-18-pr-114-external-review.md:
Doug scored 1 of 5. Its one true finding (severity bar drew three segments over
a total the three buckets need not sum to — `findings.severity` is nullable and
store.py counts total as COUNT(*) against three conditional SUMs) it ranked
LOW; its two most confident findings both die to `session-api.ts`'s boundary
validation, a file the diff never contained. The external pass found the defect
Doug missed, and it was the one this PR was most at risk of: `RepoCountLine`
branched on `atCap` before `filtering`, so at the cap with a filter on it named
a denominator 5x larger than the set actually counted — and disagreed with the
census panel on the same screen. Both fixed with tests watched failing first
and proven by mutation; `countedOver()` now owns the branch order for both
sentences and a parity test makes the disagreement unrepresentable.
CALIBRATION: Doug's severity ranking is now anti-correlated with truth across
#109, #106 and #114. That is the axis to work on, not its cross-file tracing,
which was correct here.

Tab-strip header → three-column instrument shell: a 212px left rail (scope,
sections, live in-view readout, settings gear), the ledger, and a right dock
holding either the selected run's evidence or a census of the ledger. Rail and
dock scroll independently, so the page itself does not scroll above 1620px.

NO API CHANGE. `web/lib/ledger-census.ts` counts what `/v1/sessions/runs` has
always returned and the dashboard never rendered: `finding_counts` (severity
mix), the three job timestamps (queue wait, read duration, retries), `url` (the
PR link, now an action), and the per-window outcome census including the
CENSORING RATE prereg §3 requires. Every number is a count of the array the
table is rendering, so the two cannot disagree; `censusScope()` prints the
denominator once, above all of them.

Decisions:
- Repositories is `?view=`, not a route — both views read one fetch, one filter
  set, one lens. Rejected: a second route (duplicates the shell) and a dashboard
  layout (cannot see the page's rows to fill the rail readout).
- The repository table is a FULL OUTER join. A connected repo with no runs is
  the most useful row on the screen; a repo with runs but no connection entry
  still holds real verdicts. Both directions mutation-proven. Rejected: joining
  from either side alone — each hides a different truth.
- Census is over the FILTERED rows in view, not `fetched`. Denominator stated.
- Dock breakpoint 1620px, MEASURED. Arithmetic said 1600 and was 9px wrong
  (chrome 669px + table 940px). At 1360 the PR title rendered 40px wide.
  Rejected: crushing the title to keep a dock on a 1440 laptop.
- Breakpoint classes written out literally at all five sites — a runtime
  `${DOCK_AT}:h-screen` is invisible to Tailwind's scanner and ships no rule.
- Settings gear is a `<details>`, not a popover. A view control that fails to
  hydrate costs a view; a sign-out that fails to hydrate strands you signed in.
- Band column did NOT shrink with the others — "needs you" wraps under 102px.
  Severity renders on the NEUTRAL ramp; a finding's severity is not a verdict
  about a PR. Two data colours still.
- The `min-w` pin is DERIVED from each COLUMNS array and sliced PER ARRAY. The
  first version scanned the whole file and REPO_COLUMNS broke it one commit
  later — same cross-record defect class as #109's regexes.
- The "health"/"tenant all"/"illustrative" bans stand untouched. This is one
  tenant's own runs, not fleet health.

VERIFICATION TRAPS, both hit on this branch and both look like real failures:
`next build` fails while a dev server holds port 3000 (the auth integration
tests shell out to it), and a stale `.next/dev/types/validator.ts` naming a
deleted route fails it too. `rm -rf .next` and stop the server before believing
a red suite.

Pointers: web/lib/ledger-census.ts (+ .test.mjs, 19 tests; band, outcome tone
          and both join directions mutation-proven) ·
          web/components/census-panel.tsx · web/app/dashboard/page.tsx ·
          web/lib/dashboard-contract.test.mjs
          · fixture-data preview harness (shell, census, evidence pane and
          repositories view, no auth or API needed) parked OUTSIDE the repo at
          <scratchpad>/design-preview-harness.tsx — restore to
          web/app/design-preview/page.tsx AND temporarily `export` Evidence +
          RepositoryTable in page.tsx. Both must come off before committing;
          the surface-token test catches the harness, nothing catches the
          exports.

## What was fixed

`api/doug/outcome_worker.py:36,40` — both GitHub clients now bound to a local
for the life of their call. Three tests, each watched failing first except
where noted:

- `test_client_lifetime.py` (new) — AST guard over the whole `doug` package:
  no attribute may be taken off a client factory's return value. RED before
  the fix, naming `outcome_worker.py:36` and `:40`. Carries a second test
  proving the walk can see the banned shape, so green means clean, not blind.
- `test_outcome_worker.py::test_github_context_holds_each_client_alive_across_its_own_call`
  — reproduces the production error at the production line against a client
  held the way githubkit holds it (weakref namespace). RED before the fix
  with the exact prod message.
- `test_app_auth.py::test_a_chained_client_is_collected_mid_expression_but_a_bound_one_survives`
  — characterization against REAL githubkit; passes immediately by design
  (it pins upstream, it drives no production code). It is what justifies the
  weakref fake in the test above.

## THE LIVE DEFECT — verified against prod 2026-08-18

`doug-adjudicator` exit 1 on both runs since the first job became due:

    2026-08-18T03:00Z  doug-adjudicator-szjvw  failedCount 1
    2026-08-17T03:00Z  doug-adjudicator-swwhk  failedCount 1
    2026-08-16T03:00Z  doug-adjudicator-ncpws  succeeded (nothing due yet)

    RuntimeError: GitHub client has already been collected.
      outcome_worker.py:36 in _github_context
      app_auth.app_client().rest.apps.create_installation_access_token(...)

Live `GET /v1/showcase/scoreboard` (2026-08-18T05:00Z):
`adjudicated 0 · pending 166 · first_due 2026-08-16T04:24:51Z` — two days
past due, zero adjudications, and the surface reads exactly like the honest
empty state it was designed to render. **Nothing said anything.**

- `outcome_worker.py:36,40` are the ONLY two unbound `client().rest.x.y()`
  chains left in `api/doug`. Every other call site binds to a local.
- This is #52 again — `tenancy.py:220-225` documents the identical failure
  from prod 2026-08-05, names the string, AND warns "Tests stub
  _caller_client wholesale, so only prod traffic exercises this."
- `test_outcome_worker.py:121` stubs `app_client` with a locally-bound fake,
  so it is structurally incapable of reproducing the failure. Third
  consecutive PR whose green check passes for the wrong reason — this one
  escaped to prod, in the component whose only job is to tell the truth.
- No data loss and no countdown: `reclaim_stalled` returns the lease
  "without spending an attempt", so the pre-registered ten attempts are
  intact. The clock is stalled, not burning.

## Also found (2026-08-18, prod)

- **MT0 is CLOSED.** Zero DRIFT lines in 7d of `doug-api` logs while the
  cold-start check ran repeatedly (6 startup sweeps in the last 7h). The
  roadmap already said so ("MT0 was closed operationally the same day",
  2026-08-05); the unchecked `- [ ] MT0` box and the old handoff disagreed.
  **Tick the box.**
- **`doug-outcome-reconciler` has NEVER executed.** The Job is deployed;
  Cloud Scheduler holds only `doug-adjudicator-daily`. `schedule-reconcile`
  was never run. So the outcome-reconcile lane runs only in the reaped
  startup thread → MT3's coverage hole is live today, not hypothetical.
  (Check intent first: MT3's D2 moves the full sweep INTO that Job, so
  leaving it unscheduled may be deliberate.)
- **Zero alert policies, zero notification channels** in doug-prod0.
- ~~The Job runs stale code after every merge.~~ **WRONG — see the
  correction at the top of this file.** `deploy()` refreshes both Jobs.
- `deep_reads 200/200` on the public meter is `PLAN_DEEP_READ_CAP`
  saturating for display only; enforcement is `INSTALLATION_MONTHLY_READ_CAP
  = 4000`. Not blocking, but the public meter reads pegged for August.

## Recommended order

1. ~~The two-line bind + a test that can fail~~ DONE, uncommitted.
   Deploy + manual execution remain — see Next, and note that merging alone
   does NOT deploy the Job.
2. Watch one real adjudication land; check one receipt end-to-end. That
   closes the last open half of the M3 exit gate.
3. The liveness item: surface `first_due` in the past + `adjudicated 0` as
   the contradiction it is, and alert on adjudicator `failedCount >= 1`.
   Roadmap has it under M3; nothing is built.
4. MT3 (spec approved, decisions locked below).
5. M4's 3 prospect interviews — highest information per hour in the plan,
   and they carry the standing kill criterion. Gated on a scoreboard that
   shows a real number, which is gated on step 1.

## MT3 — decisions locked (do not re-litigate)

- D1 Design for the org-install case (10k repos), not design-partner scale.
- D2 Full sweep moves to its own scheduled Cloud Run Job, mirroring
     doug-outcome-reconciler. Startup thread drops the full sweep.
- D3 Job ENQUEUES ONLY; drain stays in the API. Keeps the Job SA narrow.
- D4 One shared primitive applied to BOTH lanes.
- D5 Startup thread keeps a BOUNDED stalest-N pass — not nothing.
     Rejected: accept the regression; shorten the Job cadence.
- CONSEQUENCE: THREE entry points, three different bounds — unbounded
  (installation.created), budgeted (Job), bounded (startup). Collapsing any
  two is a regression that looks like correct behaviour. One test per site.
- Design: staleness within a tenant, round-robin across tenants.
- REJECTED: global staleness ordering — a 10k-repo tenant joining degrades
  every other tenant 200x, which is MT3's own complaint.
- REFUTED: that global interleaving re-mints a token per repo. githubkit's
  DEFAULT_CACHE_STRATEGY is a module-level singleton — verified empirically.
- MT3 takes migration **11** (9 = Front Door 1a, 10 = review_jobs.base_sha).
  `installations.reconciled_at` cannot close it: sweep state is per REPO.
- MT3 is a CORRECTNESS item: `active_repos` has no ORDER BY and
  `reconcile_all`'s only caller is a reaped daemon thread, so the tail is
  never swept on any cold start.

## Decision debt — Andrew's call, blocks the scoreboard spec

- #106 ships ten fields (`api.py:718-727`) and **none** of prereg §3's
  disclosure columns — no `censoring_rate`, `N_at_risk`, `misses`,
  `unverdicted_merges`, `partial_read_share`, `repos_withheld`. §3 says
  "Published together, never separately."
- Approach A §4.3 says the venue "can be the scoreboard page"; the later
  ruling ("the scoreboard is proof, not venue") says the opposite. Later
  ruling should govern and §4.3 should be amended. Neither is written down
  outside a session transcript, so no code review can see it.
- Latent trap live on main: the zero state is pinned in three coupled places
  (`miss_rate: None` in Pydantic, `miss_rate: null` as a TS literal, and
  `isScoreboardResponse` rejecting anything else), and on validation failure
  `cachedShowcaseFetch` silently serves a fixture reading `adjudicated: 0`.
  **Note the shape** — that fallback is the same mask as the defect above.

Pointers: branch `claude/doug-next-priorities-5851da` off main @ 412298e ·
          fix in `api/doug/outcome_worker.py:36,40` ·
          precedent + lifetime note `api/doug/tenancy.py:220-225` · the
          test that cannot fail `api/tests/test_outcome_worker.py:121` ·
          MT3 spec
          docs/superpowers/specs/2026-08-17-reconcile-sweep-scheduling-design.md
          · roadmap docs/design/outcome-loop/ROADMAP.md (grep item names,
          line numbers shift) · prereg §3
          docs/design/outcome-loop/publication-preregistration.md:337
