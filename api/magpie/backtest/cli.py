"""magpie-backtest: replay a repo's history, measure the capture curve.

Usage:
    uv run magpie-backtest owner/repo [--limit 500] [--before 2026-06-15]

The kill criterion, from the thesis: if flagging ~10% of PRs captures
~40% of defect-inducing changes instead of ~70%, Magpie is an expensive
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

from .curve import capture_curve, rule_stats
from .git_labels import find_reverted_prs
from .harvest import harvest, resolve_token, search_reverts
from .label import label_defects
from .replay import replay

# Progress output should be visible when piped (CI, terminals files).
print = functools.partial(print, flush=True)  # noqa: A001

FLAG_RATES = [0.05, 0.10, 0.20, 0.30]


def main() -> int:
    ap = argparse.ArgumentParser(prog="magpie-backtest", description=__doc__)
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
    magpie = capture_curve([(s, pr.number in defects) for pr, s, _ in scored])
    size = capture_curve(
        [(float(pr.additions + pr.deletions), pr.number in defects) for pr, _, _ in scored]
    )

    print(f"\n{'flag rate':>10} {'magpie':>8} {'size-only':>10} {'random':>8}")
    for f in FLAG_RATES:
        print(
            f"{f:>10.0%} {magpie.capture_at(f):>8.0%} {size.capture_at(f):>10.0%} {f:>8.0%}"
        )
    print(f"\nAUC — magpie {magpie.auc:.3f} · size-only {size.auc:.3f} · random 0.500")

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
                    f"{f:.2f}": round(magpie.capture_at(f), 4) for f in FLAG_RATES
                },
                "auc": {"magpie": magpie.auc, "size_only": size.auc},
                "curve": [p.model_dump() for p in magpie.points],
                "rules": [s.model_dump() for s in stats],
            },
            indent=1,
        )
    )
    print(f"\nreport written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
