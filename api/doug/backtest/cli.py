"""doug-backtest: replay a repo's history, measure the capture curve.

Usage:
    uv run doug-backtest owner/repo [--limit 500] [--before 2026-06-15]

The kill criterion, from the thesis: if flagging ~10% of PRs captures
~40% of defect-inducing changes instead of ~70%, Doug is an expensive
random sampler. This command produces that number.

Default labeling is git history (treeless clone, zero API quota for
labels). The scored set is a contiguous harvest window — known defects
are *not* preferentially injected, because that would bias the capture
curve used for the kill criterion. Widen --limit to raise defect n.
"""

import argparse
import functools
import json
import sys
from pathlib import Path

from .curve import capture_curve, cleared_band, rule_stats
from .git_labels import find_reverted_prs
from .harvest import backfill_file_details, harvest, resolve_token, search_reverts
from .hotspots import learn_hotspot_segments
from .label import label_defects
from .replay import replay

# Progress output should be visible when piped (CI, terminals files).
print = functools.partial(print, flush=True)  # noqa: A001

FLAG_RATES = [0.05, 0.10, 0.20, 0.30]


def main() -> int:
    ap = argparse.ArgumentParser(prog="doug-backtest", description=__doc__)
    ap.add_argument("repo", help="owner/repo, e.g. astral-sh/ruff")
    ap.add_argument("--limit", type=int, default=300, help="merged PRs to harvest")
    ap.add_argument("--token", default=None, help="GitHub token (default: env or gh)")
    ap.add_argument(
        "--cache-dir", type=Path, default=Path(".backtest-cache"), help="harvest cache"
    )
    ap.add_argument(
        "--before",
        default=None,
        help="only harvest PRs created before this date (YYYY-MM-DD); "
        "guards against right-censoring — young PRs haven't had time to be reverted",
    )
    ap.add_argument(
        "--labels",
        choices=("git", "api", "both"),
        default="git",
        help="defect label source (default: git — dense, zero API quota)",
    )
    ap.add_argument("--output", type=Path, default=None, help="JSON report path")
    ap.add_argument(
        "--backfill-details",
        action="store_true",
        help="fetch per-file stats + patch text for cached PRs missing them "
        "(~1 request/PR; checkpointed, resumable)",
    )
    args = ap.parse_args()

    owner, _, repo = args.repo.partition("/")
    if not repo:
        ap.error("repo must be owner/repo")

    token = resolve_token(args.token)
    if token is None:
        print("warning: no GitHub token found; unauthenticated rate limit is 60/hr")

    git_defects: set[int] = set()
    if args.labels in ("git", "both"):
        print(f"labeling defects from git history of {owner}/{repo}…")
        git_defects = find_reverted_prs(owner, repo, args.cache_dir, token=token)
        print(f"  {len(git_defects)} PR numbers referenced by revert commits")

    print(f"harvesting {args.limit} merged PRs from {owner}/{repo}…")
    prs = harvest(owner, repo, args.limit, token, args.cache_dir, before=args.before)
    if args.backfill_details:
        n = backfill_file_details(
            owner, repo, args.limit, token, args.cache_dir, before=args.before
        )
        print(f"  backfilled file details for {n} PRs")
        prs = harvest(owner, repo, args.limit, token, args.cache_dir, before=args.before)
    seen = {p.number for p in prs}

    defects: set[int] = set()
    api_revert_count = 0
    if args.labels in ("api", "both"):
        reverts = search_reverts(owner, repo, token, args.cache_dir)
        api_revert_count = len(reverts)
        defects |= label_defects(prs, extra_reverts=reverts)
    if args.labels in ("git", "both"):
        # Contiguous window ∩ git labels. No outcome-dependent injection —
        # that would bias capture@10% used for the kill criterion.
        defects |= seen & git_defects

    print(
        f"{len(prs)} scored PRs · "
        f"{api_revert_count} API revert PRs · "
        f"{len(git_defects)} git-labeled defect numbers · "
        f"{len(defects)} in-window labeled defect-inducing"
    )

    if not defects:
        print("no reverts found in this window — widen --limit or pick another repo")
        return 1

    scored = replay(prs)
    doug = capture_curve([(s, pr.number in defects) for pr, s, _ in scored])
    size = capture_curve(
        [(float(pr.additions + pr.deletions), pr.number in defects) for pr, _, _ in scored]
    )

    print(f"\n{'flag rate':>10} {'doug':>8} {'size-only':>10} {'random':>8}")
    for f in FLAG_RATES:
        print(
            f"{f:>10.0%} {doug.capture_at(f):>8.0%} {size.capture_at(f):>10.0%} {f:>8.0%}"
        )
    print(f"\nAUC — doug {doug.auc:.3f} · size-only {size.auc:.3f} · random 0.500")

    # Capture describes the flagged band. The product sells the other one:
    # "auto-merge what Doug cleared" is a claim about defect density among
    # cleared PRs. density_lift < 1 means clearing carries information;
    # at 1 the cleared band is exactly as risky as merging blind.
    base_rate = len(defects) / len(prs)
    bands = [cleared_band(doug, len(prs), len(defects), f) for f in FLAG_RATES]
    print(f"\ncleared band (base defect rate {base_rate:.2%}):")
    print(
        f"{'flag rate':>10} {'cleared':>9} {'missed':>8} "
        f"{'miss rate':>10} {'density':>9} {'vs base':>9}"
    )
    for b in bands:
        print(
            f"{b.flag_rate:>10.0%} {b.cleared_prs:>9} {b.cleared_defects:>8.1f} "
            f"{b.miss_rate:>10.0%} {b.density:>9.2%} {b.density_lift:>8.2f}x"
        )

    stats = rule_stats(
        [rules for _, _, rules in scored], [pr.number in defects for pr, _, _ in scored]
    )
    base = len(defects) / len(prs)
    print(f"\nper-rule precision (base defect rate {base:.1%}):")
    for s in stats:
        print(
            f"  {s.rule:<28} fired {s.fired:>4} · hit {s.defects_hit:>3} "
            f"· precision {s.precision:>6.1%} · lift {s.lift:>5.2f}x"
        )

    # Time-split holdout: learn hotspots on the older half only, score the newer.
    # Requires defects in *both* halves so capture_at can't collapse to 100%.
    holdout = None
    if len(prs) >= 200 and len(defects) >= 8:
        ordered = sorted(prs, key=lambda p: p.created_at)
        mid = len(ordered) // 2
        train, test = ordered[:mid], ordered[mid:]
        train_defs = {p.number for p in train} & defects
        test_defs = {p.number for p in test} & defects
        if len(train_defs) >= 4 and len(test_defs) >= 4:
            learned = learn_hotspot_segments(train, train_defs)
            print(
                f"\nholdout: train n={len(train)} defects={len(train_defs)} · "
                f"test n={len(test)} defects={len(test_defs)} · "
                f"learned hotspots={sorted(learned)[:12]}"
            )
            test_scored = replay(test, extra_hotspots=learned)
            hold = capture_curve(
                [(s, pr.number in test_defs) for pr, s, _ in test_scored]
            )
            print(
                f"holdout capture @10%={hold.capture_at(0.10):.0%}  "
                f"@20%={hold.capture_at(0.20):.0%}  AUC={hold.auc:.3f}"
            )
            hold_bands = [
                cleared_band(hold, len(test), len(test_defs), f) for f in FLAG_RATES
            ]
            print(
                "holdout cleared-band density vs base: "
                + " · ".join(f"@{b.flag_rate:.0%} {b.density_lift:.2f}x" for b in hold_bands)
            )
            holdout = {
                "train_prs": len(train),
                "test_prs": len(test),
                "train_defects": len(train_defs),
                "test_defects": len(test_defs),
                "learned_hotspots": sorted(learned),
                "capture": {
                    f"{f:.2f}": round(hold.capture_at(f), 4) for f in FLAG_RATES
                },
                "auc": hold.auc,
                "cleared_band": [b.model_dump() for b in hold_bands],
            }
        else:
            print(
                f"\nholdout skipped — need ≥4 defects in each half "
                f"(train={len(train_defs)}, test={len(test_defs)})"
            )

    out = args.output or Path(f"backtest-{owner}-{repo}.json")
    out.write_text(
        json.dumps(
            {
                "repo": f"{owner}/{repo}",
                "prs": len(prs),
                "sampling": "contiguous_window",
                "label_source": args.labels,
                "before": args.before,
                "git_defects_total": len(git_defects),
                "defects": sorted(defects),
                "capture": {
                    f"{f:.2f}": round(doug.capture_at(f), 4) for f in FLAG_RATES
                },
                "auc": {"doug": doug.auc, "size_only": size.auc},
                "base_defect_rate": base_rate,
                "cleared_band": [b.model_dump() for b in bands],
                "curve": [p.model_dump() for p in doug.points],
                "rules": [s.model_dump() for s in stats],
                "holdout": holdout,
            },
            indent=1,
        )
    )
    print(f"\nreport written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
