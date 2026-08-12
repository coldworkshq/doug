# HANDOFF — doug

State:    review — dashboard-ux is code-complete and every automated gate is
          green, but the four behaviours have NEVER been seen in a browser.
          Not mergeable until Andrew looks at it.
          web 204/204 · console 110/110 · tsc clean (both) · eslint clean ·
          `npm run build` clean (20 routes). 23 commits off origin/main @ 7f64652.

Next:     ANDREW RUNS IT. `npm run dev --workspace=web` from the worktree needs
          WorkOS credentials this repo does not carry — the dev server errors with
          "You are calling 'withAuth' on a route that isn't covered by the AuthKit
          middleware" and /dashboard never renders. Check, in this order:
          1. THE TABLE. Four CSS mechanisms compose here and every pin on them is a
             string grep: sticky <th> inside a container that is both overflow-x-auto
             (base) and overflow-y-auto + max-h-[55vh]; border-separate with cell-level
             borders; the :has() disclosure under the separated model; horizontal
             scroll below 980px. FIRST: find a run with job.error set and look at the
             job column — it is w-[118px], fixed layout, arbitrary-length string.
          2. THE GEAR IN DARK MODE. Toggle dark on the marketing site, then open
             /dashboard and open the gear. This was a confirmed defect (see C1 below);
             the fix is unobserved. Also check it isn't clipped by the sticky header.
          3. THE SPACE PICKER IN FIREFOX AND SAFARI. The keyboard path was traced
             against Chrome's event model only. Firefox historically does not fire
             `change` on arrow keys in a closed <select>; if it doesn't, `pending` is
             never armed and the onBlur commit silently does nothing.
          4. THE TYPE SCALE. Band column is w-[112px], sized when the chip was 10.5px
             and could wrap; the chip is now 11.5px and TableCell forbids wrapping.

Blockers: WorkOS credentials for a local dev server. Not a code problem.

Decisions this session:
- The threshold control is a VIEW LENS, not a setting — the needs-you line is a
  server-side env var stamped per verdict at scoring time, so no UI can change what
  Doug did — rejected: a real persisted per-space threshold (store schema + endpoint
  + worker read; would only affect future runs), and a plain "score >= X" filter
  (honest but can't answer "what would a tighter line have caught?")
- The lens rewrites `band` on the row objects at the boundary rather than threading a
  `lens` parameter — five of the modules that read `run.band` are byte-locked to
  console's copies, so a parameter would have been rejected by the lockstep; the
  rewrite also makes pills, counts, chips and the count line agree for free —
  rejected: re-colouring chips only (pills would then disagree with the table)
- `.paper-tokens` as a third selector on the SHARED palette block — rejected: a second
  copy of the values in the component (globals.css's own comment warns it will drift),
  and removing Radix's Portal (changes clipping semantics for every future popover)
- Space picker commits on pointer immediately, defers keyboard to Enter/Tab/blur —
  auto-submitting every `change` navigates on every arrow key (WCAG 3.2.2) — rejected:
  shipping the naive version Andrew asked for, and keeping the "open" button visible
- The branch does NOT touch package-lock.json — shadcn add pulled zero new deps; the
  29 "peer": true lines were npm renormalising metadata — rejected: committing the
  churn with a corrected description
- Type scale bumped in console/ too, for band-chip.tsx and run-spine.tsx only — that is
  what the lockstep pin is for. COST, not yet addressed: console's own surfaces were
  not bumped, so those two components are now oversized inside console
  (console/components/runs-table.tsx:646, console/app/runs/[verdictId]/page.tsx:104)

Pointers: worktree .worktrees/dashboard-ux · branch dashboard-ux · spec
          docs/superpowers/specs/2026-08-12-dashboard-ux-design.md · plan
          docs/superpowers/plans/2026-08-12-dashboard-ux.md · SDD ledger with every
          review round, parked finding and deferred minor at
          .superpowers/sdd/2026-08-12-dashboard-ux/progress.md
          THREE PLAN DEFECTS were caught by review, not by tests, and all three are
          worth knowing about: the gear's Clear button re-applied the lens (duplicate
          name="threshold" fields, first-value-wins); a /sticky/ assertion that a doc
          comment could satisfy; and C1, a Radix portal escaping .dashboard-surface so
          the popover rendered dark over the light page — the only portal in the app.
