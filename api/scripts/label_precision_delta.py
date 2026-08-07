"""How much do the impossible labels actually move the numbers?

A revert cannot land before the PR it reverts. Some do in our label set —
6/67 on sentry, 6/54 on grafana at >1 day — because `pr_titles_from_subjects`
is newest-wins, so a revert of an older PR with a reused title gets
attributed to a newer one.

Filtering them is tempting but it invalidates every published figure, and the
detector is partial: it only catches collisions with an *older* PR (negative
lag). A collision with a newer one produces positive lag and stays invisible.
So before making the filter a default, measure whether it changes anything.

This prints every headline number both ways. It decides nothing.

It did, however, settle it: on this evidence the filter was adopted for the
live path too (`publication-preregistration.md` §6.1), so `TOLERANCE_DAYS` is
now `git_labels`' and this script measures the cost of a decision rather than
informing an open one. The "AS-IS" column is what the published rate would
have been without the bound, which is what §6.1 requires stay visible.

    cd repo/api && uv run python scripts/label_precision_delta.py
"""

import functools
from datetime import datetime
from pathlib import Path

from doug.backtest.curve import capture_curve, cleared_band
from doug.backtest.git_labels import TOLERANCE_DAYS, find_reverted_prs_dated
from doug.backtest.harvest import harvest
from doug.backtest.hotspots import learn_hotspot_segments
from doug.backtest.replay import replay

print = functools.partial(print, flush=True)  # noqa: A001

CACHE = Path(".backtest-cache")
RATES = [0.05, 0.10, 0.20, 0.30]
REPOS = [
    ("getsentry", "sentry", 5000, "2026-06-15"),
    ("grafana", "grafana", 12000, "2026-06-15"),
]


def lag_days(revert_iso: str, merged_iso: str) -> float:
    delta = datetime.fromisoformat(revert_iso) - datetime.fromisoformat(merged_iso)
    return delta.total_seconds() / 86400


def evaluate(prs, defects):
    """Full-sample curve + cleared band, and the time-split holdout."""
    scored = replay(prs)
    curve = capture_curve([(s, pr.number in defects) for pr, s, _ in scored])
    bands = {r: cleared_band(curve, len(prs), len(defects), r) for r in RATES}

    ordered = sorted(prs, key=lambda p: p.created_at)
    mid = len(ordered) // 2
    train, test = ordered[:mid], ordered[mid:]
    train_defs = {p.number for p in train} & defects
    test_defs = {p.number for p in test} & defects
    hold = hold_bands = None
    if len(train_defs) >= 4 and len(test_defs) >= 4:
        learned = learn_hotspot_segments(train, train_defs)
        test_scored = replay(test, extra_hotspots=learned)
        hold = capture_curve([(s, pr.number in test_defs) for pr, s, _ in test_scored])
        hold_bands = {r: cleared_band(hold, len(test), len(test_defs), r) for r in RATES}
    return curve, bands, hold, hold_bands, len(test_defs)


def main() -> int:
    for owner, repo, limit, before in REPOS:
        prs = harvest(owner, repo, limit, None, CACHE, before=before)
        by = {p.number: p for p in prs}
        dated = {n: d for n, d in find_reverted_prs_dated(owner, repo, CACHE).items() if n in by}

        # Sub-day negatives are committer-date vs merged_at skew on same-day
        # reverts, not mislabels, so only a revert dated a clear day or more
        # before the merge is impossible. `TOLERANCE_DAYS` is `git_labels`'
        # since the adjudicator adopted the same bound — this script measures
        # what that bound costs, so it has to read the adjudicator's number
        # rather than keep one of its own.
        dropped = {
            n: lag_days(d, by[n].merged_at)
            for n, d in dated.items()
            if lag_days(d, by[n].merged_at) < -TOLERANCE_DAYS
        }
        all_defects = set(dated)
        clean_defects = all_defects - set(dropped)

        print(f"\n{'=' * 74}\n{owner}/{repo} — {len(prs)} PRs")
        print(
            f"labels {len(all_defects)} → {len(clean_defects)} "
            f"(dropped {len(dropped)} = {len(dropped) / len(all_defects):.0%} "
            f"with revert >{TOLERANCE_DAYS}d before merge)"
        )
        for n, lag in sorted(dropped.items(), key=lambda kv: kv[1]):
            print(f"   {lag:>8.1f}d  #{n}  {by[n].title[:58]}")

        a = evaluate(prs, all_defects)
        b = evaluate(prs, clean_defects)

        print(f"\n{'':<22}{'AS-IS':>22}{'FILTERED':>22}")
        print(f"{'full-sample capture':<22}", end="")
        for curve, _, _, _, _ in (a, b):
            print(
                f"{'  '.join(f'{curve.capture_at(r):.0%}' for r in RATES):>22}", end=""
            )
        print(f"\n{'full-sample AUC':<22}{a[0].auc:>22.3f}{b[0].auc:>22.3f}")

        print(f"{'cleared lift @20/@30':<22}", end="")
        for _, bands, _, _, _ in (a, b):
            lifts = f"{bands[0.20].density_lift:.2f}x  {bands[0.30].density_lift:.2f}x"
            print(f"{lifts:>22}", end="")
        print()

        if a[2] and b[2]:
            print(f"{'holdout defects':<22}{a[4]:>22}{b[4]:>22}")
            print(f"{'holdout capture':<22}", end="")
            for _, _, hold, _, _ in (a, b):
                caps = "  ".join(f"{hold.capture_at(r):.0%}" for r in RATES)
                print(f"{caps:>22}", end="")
            print(f"\n{'holdout AUC':<22}{a[2].auc:>22.3f}{b[2].auc:>22.3f}")
            print(f"{'holdout cleared @20/@30':<22}", end="")
            for _, _, _, hb, _ in (a, b):
                lifts = f"{hb[0.20].density_lift:.2f}x  {hb[0.30].density_lift:.2f}x"
                print(f"{lifts:>22}", end="")
            print()
        else:
            print("holdout: skipped (too few defects in a half)")

    print(f"\n{'=' * 74}")
    print("Rates shown are @5/@10/@20/@30. Nothing here changes a default.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
