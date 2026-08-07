# HANDOFF — doug

State:    review — PR #63 open (console-ux), CI running
Next:     Watch #63 checks; merge when green, then redeploy doug-console
          (`bash deploy/gcp.sh console` from api/, project doug-prod0).
          Console changes do NOT auto-deploy — deploy.yml's `changes` job
          only greps ^api/ and ^web/, so `console` has no filter branch.
Blockers: none
Decisions this session:
- Grouping/sorting/facets computed client-side over the fetched page, not
  server-side — correct at any size but buys nothing at 68 runs; rejected:
  new ?sort=/?group= query params, store functions and pytest coverage.
- Fetch raised 100 → 500 (API max) and `atCap` degrades group counts to
  "8+" — the three new features can each assert a fact the page lacks,
  and this is the one flag that already existed to catch it.
- Absent coverage sorts LAST in both directions; "no read" is not 0%.
- Accordion state is local, not URL; facet state IS in the URL (shareable),
  written via native history API to avoid a server refetch per click.
Pointers: branch console-ux · PR #63 · console/lib/{grouping,sorting,facets}.ts
          + console/components/{runs-table,facet-bar}.tsx · 55 node --test cases
          · worktree .claude/worktrees/console-ux

## Deferred (Phase 2 queue, unchanged)
- failed-job surface + live health strip (needs a jobs-keyed query; a failed
  attempt has no verdict row, so it cannot appear in run_history)
- render-test infrastructure for console components (all 55 tests are pure
  logic; the table/pill components have no automated render coverage)
- /v1/repos + Repos page
- mark unseen files by read tier
