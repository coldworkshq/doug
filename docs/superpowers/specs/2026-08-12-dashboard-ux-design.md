# Dashboard UX pass — design

**Date:** 2026-08-12
**Branch:** `dashboard-ux`, cut from `origin/main` @ `7f64652` (PR #102, the Phase B rebuild)
**Surface:** `web/app/dashboard`

Four changes asked for against the shipped dashboard: a shadcn table that does
not eat the page, a control for the needs-you line, a larger type scale, and a
space picker that navigates on selection instead of on a second click.

---

## 0. What the existing tests will not let us do

Two pins constrain every decision below. Both are deliberate and neither is
being relaxed.

**`lib/dashboard-contract.test.mjs` — "every filter the dashboard offers lives
in the URL, not in client memory"** asserts that `app/dashboard/page.tsx`
contains neither `"use client"` nor any of `useState`, `useEffect`,
`useSearchParams`, `useRouter`, `usePathname`. It pins the *page file*, not the
route: importing a client leaf is permitted. The claim it protects is the one
the page prints in its own count line — *filters live in the URL* — so any new
control must still write its state to the query string.

**`lib/console-lockstep.test.mjs`** holds `lib/{facets,sorting,paging,grouping,search}.ts`
and `components/{band-chip,coverage-ruler,run-spine}.tsx` byte-identical to
`console/`'s copies. None of them may be forked for this work. Where one has to
change, both sides change together — that is what the pin is for.

**`lib/design-system.test.mjs` — "the surface-scoped tokens are used only where
the surface is mounted"** asserts that `--rule-soft`, `--dim` and `--row-hover`
appear in exactly one source file, `app/dashboard/page.tsx`. New components must
not reach for them. They use `border-border`, `text-muted-foreground` and
`bg-muted` instead, and the test's expected file list stays untouched.

---

## 1. Threshold lens

### What it is not

The needs-you line is not a user setting today and this change does not make it
one. `api/doug/scoring.py:21` reads `DOUG_THRESHOLD` (default `0.62`) from the
environment, `api/doug/reader.py:347` reads `DOUG_READER_THRESHOLD`, and the
resolved value is stamped onto each verdict row at scoring time
(`api/doug/store.py:74`). `band` is decided server-side, once, and is a record
of what happened.

So the control is a **view lens**: it re-derives needs-you/cleared from each
run's *recorded score* against a line the reader chooses. It changes what the
ledger shows, never what Doug did.

### Mechanism

`lib/threshold-lens.ts` — new, web-only, not lockstepped.

```
fetched ──► applyLens(rows, lens) ──► buildFacets
                                 ├──► filterRuns
                                 ├──► groupRunsByPr
                                 └──► BandChip
```

The lens rewrites `band` on the row objects *before* they reach anything else.
Every lockstepped module then reasons about the lens band without being
modified — `matchesFacets` reads `row.band`, `buildFacets`'s `facetValue` reads
`run.band`, `BandChip` takes the band as a prop. This is why the lens is applied
at the boundary rather than threaded through: the alternative is a `lens`
parameter on five pinned functions, and the pin would reject all five.

It also delivers the chosen semantic for free. Band pills, their counts, the
band chips and the count line all agree, because they are all looking at the
same rewritten rows. There is no state in which the `needs you` pill says 12 and
the table shows a different 12.

Exports:

- `parseThresholdLens(raw: string | undefined): number | null` — `null` means no
  lens. Rejects non-numeric, out-of-range (outside `0..1`) and blank values by
  returning `null`, the same empty-vs-absent rule `parseFacetSelection`
  documents. A malformed `?threshold=` is *not* an error page; it is no lens.
- `applyLens<T extends RunSummary>(rows: T[], lens: number | null): T[]` —
  identity when `lens` is null, so the no-lens path allocates nothing new and
  the default render is bit-for-bit what it is today.
- `rebandedCount(before: RunSummary[], after: RunSummary[]): number` — how many
  rows the lens moved. Drives the banner's number.
- `serializeThresholdLens(lens: number | null)` / `thresholdChanges(lens)` —
  the query-string rewrite, shaped like `predicateChanges` in
  `dashboard-view.ts`. Returns `{ threshold: … , page: null }`; a control that
  changes which rows are flagged returns to page 1 exactly as a facet does.

The band a lens assigns is `score >= lens ? "flagged" : "cleared"` — `>=`, so a
run exactly on the line needs you, matching `scoring.py`'s own comparison rather
than inventing a second convention.

### Registration

`threshold` is added to `DASHBOARD_OWN_PARAMS` in `lib/dashboard-view.ts` (not
lockstepped). Two consequences, both wanted: `carriedParams` makes the search
form re-submit the lens instead of silently dropping it, and the facet-collision
guard in `facets.test.mjs` now covers the name.

### The evidence pane stays honest

`Evidence` is fed from the **unlensed** array. `detail.band`, `detail.score` and
`detail.threshold` continue to print what Doug recorded. The selected summary is
looked up in `fetched` before `applyLens` runs, so no lensed row can reach it.

### Surface

`components/threshold-gear.tsx`, `"use client"`. shadcn `Popover` + `Slider` +
`Button`, wrapping a `method="GET" action="/dashboard"` form with the carried
params as hidden inputs. **The form navigates, not a router call** — the lens
lands in the URL and the page re-renders on the server, so the lens is server
state like every other filter and a shared link reproduces it exactly.

Radix's `Popover` and `Slider` both require JavaScript, so the *gear* is a
JS-only control. The *lens* is not: it is a query param the server reads, and
the banner and its reset link below are server-rendered. Without JavaScript an
active lens is still visible, still correct, and still clearable — only the
composing control is missing. This is stated rather than papered over; a control
that silently does nothing is the failure mode being avoided.

The slider's value reaches the form through an explicit
`<input type="hidden" name="threshold">` bound to the same state, not through
Radix's own form bubbling — one visible mechanism rather than a dependency on a
primitive's internals.

Placement: beside the search box. When a lens is active the trigger carries a
dot, and a banner sits above the table:

> Viewing at 0.30 · Doug scored these against its own line — **N** rows
> re-banded by this view. **Clear**

The banner is not optional and not a tooltip. A ledger silently showing bands
that no verdict asserts is the failure this whole surface exists to refuse; the
banner is what makes the lens a lens rather than a lie. It renders on chrome
colours (`--iridescent`, `bg-accent`), never on `--flag`/`--clear` — those are
the two data colours and a view state is not a verdict.

---

## 2. Table

`components/ui/table.tsx` installed from shadcn (`radix-nova`, already
configured in `components.json`), then **adapted** — which is the point of
shadcn's copy-in model. Two edits, both verified against the generated source:

1. **Drop its `"use client"` directive.** Every one of the eight components is a
   pure prop spread over an intrinsic element — no hooks, no handlers, no state.
   The directive is boilerplate on the generated file, and keeping it would drag
   a client boundary around the entire run ledger for styling that needs none.
   `Popover` and `Slider` keep theirs; they are Radix primitives and genuinely
   need it.
2. **Let `Table` take a `containerClassName`.** It already renders its own
   `overflow-x-auto` container div. Without this the bounded-height wrapper
   becomes a second, nested scroll container inside the first, which is where
   sticky headers break. The bound goes on the container shadcn already has.

`RunTable` then renders through `Table`/`TableHeader`/`TableHead`/`TableRow`/`TableCell`.

Everything already working is preserved: the three sortable columns and their
carets (`lib/sorting.ts`, URL-driven), the per-PR `<tbody>` grouping, the
`:has()` disclosure and its fail-open `@supports` guard, and the eight-column
layout with its documented widths.

Bounded height: the scroll wrapper takes `max-h-[55vh] overflow-auto`, with
`position: sticky; top: 0` on the header cells. This requires
`border-separate border-spacing-0` on the table — collapsed borders are painted
by the table, not the cell, and vanish from a sticky header. Column borders move
onto the cells to compensate.

`min-w-[980px]` and the horizontal scroll stay; the vertical bound is added, not
substituted.

---

## 3. Type scale — one notch

| | before | after |
|---|---|---|
| PR title | 12px | 14px |
| body / cell text | 10px | 12px |
| uppercase micro-labels | 9px | 10px |
| score | 14.5px | 16px |
| row height | 34px | 40px |

Two lockstepped components sit inside this table and would be left visibly
undersized: `BandChip` (10.5px) and `RunSpine`. The identical bump is applied to
`console/components/band-chip.tsx` and `console/components/run-spine.tsx` in the
same commit. That is what the lockstep pin is for — it fails when one side
moves, and passes when both do. `coverage-ruler.tsx` is unchanged.

This is the one part of the work that touches the console app, and it touches it
only to keep the two surfaces the same size.

---

## 4. Space picker

`ScopePicker` **stays in `page.tsx`**. `dashboard-contract.test.mjs` pins
`aria-label="Connected space"` inside `function ScopePicker(` and separately
pins that the control's wrapper class carries a `focus-within:` ring — the
control that changes whose data you are looking at must be visibly focusable.
Extracting the whole component would break both pins for a styling reason.

Only the `<select>` moves: `components/auto-submit-select.tsx`, `"use client"`,
a thin wrapper that calls `form.requestSubmit()` on change and otherwise
forwards `name`, `defaultValue`, `aria-label`, `className` and children
untouched. The existing `switchConnectionAction` server action is unchanged, so
`action={switchConnectionAction}` still appears in `page.tsx` where its pin
expects it.

The `open` button moves inside `<noscript>`. Without JavaScript the form still
has a submit control; with it, the button is gone and selection navigates. The
same treatment is *not* applied to the `repo` filter — it is a GET form on the
same page rather than an org switch, and it is left alone this pass.

---

## Testing

New:

- `lib/threshold-lens.test.mjs` — parse (valid, blank, non-numeric,
  out-of-range, boundary `0` and `1`), `applyLens` identity at `null`, `>=`
  boundary behaviour, `rebandedCount`, and that `applyLens` does not mutate its
  input.
- A pin in `dashboard-contract.test.mjs`: **the lens never reaches the evidence
  pane** — the selected summary is resolved before `applyLens`, and the pane
  prints `detail.threshold`.
- A pin in `dashboard-contract.test.mjs`: **an active lens is announced** — the
  banner copy is gated on the lens being non-null, the way the `scopeUnconfirmed`
  note is gated on its signal. An always-present caveat is its own dishonesty;
  an ungated one would still satisfy a test that only looked for the words.
- `lib/dashboard-view.test.mjs` — `threshold` is in `DASHBOARD_OWN_PARAMS`,
  `thresholdChanges` resets `page`, and `carriedParams` carries it.

Existing, expected to stay green without modification:

- `console-lockstep.test.mjs` — proves the two `BandChip`/`RunSpine` edits landed
  on both sides.
- `design-system.test.mjs` — proves no new component reached for a
  surface-scoped token.
- `dashboard-contract.test.mjs`'s no-client-boundary test — proves the page file
  itself never grew one.

Manual: the dashboard runs against a live session, so the four changes are
verified in the browser against a real space before the PR opens.

## Out of scope

- Persisting the lens (cookie or account setting). It lives in the URL, like
  every other filter.
- A real per-space threshold that changes scoring. That is a store schema, an
  endpoint and a worker read — a separate PR, and it would only affect future
  runs since past verdicts keep their stamped line.
- The `repo` filter's submit button.
- Any change to `console/`'s own dashboard beyond the two font-size edits.
