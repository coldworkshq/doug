# Convergence — pre-registered evaluation results

**Date:** 2026-08-11 · **Charter:** `docs/superpowers/plans/2026-08-11-lane2-agent-door.md`
Task 3 · **Bars:** `docs/design/outcome-loop/convergence-design.md` §"Pre-registered bars"

This document has two parts, written in this order and committed separately:

- **Part 1 — the sampling plan.** Declared and committed BEFORE any finding was
  read and before any label was assigned. It is immutable from its commit
  onward. If it turns out to be a bad plan, that is recorded as a limitation of
  this evaluation, not repaired by redrawing.
- **Part 2 — the results.** Filled in afterward.

---

# Part 1 — Sampling plan (declared before labelling)

## Provenance of the evaluated run

| item | value |
| --- | --- |
| eval output | `workspace/research/two-lane-2026-08-11/convergence-eval-run1.json` |
| produced by | `api/scripts/convergence_eval.py` @ `ffc0d27` (PR #91) |
| run | 2026-08-11, read-only prod ledger session, exit 0; the proxy has since been closed |
| classifier | `api/doug/convergence.py` @ `ffc0d27` — the shipped module, not a re-implementation |

## Disclosure — what was inspected before this plan was fixed

Pre-registration is only worth something if the author says what they had
already seen. Before writing this plan I read, from the eval JSON, **only**:

- the `summary` block (aggregate counts and exposures — already transcribed
  into `HANDOFF.md` at the end of the previous session, i.e. it predates this
  session);
- the JSON **schema**: top-level keys, the key set of a pair record, the key
  set and value *types* of a classification record;
- **counts and structural metadata only**: resolved-count per pair, pair count
  per repo / per `key_kind` / per month, head-SHA availability, `later_coverage`
  presence, and the count of resolved findings inside pairs with no read row.

I did **not** read any finding's `rule`, `label`, `file`, or `severity` value,
any coverage path list, or any per-finding classification, and no ground-truth
label existed anywhere at the time this was written. The structural facts above
are what the sample design needed and nothing beyond that was opened.

Two of those facts drove the design and are stated plainly because they are
adverse:

1. **42 of 118 pairs carry no head SHAs on either side** (70 of the 335
   resolved-classified findings). Head SHAs are what let a labeller diff the
   exact code the two verdicts saw.
2. **The no-SHA stratum is not a random slice.** It is *every* `lemahq/lema`
   pair (22) plus 20 older `drewjst/doug` pairs. Every SHA-bearing pair is
   `drewjst/doug`, all in 2026-08. Restricting the frame to SHA-bearing pairs
   therefore removes the second repo entirely — a confound, not a convenience.

## Bar 1 — resolved-precision ≥ 0.90

### The bar is unchanged

> `resolved` precision ≥ 0.90 on the hand-labelled consecutive-pair sample.

This is a **point estimate**, as pre-registered. A Clopper-Pearson interval is
reported alongside it and **never gates** — substituting a confidence bound for
the declared threshold now, after seeing that the population is large enough to
support one, would be tightening a pre-registered bar post hoc. The bar is the
bar.

### Frame

The **75 pairs that carry both head SHAs and at least one resolved-classified
finding**, holding **265** resolved-classified findings. All are
`drewjst/doug`, 2026-08.

Bar 1 therefore speaks to *SHA-bearing pairs*, and its statement of result must
carry that qualifier. The excluded stratum is not ignored — it is measured
separately by the no-SHA probe below, whose result is reported on its own and is
**never pooled into bar 1**.

### Unit, order, seed, stopping rule

- **Sampling unit: the pair (cluster).** Every resolved-classified finding in a
  drawn pair is labelled. Chosen because the labelling evidence is a PR diff:
  one diff grades every finding on that pair at close to the cost of one.
- **Canonical order:** pairs sorted ascending by `(from_verdict_id,
  to_verdict_id)`. These are stable primary keys; the order does not depend on
  anything about the findings.
- **Seed: `20260811`** (the run date). Declared here, before the draw.
- **Draw:** `random.Random(20260811).shuffle(frame)` over the canonically
  ordered frame; take pairs from the head of the shuffled list.
- **Stopping rule:** stop after the first pair at which the cumulative count of
  resolved-classified findings reaches **40**. That pair is included **whole**,
  so the realised n lands in 40–46. Target n = 40 was chosen against the bar:
  a clean sweep of 40 puts the one-sided 95% lower bound at 0.928, clear of
  0.90.
- **No unit is ever dropped.** A drawn pair whose evidence cannot be recovered
  does not get replaced; its findings are labelled `cant-tell` and flow through
  the rules below. Replacement-on-difficulty is the exact move that turns a
  sample into a selection.

The exact draw code and its output are recorded verbatim in Part 2, along with
the Python version, so the draw is re-runnable.

### Label vocabulary

Each sampled prior finding gets exactly one label, judged **against the code at
the later verdict's head SHA**:

| label | meaning |
| --- | --- |
| `fixed` | the defect the finding describes is gone at `to_head_sha` |
| `still-present` | the defect is still in the code at `to_head_sha` — **this is a false-resolved** |
| `not-a-defect` | the finding did not describe a real defect at `from_head_sha` |
| `cant-tell` | cannot be determined from the available evidence |

`not-a-defect` exists because Doug's reader has false positives, and neither
available alternative is honest: grading a hallucinated finding `still-present`
would charge convergence for the reader's error, and grading it `fixed` would
flatter it. It is labelled for what it is and handled explicitly below.

### Estimators — declared now, all three reported

- **PRIMARY (this is the gate):**
  `precision = fixed / (fixed + still-present)`.
  `not-a-defect` and `cant-tell` are excluded from both numerator and
  denominator. This measures the thing bar 1 names: when the finding-diff says
  a real finding went away, was it really gone?
- **Co-reported, harm-weighted:**
  `(fixed + not-a-defect) / (fixed + not-a-defect + still-present)`.
  Rationale: the harm model in the design note is "false-resolved tells an agent
  it is done". If the finding was never a defect, the agent *is* done, so on an
  agent-facing reading those units are harmless. Reported, never gates.
- **Co-reported, worst case:**
  `fixed / (every labelled unit)` — `cant-tell` and `not-a-defect` both count
  against. Reported, never gates.

Also reported, none of them gating: the Clopper-Pearson 95% two-sided interval
on the primary; the `cant-tell` rate; the cluster design effect (findings within
a pair are correlated, so the effective sample is smaller than its face count,
and the face count must not be passed off as independent evidence).

### What this sample cannot measure

Every sampled unit is resolved-classified **by construction**. This measures
**precision only**. It says nothing about recall — about findings that were
really fixed and that the classifier failed to call resolved. No recall claim
may be drawn from it.

### Labelling procedure

For each sampled finding I retrieve the diff between `from_head_sha` and
`to_head_sha` on the PR, propose a label with the specific evidence (file, hunk)
attached, and Andrew confirms or overrides. **The recorded label is Andrew's.**
The count of proposals he overrode is reported as a covariate — if that number
is high, my proposals were not independent evidence and the sample is weaker
than its size suggests.

## No-SHA probe (reported separately, never pooled into bar 1)

Frame: the **26 no-SHA pairs carrying at least one resolved finding** (70
findings). Same cluster method, **separate declared seed `20260812`**, target
**10** findings, same labels and same estimators. Evidence is reconstructed from
the commit range implied by the two `scored_at` timestamps rather than from a
SHA diff; where that reconstruction fails, the unit is `cant-tell` — which is
itself the finding worth reporting about this stratum.

## Bar 2 — zero false-resolved on uncovered files

Two halves, both required; declared here in full.

- **(a) Census — mechanical, no labels, whole population.** For all 118 pairs,
  assert that no finding classified `resolved` has a `file` that string-matches
  a path in the later read's `files_unseen` or `files_dropped`, or equals its
  `file_cut`. Any hit ⇒ **bar 2 FAILS**. This runs over every pair, not a
  sample. Exposure is real: 39 uncovered findings across 22 pairs.
- **(b) Path-form audit — judgement, the known weakness.** The census in (a) is
  exact-string, and so is the classifier, so (a) cannot catch the case the
  design note names explicitly: a finding whose `file` refers to the same file
  as an uncovered coverage path *in a different string form*, which fails toward
  `resolved`. I audit (i) the one `path_form_suspect` pair the eval emitted
  (`web/app/page.tsx` vs `web/app/queue/page.tsx`) and (ii) every resolved
  finding in the bar-1 sample, checking its `file` against the later read's
  coverage lists for same-file-different-form. Any true same-file mismatch
  that produced a `resolved` ⇒ **bar 2 FAILS**.

## Bar 3 — settled findings never resolve: **NO EVIDENCE**

Declared now, before scoring, so it cannot be written up as a pass later:

The run produced **`findings_settled = 0` across all 118 pairs — zero
exposures.** A bar with zero exposures **has not passed**; it has produced no
evidence. It is reported as **NO EVIDENCE**, and rule 4 remains
**construction-tested only**, by the unit tests and the settle.py↔convergence.py
pinning test — which is a claim about the code, not about the ledger. Any
downstream document, receipt, or MCP description that describes bar 3 as passed
is wrong.

---

# Part 2 — Results

*(Filled in after Part 1 was committed. Empty at declaration time.)*
