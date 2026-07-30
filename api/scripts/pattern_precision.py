"""Per-pattern precision from the ledger's findings x outcomes join.

Step 3 of the distillation loop. Steps 1 and 2 exist: every scored PR gets a
durable verdict, and findings are stored against PR identity instead of
being consumed. This asks the question those steps were built for — *which
defect patterns actually predicted defects* — and it is the first analysis
that reads the ledger rather than the probe JSON.

Two tables, because one number would be a lie:

  CORPUS   Precision among ledger rows, and lift against the ledger's own
           base rate. Assumption-free and it works on any ledger, including
           live rows as they accumulate. But the seed corpus is a
           *stratified* draw — ALL known defects plus a uniform subsample of
           clean PRs — so its base rate is ~40%, not the ~2% a repo really
           runs at. Corpus precision is therefore NOT the precision a user
           would see. Lift within the corpus is the comparable quantity.

  POP      The same patterns reweighted to the repo's true base rate pi via
           Bayes, restricted to the newer half where both strata were drawn
           from one frame. This estimates what a user would see. Bootstrap
           CIs over both strata, 1000 resamples, same method and seed as
           llm_probe.population(). Probe rows only — live rows carry no
           stratum, so they are excluded here and counted in CORPUS.

Publishing rule (see the DO NOT RETRY table): never quote a CORPUS
precision as a precision. Quote lift, or quote POP with its interval.

    DATABASE_URL=... uv run python scripts/pattern_precision.py
    ... scripts/pattern_precision.py --min-prs 3 --repo getsentry/sentry
"""

import functools
import json
import sys
from pathlib import Path

import numpy as np
from rf_kamei import REPOS, load

from doug import store
from doug.precision import corpus_table, fold

print = functools.partial(print, flush=True)  # noqa: A001

CACHE = Path(".backtest-cache")
FRAME = CACHE / "pattern-precision-frame.json"
PROBES = {
    "getsentry/sentry": ("llm-probe", "sentry"),
    "grafana/grafana": ("llm-probe-grafana", "grafana"),
}
SEED = 0
BOOTSTRAPS = 1000
DEFAULT_MIN_PRS = 5  # matches the distillability bar's "slugs on >=5 PRs"


