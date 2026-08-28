# HANDOFF — doug

State:    review — the org move's real casualty was the OUTCOME LOOP, not the
          dashboard. Fix + repair built and green on branch
          worktree-backfill-historical-runs (worktree
          .claude/worktrees/backfill-historical-runs). api 1714 passed, ruff
          clean, web 376, console 113.
Next:     Open the PR, merge, DEPLOY (the fix only helps once deployed), then
          run the repair against prod with the proxy up:
            uv run python scripts/repair_transfer_censored.py --dry-run \
              --from-gcp doug-prod0
            uv run python scripts/repair_transfer_censored.py --apply \
              --expect-outcomes 15 --manifest <abs path> --from-gcp doug-prod0
          Dry-run against prod already returns exactly 15/15/15.
Blockers: none. Deadline: the next wrong censoring lands 2026-08-30 (PR 108).

## What was actually wrong

Andrew's report was "the dashboard lost every pre-org-move run". True, and
harmless — but underneath it the outcome adjudicator had been silently
destroying the dogfood corpus since the transfer.

`outcome_queue._repository_identity` set
`permanent = installation_state == "deleted" or repo.state != "active"`.
After the 2026-08-26 transfer BOTH held for installation 150424894 +
github_repo_id 1314318717 (`installations.state='deleted'`,
`installation_repos.state='removed'`) while the repo stayed perfectly
readable under active installation 153075663. `permanently_unreachable`
makes outcome_worker adjudicate with `revert_map={}, default_branch=None`,
which settles every job as `censored` — terminal, never retried, and a
censored PR leaves the risk set, so this ran in the flattering direction.

Measured in prod (SELECT only, scratchpad/census{,2,3,4}.py):
  2026-08-26  11 clean    PRs 82-92   — last healthy day
  2026-08-27  13 censored PRs 93-105
  2026-08-28   2 censored PRs 106-107
165 more pending jobs were queued to follow, through 2026-10-25, covering
every 60-day window for PRs 28-223.

## What shipped

1. `outcome_queue._live_registration` — resolve a repo id to the
   installation that covers it NOW (both `installation_repos.state` and
   `installations.state` active, newest wins, matching `store.repo_id_for`).
   Consulted ONLY when a row would otherwise be censored, so nothing about
   which jobs get adjudicated widens. `ClaimedBatch.reader_installation_id`
   carries it; `outcome_worker._repository_evidence` mints the clone token
   through it. The outcome still settles under the job's own installation —
   who paid for the verdict does not change.
2. `store.installation_lineage` + `_tenant_ids`, and `installation_ids=` on
   run_history / latest_reviews / _load_verdict_row / run_detail /
   job_health. `api._readable_installations` unions the lineage with the
   session's own installation. Tenancy boundary is unchanged: every caller
   pairs it with `repo_ids=` over the same proven set, so a row is visible
   only if the session provably holds that repo NOW and the writing
   installation provably held it once. Test
   `test_the_lineage_widens_installations_but_never_repositories` pins that.
3. `doug/transfer_repair.py` + `scripts/repair_transfer_censored.py` —
   dry-run/apply/rollback with a manifest of the whole deleted row. Repairs
   a row only when it is censored AND `censor_reason == 'unreachable'` AND a
   live successor installation exists. The two legitimate `base_ref`
   censorings (PRs 40, 46, 2026-08-18) are excluded by that predicate, not
   by a date.

## Decisions this session

- RULING (Andrew): fix identity resolution, do not write migration 18.
  Rejected: flipping installation_id across 261 verdicts + 269 review_jobs +
  79 outcomes + 244 outcome_jobs — mirrors migration 17 but is a one-off
  (the next transfer needs migration 19) and erases that drewjst ever
  scored those runs. Precedent for the chosen shape: #218 ("installation_id
  remains operational plumbing only") and #228's name-alias fix.
- RULING (Andrew): the pre-App CI-token era stays out — 87 runs / 43 PRs
  (PRs 9-53) with installation_id AND github_repo_id both NULL. Adopting
  them means inventing a tenancy no installation ever had, and
  `include_untenanted=False` is load-bearing (it also excludes 653
  probe-corpus rows). Filed as an issue.
- `receipt` and `_select_governing_verdict` deliberately NOT widened:
  §2.2's publication partition keys on installation_id, so widening it
  would change a pre-registered published quantity. Filed separately.
- #228's hazard has ALREADY FIRED, contrary to its "when it flips" framing:
  the old junction row is `removed` today, so historical sticky-comment
  receipt links are 404ing now.

Pointers: api/doug/outcome_queue.py `_live_registration` ·
          api/doug/outcome_worker.py:105 · api/doug/store.py
          `installation_lineage` / `_tenant_ids` · api/doug/api.py
          `_readable_installations` · api/doug/transfer_repair.py ·
          scratchpad/census{,2,3,4}.py · issues #218, #228

