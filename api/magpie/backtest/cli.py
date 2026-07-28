"""magpie-backtest: replay a repo's history, measure the capture curve.

Usage:
    uv run magpie-backtest owner/repo [--limit 300] [--token ...]

The kill criterion, from the thesis: if flagging ~10% of PRs captures
~40% of defect-inducing changes instead of ~70%, Magpie is an expensive
random sampler. This command produces that number.
"""

import argparse
import functools
import json
import sys
from pathlib import Path

from .curve import capture_curve, rule_stats
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
    ap.add_argument("--output", type=Path, default=None, help="JSON report path")
    args = ap.parse_args()

    owner, _, repo = args.repo.partition("/")
    if not repo:
        ap.error("repo must be owner/repo")

    token = resolve_token(args.token)
    if token is None:
        print("warning: no GitHub token found; unauthenticated rate limit is 60/hr")

    print(f"harvesting {args.limit} merged PRs from {owner}/{repo}…")
    prs = harvest(owner, repo, args.limit, token, args.cache_dir, before=args.before)
    reverts = search_reverts(owner, repo, token, args.cache_dir)
    defects = label_defects(prs, extra_reverts=reverts)
    print(
        f"{len(prs)} merged PRs · {len(reverts)} revert PRs repo-wide · "
        f"{len(defects)} in-window PRs labeled defect-inducing"
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