def _frame_pi(repo: str, tag: str) -> tuple[float, int, int]:
    """Base rate of the newer half of the harvest frame — the population
    the probe sampled from. Cached: recomputing means re-reading ~500MB."""
    cached = json.loads(FRAME.read_text()) if FRAME.exists() else {}
    if repo in cached:
        c = cached[repo]
        return c["pi"], c["n_newer"], c["n_defects"]
    prs, defects = load(*REPOS[tag])
    ordered = sorted(prs, key=lambda p: p.created_at)
    newer = ordered[len(ordered) // 2 :]
    n_def = sum(1 for p in newer if p.number in defects)
    pi = n_def / len(newer)
    cached[repo] = {"pi": pi, "n_newer": len(newer), "n_defects": n_def}
    FRAME.write_text(json.dumps(cached, indent=2))
    return pi, len(newer), n_def


def _pop_precision(d_hit: int, d_n: int, c_hit: int, c_n: int, pi: float) -> float:
    """P(defect | pattern) at the population base rate, from the two strata.

    Bayes: the strata estimate P(pattern | defect) and P(pattern | clean);
    pi supplies the prior the enriched sample destroyed.
    """
    if d_n == 0 or c_n == 0:
        return float("nan")
    p_d, p_c = d_hit / d_n, c_hit / c_n
    denom = pi * p_d + (1 - pi) * p_c
    return pi * p_d / denom if denom else float("nan")


def population_table(repo: str, carriers: dict, min_prs: int) -> tuple[list[dict], dict]:
    probe_dir, tag = PROBES[repo]
    meta = json.loads((CACHE / probe_dir / "sample.json").read_text())
    newer = set(meta["newer_half"])
    d_stratum = [n for n in meta["defects"] if n in newer]
    c_stratum = [n for n in meta["clean"] if n in newer]
    pi, n_newer, n_def = _frame_pi(repo, tag)

    carried: dict[str, set] = {
        p: {k[1] for k in prs if k[0] == repo} for p, prs in carriers.items()
    }
    rng = np.random.default_rng(SEED)
    d_arr, c_arr = np.array(d_stratum), np.array(c_stratum)
    # One resample draw shared by every pattern, so the intervals reflect a
    # common sample rather than independent luck per pattern.
    draws = [
        (d_arr[rng.integers(0, len(d_arr), len(d_arr))],
         c_arr[rng.integers(0, len(c_arr), len(c_arr))])
        for _ in range(BOOTSTRAPS)
    ]

    rows = []
    for pattern, prs in carried.items():
        d_hit = sum(1 for n in d_stratum if n in prs)
        c_hit = sum(1 for n in c_stratum if n in prs)
        if d_hit + c_hit < min_prs:
            continue
        prec = _pop_precision(d_hit, len(d_stratum), c_hit, len(c_stratum), pi)
        boots = [
            _pop_precision(
                int(np.isin(d, list(prs)).sum()), len(d),
                int(np.isin(c, list(prs)).sum()), len(c), pi,
            )
            for d, c in draws
        ]
        boots = [b for b in boots if not np.isnan(b)]
        lo, hi = (np.percentile(boots, [2.5, 97.5]) if boots else (float("nan"),) * 2)
        rows.append({
            "pattern": pattern,
            "d_hit": d_hit, "d_n": len(d_stratum),
            "c_hit": c_hit, "c_n": len(c_stratum),
            "precision": prec, "ci": (lo, hi),
            "lift": prec / pi if pi else 0.0,
            "clears_base": lo > pi,
        })
    rows.sort(key=lambda r: -r["lift"])
    frame = {"pi": pi, "n_newer": n_newer, "n_defects": n_def,
             "d_n": len(d_stratum), "c_n": len(c_stratum)}
    return rows, frame


def main() -> int:
    args = sys.argv[1:]
    min_prs = int(args[args.index("--min-prs") + 1]) if "--min-prs" in args else DEFAULT_MIN_PRS
    only = args[args.index("--repo") + 1] if "--repo" in args else None

    if not store.enabled():
        print("DATABASE_URL not set — nothing to join")
        return 1
    join = store.pattern_join(repo=only)
    if not join["prs"]:
        print("no PRs with known outcomes in the ledger")
        return 1
    is_defect, carriers = fold(join)

    repos = sorted({k[0] for k in is_defect})
    print(
        f"ledger join: {len(is_defect)} PRs with known outcomes across "
        f"{len(repos)} repo(s), {sum(is_defect.values())} defects, "
        f"{len(carriers)} patterns ({len(join['hits'])} PR-pattern pairs)"
    )

    rows, base = corpus_table(is_defect, carriers, min_prs)
    print(
        f"\nCORPUS — precision among ledger rows (base {base:.0%}). "
        "ENRICHED SAMPLE: read the lift column, not the precision column."
    )
    print(f"  {'pattern':<28}{'PRs':>5}{'def':>5}{'prec':>7}{'95% CI':>14}{'lift':>7}")
    for r in rows:
        star = " *" if r["clears_base"] else ""
        ci = "[{:.0%},{:.0%}]".format(r["ci_low"], r["ci_high"])
        print(
            f"  {r['pattern']:<28}{r['prs']:>5}{r['defects']:>5}{r['precision']:>7.0%}"
            f"{ci:>14}{r['lift']:>6.2f}x{star}"
        )
    n_star = sum(r["clears_base"] for r in rows)
    print(
        f"  * interval clears the corpus base rate ({n_star} of {len(rows)} patterns "
        f"at >={min_prs} PRs). Uncorrected for multiplicity: at 95% and "
        f"{len(rows)} patterns, ~{0.05 * len(rows):.1f} stars are expected by chance."
    )

    for repo in repos:
        if repo not in PROBES:
            print(f"\nPOP — {repo}: no probe stratum recorded, skipped (live rows).")
            continue
        rows, frame = population_table(repo, carriers, min_prs)
        print(
            f"\nPOP — {repo} reweighted to pi={frame['pi']:.2%} "
            f"({frame['n_defects']}/{frame['n_newer']} newer-half frame) · strata "
            f"{frame['d_n']} defect + {frame['c_n']} clean"
        )
        print(f"  {'pattern':<28}{'D':>7}{'C':>9}{'prec':>7}{'95% CI':>16}{'lift':>7}")
        for r in rows:
            star = " *" if r["clears_base"] else ""
            d = f"{r['d_hit']}/{r['d_n']}"
            c = f"{r['c_hit']}/{r['c_n']}"
            ci = "[{:.1%},{:.1%}]".format(*r["ci"])
            print(
                f"  {r['pattern']:<28}{d:>7}{c:>9}{r['precision']:>7.1%}"
                f"{ci:>16}{r['lift']:>6.1f}x{star}"
            )
        print(f"  * interval clears pi ({sum(r['clears_base'] for r in rows)} of {len(rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
