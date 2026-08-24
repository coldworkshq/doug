# HANDOFF — doug

State:    review — dashboard UX pass on branch feat/wider-dock-legible-ledger,
          committed, not pushed. Web suite 345/345, lint clean (2 pre-existing
          <img> warnings on /about), build clean.
Next:     Andrew looks at the before/after and says push + PR, or adjusts the
          numbers (dock stops 400/560/640, row height 38px, --dim #757269).
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
Pointers: branch feat/wider-dock-legible-ledger off main @ d6dd0eb ·
          web/app/dashboard/page.tsx (dock grid ~line 1600, COLUMNS, TD/TH) ·
          web/app/globals.css (.dashboard-surface tokens) ·
          mock + screenshots in the session scratchpad (mock.py, before.html,
          after.html, ledger-before.jpg, ledger-after.jpg)
          NOTE: a stash holds the PR #188 branch's uncommitted HANDOFF.md trim
          ("pr188 handoff trim"), backed up at scratchpad/HANDOFF-pr188-backup.md
