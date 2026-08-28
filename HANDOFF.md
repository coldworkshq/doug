# HANDOFF — doug

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
