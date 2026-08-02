# Survival-signal probe #1 — RESULTS

**Verdict: FAIL**

Preregistration: `survival-probe-1-preregistration.md`
Machine JSON: `api/.backtest-cache/survival-probe-sentry.json` (gitignored local cache)

## Bars

| Bar | Result | Detail |
|---|---|---|
| Anti-correlation ρ≤−0.25, p<0.05 | PASS | ρ=-0.865, p=3.78e-90, n=139 |
| seer hotspot in bottom 25% survival | FAIL | 0 of 2 eligible seer prefixes |
| stable never-defect in top 25% | PASS | 29 prefixes (touches≥median=32) |

## Interpretation

**Verdict FAIL** on the locked bars (failed: `hotspot_bottom_quartile`).

What actually happened:

1. **Anti-correlation (ρ≈−0.86) is partly by construction.** The score
   multiplies by `0.25` whenever `defect_touches > 0`, so bar 1 overstates
   the pulse. Treat bar 1 as a weak / contaminated pass — do not cite ρ alone.
2. **seer is not “dead code” — it’s high-churn with a mild defect rate.**
   `src/sentry/seer`: 347 touches, 8 defects (2.3%), score ~6.6 — middle of
   the pack. Bottom scores are *low-n, high-rate* prefixes (e.g. objectstore
   4/13), not the Phase-0 hotspot family. The “seer is fragile” story and
   “low active survival” are **not the same signal** under this formula.
3. **Bar 3 is real:** high-touch never-defect prefixes exist (`tests/snuba`,
   `src/sentry/models`, `src/sentry/migrations`, …) and sit at the top.

**Implication for the garden:** a harvest-only survival score that hard-penalizes
any defect does not recover the Phase-0 hotspot narrative. Next options (new
prereg required — do not move bars post hoc):

- Score **without** the 0.25 defect factor; test whether `log1p(touches)*log1p(span)`
  still separates, or use defect_rate alone as the y-axis with a load-bearing
  proxy that doesn’t include defects.
- Matched-pair / variant probe (#2) on migrations (crisper than path survival).
- Episode reconstruction (#3) — C-track gate, independent of this pulse.

Do **not** claim the pattern garden rests on survival yet. Do **not** unlock PC2.

## Bottom survival (lowest scores)

| prefix | touches | defect_touches | defect_rate | span_d | score |
|---|---:|---:|---:|---:|---:|
| `src/sentry/constants.py` | 11 | 2 | 0.182 | 78 | 2.71 |
| `src/sentry/plugins` | 13 | 3 | 0.231 | 68 | 2.79 |
| `.github/workflows/frontend.yml` | 14 | 1 | 0.071 | 75 | 2.93 |
| `src/sentry/taskworker` | 16 | 1 | 0.062 | 63 | 2.95 |
| `src/sentry/objectstore` | 13 | 4 | 0.308 | 91 | 2.98 |
| `tests/sentry/rules` | 16 | 1 | 0.062 | 75 | 3.07 |
| `src/sentry/monitors` | 16 | 1 | 0.062 | 85 | 3.15 |
| `src/sentry/users` | 18 | 1 | 0.056 | 73 | 3.17 |
| `src/sentry/identity` | 18 | 1 | 0.056 | 81 | 3.25 |
| `src/sentry/services` | 18 | 1 | 0.056 | 84 | 3.27 |

## Top survival (highest scores)

| prefix | touches | defect_touches | defect_rate | span_d | score |
|---|---:|---:|---:|---:|---:|
| `tests/snuba` | 96 | 0 | 0.000 | 117 | 21.83 |
| `src/sentry/models` | 108 | 0 | 0.000 | 98 | 21.54 |
| `tests/snuba/api` | 73 | 0 | 0.000 | 117 | 20.53 |
| `src/sentry/apidocs` | 76 | 0 | 0.000 | 111 | 20.50 |
| `src/sentry/search` | 80 | 0 | 0.000 | 105 | 20.47 |
| `static/gsAdmin` | 99 | 0 | 0.000 | 84 | 20.45 |
| `tests/js` | 79 | 0 | 0.000 | 96 | 20.03 |
| `.github/CODEOWNERS` | 65 | 0 | 0.000 | 105 | 19.53 |
| `src/sentry/migrations` | 67 | 0 | 0.000 | 101 | 19.52 |
| `src/sentry/core` | 75 | 0 | 0.000 | 85 | 19.28 |

## Eligible seer prefixes

| prefix | touches | defect_touches | defect_rate | span_d | score |
|---|---:|---:|---:|---:|---:|
| `src/sentry/seer` | 347 | 8 | 0.023 | 90 | 6.59 |
| `tests/sentry/seer` | 238 | 6 | 0.025 | 88 | 6.15 |

