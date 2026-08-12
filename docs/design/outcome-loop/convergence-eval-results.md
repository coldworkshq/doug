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

## The draw (executed after Part 1 was committed at `bfa8c6b`)

Python 3.9.6. Script and output preserved verbatim in the session scratchpad.

| | frame | drawn | findings |
| --- | --- | --- | --- |
| bar 1 (seed 20260811, target 40) | 75 pairs / 265 findings | 13 pairs | **43** |
| no-SHA probe (seed 20260812, target 10) | 26 pairs / 70 findings | 6 pairs | 12 |

Bar-1 sample spans 11 distinct PRs: #90, #50 (×2 pairs), #43 (×2), #56, #69,
#59, #48, #67, #39, #38, #75. All 26 head SHAs resolve locally.

## Bar 2 — **PASS**, on real exposure, whole population

Not sampled: the census ran over all 118 pairs and all 335 resolved-classified
findings.

| check | result |
| --- | --- |
| resolved findings whose `file` string-matches `files_unseen` / `files_dropped` / `file_cut` | **0** |
| resolved findings in a pair with a missing read row (rule 3) | **0** |
| `unknown(file-uncovered)` abstentions actually taken | **39**, across 22 pairs |

The exposure is real, so this is a pass rather than a vacuous one: the
classifier had 39 genuine opportunities to wrongly resolve an uncovered
finding and took none of them.

**Path-form half (bar 2(b)).** Part 1 declared this check over the bar-1
sample; it was instead run over the whole population, which is strictly
stronger. Across all 335 resolved findings, exactly **one** suspect: `drewjst/doug#42`,
finding file `web/app/page.tsx` against coverage path `web/app/queue/page.tsx`.
**Adjudicated FALSE** — distinct blobs on `origin/main`, a Next.js app-router
basename collision between two genuinely different route files, not one file in
two string forms. No true same-file mismatch exists in the run.

**Correction to the design note's premise.** `reads.changed_files` is a COUNT
(integer), not a path list — the only paths a read row carries are
`files_unseen`, `files_dropped` and `file_cut`. Any future path-form check must
use those three and not `changed_files`.

## Bar 3 — **NO EVIDENCE** (not a pass)

`findings_settled = 0` across all 118 pairs: zero exposures. As declared in
Part 1 before scoring, a bar with no exposures has produced no evidence. Rule 4
remains **construction-tested only**, by the unit tests and the
settle.py↔convergence.py pinning test — a claim about the code, not about the
ledger. Any document, receipt or MCP tool description asserting bar 3 passed is
wrong.

## Bar 1 — labelling in progress; interim evidence

The mechanical half of the evidence is complete and is recorded here because it
is what the labelling rests on.

**Every one of the 13 drawn pairs is linear** — `from_head` is an ancestor of
`to_head` in all 13. No rebases, so no file left the PR diff between the two
verdicts; the diff only grew. This rules out the benign explanation that a
finding's file stopped being reviewed.

Against that: **26 of the 43 drawn findings sit on files that are byte-identical
between the two verdict heads**, and **13 of those sit in pairs where no code
changed anywhere at all** (only `docs/` or `HANDOFF.md`) — PR#48 (5), #39 (3),
#38 (3), #43 v1043→1045 (2). A finding on unchanged code cannot have been
fixed, so each such unit is `still-present` or `not-a-defect`, never `fixed`.

Confirmed false-resolved so far, with documentary evidence rather than
inference:

| PR | pair | finding | evidence |
| --- | --- | --- | --- |
| #75 | 1144→1145 | `reader:unauthenticated-data-exposure` (api.py) | findings-log adjudicates it `real`; the pair contains exactly one commit (deploy.yml); its fixes `7430600`+`b6253c9` land **after** `to_head` |
| #75 | 1144→1145 | `reader:missing-smoke-test` (gcp.sh) | fix `e681064` lands **after** `to_head` |
| #48 | 1062→1064 | `reader:error-handling-gap` (api.py) | findings-log `real`, `changed=true`, but api.py is untouched in this pair — fixed later |
| #48 | 1062→1064 | `reader:unbounded-external-calls` (api.py) | findings-log `real` (`unauthenticated-endpoint-abuse`); only `docs/findings-log.jsonl` changed in the pair |

Genuine resolutions also exist and are labelled `fixed`: PR#75's
`reader:deploy-ordering-hazard`, fixed inside the pair by `70fe216` — the
finding asked for `needs: [changes, api]` and the commit delivers exactly that,
with a `!cancelled()` guard; and PR#90's `reader:tooling-resolution-fallback`,
adjudicated `real`+`changed` with the file touched in the pair.

**Evidence source declared:** `docs/findings-log.jsonl` carries 112 prior human
adjudications (`real` 45 / `disproved` 40 / `adjacent` 27) covering 4 of the 11
sampled PRs. It is used as *evidence* for a label, never as the label — its
vocabulary is not the pre-registered one, `adjacent` has no clean mapping to it,
and it keys on `rule` alone, which matches only **7 of 43** sampled findings
(PR#75's rows use unprefixed slugs — the slug-drift covariate showing up in
practice). The remaining 36 need direct judgement.

*(Bar-1 scoring is not complete and no precision figure is recorded here yet.)*
