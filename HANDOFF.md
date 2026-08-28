# HANDOFF — doug

State:    review — PR #251 OPEN off origin/main (91c3204, branch
          worktree-backfill-historical-runs, worktree
          .claude/worktrees/backfill-historical-runs). All 6 CI checks
          green; MERGEABLE. Two rounds of Doug's own review dispositioned,
          13 rows in docs/findings-log.jsonl. api 1728, ruff clean, web 376,
          console 114.
Next:     Andrew merges, DEPLOY, then run the repair (commands below).
          Doug's read of 91c3204 had not landed at handoff time — its
          comment still names head 660a974.
Blockers: none. DEADLINE: the next wrong censoring lands 2026-08-30 03:00
          UTC (PR 108), scheduler doug-adjudicator-daily `0 3 * * *`.
          Merging and deploying before then means it never happens.

## Why this PR exists

Andrew asked why the dashboard had lost every pre-org-move run. It had —
261 runs / 121 PRs behind a filter, nothing deleted — but underneath that
the outcome adjudicator had been destroying the dogfood corpus since the
2026-08-26 transfer.

`outcome_queue._repository_identity` treated
`installations.state='deleted' or installation_repos.state != 'active'` as
permanent blindness. Both hold after a transfer, while the repo stays
readable under the successor. `permanently_unreachable` settles every job
`censored` — terminal, and a censored PR leaves the risk set, so it ran in
the flattering direction with nothing to alert on.

  2026-08-26  11 clean     PRs  82-92   last healthy day
  2026-08-27  13 censored  PRs  93-105
  2026-08-28   2 censored  PRs 106-107
  queued: 165 pending jobs through 2026-10-25 (every 60-day window, PRs 28-223)

## After merge + deploy — the repair

Deploy FIRST; applied before the fix is live, the next drain re-censors the
same rows.

  cloud-sql-proxy doug-prod0:us-central1:doug-ledger --port 5433
  cd api
  uv run python scripts/repair_transfer_censored.py --dry-run --from-gcp doug-prod0
  # must print 15; anything else means STOP and re-read
  uv run python scripts/repair_transfer_censored.py --apply \
      --expect-outcomes 15 --manifest <ABSOLUTE path> --from-gcp doug-prod0

Keep the manifest — it is the only way back (`--rollback`, same
`--expect-outcomes`, idempotent). Verify after the next 03:00 UTC drain:
`SELECT kind, count(*) FROM outcomes WHERE github_repo_id = 1314318717 AND
observed_at >= CURRENT_DATE GROUP BY 1;` — want clean/revert, not censored.

## Decisions this session

- RULING (Andrew): fix identity resolution, not migration 18. Rejected:
  flipping installation_id across 261 verdicts + 269 review_jobs + 79
  outcomes + 244 outcome_jobs — mirrors migration 17 but is a one-off and
  erases that drewjst ever scored those runs. Precedent: #218, #228.
- RULING (Andrew): the pre-App CI-token era stays out — 87 runs / 43 PRs
  (PRs 9-53), NULL in both installation_id and github_repo_id. Adopting
  them invents a tenancy that never existed, and include_untenanted=False
  also excludes 653 probe-corpus rows. Issue #249.
- `receipt` and `_select_governing_verdict` deliberately NOT widened:
  §2.2's publication partition keys on installation_id, so widening changes
  a published quantity, not a view. Issue #250 — until it lands, every
  restored run's receipt LINK is dead.
- Doug's `reader:read-scope-widening` was right that the repo_ids pairing
  was a docstring convention. `_tenant_ids` now takes repo_ids and raises
  on an unpaired lineage, so it is checked rather than remembered.
- Doug's `reader:identity-inconsistency` is real and ALREADY LIVE: outcomes
  for repo id 1314318717 hold 'coldworkshq/doug' x77 AND 'drewjst/doug' x2
  (PRs 106/107, settled after migration 17), so run_history's name-keyed
  outcome join misses them. Self-clears via this PR's repair; the defect
  re-forks on the next transfer. Issue #256.
- #228's hazard has ALREADY FIRED — the old junction row is `removed`
  today, so historical sticky-comment receipt links are 404ing now.

Issues opened: #249, #250, #255 (transfer between UNRELATED accounts —
tenancy contract decision debt), #256. Commented on #218 and #228.

Pointers: api/doug/outcome_queue.py `_live_registration` ·
          api/doug/outcome_worker.py `reader_installation_id` ·
          api/doug/store.py `installation_lineage` / `_tenant_ids` ·
          api/doug/api.py `_readable_installations` ·
          api/doug/transfer_repair.py + scripts/repair_transfer_censored.py

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
