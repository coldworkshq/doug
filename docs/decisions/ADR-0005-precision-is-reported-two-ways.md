---
title: Never report corpus precision as precision
status: accepted
date: 2026-07-30
---

## Context

The seed corpus in the ledger is 653 PRs with known outcomes, and its
base rate is ~30%. The repos it was drawn from run at 1.34% (sentry) and
0.37% (grafana). The gap is deliberate — the probe sampled ALL known
defects plus a uniform subsample of clean PRs, because that is how you
get enough positive examples to measure anything.

The consequence is that every raw precision figure from this corpus is
inflated by more than an order of magnitude. A pattern showing "50%
precision" in the ledger describes a population that does not exist.

## Decision

The per-pattern precision report always emits two tables.

**CORPUS** is assumption-free and works on any ledger: precision among
the rows present, plus lift against those same rows' base rate, plus a
Wilson interval. The lift column is the comparable quantity; the
precision column is labelled as within-corpus and must not be quoted
alone.

**POP** reweights to the repo's true base rate by Bayes on the two
strata, restricted to the newer half where both strata came from one
frame, with bootstrap CIs.

The API response carries the caveat in its own body, so a number cannot
be lifted out of the endpoint without it.

## Rejected

**Reporting corpus precision alone.** It is the most flattering number
available and it is wrong by ~20x. This is the same class of error as
quoting enriched-sample capture next to literature figures, which is
already a closed route.

**Reporting only the population estimate.** It needs the probe's stratum
design, which live rows do not have. The corpus table is what keeps
working as real verdicts accumulate.

## Consequences

- The honest answer at n=653 is negative: reweighted, only `import-cycle`
  clears the base rate on sentry and nothing clears on grafana. Per-pattern
  population precision is not resolvable at this sample size, and the
  report says so rather than printing a confident number.
- Stars are uncorrected for multiplicity; the output states how many are
  expected by chance.
