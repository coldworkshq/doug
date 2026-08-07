"""Screen candidate features against the bar today's evidence set.

Doug is doing Just-In-Time defect prediction, a field with ~25 years of
results. This harness screens candidates from that literature instead of
inventing our own, and reports them the way the field does.

Feature families are Kamei et al. (TSE 2013), "A Large-Scale Empirical Study
of Just-in-Time Quality Assurance" — 14 metrics in five dimensions: diffusion,
size, purpose, history, experience. Change entropy is Hassan (ICSE 2009).
Every one is computed from data already in the harvest cache, and none
contains repo-specific vocabulary — which is exactly what `hotspot_path` and
`config_flag` got wrong (both fire 0/12,000 times on grafana).

Two bars, both from today's measurements:

  1. Beat `size` (LA+LD). Zhou et al. (TOSEM 2018) showed a bare module-size
     ranking matches or beats most published cross-project models, so the
     field now requires it as a baseline. On grafana, size already beats
     shipped Doug — anything that cannot clear it is not a finding.
  2. Earn its place on the population `hotspot_path` misses. On sentry the
     hotspot band is 23% of PRs at 2.34x and so *is* the 20% budget; a
     feature overlapping it adds nothing and one firing outside it at lower
     lift costs capture by eviction. On grafana hotspot is silent, so the
     whole repo is that population and the bar is simply "beat random" —
     which makes grafana the clean portability instrument.

Reports single-feature AUC and capture@20% per repo, plus the same restricted
to non-hotspot PRs. It ranks candidates; it does not fit weights.

    cd repo/api && uv run python scripts/screen_features.py
"""

import functools
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from doug.backtest.curve import capture_curve
from doug.backtest.git_labels import TOLERANCE_DAYS, find_reverted_prs_dated
from doug.backtest.harvest import harvest
from doug.backtest.replay import to_metadata
from doug.features import extract_features

print = functools.partial(print, flush=True)  # noqa: A001

CACHE = Path(".backtest-cache")
REPOS = [
    ("getsentry", "sentry", 5000, "2026-06-15"),
    ("grafana", "grafana", 12000, "2026-06-15"),
]

_FIX_WORDS = ("fix", "bug", "hotfix", "patch", "repair", "correct")


def _dirs(files: list[str]) -> set[str]:
    return {f.rsplit("/", 1)[0] if "/" in f else "" for f in files}


def _subsystems(files: list[str]) -> set[str]:
    return {f.split("/", 1)[0] for f in files}


def _entropy(pr) -> float:
    """Hassan's change entropy: how evenly churn is spread across files.

    A diffuse change is harder to reason about than the same churn in one
    place. Needs per-file counts, so it is unavailable on detail-less rows.
    """
    if not pr.file_details:
        return 0.0
    churn = [f.additions + f.deletions for f in pr.file_details]
    total = sum(churn)
    if total <= 0:
        return 0.0
    ps = [c / total for c in churn if c > 0]
    return -sum(p * math.log(p) for p in ps)


def history_index(prs):
    """For each PR, what the repo knew about its files *before* it merged.

    Kamei's history (NDEV/NUC/AGE) and experience (EXP/SEXP) dimensions.
    Built by walking merge order and reading state strictly before each PR,
    so nothing here can see its own future.
    """
    ordered = sorted(prs, key=lambda p: p.merged_at)
    file_authors: dict[str, set[str]] = defaultdict(set)
    file_touches: dict[str, int] = defaultdict(int)
    file_last: dict[str, datetime] = {}
    author_prs: dict[str, int] = defaultdict(int)
    author_subsys: dict[tuple[str, str], int] = defaultdict(int)

    out = {}
    for pr in ordered:
        merged = datetime.fromisoformat(pr.merged_at)
        ndev = set()
        nuc = 0
        ages = []
        for f in pr.files:
            ndev |= file_authors[f]
            nuc += file_touches[f]
            if f in file_last:
                ages.append((merged - file_last[f]).total_seconds() / 86400)
        subs = _subsystems(pr.files)
        out[pr.number] = {
            "ndev": len(ndev),
            "nuc": nuc,
            # Recently-touched files are the churny ones; unseen files score 0.
            "recency": 1 / (1 + min(ages)) if ages else 0.0,
            "exp": author_prs[pr.author],
            "sexp": sum(author_subsys[(pr.author, s)] for s in subs),
        }

        for f in pr.files:
            file_authors[f].add(pr.author)
            file_touches[f] += 1
            file_last[f] = merged
        author_prs[pr.author] += 1
        for s in subs:
            author_subsys[(pr.author, s)] += 1
    return out


