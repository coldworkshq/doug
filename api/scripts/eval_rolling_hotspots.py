"""Does re-learning hotspots beat learning them once?

Rolling-origin backtest on the TRAIN HALF ONLY (older 2500 of the sentry
5000). Protocol pre-registered in workspace/research/rolling-hotspots-design.md
before this ran. The newer 2500 holdout is never loaded here.

Three arms, scored on identical 250-PR blocks and pooled the same way as
scripts/tune_refactor_weight.py so the two are directly comparable:

    static       HOTSPOT_SEGMENTS only, no learning at all
    frozen       learned once on the run-up window, then never updated
    rolling(K,D) adaptive window recomputed at every block

Only *training* labels are censored by revert date — a learner at time T may
use a defect only if its revert had already landed. Evaluation uses full
hindsight labels, because the question is whether the block's PRs really did
turn out bad, not whether we would have found out in time.

    cd repo/api && uv run python scripts/eval_rolling_hotspots.py
"""

import functools
from pathlib import Path

from doug.backtest.curve import capture_curve
from doug.backtest.git_labels import find_reverted_prs_dated
from doug.backtest.harvest import harvest
from doug.backtest.hotspots import learn_hotspot_segments, rolling_window
from doug.backtest.replay import replay

print = functools.partial(print, flush=True)  # noqa: A001

CACHE = Path(".backtest-cache")
REPO = ("getsentry", "sentry")
LIMIT, BEFORE = 5000, "2026-06-15"

RATES = [0.05, 0.10, 0.20, 0.30]
BLOCK = 250
RUN_UP = 500  # history reserved before the first scored block

K_GRID = [8, 12, 16, 24]
D_GRID = [30, 60, 90, 180]


def load():
    """Train half only, ordered by merge time, plus dated labels."""
    prs = harvest(*REPO, LIMIT, None, CACHE, before=BEFORE)
    # Train/holdout split stays on created_at, matching every prior run.
    train = sorted(prs, key=lambda p: p.created_at)[: len(prs) // 2]
    # The rolling axis is merge time: that is when a PR enters the history a
    # learner can see.
    train.sort(key=lambda p: p.merged_at)
    labels = find_reverted_prs_dated(*REPO, CACHE)
    return train, {n: d for n, d in labels.items() if n in {p.number for p in train}}


def blocks(train):
    for start in range(RUN_UP, len(train) - BLOCK + 1, BLOCK):
        yield train[start : start + BLOCK]


def evaluate(train, labels, learn_for):
    """Pooled capture for one arm. `learn_for(as_of) -> hotspot segments`."""
    caught = dict.fromkeys(RATES, 0.0)
    total = 0
    learned_sets = []
    for block in blocks(train):
        block_defects = {p.number for p in block if p.number in labels}
        if not block_defects:
            continue
        hot = learn_for(block[0].merged_at)
        learned_sets.append(hot)
        scored = replay(block, extra_hotspots=hot)
        curve = capture_curve([(s, pr.number in block_defects) for pr, s, _ in scored])
        for r in RATES:
            caught[r] += curve.capture_at(r) * len(block_defects)
        total += len(block_defects)
    return {r: caught[r] / total for r in RATES}, total, learned_sets


def churn(sets):
    """Mean Jaccard distance between consecutive learned sets."""
    pairs = [
        1 - len(a & b) / len(a | b)
        for a, b in zip(sets, sets[1:], strict=False)
        if a or b
    ]
    return sum(pairs) / len(pairs) if pairs else 0.0


def row(name, res, n, baseline=None):
    line = f"{name:<18}" + " ".join(f"{res[r]:>8.1%}" for r in RATES)
    if baseline is not None:
        line += f"   {(res[0.20] - baseline[0.20]) * n:+6.2f} def @20%"
    return line


def main() -> int:
    train, labels = load()
    scored_blocks = [b for b in blocks(train) if {p.number for p in b} & set(labels)]
    print(
        f"train half: {len(train)} PRs ({train[0].merged_at[:10]} → "
        f"{train[-1].merged_at[:10]}), {len(labels)} defects"
    )
    print(f"{len(scored_blocks)} scored blocks of {BLOCK} after a {RUN_UP}-PR run-up")
    for i, b in enumerate(scored_blocks):
        print(
            f"  block {i + 1}: {b[0].merged_at[:10]} → {b[-1].merged_at[:10]}, "
            f"{len({p.number for p in b} & set(labels))} defects"
        )

    header = f"{'arm':<18}" + " ".join(f"{f'@{int(r * 100)}%':>8}" for r in RATES)

    static_res, n, _ = evaluate(train, labels, lambda _as_of: None)

    # Frozen: exactly today's design — learn once, never update. Censored at
    # the first origin so it is not quietly handed future labels.
    first = next(blocks(train))[0].merged_at
    fw, fd = rolling_window(train, labels, first, min_defects=10**6, max_days=36500)
    frozen_set = learn_hotspot_segments(fw, fd)
    frozen_res, _, _ = evaluate(train, labels, lambda _as_of: frozen_set)
    print(
        f"\nfrozen run-up: {len(fw)} PRs, {len(fd)} defects KNOWN by {first[:10]}, "
        f"{len(frozen_set)} segments learned"
    )

    print(f"\npooled over {n} defects (defect-weighted across blocks)")
    print(header)
    print(row("static", static_res, n, frozen_res))
    print(row("frozen (today)", frozen_res, n))

    results = {}
    for k in K_GRID:
        for d in D_GRID:
            def learn_for(as_of, k=k, d=d):
                w, defs = rolling_window(train, labels, as_of, min_defects=k, max_days=d)
                return learn_hotspot_segments(w, defs)

            results[(k, d)], _, sets = evaluate(train, labels, learn_for)
            print(
                row(f"rolling K={k} D={d}", results[(k, d)], n, frozen_res)
                + f"   churn {churn(sets):.2f}"
            )

    # Pre-registered: max @20%, ties → @30%, @10%, then larger K.
    best = max(results, key=lambda kd: (
        results[kd][0.20], results[kd][0.30], results[kd][0.10], kd[0]
    ))
    gain = (results[best][0.20] - frozen_res[0.20]) * n
    print(f"\nselected: K={best[0]} D={best[1]}  ({gain:+.2f} defects @20% vs frozen)")
    if gain >= 1.0:
        print("GATE PASS — re-learning beats learning once.")
    else:
        print("GATE FAIL — no evidence re-learning beats frozen on this window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
