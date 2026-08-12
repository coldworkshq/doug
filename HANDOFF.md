# HANDOFF — doug

State:    building — /docs 404 in production is ROOT-CAUSED AND FIXED (deploy
          config, not the pages). Now building out the docs content itself.
          api 43/43 deploy tests pass. Branch claude/hosted-docs-page-365b6f.

Next:     Render /docs locally from the built image and judge the existing 11
          pages against the "Stripe-like" bar before writing content — these
          pages have NEVER been seen rendered by anyone, in any environment,
          because they never shipped.

Blockers: none

Decisions this session:
- ROOT CAUSE of the /docs 404: `.gcloudignore` is gitignore syntax, where a
  bare `docs` matches a dir named docs at ANY depth; `.dockerignore` anchors
  bare patterns to the context root. The two files were deliberately kept
  BYTE-IDENTICAL by test_root_gcloudignore_tracks_dockerignore_for_node_builds,
  so the shared `docs` line stripped web/app/docs/** and web/components/docs/**
  from `gcloud builds submit` ONLY — the one context nothing exercised. Pages
  and the components they import vanished together, so no import dangled,
  `next build` went green on 11 routes instead of 21, and the deploy smoke test
  only probes `/`. site-header.tsx is not under a docs/ dir, so the Docs link
  shipped pointing at a route never compiled. Proven with
  `gcloud meta list-files-for-upload .` (152 files → 0 under web/app/docs) and
  by pulling the live image: app-paths-manifest.json has 11 routes, no docs.
- FIX: anchor /api /docs /data /out /reports in BOTH files. Docker Cleans a
  leading slash away, so `/docs` means root-only in both — semantics now match
  AND the text stays identical, so the existing lockstep pin still holds.
  Verified 3 ways: gcloud lister 152→173 (+21, exactly the missing files),
  and a COPY . probe under BuildKit AND legacy builder (root docs/ + api/ still
  excluded, web/app/docs = 12 files) — rejected: deleting the lockstep test
  (it is still load-bearing, just insufficient on its own).
- Added test_gcloudignore_keeps_every_tracked_web_source_file_in_the_upload:
  asserts every tracked non-.md web/console file survives the ignore filter,
  using a scratch git repo as the gitignore oracle (no new dependency; cannot
  drift from real matching the way a hand-rolled matcher would). CONFIRMED it
  fails on the pre-fix state naming all 21 files, while the byte-identity test
  still passed — that is the whole point of adding it.

Pointers: worktree .claude/worktrees/hosted-docs-page-365b6f · fix in
          .gcloudignore + .dockerignore (lines 36-40 / 15-19) · new pin at
          api/tests/test_deploy_gcp.py:472 · pages web/app/docs/*,
          components web/components/docs/*, nav web/lib/docs-nav.ts
          NOT YET DONE: this fix is unshipped — /docs stays 404 until it
          merges to main and the deploy runs.