--- prior stream (#252 landing facelift) below, preserved ---

State:    review — landing facelift is PR #252 OPEN off origin/main
          (e61fa03), branch landing-facelift, one commit, rebased over #246
          (HANDOFF.md conflict resolved by stacking streams). Verified after
          the rebase: web 376 pass, tsc clean, eslint clean (2 pre-existing
          <img> warnings on /about). Screenshotted at 1280 light+dark and
          390 light, fixture data only — no local API.
Next:     Watch CI on #252, then Andrew merges. Open question for Andrew:
          the cost section names `/code-review` by name — keep or
          generalise.
Blockers: none

Decisions this session:
- 2026-08-27: palette and tokens stay (design-system/dashboard-contract/
  site-bar tests pin them); the facelift is layout, type, structure, copy.
  Bricolage gets its opsz+wdth axes for a condensed hero — rejected: a new
  display face (the console shares the brand tokens).
- The hero object is a facsimile of the neutral check run rendered from the
  live queue + scoreboard (headline, table, Needs-you note, footer lines) —
  rejected: the stat card, which no competitor could not also render.
- Cost claim is structural, no dollar figures: one bounded read per PR and
  a human reads only the flagged fraction — ADR-0004 forbids "no model in
  the hot path"; pricing belongs in the private hq repo.
- Pinned copy stays in app/page.tsx (landing-copy.test.mjs,
  public-surface.test.mjs, auth-entry.integration.test.mjs read it).
Pointers: branch landing-facelift · web/app/page.tsx ·
          web/components/landing/ · web/app/layout.tsx (font axes) ·
          web/app/globals.css (landing utilities, ABOVE the lockstep block)

--- prior stream (#246 deploy gate, merged) below, preserved ---

State:    review — PR #246 OPEN off origin/main (6d907b1, branch
          worktree-restore-auto-deploy, in worktree
          .claude/worktrees/restore-auto-deploy). Restores automated
          deploy-on-merge: ADR-0021's reviewer gate retired, its WIF ref
          pin kept. The `production` GitHub environment is already DELETED
          live (2026-08-28) — that half is done and does not wait on merge.
          Doug's 3 findings + 2 deviations on e72f135 all settled;
          5 rows in docs/findings-log.jsonl. Rebased onto c081aaa (#243)
          to clear a findings-log conflict. All six CI checks green;
          mergeable.
          ALREADY PROVEN LIVE: run 33141122253 deployed c081aaa to
          production in 10m08s with no approval step, vs 17h00m / 8h56m /
          one cancelled at 13h29m under the gate. Both services promoted,
          which also settles auth-config-change empirically.
Next:     Andrew merges #246. Nothing to click afterwards.
Blockers: none

Decisions this session:
- 2026-08-28: retire ADR-0021's reviewer gate, keep its ref pin — the gate
  cancelled #229's deploy outright (run 33042841775, evicted from the
  concurrency group's pending slot one second after the next merge's run
  was created) and held others up to 17h, so main and production disagreed
  for most of two days. Rejected: keeping the environment and deleting only
  the reviewer rule (a settings click could re-gate with no diff), and
  fixing the eviction with a per-SHA concurrency group (closes the silent
  cancellation, leaves the hours of drift, which is the gate working as
  designed).
- 2026-08-28: delete the environment rather than strip it, and pin the
  ABSENCE of `environment:` in test_deploy_jobs_name_no_github_environment
  — the protection rule lives in GitHub settings where no diff shows it, so
  the reviewable artifact has to be the workflow key.
- 2026-08-28: ADR-0025 `amends` ADR-0021, not `supersedes` — the ref pin
  survives and must keep reaching the reader. Markers on both sides, plus
  ADR-0009's banner corrected (it still asserted the gate).
- 2026-08-28: Doug's auth-config-change and missing-config-dependency are
  both DISPROVED, but only after checking live rather than asserting —
  deployer SA's only binding is the principalSet on attribute.repository
  (no principal://.../subject/ member), applied condition is
  repository && refs/heads/main, deploy.yml has zero secrets.* and two
  repo-scoped vars.*. Rejected: leaving ADR-0025's "verified while settling
  #223" citation, which was the thing the finding correctly objected to.
- 2026-08-28: beyond-ticket was the sharpest finding — the ref pin became a
  single point of failure and was defended only in prose. Two of ADR-0021's
  three "must agree" legs now pinned by
  test_setup_cicd_pins_both_the_repository_and_the_ref (mutation-verified
  red). Third leg deferred to #247, NOT landed blind: it needs a gcloud
  call from the deploy job and the deployer SA probably cannot read the
  pool — a 403 would fail healthy deploys, the same trap #225 named.

Watch out:
- Running a mutation test on a file the background /code-review agent is
  also editing will clobber its fix on restore. It happened here with
  deploy.yml; re-check `git status` after any backup-restore cycle.
- api/.venv in THIS worktree is fresh. The one in the main checkout still
  needs `uv sync --reinstall` after the org move.

Pointers: branch worktree-restore-auto-deploy · PR #246 · issues #247 (open,
          WIF drift check) and #225 (closing from #246 as obsolete) ·
          .github/workflows/deploy.yml · api/deploy/setup-cicd.sh ·
          api/tests/test_deploy_gcp.py (both new guards) ·
          docs/decisions/ADR-0025-a-merge-deploys-without-waiting.md ·
          ADR-0021 and ADR-0009 amendment banners ·
          docs/findings-log.jsonl (last 5 rows).
          Prior session's #235/PR #243 work is on branch
          fix-235-findings-log-rule-prefix in the main checkout.
