---
title: The web app wears the Coldworks look in both themes
status: proposed
date: 2026-09-15
amends: ADR-0020
---

## Context

On 2026-09-15 Andrew ruled, in session, that the web app uses the Coldworks
look everywhere: its UI, its fonts, and its colours (doug#351). He ruled in
the same session that dark mode stays, redrawn in Coldworks colours. Doug
keeps its name, its mark, and the story on `/about`.

Before this record, `coldworks.dev` served two looks on one origin. The
landing page (`public/landing.html`) and, after #350, every page under
`/docs` set Archivo, Instrument Sans, and IBM Plex Mono on the molten, ember,
and coolant palette. Every other page set Bricolage Grotesque and Geist on
Doug's slate palette with a rust accent. ADR-0034 ruled the public header
Coldworks-branded because two brands on one origin read as two products; the
same failure held for the look beneath the header.

The brand's colours do not all work as text. Against white, molten
(`#e0430a`) measures 4.22:1 and ember (`#f08c1a`) 2.48:1, both under AA for
body text, and the brand's faint (`#8a9aa1`) measures 2.91:1. The previous
palette had the opposite problem in its chrome: its accent sat ΔE2000 9.2
from its flag colour in normal vision and 2.3 under simulated deuteranopia,
the closeness the data-colour rule warns against, and the figure the rule
itself quoted ("ΔE 6.1") reproduced under no formula (#210).

## Decision

- **Faces.** Archivo (display), Instrument Sans (body), and IBM Plex Mono
  (numbers and code) load once, in `app/layout.tsx`, through
  `next/font/google`, and `/docs` reads the same variables. The utilities
  block shared with the console names `--mono-face`, which each app declares.
- **One palette, two themes.** `app/globals.css` declares the Coldworks
  palette in its light and dark blocks, and `components/docs/docs.module.css`
  reads it rather than carrying its own. The dark values are the audit docs'
  dark palette, with faint text raised to clear AA on the card.
- **Inks hold AA where the brand colour does not.** When a brand colour fails
  AA on the grounds its text renders on, the text token is a darker shade of
  it: `--flag` is molten darkened until it clears 4.5:1 on its own chip tints
  over the page, and `--faint` is the brand's faint darkened until it clears
  4.5:1 on the page, the card, and a hovered row. A brand colour that fails as
  text is for fills, marks, and display type, where AA asks 3:1.
- **Figures are computed, not typed.** `lib/design-system.test.mjs` computes
  every contrast ratio and every ΔE2000 separation from the stylesheet's
  hexes, in normal vision and under deuteranopia and protanopia (Machado,
  Oliveira and Fernandes, 2009, in linear RGB), and checks its CIEDE2000
  against the reference pairs of Sharma, Wu and Dalal (2005). Under
  deuteranopia and protanopia the data pair must stay at least as separable
  as the palette this record replaced, whose weakest figures were 11.6 and
  8.2; in normal vision its floor is ΔE2000 40. The light pair measures closer
  in normal vision than the pair it replaced (53.9 against 57.9) and further
  apart under protanopia (12.9 against 8.2). The chrome accent must clear a
  floor that the replaced accent fails: ΔE2000 20 in normal vision and 10
  under each dichromacy.
- **Doug keeps its name and its mark.** The mark's ears and muzzle are molten
  and its line work is ink, written into `components/doug-logo.tsx` (#214).
- **Surfaces are flat.** The dot grid and the accent glow leave with the
  palette they textured.
- **ADR-0020's mechanism is unchanged.** Light is the default, and dark comes
  from the header toggle and the account menu. This record amends ADR-0020's
  palette: its accent token, `--iridescent`, is now `--coolant`, a colour in
  both themes, and the only gradient token is `--thermal`, which only
  `.bg-thermal` reads.

## Rejected

- **Doug's look inside the app and the Coldworks look at the door.** Two
  looks on one origin is the two-products failure ADR-0034 refused for the
  header.
- **Brand hexes as text, whatever they measure.** Molten body text at 3.89:1
  on the page and ember at 2.28:1 would keep the palette exact and make the
  text harder to read.
- **Light only.** Retiring dark mode removes a setting ADR-0020 shipped in the
  account menu. Andrew chose a Coldworks dark theme instead.
- **Extending #350's local font subsets.** They stop at Instrument Sans 500,
  and the app sets 600 and 700, which a 500 file can only fake.
  `next/font/google` is the loader the app already used.
- **Docs-local copies of the palette's values.** Two declarations of one value
  drift apart; the docs read the palette.

## Consequences

- Every future component owes an answer in both themes, in Coldworks colours.
  This is ADR-0020's permanent cost, unchanged.
- The brand's hexes live in three places: `public/landing.html`,
  `apps/registry/app/globals.css` in coldworkshq/coldworks, and this app's
  `app/globals.css`. A change to the brand edits all three.
- The UI grammar is still Doug's: uppercase tracked labels, Doug's card
  shapes, and the header. doug#351 owns that as its second PR.
- Component edges keep ADR-0020's separation from the card (`--border`), and
  row dividers use the brand's hairline (`--line`). Whether edges become the
  brand hairline is Andrew's call on doug#351.
- The console keeps its own palette and faces. Only the utilities block it
  shares with web changed.
