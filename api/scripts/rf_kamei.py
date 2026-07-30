"""RandomForest on Kamei's 14 — the pre-registered Phase-1 baseline.

Kamei et al. (TSE 2013) report ~+8.8 AUC for nonlinear models over logistic
regression on these exact inputs, so before any LLM read is worth judging we
need the number a learned model puts on the metadata ceiling. Protocol and
interpretation bars are pre-registered in
workspace/research/phase1-entry-preregistration.md (2026-07-29) — hyperparams
below are fixed a priori; nothing here was tuned on a test slice.

Three splits, per the pre-registration:

  A. within-sentry temporal   — older-10k sample, the exact created_at 50/50
                                split cli.py uses, so v3 numbers compare 1:1.
  B. within-grafana temporal  — does in-domain learning work where every
                                shipped artifact sits at random?
  C. cross-repo (Tabassum OP) — train one repo, score the other. The
                                published failure mode of our architecture.

The sentry-5000 sample (both halves) is deliberately untouched — its newer
half is the twice-spent holdout.

    cd repo/api && uv run python scripts/rf_kamei.py
"""

import functools
from datetime import datetime

import numpy as np
from screen_features import CACHE, FEATURES, TOLERANCE_DAYS, history_index
from sklearn.ensemble import RandomForestClassifier

from doug.backtest.curve import capture_curve, cleared_band
from doug.backtest.git_labels import find_reverted_prs_dated
from doug.backtest.harvest import harvest
from doug.backtest.hotspots import learn_hotspot_segments
from doug.backtest.replay import replay

print = functools.partial(print, flush=True)  # noqa: A001

REPOS = {
    "sentry": ("getsentry", "sentry", 10000, "2026-03-20"),
    "grafana": ("grafana", "grafana", 12000, "2026-06-15"),
}

RF = dict(
    n_estimators=500,
    min_samples_leaf=5,
    class_weight="balanced_subsample",
    random_state=0,
    n_jobs=-1,
)
BOOTSTRAP = 1000


def load(owner: str, repo: str, limit: int, before: str):
    prs = harvest(owner, repo, limit, None, CACHE, before=before)
    by = {p.number: p for p in prs}
    dated = {
        n: d
        for n, d in find_reverted_prs_dated(owner, repo, CACHE).items()
        if n in by
    }
    defects = {
        n
        for n, d in dated.items()
        if (datetime.fromisoformat(d) - datetime.fromisoformat(by[n].merged_at)).days
        >= -TOLERANCE_DAYS
    }
    return prs, defects


def matrix(prs, hist) -> np.ndarray:
    return np.array(
        [[fn(p, hist[p.number]) for _, _, fn in FEATURES] for p in prs]
    )


def report(name: str, scored: list[tuple[float, bool]]):
    n = len(scored)
    n_def = sum(1 for _, d in scored if d)
    curve = capture_curve(scored)
    b20 = cleared_band(curve, n, n_def, 0.20)
    b30 = cleared_band(curve, n, n_def, 0.30)
    print(
        f"  {name:<18} AUC {curve.auc:.3f}  "
        f"@10% {curve.capture_at(0.10):>4.0%}  @20% {curve.capture_at(0.20):>4.0%}  "
        f"@30% {curve.capture_at(0.30):>4.0%}  "
        f"density_lift @20 {b20.density_lift:.2f}x  @30 {b30.density_lift:.2f}x"
    )
    return curve


def bootstrap_auc_ci(scored: list[tuple[float, bool]]) -> tuple[float, float]:
    rng = np.random.default_rng(0)
    n = len(scored)
    aucs = []
    while len(aucs) < BOOTSTRAP:
        sample = [scored[i] for i in rng.integers(0, n, n)]
        if not any(d for _, d in sample) or all(d for _, d in sample):
            continue
        aucs.append(capture_curve(sample).auc)
    return float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def fit_rf(x_train: np.ndarray, y_train: np.ndarray) -> RandomForestClassifier:
    rf = RandomForestClassifier(**RF)
    rf.fit(x_train, y_train)
    return rf


def within_repo(tag: str):
    owner, repo, limit, before = REPOS[tag]
    prs, defects = load(owner, repo, limit, before)
    hist = history_index(prs)
    ordered = sorted(prs, key=lambda p: p.created_at)
    mid = len(ordered) // 2
    train, test = ordered[:mid], ordered[mid:]
    train_defs = {p.number for p in train} & defects
    test_defs = {p.number for p in test} & defects
    print(
        f"\n{'=' * 78}\nSplit {'A' if tag == 'sentry' else 'B'} — within-{tag} "
        f"temporal (train n={len(train)} defects={len(train_defs)} · "
        f"test n={len(test)} defects={len(test_defs)})"
    )

    rf = fit_rf(matrix(train, hist), np.array([p.number in train_defs for p in train]))
    proba = rf.predict_proba(matrix(test, hist))[:, 1]
    y_test = [p.number in test_defs for p in test]
    rf_scored = list(zip(proba.tolist(), y_test, strict=True))
    curve = report("RF (Kamei 14)", rf_scored)
    lo, hi = bootstrap_auc_ci(rf_scored)
    print(f"  {'':<18} AUC 95% CI [{lo:.3f}, {hi:.3f}] ({BOOTSTRAP} resamples)")

    learned = learn_hotspot_segments(train, train_defs)
    v3 = replay(test, extra_hotspots=learned)
    report("v3 (train-learned)", [(s, pr.number in test_defs) for pr, s, _ in v3])
    report(
        "size (LA+LD)",
        [(float(p.additions + p.deletions), p.number in test_defs) for p in test],
    )

    top = sorted(
        zip((f[0] for f in FEATURES), rf.feature_importances_, strict=True),
        key=lambda t: -t[1],
    )[:6]
    print("  RF importances:  " + " · ".join(f"{n} {v:.2f}" for n, v in top))
    return curve


def cross_repo(src: str, dst: str):
    s_owner, s_repo, s_limit, s_before = REPOS[src]
    d_owner, d_repo, d_limit, d_before = REPOS[dst]
    s_prs, s_defs = load(s_owner, s_repo, s_limit, s_before)
    d_prs, d_defs = load(d_owner, d_repo, d_limit, d_before)
    print(
        f"\n{'=' * 78}\nSplit C — {src}→{dst} (Tabassum OP condition; "
        f"train n={len(s_prs)} defects={len(s_defs)} · "
        f"test n={len(d_prs)} defects={len(d_defs)})"
    )
    rf = fit_rf(
        matrix(s_prs, history_index(s_prs)),
        np.array([p.number in s_defs for p in s_prs]),
    )
    proba = rf.predict_proba(matrix(d_prs, history_index(d_prs)))[:, 1]
    y = [p.number in d_defs for p in d_prs]
    report("RF (Kamei 14)", list(zip(proba.tolist(), y, strict=True)))
    report("v3 (static only)", [(s, pr.number in d_defs) for pr, s, _ in replay(d_prs)])
    report(
        "size (LA+LD)",
        [(float(p.additions + p.deletions), p.number in d_defs) for p in d_prs],
    )


def main() -> int:
    within_repo("sentry")
    within_repo("grafana")
    cross_repo("sentry", "grafana")
    cross_repo("grafana", "sentry")
    print(
        "\nBars are pre-registered in "
        "workspace/research/phase1-entry-preregistration.md — read outcomes "
        "against those, not against taste."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
