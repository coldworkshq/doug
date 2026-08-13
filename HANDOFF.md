# HANDOFF — doug

State:    review — /docs 404 root-caused and fixed, code review run at medium
          and all 4 findings fixed. web 204/204 + lint + build (11 docs routes)
          · api 1344/1344 + ruff. 3 commits off main @ b3fa8d8.

Next:     Merge the PR. /docs STAYS 404 until this lands on main and the deploy
          runs — nothing about the fix is live yet.

Blockers: none

Decisions this session:
- ROOT CAUSE of the /docs 404: `.gcloudignore` is gitignore syntax, where a
  bare `docs` matches a dir named docs at ANY depth; `.dockerignore` anchors
  bare patterns to the context root. The two were deliberately kept
  BYTE-IDENTICAL by test_root_gcloudignore_tracks_dockerignore_for_node_builds,
  so the shared `docs` line stripped web/app/docs/** and web/components/docs/**
  from `gcloud builds submit` ONLY — the one context nothing exercised. Pages
  and the components they import vanished together, so no import dangled,
  `next build` went green on 11 routes instead of 21, and the deploy smoke test
  only probes `/`. site-header.tsx is not under a docs/ dir, so the Docs link
  shipped pointing at a route never compiled. Proven with
  `gcloud meta list-files-for-upload` and by pulling the live image, whose
  app-paths-manifest.json lists 11 routes and no docs.
- FIX: anchor /api /docs /data /out /reports in BOTH files. Docker Cleans a
  leading slash away, so `/docs` is root-only in both — semantics now agree AND
  the text stays identical, so the lockstep pin still holds — rejected:
  deleting that pin (still load-bearing, just insufficient alone).
- The docs CONTENT needed nothing: /docs is already a faithful port of the
  gh-pages site (same 5 groups, 11 sections, real commands and numbers). The
  ask was "build a Stripe-like docs page"; it was already built in #101 and
  had simply never been served — rejected: writing new content before Andrew
  can see what exists.
- Two rendering bugs found by being the first to ever render this surface:
  DocsTwoCol's rail lacked min-w-0 (below lg the grid collapses to one column,
  the rail's min-content = the code block's longest line, so the column
  stretched to 462px in a 375px viewport and clipped body copy off the right
  edge of EVERY docs page on mobile); ParamsTable's name overflowed its 13rem
  track.
- Code review (medium) found 4 real defects in THIS branch's own code, all
  fixed: nowrap on the meta re-overflowed the track (216px vs 208px); and the
  new pin inherited the dev's global core.excludesFile (spurious red on some
  machines, green in CI), never checked check-ignore's returncode (a git error
  = empty stdout = vacuous pass), and parsed `git ls-files` with .split()
  (breaks on paths with whitespace, silently dropping the file it covers).
- The "pl/anned" tearing was NOT an overflow-wrap problem: {r.name} and the
  meta span are adjacent JSX expressions with no whitespace text node between
  them, and ml-2 is a margin, not a break opportunity — so the run was
  unbreakable and the browser had to split mid-token. Fixed with an explicit
  {" "} — rejected: flex-wrap (works, but items-baseline inflates a two-line
  name's line box by 42px).

Pointers: worktree .claude/worktrees/hosted-docs-page-365b6f · branch
          claude/hosted-docs-page-365b6f · fix in .gcloudignore +
          .dockerignore · pin at api/tests/test_deploy_gcp.py:472 · components
          web/components/docs/{docs-two-col,params-table}.tsx · pages
          web/app/docs/* · nav web/lib/docs-nav.ts
          Untracked and deliberately NOT committed: .claude/launch.json (local
          preview config; the repo does not track .claude).
