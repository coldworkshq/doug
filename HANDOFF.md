# HANDOFF — doug

State:    review — PR #193 open (feat/wider-dock-legible-ledger): dock stops
          400/560/640, --dim to 4.65:1, --rule-soft to 1.20:1, rows 34→38px.
          Web suite 345/345, lint clean (2 pre-existing <img> warnings on
          /about), build clean. Not merged — merging deploys (ADR-0009) and
          that is Andrew's call.
Next:     Andrew merges #193 after a look at the deploy, or says which of the
          numbers to adjust (dock stops, row height, --dim #757269).
Blockers: none
Decisions this session:
- The 1620 dock stop stays at 400 — measured, a 440 dock leaves the title
  column ~148px there vs ~188px, which buys dock prose with the master
  column's ability to name a row — rejected: widening all three stops.
- Only --dim and --rule-soft were retuned, not the whole palette — --dim at
  2.3:1 was painting the smallest text on the page; --rule-soft is capped by
  --border (1.22:1) so row separation came from height (34→38px) instead —
  rejected: darker dividers, zebra striping.
- design-system.test.mjs pin MOVED to the new hex rather than loosened — the
  A5.6 ruling forbids substituting a palette neighbour, not correcting a value
  that fails to be legible — rejected: a range assertion.
- Verified against a static 2000px mock served over localhost, not the real
  dashboard — /dashboard needs WorkOS auth + the API and has no fixture mode —
  rejected: standing up auth locally for a CSS change.
- PR #193's first push ran NO CI: the branch came off a stale local main (3
  behind origin) and conflicted on HANDOFF.md, and GitHub cannot build the
  merge ref for a CONFLICTING pr, so `pull_request` workflows never fire. The
  only check was Doug's own, reporting `skipping`. A checks-empty PR page is
  the symptom to watch for — rejected: reading the silence as "nothing to run".
- Updated the branch by MERGING origin/main, not rebasing — the force-push a
  rebase needs was blocked by the permission classifier, and the merged tree
  was verified byte-identical to the rebased one before pushing — rejected:
  asking for force-push rights for a change that did not need history rewritten.
- The HANDOFF.md trim in this PR (-846 lines) is safe: main's 849-line copy is
  byte-for-byte archived at workspace/handoff-archive-2026-08-23.md, confirmed
  with diff — rejected: assuming the archive existed.
Pointers: PR #193 · branch feat/wider-dock-legible-ledger, merged up to
          origin/main @ a309395 ·
          web/app/dashboard/page.tsx (dock grid ~line 1600, COLUMNS, TD/TH) ·
          web/app/globals.css (.dashboard-surface tokens) ·
          mock + screenshots in the session scratchpad (mock.py, before.html,
          after.html, ledger-before.jpg, ledger-after.jpg)
          NOTE: a stash holds the PR #188 branch's uncommitted HANDOFF.md trim
          ("pr188 handoff trim"), backed up at scratchpad/HANDOFF-pr188-backup.md
