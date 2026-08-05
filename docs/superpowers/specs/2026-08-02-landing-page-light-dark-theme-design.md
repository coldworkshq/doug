# Landing + docs site: light/dark theme

**Date:** 2026-08-02
**Status:** approved, not yet built
**Branch:** `landing-light-dark-theme`, worktree `.claude/worktrees/landing-theme`, based on `gh-pages` (not `main` — the hosted site has no shared history with the app code)

## Why

Andrew likes how the dark "Pattern Garden" cell (`#garden`) reads on the
hosted landing page (drewjst.github.io/doug) and wants that treatment
available site-wide as a toggleable dark theme, blended with the existing
light design rather than bolted on, landing on light by default.

## Scope

In scope: `index.html` (landing) and `docs/index.html` (docs), both on the
`gh-pages` branch — the only two files that branch contains besides
`.nojekyll` and `llms.txt`.

Out of scope: the Next.js app in `web/` (a different product surface, on
`main`, unrelated to this branch); a three-way (light/dark/system) toggle —
binary only, manual switch, default light regardless of OS preference, per
explicit instruction.

## Design

**Token system.** Both files already define a light `:root` palette plus a
`--night` / `--night2` / `--night-line` trio used only by the dark Garden
cell and the final CTA band. `--night2` is defined but currently unused.
Add a `:root[data-theme="dark"]` override block per file that remaps the
light tokens onto that existing dark trio:

| token | light (unchanged) | dark (new) |
|---|---|---|
| `--bg` | `#FCFCFA` | `var(--night)` `#101210` |
| `--card` / `--bg2` | `#FFFFFF` / `#F6F5F1` | `var(--night2)` `#181B18` (first real use) |
| `--line` / `--line2` | `#E7E5DE` / `#D9D6CD` | `var(--night-line)` / `#3A3F39` |
| `--ink` / `--ink2` / `--ink3` | dark grays | the near-white/gray tones already used inside `.cell.dark` |
| `--ok` / `--hot` | `#177A50` / `#C93A2B` | the brighter terminal variants already defined for the code block (`#5CC98B` / `#EF7B66`) |
| `--accent` / `--accent-ink` / `--accent-soft` | `#D1571E` / … | **unchanged** — same orange in both themes |

`--accent` staying constant across themes is the "blend of both worlds":
same brand color, same mono/terminal accents, same layout — only the
surrounding surface re-lights.

**Signature cells stay the deepest surface.** `.cell.dark` and
`.cta-final` currently pop because they're the only dark thing on a light
page. If dark mode simply mapped everything to `--night`, they'd flatten
into the background and lose that effect. Fix: in dark mode they step one
level deeper than ordinary cards, reusing `#0B0D0B` (the tone already
used inside the Garden's embedded code block) as their background — so
they're still the visually deepest, most "technical" element on the page
in either theme.

**Toggle.** A sun/moon icon button in the navbar on both pages. Click
toggles `data-theme` on `<html>` and persists the choice to
`localStorage` (key `doug-theme`). An inline, pre-paint script in
`<head>` applies a stored `dark` preference before first render (avoids
flash-of-wrong-theme on repeat visits); absent a stored preference the
page is light, full stop — no `prefers-color-scheme` check, per Andrew's
explicit call to land on light.

**Shared toggle script.** The ~20-line toggle/persistence logic moves into
one `theme.js` referenced by both pages (`./theme.js` from the root,
`../theme.js` from `docs/`) instead of being duplicated inline, so the two
copies can't drift. CSS dark-mode overrides stay inline per file, matching
how the rest of the site is already built (no bundler, no shared
stylesheet today).

## Verification

Static HTML, no build step — verify by serving the worktree locally
(`python3 -m http.server` from `.claude/worktrees/landing-theme`) and,
via the browser:
- Screenshot light and dark on both `index.html` and `docs/index.html`.
- Confirm the toggle persists across a reload and across navigating
  landing → docs.
- Confirm first-ever load (cleared storage) is always light.
- Spot-check contrast on the remapped tokens, especially body text and
  the metrics band.
