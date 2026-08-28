# HANDOFF — doug

State:    review — PR #246 OPEN off origin/main (aeea209, branch
          worktree-restore-auto-deploy, in worktree
          .claude/worktrees/restore-auto-deploy). Restores automated
          deploy-on-merge: ADR-0021's reviewer gate is retired, its WIF
          ref pin is kept. The `production` GitHub environment is already
          DELETED live (gh api -X DELETE, 2026-08-28) — that half is done
          and does not wait for the merge.
Next:     Watch CI on #246, then Andrew merges. That merge deploys
          automatically with nothing to click; confirm doug-api and
          doug-web promote.
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

Pointers: branch worktree-restore-auto-deploy · PR #246 ·
          .github/workflows/deploy.yml ·
          api/tests/test_deploy_gcp.py::test_deploy_jobs_name_no_github_environment ·
          docs/decisions/ADR-0025-a-merge-deploys-without-waiting.md ·
          ADR-0021 and ADR-0009 amendment banners.
          Prior session's #235/PR #243 work is on branch
          fix-235-findings-log-rule-prefix in the main checkout.
          api/.venv in THIS worktree is fresh; the one in the main checkout
          still needs `uv sync --reinstall` after the org move.
