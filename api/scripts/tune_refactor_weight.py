"""v4 attempt 2: pick the `refactor-pure-mod` weight on the TRAIN HALF ONLY.

Protocol is pre-registered in workspace/research/backtest-phase0-notes.md and
was written before this script ran. In one sentence: the older 2500 of the
5000-PR sentry cache is split into four expanding-window folds, each fold
learns its own hotspot segments and scores the next 500 PRs, and candidate
weights are compared on the defect-weighted pooled capture curve. The newer
2500 (the holdout) is never loaded here.

Sweeping happens through `doug.scoring.score` itself: the candidate rule is
appended to whatever the real `_rules` returns, so base score, weight summing,
capping and banding are the shipped code, not a copy of it. Only the rule
under test is supplied by the harness — which is what makes it a candidate.

    cd repo/api && uv run python scripts/tune_refactor_weight.py
"""

import functools
from pathlib import Path

from doug import scoring
from doug.backtest.curve import capture_curve
from doug.backtest.git_labels import find_reverted_prs
from doug.backtest.harvest import harvest
from doug.backtest.hotspots import learn_hotspot_segments
from doug.backtest.replay import replay
from doug.models import Reason

print = functools.partial(print, flush=True)  # noqa: A001

CACHE = Path(".backtest-cache")
REPO = ("getsentry", "sentry")
LIMIT, BEFORE = 5000, "2026-06-15"

# Pre-registered. 0.15 and 0.20 are diagnostics only — at 0.15 a refactor-only
# PR ties the config-flag band, and 0.20 is the attempt-1 setting that failed.
GRID = [0.0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12]
DIAGNOSTIC_ONLY = [0.15, 0.20]
RATES = [0.05, 0.10, 0.20, 0.30]

FOLD_EDGES = [(0, 500), (0, 1000), (0, 1500), (0, 2000)]  # learn windows
FOLD_SIZE = 500


_SHIPPED_RULES = scoring._rules


def with_candidate(weight: float):
    """Shipped ruleset + `refactor-pure-mod` at `weight`."""

    def rules(f):
        out = _SHIPPED_RULES(f)
        if weight > 0 and f.refactor_title and f.pure_modification:
            out.append(
                Reason(
                    rule="refactor-pure-mod",
                    label="Titled a refactor, but every file was edited in place",
                    weight=weight,
                )
            )
        return out

    return rules


def load():
    prs = harvest(*REPO, LIMIT, None, CACHE, before=BEFORE)
    defects = {p.number for p in prs} & find_reverted_prs(*REPO, CACHE)
    ordered = sorted(prs, key=lambda p: p.created_at)
    return ordered[: len(ordered) // 2], defects


def folds(train, defects):
    """(learn_window, eval_window, eval_defects) per pre-registered split."""
    out = []
    for lo, hi in FOLD_EDGES:
        learn = train[lo:hi]
        evalw = train[hi : hi + FOLD_SIZE]
        if not evalw:
            continue
        out.append((learn, evalw, {p.number for p in evalw} & defects))
    return out


def pooled(fold_specs, weight):
    """Defect-weighted pooled capture at each flag rate for one weight."""
    scoring._rules = with_candidate(weight)
    caught = dict.fromkeys(RATES, 0.0)
    total = 0
    for learn, evalw, eval_defs in fold_specs:
        if not eval_defs:
            continue
        hot = learn_hotspot_segments(learn, {p.number for p in learn} & ALL_DEFECTS)
        scored = replay(evalw, extra_hotspots=hot)
        curve = capture_curve([(s, pr.number in eval_defs) for pr, s, _ in scored])
        for r in RATES:
            caught[r] += curve.capture_at(r) * len(eval_defs)
        total += len(eval_defs)
    return {r: caught[r] / total for r in RATES}, total


def main() -> int:
    global ALL_DEFECTS
    train, ALL_DEFECTS = load()
    fold_specs = folds(train, ALL_DEFECTS)

    print(f"train half: {len(train)} PRs, {len({p.number for p in train} & ALL_DEFECTS)} defects")
    for i, (learn, evalw, d) in enumerate(fold_specs):
        print(f"  fold {'ABCD'[i]}: learn {len(learn)} → score {len(evalw)}, {len(d)} defects")

    results = {}
    for w in GRID + DIAGNOSTIC_ONLY:
        results[w], pooled_n = pooled(fold_specs, w)

    print(f"\npooled over {pooled_n} defects (defect-weighted across folds)")
    print(f"{'w':>6} " + " ".join(f"{f'@{int(r * 100)}%':>8}" for r in RATES) + "   Δ@20%")
    baseline = results[0.0]
    for w in GRID + DIAGNOSTIC_ONLY:
        row = results[w]
        d20 = (row[0.20] - baseline[0.20]) * pooled_n
        tag = "  (diagnostic)" if w in DIAGNOSTIC_ONLY else ""
        print(
            f"{w:>6.2f} "
            + " ".join(f"{row[r]:>8.1%}" for r in RATES)
            + f"   {d20:+.2f} defects{tag}"
        )

    # Pre-registered selection: max pooled @20%, ties → @30%, @10%, smaller w.
    best = max(GRID, key=lambda w: (results[w][0.20], results[w][0.30], results[w][0.10], -w))
    b = results[best]
    print(f"\nselected by criterion: w={best:.2f}")

    gains = {w: (results[w][0.20] - baseline[0.20]) * pooled_n for w in GRID}
    idx = GRID.index(best)
    neighbours = [GRID[i] for i in (idx - 1, idx + 1) if 0 <= i < len(GRID)]
    gates = {
        "1. beats w=0 on @20% by >=1 pooled defect": gains[best] >= 1.0,
        "2. no loss at @30% or @10% vs w=0": (
            b[0.30] >= baseline[0.30] and b[0.10] >= baseline[0.10]
        ),
        "3. plateau: an adjacent weight also beats w=0": any(
            gains[n] > 0 for n in neighbours
        ),
    }
    print()
    for name, ok in gates.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    if all(gates.values()):
        print(f"\nGATES PASS → set REFACTOR_PURE_MOD_WEIGHT = {best:.2f}, spend the holdout once.")
    else:
        print("\nGATES FAIL → rule stays out, holdout NOT spent. Record the negative.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
