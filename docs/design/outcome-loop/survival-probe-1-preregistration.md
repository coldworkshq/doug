# Survival-signal probe #1 — PRE-REGISTRATION

**Status:** BARS LOCKED before run — 2026-08-01  
**IDEAS ref:** pattern garden § “Smallest honest test” probe 1  
**Roadmap:** PC2 lists this among three garden probes; this pulse is **free**
(no LLM, existing harvest + local clone) and may run before PC1 unlocks PC2 spend.

---

## Question

Does an *active survival* signal on `getsentry/sentry` anti-correlate with
known defect concentration — i.e. does the signal have a pulse?

Active survival (operationalized for this probe, no full-repo blame):

For each path **prefix** (depth-2 / depth-3 directory under the repo):

| Component | Source |
|---|---|
| `touches` | # of harvested PRs (5000 window) that touch a file under the prefix |
| `defect_touches` | # of those PRs in the dated git-defect set |
| `churn_span_days` | last − first `merged_at` among harvested PRs touching the prefix (corpus-native; no blame pass) |
| `never_defect` | `defect_touches == 0` |

```
survival_score = log1p(touches) * log1p(churn_span_days)
                 * (0.25 if defect_touches > 0 else 1.0)
```

Paths with `touches < 10` are excluded (noise).

---

## Pre-registered bars

**Pass (pulse detected)** — all three:

1. **Anti-correlation:** Spearman ρ between `survival_score` and
   `defect_rate` (= defect_touches / touches) across eligible prefixes is
   **ρ ≤ −0.25** and two-sided p < 0.05.
2. **Hotspot rank:** At least one of the known sentry AI-product prefixes
   (`seer`, path containing `/seer/`) that meets the touch floor ranks in the
   **bottom 25%** of `survival_score` among eligible prefixes.
3. **Stable contrast:** At least one eligible prefix with `never_defect` and
   `touches ≥ median` ranks in the **top 25%** of `survival_score`.

**Fail / no pulse:** any of (1)–(3) false. Record and do not claim the
garden rests on survival until a redesigned signal or matched-pair probe (#2)
recovers it.

**Does not unlock:** variant separation (probe 2), episode reconstruction
(probe 3), or PC2 spend. This is a pulse check only.

---

## Data (already on disk)

- Harvest: `repo/api/.backtest-cache/getsentry-sentry-5000-before-2026-06-15.json`
- Labels: `repo/api/.backtest-cache/getsentry-sentry-git-defects-dated.json`
- Clone: `repo/api/.backtest-cache/clones/getsentry-sentry.git` (bare, treeless)

---

## Artifacts

- Script: was `api/scripts/survival_probe.py` (local; re-add if re-running)
- Results: `survival-probe-1-results.md`
- Machine JSON: `api/.backtest-cache/survival-probe-sentry.json` (gitignored)