# (name, dimension, fn(pr, hist) -> float). Higher is predicted riskier.
FEATURES = [
    ("size (LA+LD)", "size", lambda p, h: float(p.additions + p.deletions)),
    ("la", "size", lambda p, h: float(p.additions)),
    ("ld", "size", lambda p, h: float(p.deletions)),
    ("nf (files)", "diffusion", lambda p, h: float(len(p.files))),
    ("nd (dirs)", "diffusion", lambda p, h: float(len(_dirs(p.files)))),
    ("ns (subsystems)", "diffusion", lambda p, h: float(len(_subsystems(p.files)))),
    ("entropy", "diffusion", lambda p, h: _entropy(p)),
    ("churn per file", "size", lambda p, h: (p.additions + p.deletions) / max(1, len(p.files))),
    ("is_fix (title)", "purpose",
     lambda p, h: float(any(w in p.title.lower() for w in _FIX_WORDS))),
    ("ndev", "history", lambda p, h: float(h["ndev"])),
    ("nuc", "history", lambda p, h: float(h["nuc"])),
    ("recency", "history", lambda p, h: h["recency"]),
    ("exp (author PRs)", "experience", lambda p, h: -float(h["exp"])),
    ("sexp (subsystem)", "experience", lambda p, h: -float(h["sexp"])),
    ("no test delta", "purpose",
     lambda p, h: float(extract_features(to_metadata(p)).test_files == 0)),
]


def screen(prs, defects, hist, subset=None):
    """Single-feature AUC and capture@20% for each candidate."""
    pool = prs if subset is None else subset
    pool_defects = {p.number for p in pool} & defects
    rows = []
    if len(pool_defects) < 4:
        return rows, len(pool), len(pool_defects)
    for name, dim, fn in FEATURES:
        curve = capture_curve(
            [(fn(p, hist[p.number]), p.number in pool_defects) for p in pool]
        )
        rows.append((name, dim, curve.auc, curve.capture_at(0.20)))
    return rows, len(pool), len(pool_defects)


def main() -> int:
    results = {}
    for owner, repo, limit, before in REPOS:
        prs = harvest(owner, repo, limit, None, CACHE, before=before)
        by = {p.number: p for p in prs}
        dated = {n: d for n, d in find_reverted_prs_dated(owner, repo, CACHE).items() if n in by}
        defects = {
            n for n, d in dated.items()
            if (datetime.fromisoformat(d) - datetime.fromisoformat(by[n].merged_at)).days
            >= -TOLERANCE_DAYS
        }
        hist = history_index(prs)
        cold = [p for p in prs if not extract_features(to_metadata(p)).hotspot_path]

        full, n_full, d_full = screen(prs, defects, hist)
        nonhot, n_cold, d_cold = screen(prs, defects, hist, subset=cold)
        results[f"{owner}/{repo}"] = (full, nonhot, n_full, d_full, n_cold, d_cold)

        print(f"\n{'=' * 78}")
        print(f"{owner}/{repo} — {n_full} PRs, {d_full} defects (impossible labels dropped)")
        print(f"non-hotspot subset: {n_cold} PRs, {d_cold} defects")
        print(f"\n{'feature':<22}{'dim':<12}{'AUC':>8}{'@20%':>8}   {'AUC*':>8}{'@20%*':>8}")
        order = sorted(range(len(full)), key=lambda i: -full[i][2])
        for i in order:
            name, dim, auc, cap = full[i]
            star = f"{nonhot[i][2]:>8.3f}{nonhot[i][3]:>8.0%}" if nonhot else f"{'—':>8}{'—':>8}"
            print(f"{name:<22}{dim:<12}{auc:>8.3f}{cap:>8.0%}   {star}")
        print("* = restricted to PRs where hotspot_path does not fire")

    # Portability is the whole question: a feature that only works on one repo
    # is what we already have.
    print(f"\n{'=' * 78}\nPORTABILITY — AUC on both repos (>0.5 = better than random)\n")
    keys = list(results)
    print(f"{'feature':<22}" + "".join(f"{k:>22}" for k in keys) + f"{'min':>8}")
    scored = []
    for i, (name, _, _, _) in enumerate(results[keys[0]][0]):
        aucs = [results[k][0][i][2] for k in keys]
        scored.append((min(aucs), name, aucs))
    for worst, name, aucs in sorted(scored, reverse=True):
        print(f"{name:<22}" + "".join(f"{a:>22.3f}" for a in aucs) + f"{worst:>8.3f}")
    print("\nRanked by worst-repo AUC. Nothing here is wired into scoring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
