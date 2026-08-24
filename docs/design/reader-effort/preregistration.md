# Raising the reader's EFFORT — PRE-REGISTRATION

**Status:** BARS LOCKED before run — 2026-08-23
**Amends:** ADR-0012 (which narrowed ADR-0002's freeze from six constants to five)
**Instrument under test:** `reader.EFFORT`, `api/doug/reader.py:47`
**Companion ADR:** ADR-0016, to be written only if this run PASSES

---

## Question

`reader.EFFORT` is `"medium"`. The Claude API's default is `"high"`, so the
shipped reader runs one step **below** the provider default, and has since the
probe chose that value on 2026-07-29.

On `claude-opus-5`, `effort` governs thinking depth. Doug's measured failure
mode is not misreading the diff it was given — it is asserting things about a
repository from a diff, without doing the reasoning that would expose the claim
as unresolvable from the evidence in hand. That is the class `effort` is
supposed to move.

**Does raising `EFFORT` from `"medium"` to `"high"` reduce the rate at which
Doug publishes findings that a look at the repository disproves, without
reducing the rate at which it publishes real ones?**

---

## Why this needs a pre-registration at all

`EFFORT` is one of ADR-0012's five frozen constants, pinned by
`test_reader_and_probe_share_the_validated_prompt_bytes`
(`api/tests/test_reader.py:1051`) against `scripts/llm_probe.py`. ADR-0002's
rule stands for it: changing it is a new experiment, not a tweak.

ADR-0012 established the escape hatch this document uses. It removed
`DIFF_BUDGET` from the freeze and replaced "never change this" with "change it
against a stated, checkable bar." This run proposes the same move for `EFFORT`,
and it must clear a bar declared before the run to make it.

---

## What changes if this passes

1. `reader.EFFORT` becomes `"high"`. `scripts/llm_probe.py:54` keeps `"medium"`,
   because the probe must go on reporting what it actually measured.
2. The freeze narrows to **four** constants: `SYSTEM`, `SCHEMA`, `MODEL`,
   `MAX_TOKENS`.
3. A test pins the divergence as deliberate and sized, in the shape
   `test_diff_budget_diverges_from_the_probe_on_purpose`
   (`api/tests/test_reader.py:1077`) already uses: assert **both** sides, so
   that anyone who "fixes the drift" by syncing either constant breaks a test
   and is sent to this document.
4. `read_with_decisions` (the intent tier) reads the same `EFFORT` constant and
   therefore moves with it. This is in scope and is stated here rather than
   discovered later; ADR-0007 keeps that tier's output off the risk score, so
   moving it changes no band.

`MECHANICAL_EFFORT` is a separate constant and does **not** move. The verify and
attribution passes were never in the probe and are not governed by the freeze
(ADR-0016).

5. **`EFFORT` is in the Example Pack manifest** (`output_config.effort`), so
   raising it moves `instrument_id` and partitions the labelled corpus at the
   cutover: reads before and after are not the same instrument and must not be
   pooled. It does **not** move `PROMPT_HASH`, which is
   `sha256(SYSTEM + repr(SCHEMA))` and never took `EFFORT` as an input — so
   verdict comparability on prompt identity survives while instrument
   comparability does not. Stated here because discovering it after the
   cutover is how a corpus silently becomes two.

---

## Corpus

`docs/findings-log.jsonl` — **153 findings across 27 pull requests**, dated
2026-07-29 to 2026-08-20, every one hand-dispositioned `real` / `disproved` /
`adjacent`, each carrying a `settled_by` string naming the artifact that decided
it. Median 4 findings per PR; range 1 to 32.

Baseline, as recorded:

| Disposition | n | share |
|---|---|---|
| `real` | 68 | 44.4% |
| `disproved` | 49 | 32.0% |
| `adjacent` | 36 | 23.5% |

This is Doug's own review history, not a held-out corpus. It is the only
labelled data that exists at the granularity the question asks about — *findings*,
not revert-prediction.

### Amendment, 2026-08-23: the AUC replication was cheaper than "declined" implies

An earlier draft of this document justified the findings-log corpus partly on the
grounds that "the alternative was already declined on cost by ADR-0012." **That
premise does not survive arithmetic and is withdrawn.**

`scripts/llm_probe.py:250` already submits through
`client.messages.batches.create`, so the Batch API's 50% discount was in force
when the decline was recorded on 2026-08-06. The probe reads
`N_CLEAN + N_COUNTERFACTUAL` = 260 PRs per repo:

| Scope | Reads | At `medium` | At `high` (3x output, assumed) |
|---|---|---|---|
| sentry only | 260 | $7.28 | $11.81 |
| sentry + grafana, full replication | 520 | $14.56 | **$23.63** |

Batched, at the $0.056/read mean ADR-0012 measured for the probe's own
30,000-char budget. **A full two-repo replication at `high` costs about $24.**

That changes the recommendation. A replication answers the question ADR-0002
actually froze `EFFORT` to protect — *does the AUC hold* — on the pre-registered
instrument, against the same labels, with a comparable baseline. The findings-log
run answers a different and narrower question, on a corpus that cannot record a
miss.

**Run the AUC replication as the primary arm.** The findings-log design below
stands as the secondary arm: it measures published-finding precision, which the
AUC probe does not, and it costs nothing extra in API spend because Arm A is
already on disk. Report both. If they disagree, the replication governs the
freeze and the log governs the product claim.

The `$24` figure carries the same caveat as every other number here: the 3x
output multiplier at `high` is assumed, not measured. Nothing in this repo has
measured what `effort` does to output tokens on this prompt. That is the first
thing a pilot of 20 PRs would settle, for about $1.

### Design

Paired, re-read at the recorded head SHA:

- **Arm A (control)** is already on disk: the findings as published, at
  `EFFORT="medium"`.
- **Arm B (treatment)** re-reads the same 27 PRs at the same head SHAs, with
  every other constant identical, at `EFFORT="high"`.

Pairing on PR removes between-PR variance, which is the dominant noise source
here — a 32-finding PR and a 1-finding PR are not exchangeable.

---

## Pre-registered bars

**PASS** requires 1 and 2. Bar 3 is reported but does not gate.

1. **Precision improves.** Arm B's `disproved` share is **≤ 19.6%**, against the
   32.0% baseline. That threshold is not a preference — it is the minimum
   detectable effect at this corpus size (see below). A smaller improvement is
   real-or-noise-indistinguishable here and is recorded as INCONCLUSIVE, not as
   a pass.
2. **Recall does not regress.** Arm B's count of `real` findings is **≥ 68**,
   the Arm A count. Falling below is a FAIL even if bar 1 clears: a reader that
   buys precision by finding less is not the trade this run is asking for.
3. **Reported, not gating — externally-verified recall.** `docs/reviews/` holds
   two calibration records (PR #106, PR #114) listing **11 externally-verified
   defects** with a "doug caught it?" column; Doug caught 1 outright and 2
   partially. Report how many of the 11 Arm B catches. n=11 gates nothing, and
   saying so here is what stops it from being promoted to a bar afterwards if it
   happens to look good.

**FAIL** is any of: bar 1 missed, bar 2 missed, or Arm B raising the mean cost
per read above **$0.30** (see Cost). Record the FAIL as a FAIL. Do not re-run at
`xhigh` and report that instead — a second arm chosen after seeing the first is
a different experiment and needs its own document.

### Statistical power, stated before the run

Two-proportion test, α = 0.05 two-sided, 80% power, n ≈ 153 per arm:

| Findings per arm | Smallest detectable drop from 32.0% |
|---|---|
| 153 | to 18.2% (−43% relative) |
| 250 | to 21.0% (−34% relative) |
| 400 | to 23.2% (−28% relative) |

**This corpus can only detect a large effect.** A genuine improvement from 32%
to 25% would not clear bar 1, and the run would correctly report INCONCLUSIVE.
That is the honest cost of a 153-finding corpus, and it is written down before
the run so it cannot be rediscovered afterwards as a reason the bar was unfair.
The one-sided threshold at n=153 is 19.6%, which is the number bar 1 uses.

---

## Dispositioning protocol

This is the part that decides whether the run means anything.

1. Arm B's findings are pooled with Arm A's, shuffled, and stripped of any
   arm label before anyone reads them.
2. The dispositioner records `real` / `disproved` / `adjacent` and a
   `settled_by` artifact for each, to the same standard the existing log uses —
   a named file, a query, or a document, never "looks wrong to me."
3. Arm labels are rejoined only after every disposition is written.
4. Arm A's findings are **re-dispositioned blind in the same pass**, not carried
   over from the log. Reusing the stored labels while judging Arm B fresh would
   compare a 2026-07 standard against a 2026-08 one and attribute the drift to
   `effort`.

The failure this protocol exists to prevent is named in ADR-0002: "Post-hoc bar
edits are how a failed experiment becomes a passed one."

---

## Cost

Arm A is on disk. Arm B is 27 reads.

| | per read | 27 reads |
|---|---|---|
| Arm B at `EFFORT="medium"` (ADR-0012's measured mean) | $0.074 | $2.00 |
| Arm B at `EFFORT="high"`, assuming 3× output tokens | ~$0.16 | ~$4.32 |

Under $5. The money is not the constraint and must not be cited as one. **The
real cost is the blind dispositioning of roughly 300 pooled findings by someone
competent to settle them against the repository** — call it a day of work, and
it is not delegable to Doug, which is the instrument under test.

The $0.30/read FAIL ceiling in bar 3 is set four times above the estimate,
because the estimate is the one number in this document with no measurement
behind it. `effort` changes thinking tokens, which bill as output, and nothing
in this repo has measured that multiplier on this prompt.

---

## Known weaknesses, recorded before the run

- **The corpus is not held out.** These 27 PRs are Doug's own history on its own
  repository, dispositioned by the people who wrote the code under review. A
  result here does not generalize to sentry or grafana, and no claim from this
  run may be stated without naming the corpus. The AUC replication arm added by
  the 2026-08-23 amendment does not share this weakness, which is the main
  reason it is now primary.
- **`findings-log.jsonl` cannot record a miss.** All 153 rows are `layer=doug`
  and all three verdicts presuppose that Doug emitted something. Bar 2 therefore
  measures "did Arm B emit fewer findings later judged real", not recall. True
  recall is unmeasurable on this corpus at any sample size, and bar 3's n=11 is
  the only rater-independent evidence that exists.
- **`real` is not a fixed target.** Arm B may emit findings that are real and
  that Arm A never emitted, which inflates bar 2's numerator for a reason that
  has nothing to do with precision. Bars 1 and 2 are therefore reported as
  shares and counts side by side, never collapsed into one score.
- **Arm A's diff and Arm B's diff are identical by construction** (same head
  SHA, same `DIFF_BUDGET`, same `read_order`), so this run says nothing about
  truncation. A PR whose Arm A read was partial has an equally partial Arm B
  read. Truncation is a separate change with a separate bar.
- **`n=11` on external recall.** Bar 3 is an observation, not evidence.

---

## Does not unlock

The generalized settlement pass, the split read for truncation, or any change to
`SYSTEM`, `SCHEMA`, `MODEL` or `MAX_TOKENS`. Each needs its own bar. A PASS here
licenses exactly one edit: `EFFORT = "high"` in `api/doug/reader.py`, plus the
ADR that records it.
