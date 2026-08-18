# External review vs Doug — PR #114 @ 3461657

A calibration record for Doug's self-improvement loop: what an external
medium-effort review found on this PR, next to what Doug's own check run
flagged on the same diff. Machine-readable table first; the narrative
deltas below are the training signal.

PR #114 is the dashboard redesign — a rail/ledger/dock shell, a ledger
census over data the runs endpoint already returned, and the Repositories
view. Web only, no API change.

Doug's read was **partial: 64% (100,000 of 155,479 chars)**, cut inside
`web/app/dashboard/page.tsx`, and never sent
`web/lib/dashboard-contract.test.mjs`, `web/lib/ledger-census.test.mjs` or
`HANDOFF.md`. That matters for the disposition below and Doug said so
itself — two of its five findings die to a file it was never given, and the
one defect it missed lives in the file its read was cut inside.

## External findings (all verified, all fixed in this branch)

| # | file:line | category | finding | doug caught it? |
|---|-----------|----------|---------|-----------------|
| 1 | web/app/dashboard/page.tsx:557 | correctness | `RepoCountLine` branched on `atCap` before `filtering`, so at the page cap it announced "counts over the latest 500 runs fetched" while every number beside it was counted over the filtered subset — and `censusScope`, branching the other way, printed a different denominator for the same rows on the same screen | no |
| 2 | web/components/census-panel.tsx:270 | correctness | Severity bar drew three segments over `severity.total`, but `high+medium+low` need not equal `total`; the shortfall rendered as empty track, which `Bar`'s own docstring defines as "not yet observed" | **yes** (`reader:aggregate-mismatch`, ranked low) |
| 3 | web/lib/ledger-census.ts:486 | correctness | `charsLabel(999_999)` renders `"1000k"` — a label claiming the next unit was not reached when rounding already crossed it | no |

### How each was fixed

1. `countedOver()` now owns the branch order and **both** sentences go
   through it. A parity test asserts that whenever `filtering` is on,
   neither sentence may lead with the cap and both must name `shown`. The
   original bug (restore the `atCap`-first branch) is caught by three
   tests, verified by mutation.
2. `severityCensus` returns `unclassified = total - high - medium - low`
   (clamped at zero) so the invariant `high + medium + low + unclassified
   === total` is a value rather than a subtraction the caller can forget —
   forgetting it is exactly what produced the bug. The bar draws a fourth,
   hatched segment and the caption names it. Hatched, not a fourth step of
   the ramp: this is the absence of a recorded severity, not a fourth
   severity, and a solid step would rank it against the three that are real.
3. `charsLabel` falls through to the M branch when the kilo rounding
   crosses 1000.

Finding 2 is reachable in production today, not hypothetically:
`store.py:114` declares `Column("severity", String(10))` — nullable —
`store.py:852` writes it straight off a Reason whose severity is
`str | None`, and the aggregation counts `total` as `COUNT(*)` against
three `SUM(CASE WHEN severity = 'x' THEN 1 ELSE 0 END)` with `else_=0`.
The web already knew: the evidence pane renders `reason.severity ?? "rule"`.

## Doug's findings, dispositioned

- `reader:aggregate-mismatch` (low) — **CONFIRMED**, row 2 above. Doug's
  only true finding, and it named the mechanism correctly.
- `reader:missing-null-check` on `severityCensus` (medium) — **REFUTED.**
  `session-api.ts`'s `runSummary()` does an `exact()` key-set check plus
  `record(counts) && exact(counts, [...]) && Object.values(counts).every(Number.isInteger)`,
  and `getSessionRuns` **throws** `SessionApiError` when it fails. A row
  with absent or null `finding_counts` never reaches the census; the whole
  response is rejected at the boundary. Doug could not see this —
  `session-api.ts` is unchanged and therefore not in the diff.
- `reader:missing-null-check` on `readCensus` (low) — **REFUTED**, same
  mechanism: `coverage()` requires `exact()` on all five keys and
  `Array.isArray(files_unseen)`. A `files_unseen: undefined` object fails
  validation twice over.
- `reader:float-equality-bucketing` (low) — **REFUTED as stated.**
  `threshold` is `Column("threshold", Float, nullable=False)` — *stored*
  per verdict from `verdict.threshold`, not computed per row — so rows
  scored under one config store and serialise the same float and the `Set`
  dedupes them. Producing `0.30000000000000004` would require the API to
  compute rather than store. And the failure direction is safe: the marker
  is withdrawn and the chart prints "thresholds differ — no single line to
  draw", i.e. it refuses to draw rather than drawing a wrong line.
- `reader:layout-regression` (low) — **REFUTED**, and the stated range is
  exactly inverted. Below 1620px the dock is **not** beside the ledger — it
  stacks underneath — so the "400px dock" in Doug's mechanism is not
  present at the widths it names. At 1440–1619px the ledger has 1171–1350px
  against a 940px table: it fits with room. Horizontal scroll appears below
  ~1210px, which is deliberate, documented in `COLUMNS`' docstring, and the
  chosen alternative to crushing the PR title (measured: at a 1360px
  breakpoint the title rendered 40px wide).

**Score: 1 of 5.**

## Deltas worth encoding

1. **Doug does not read outside the diff, and says so — but its confidence
   does not fall accordingly.** Both `missing-null-check` findings assume
   no validation exists anywhere; both die to one unchanged file. The
   partial-read disclaimer covers *what was cut from the diff*, not *what
   was never in the diff because it did not change*. A finding of the form
   "X is dereferenced without a guard" is a claim about the whole call
   path, and the call path is mostly outside any diff. Either trace the
   producer or lower the severity.

2. **Severity ordering inverted again — third occurrence.** #109's record
   noted "the one finding that lets a defect through CI was ranked last".
   Here the only true finding is ranked joint-last at `low`, and the two
   refuted null-checks lead the list, one at `medium`. Doug's ranking is
   currently anti-correlated with truth on this corpus.

3. **Doug flagged a layout regression without computing the layout.** The
   claim conflates two rules that never apply at the same width — a 400px
   dock and viewports below 1620px — which one arithmetic pass rules out.
   Same family as #106's "plausible mechanism, no refutation step".

4. **The defect Doug missed is the one this PR was most at risk of.** The
   PR's own commit message and code comments claim `RepoCountLine` exists
   specifically to stop a complete total lending its authority to partial
   counts; the implementation then got the branch order wrong. A reviewer
   reading the stated intent against the code would have caught it. Doug
   read the code and not the intent — and its read was cut inside that very
   file, so it may not have seen the function at all.

5. **What Doug did well, worth preserving:** row 2 required joining a web
   render site to a Python `SUM(CASE ...)` aggregation two repos-worth of
   context away, and Doug got the mechanism exactly right. That is the
   cross-file trace #106's record said it could not do. It is improving on
   the axis that matters; the ranking is what is now the weak link.

## Loop note

Recorded against a run whose own instrument line reads
`adjudicated 0 · pending 170 · first due 2026-08-16`. The clocks are not
ticking because MT0's `installation` webhook has never been redelivered and
#113's adjudicator deploy has not been run by hand — so this PR's own
verdict cannot yet be scored against an outcome. That is the gap
`docs/design/outcome-loop/ROADMAP.md` MT0 tracks, and it is why this file
exists: until the loop closes, hand-dispositioned records are the only
calibration signal Doug has.
