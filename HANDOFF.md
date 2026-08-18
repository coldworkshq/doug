# HANDOFF — doug

State:    **blocked — PRODUCTION STILL DARK. Second defect in the same
          never-executed path.** #113 merged (383daf6) and its fix WORKS —
          the traceback now gets past `_github_context`. It dies further
          down: the runtime image has no `git`.

Next:     1. Verify + ship `fix/adjudicator-needs-git` (branch cut from
             origin/main, 2 files dirty, no commit yet):
             `api/Dockerfile` installs git in the final stage;
             `.github/workflows/ci.yml` runs the built image
             (`docker run --rm doug-api-candidate git --version`) instead of
             only building it.
          2. **DO NOT re-run the Job before 16:20 UTC.** The 14:20 crash died
             AFTER `claim_repository`, so that batch is leased `running` for
             STALL_LEASE_SECONDS = 7200. `due_repositories()` selects only
             `status == 'pending'`, so every execution until the lease expires
             exits 0 having done nothing — which is exactly what `-m7vmr`
             (14:27, "Execution completed successfully") did. Scoreboard after
             it: `adjudicated 0 · pending 170`.
          3. Then execute the Job and confirm non-zero `done`.

Blockers: the image. Nothing else known.

## CORRECTION — I was wrong about the deploy trap

The "merging does not deploy the adjudicator" claim in commit 86807ee, PR
#113's body, and the ROADMAP is **FALSE**. `deploy()` in `gcp.sh` calls
`adjudicator` and `reconcile_job` at its end, and `deploy.yml:132` says so:
"then refreshes doug-adjudicator from the promoted image". Proven: after the
#113 merge both API and Job moved to `@sha256:d12a4f4c` with no manual step.
Origin of the error: a `grep | head -20` that truncated before those lines,
plus reading gcp.sh's header ("`deploy` and `web` are what CI runs") as the
full list of what deploy does. **The ROADMAP paragraph "Deploy trap, recorded
2026-08-18" must be deleted — it is a fabricated hazard sitting in the
document this project uses to decide what is true.** Carry that into the next
PR. The commit message on main cannot be amended; PR #113 needs a correction
comment (not yet posted — needs Andrew's word, it is a public write).

What survives: `doug-outcome-reconciler` still has ZERO executions and Cloud
Scheduler still holds only `doug-adjudicator-daily`. That was about the
scheduler, and `deploy` does not create schedulers.

## THE SECOND DEFECT — 2026-08-18, verified in prod

    doug-adjudicator-hvdfn  14:20Z  exit 1
      File "/app/doug/backtest/git_labels.py", line 112, in clone_treeless
        subprocess.run([...])
      FileNotFoundError: [Errno 2] No such file or directory: 'git'

- Final stage is `python:3.14-slim-trixie`, copies only `/app`, installs
  nothing. The Job runs `python -m doug.outcome_worker` from that image.
- `git` is the ONLY missing binary: the import closure of `outcome_worker`
  reaches `backtest.git_labels` (git clone/fetch/log) and never `harvest`
  (the only `gh` caller).
- Auth needs nothing extra — `_git_auth_env` injects `GIT_CONFIG_*`, no
  credential helper, no netrc.
- Hidden by the SAME structural fact as the client bug and for the third
  time running: the drain path had never executed against real work, so
  twelve green executions carried no evidence about any of it.
- `docker build api` in CI never ran the image it built. That is the check
  that could have caught this and didn't.

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
