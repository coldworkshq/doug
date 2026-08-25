---
title: The console follows the theme toggle, and the account gear holds your preferences as well as your identity
status: accepted
date: 2026-08-25
amends: ADR-0019
---

## Context

This also amends **Phase B RULING 1**, which is not an ADR — it lives in
`docs/design/plan-lane/deterministic-half.md` and the Phase B plan, and both
carry a pointer back here. The frontmatter above names only real ADR ids
because that field is parsed and fed to Doug's reader.

A contrast repair reached two recorded decisions, and neither reversal belonged
in a commit message.

**The readability report.** `/dashboard/settings` was reported as hard to read.
It was not a contrast failure in the text — `--muted-foreground` measured
7.06:1 against `#fcfcfa`, close to AAA. The faults were that the help copy was
set at 10.5px, that `--card` sat 1.03:1 from `--background` and `--border`
1.23:1 from it so nothing had an edge, and that two things were below AA
outright: the `/settings` chip at 3.65:1 and `--iridescent` as text at 4.01:1.

Fixing the second of those means raising `--border`, which #193 had explicitly
declined to do — it treated `--border` as the ceiling its row divider had to
stay under, and spent "the whole budget" of 0.02 working beneath it. Raising
the ceiling is a palette change, and a palette change is where the second ask
landed: dark mode, requested "in our settings or down by our email".

**Phase B RULING 1** pinned the signed-in console to the light paper surface.
The mechanism was that the light palette is declared ON `.dashboard-surface`,
where an inherited `.dark` on `<html>` cannot reach it, and
`lib/dashboard-contract.test.mjs` enforced it under the name "the signed-in
console stays on the reference light paper surface".

**ADR-0019** curated the rail's account gear deliberately. It renamed it
"Account", not "Settings", on the grounds that "two different things sharing
one word on one screen is the confusion the gear/flag-line naming test already
refuses". It described what the gear neighbours as "who you are signed in as,
and what Doug may do on your behalf", and it REMOVED a duplicate Settings entry
from that gear rather than leaving the same link twice at six pixels.

## Decision

- **Light remains the default, and dark is a choice.** `defaultTheme="light"`
  with `enableSystem={false}`, unchanged. An unset preference still renders
  paper; nothing about a reader's OS flips the console.
- **RULING 1 is amended, not deleted.** The console follows the toggle. The
  light palette still sits on `.dashboard-surface` and is still what the
  console holds by default; it is now defeated DELIBERATELY by
  `.dark .dashboard-surface` at specificity (0,2,0) against the light block's
  (0,1,0), rather than being unreachable. The contract test is rewritten to pin
  the amendment — default light, dark claimed at a specificity that can win,
  portalled content following the surface — instead of pinning light alone.
- **The gear holds your preferences as well as your identity.** ADR-0019's
  reading of it — identity and authority — gains a third category: how the
  console looks to you. It is still not "Settings", and the naming rule ADR-0019
  wrote is untouched.
- **Theme does NOT go on `/dashboard/settings`.** That page opens with "Per
  repository. Every setting here applies to reviews from now on", and every
  block on it is a repository. Theme is per-person and changes no review. It
  would be the only thing on that page that is neither.
- **`.paper-tokens` becomes `.surface-tokens`.** The console is no longer always
  paper, so the old name asserted something false about every portalled panel.
- **A colour token is a colour in every theme.** `--iridescent` was a
  `linear-gradient` under `.dark`; the gradient moves to `--brand-wash`, which
  only `background-clip: text` reads. See Consequences.

## Rejected

- **Leaving RULING 1 in force and putting the toggle on public pages only.** A
  control that cannot change the page it sits on reads as broken, and the ask
  was explicitly about the signed-in surface.
- **Putting theme on the settings page anyway, for consistency with ADR-0019.**
  It would be the only per-person, non-review setting on a per-repository
  review page — and a display preference you must navigate to, flip, and
  navigate back from to evaluate is the one kind of setting that most wants to
  be one click from what it changes.
- **Both places.** ADR-0019 removed a duplicate from this exact gear for this
  exact reason. Repeating the mistake to satisfy the ADR that named it would be
  perverse.
- **Following the OS preference.** `enableSystem` would hand the default to the
  reader's machine, which is a different decision from "dark is available" and
  was not the one asked for.
- **Keeping the neutrals warm and only raising their contrast.** The ground and
  the accent were both warm, which is why nothing separated; splitting the
  temperature buys separation at no contrast cost. This was accepted at the
  time as costing parity with the gh-pages marketing site the light palette
  had been tuned against — and that cost turned out not to exist. ADR-0009's
  deploy and the docs reconciliation (#211) left `drewjst.github.io/doug` a
  bare `<meta refresh>` redirect to the app: it renders no palette, so there
  is no second surface for this one to disagree with.

## Consequences

- **Three defects were latent behind RULING 1 and became reachable the moment
  it was amended.** Each was invisible to the suite, because nothing in it
  renders:
  - `.dark` set `--iridescent` to a gradient, and the console is the only place
    reading that token as a COLOUR — 34 sites of `text-[…]`, `border-[…]` and
    `color-mix(…)`, in all of which a gradient is invalid. Every focus ring in
    the console would have stopped rendering: an invisible keyboard focus
    indicator, not a cosmetic slip.
  - `run-spine` and `coverage-ruler` painted `#3d403c` / `#c9c6bd` above
    comments stating they were light-only BECAUSE of RULING 1. True when
    written; false on the day it was amended.
  - The surface painted its dot grid with `var(--border)`, so raising the
    border for item separation turned the paper texture into noise. A border
    exists to be seen and a texture exists to be barely felt; they no longer
    share a token.
- **The guard is now a tree walk, not a list.** Doug flagged the whole-palette
  swap as a broad-regression risk on PR #213 and was right: the first cut of
  the one-theme-hex pin named eleven files by hand and missed
  the Doug mark's own module (`doug-logo`), which still carries the previous palette's
  `--iridescent` and `--foreground`. The mark itself is a deliberate exemption
  — it carries its own white ground and has always rendered on the dark public
  pages — but its rust is now a different orange from the accent beside it.
  Issue #214. The usual objection to repainting a mark, that it would split the
  brand across two properties, does not apply here: there is only one property
  now.
- **The console's own dark values are declared per theme.** `--rule-soft`,
  `--dim`, `--row-hover` and `--surface-dot` now exist in both directions and
  are pinned in both; a theme that forgets one loses every row divider in the
  ledger with no error.
- **Anything rendering the rail must still mount the surface.** Unchanged from
  before, and now load-bearing in both themes rather than one.
- **The console CANNOT be assumed light by anything downstream.** Every future
  component on this surface owes a dark answer. That is the real cost of this
  ADR, and it is permanent.
