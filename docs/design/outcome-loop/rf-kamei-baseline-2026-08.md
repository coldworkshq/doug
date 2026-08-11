# RF-on-Kamei-14 — recorded baseline (2026-08-11)

**What this is.** The metadata-model baseline the LLM diff-reader is measured
against. The script has existed since 2026-07-29 and prints to stdout; its
numbers lived only in `workspace/research/phase1-entry-preregistration.md`,
outside this repo. This document brings them inside it, so the reader's cost
story has a comparator on file that a stranger with this checkout can
reproduce.

**This run is a reproduction, not a new result.** The protocol and its
interpretation bars were pre-registered on 2026-07-29 before the first fit;
the split AUCs below match the 2026-07-29 record digit-for-digit
(`random_state=0`, fixed hyperparameters, on-disk caches). Nothing was tuned,
and the script was not edited.

## Run conditions

| | |
|---|---|
| Date | 2026-08-11 |
| Script | `api/scripts/rf_kamei.py` (unmodified; byte-identical to `origin/main`) |
| Command | `cd api && uv run python scripts/rf_kamei.py` |
| Repo state at run time | `2b563762b1414f5abc7732c996cac854799503de` (`origin/main`, #88) |
| Model spend | none — no network, no model call |
| Exit code | 0 |

Harvest caches read from `api/.backtest-cache/` (gitignored, local only):

- `getsentry-sentry-10000-before-2026-03-20.json`
- `grafana-grafana-12000-before-2026-06-15.json`
- `getsentry-sentry-git-defects-dated.json`, `grafana-grafana-git-defects-dated.json` (revert labels)

Fixed a priori (`rf_kamei.py:45-52`): `n_estimators=500`,
`min_samples_leaf=5`, `class_weight="balanced_subsample"`, `random_state=0`;
1,000 bootstrap resamples.

## Captured output, verbatim

The first six lines are `uv` creating the virtualenv; the trailing `EXIT=0`
was appended by the capturing shell. Everything between is the script's own
stdout, unedited.

```
Using CPython 3.14.6 interpreter at: /opt/homebrew/opt/python@3.14/bin/python3.14
Creating virtual environment at: .venv
   Building doug-api @ file:///Users/andrew/Projects/doughq/repo/.worktrees/lane0/api
warning: `build_system.requires = ["uv-build>=0.11,<0.12"]` does not contain the current uv version 0.12.1
      Built doug-api @ file:///Users/andrew/Projects/doughq/repo/.worktrees/lane0/api
Installed 67 packages in 233ms

==============================================================================
Split A — within-sentry temporal (train n=5000 defects=69 · test n=5000 defects=67)
  RF (Kamei 14)      AUC 0.544  @10%  10%  @20%  24%  @30%  34%  density_lift @20 0.95x  @30 0.94x
                     AUC 95% CI [0.478, 0.612] (1000 resamples)
  v3 (train-learned) AUC 0.572  @10%  12%  @20%  28%  @30%  43%  density_lift @20 0.90x  @30 0.81x
  size (LA+LD)       AUC 0.605  @10%  15%  @20%  30%  @30%  45%  density_lift @20 0.88x  @30 0.79x
  RF importances:  la 0.10 · ld 0.10 · size (LA+LD) 0.09 · churn per file 0.09 · nuc 0.09 · exp (author PRs) 0.09

==============================================================================
Split B — within-grafana temporal (train n=6000 defects=35 · test n=6000 defects=22)
  RF (Kamei 14)      AUC 0.456  @10%   9%  @20%  23%  @30%  36%  density_lift @20 0.97x  @30 0.91x
                     AUC 95% CI [0.320, 0.611] (1000 resamples)
  v3 (train-learned) AUC 0.449  @10%   0%  @20%   8%  @30%  23%  density_lift @20 1.15x  @30 1.10x
  size (LA+LD)       AUC 0.401  @10%   5%  @20%  14%  @30%  18%  density_lift @20 1.08x  @30 1.17x
  RF importances:  recency 0.11 · la 0.11 · churn per file 0.11 · size (LA+LD) 0.11 · exp (author PRs) 0.09 · sexp (subsystem) 0.07

==============================================================================
Split C — sentry→grafana (Tabassum OP condition; train n=10000 defects=136 · test n=12000 defects=57)
  RF (Kamei 14)      AUC 0.568  @10%  18%  @20%  32%  @30%  39%  density_lift @20 0.86x  @30 0.88x
  v3 (static only)   AUC 0.506  @10%   6%  @20%  21%  @30%  32%  density_lift @20 0.98x  @30 0.97x
  size (LA+LD)       AUC 0.558  @10%  14%  @20%  28%  @30%  40%  density_lift @20 0.90x  @30 0.85x

==============================================================================
Split C — grafana→sentry (Tabassum OP condition; train n=12000 defects=57 · test n=10000 defects=136)
  RF (Kamei 14)      AUC 0.552  @10%  12%  @20%  29%  @30%  38%  density_lift @20 0.88x  @30 0.88x
  v3 (static only)   AUC 0.565  @10%  15%  @20%  30%  @30%  42%  density_lift @20 0.88x  @30 0.82x
  size (LA+LD)       AUC 0.615  @10%  17%  @20%  32%  @30%  49%  density_lift @20 0.85x  @30 0.72x

Bars are pre-registered in workspace/research/phase1-entry-preregistration.md — read outcomes against those, not against taste.
EXIT=0
```

## The pre-registered bars

Quoted from `workspace/research/phase1-entry-preregistration.md`, "Experiment
2 — RandomForest on Kamei's 14", § *Pre-registered reading of outcomes*
(fixed 2026-07-29, before the first fit). That file is outside this repo, so
the bars are reproduced here in full and this document stands alone.

> 1. **RF is the new baseline** if it beats BOTH v3 and size on Split-A AUC
>    and on at least one of capture@20/@30. Then the LLM probe's part (i) bar
>    becomes RF's number, not v3's.
> 2. **Metadata ceiling reconfirmed** if RF lands within noise of v3 —
>    a second method family hitting the same ceiling strengthens the case that
>    probe parts (ii)/(iii) are where the information is.
> 3. **Per-repo learning is real** if Split-B RF beats size-on-grafana and
>    random (AUC > 0.55 as a soft marker given n=~31 test defects) where every
>    sentry-derived artifact sits at ~0.50. That supports the
>    population-of-one distillation story regardless of anything else.
> 4. **Tabassum replication expected:** Split-C sentry→grafana at ~random. If
>    it clears 0.55, that's a surprise worth its own investigation.

## Reading the numbers against those bars

**1. RF is NOT the new baseline — FAIL.** On Split A, RF's 0.544 is below both
comparators on the identical test rows: v3 0.572 and size 0.605. The first
clause of bar 1 requires beating both, so the capture clause is never reached
(RF's @20/@30 of 24%/34% are also below size's 30%/45%). Size — the sum of
added and deleted lines — wins every sentry comparison in this run, and wins
Split C grafana→sentry too (0.615 vs RF 0.552).

**2. Metadata ceiling reconfirmed — PASS.** RF's Split-A 95% CI [0.478, 0.612]
contains v3's 0.572 and size's 0.605, which is what "within noise of v3"
means here. A learned nonlinear model on Kamei's 14 lands in the same band as
the hand-built rules. Kamei's reported +8.8 AUC for nonlinear models over
logistic regression on these inputs does not materialize on this data — the
constraint is the information in the metadata, not the model class.

**3. Per-repo learning is real — FAIL.** Split-B RF is 0.456. It does clear
size-on-grafana (0.401) and v3 (0.449), but the bar's second conjunct is
AUC > 0.55, and 0.456 is below random. The CI [0.320, 0.611] spans random in
both directions, so this is an underpowered result (22 test defects) rather
than a demonstration of anything — but it is not evidence for in-domain
learning, and the bar was written to be read that way. In-domain grafana RF
also scores *below* its own cross-repo number (0.456 vs 0.568), which is the
opposite of what per-repo learning predicts.

**4. Tabassum replication — the "surprise" fires on the point estimate, with
no interval to test it.** Split-C sentry→grafana is 0.568, which clears the
0.55 marker bar 4 named. Two caveats, both material:

- The script prints an AUC CI for Splits A and B only; `cross_repo()` never
  calls `bootstrap_auc_ci` (`rf_kamei.py:150-171`). **This run therefore
  produces no interval for either Split C direction** — the 0.568 is a bare
  point estimate here.
- The 2026-07-29 record in `phase1-entry-preregistration.md` carries
  `[0.491, 0.645]` for this cell and closed the item on the grounds that the
  interval touches random. That number is *not* reproducible from the current
  script and is recorded here with that provenance, not as output of this run.

The honest state: bar 4's trigger condition is met on the point estimate, and
the evidence available in-repo cannot say whether it survives an interval.
Anyone wanting to close bar 4 from this repo alone must add a CI to
`cross_repo()` first.

## Does RF beat the reader?

**No — on every comparison on file, by a wide margin, in the same direction.**

The reader's pre-registered probe result is **AUC 0.687 sentry / 0.668
grafana** (`ADR-0004`, `docs/decisions/ADR-0004-llm-reader-in-the-scoring-path.md:23`).
Every RF number in this run — 0.544, 0.456, 0.568, 0.552 — sits below both.
RF's best figure here is 0.568, which is 0.100 below the reader's weaker repo
(0.668) and 0.119 below its stronger one (0.687). No significance test is
claimed for those gaps: RF's Split-A interval [0.478, 0.612] is 0.134 wide
and Split C has no interval at all, so this is a consistent direction across
four splits rather than a tested difference.

Two qualifications that must travel with that sentence:

- **Different row sets.** The splits above and the reader's probe rows are not
  the same evaluation. The like-for-like comparison — RF and the reader scored
  on *identical* probe rows — is recorded in the same external pre-registration:
  RF 0.524 vs reader 0.687 on sentry's newer half, and RF 0.518 (cross-repo) /
  0.469 (in-domain) vs reader 0.668 on grafana. Those four numbers come from
  Experiments 1 and 1b in `phase1-entry-preregistration.md`, not from this run,
  and are cited with that provenance. They point the same way as this run's
  numbers, which is why the conclusion does not rest on the split comparison.
- **0.687/0.668 describe the historical 30,000-character original-file-order
  reader, not the shipped one.** The shipped 100,000-character tier-ordered
  reader has never been measured by that probe (`ADR-0012`,
  `product-spec.md:37`, `design-lock.md:41`). "RF does not beat the reader"
  is a statement about the *probed* configuration. It is not a performance
  claim about what runs in production today, and must not be quoted as one.

**What this means for the reader's cost story.** ADR-0004 traded the
deterministic cost wedge away on the argument that cheap metadata scoring has
a proven ceiling and does not transfer across repos. This run is that
argument's comparator, now reproducible from a clean checkout: three method
families — shape rules (v3), single features (size), and a learned nonlinear
model — all land in 0.40–0.62 across four splits, and the one that trains
in-domain on repo #2 lands below random. The reader's per-PR model cost buys
the only ranking on file that clears that band on both repos. That is the
whole of the cost defense; it does not extend to any claim about which
configuration is deployed.

## What this run does not establish

- Nothing about the **shipped** reader. See the second qualification above.
- Nothing about **population-budget capture** or cleared-band density for the
  reader. The density-lift figures above are RF's, on full frames.
- Nothing about **grafana with more labels**. 22 test defects on Split B and
  57 on Split C carry intervals that span most of the plausible range.
- No **interval on either Split C direction**, per bar 4 above.
