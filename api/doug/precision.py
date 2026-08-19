"""Per-pattern precision over the ledger — assumption-free half.

Everything here works on any ledger with outcomes, makes no claim about how
its rows were sampled, and is therefore safe to serve. The counterpart that
reweights to a repo's true base rate lives in scripts/pattern_precision.py,
because it needs the probe's stratum design and cannot be recovered from
the ledger alone.

The honesty constraint this module encodes: `precision` is precision
*within these rows*. On the seed corpus that is ~30%, against repos whose
real defect rate is 0.4-1.3%, because the corpus deliberately oversampled
defects. Quote `lift`, or quote the reweighted estimate with its interval;
never quote `precision` as the precision a user would see.
"""

from math import sqrt

from .adjudicate import OutcomeKind
from .patterns import from_rule


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n.

    Chosen over the normal approximation because most patterns are sparse
    and sit at k=0 or k=n, where the approximation returns bounds outside
    [0, 1] — an impossible interval printed beside a precision claim.
    """
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def fold(join: dict) -> tuple[dict, dict]:
    """store.pattern_join() rows -> ({(repo, pr): is_defect}, {pattern: {keys}}).

    Three rules worth stating, because all three are silent corruptions:
    - A CENSORED row is a NON-OBSERVATION, not a defect. The PR left the
      risk set, so it belongs in neither the numerator nor the denominator:
      prereg §3's arithmetic is `N_at_risk = N_done - censored`, and it
      names and rejects the alternative outright — "counting censored as
      misses ... a censoring rate wearing a miss rate's name". This module
      did exactly that until 2026-08-18, when `/v1/patterns` reported
      `defects: 2` for drewjst/doug and both were gh-pages merges: 100% of
      the published base rate was non-observation. Censoring in ONE window
      does not unobserve another — `outcomes` carries `window_days`, so a
      PR can hold a censored 14-day row beside an observed 60-day one.
    - A non-clean OBSERVATION makes a PR a defect. "clean" means "nothing
      observed", so it must never overwrite an observed revert. Tested as
      `!= CLEAN` rather than `== REVERT` deliberately: a kind added to the
      enum later then surfaces as a defect, which is loud, instead of
      dissolving into "clean", which flatters.
    - A PR is counted once per pattern. Two synonymous slugs that merge to
      one pattern are one piece of evidence, or the merge map would
      manufacture the recurrence it exists to measure.
    """
    is_defect: dict[tuple[str, int], bool] = {}
    for r in join["prs"]:
        key = (r["repo"], r["pr_number"])
        if r["kind"] == OutcomeKind.CENSORED:
            continue
        is_defect[key] = is_defect.get(key, False) or r["kind"] != OutcomeKind.CLEAN
    carriers: dict[str, set] = {}
    for r in join["hits"]:
        pattern = from_rule(r["rule"])
        if pattern is None:
            continue  # deterministic-tier reason — a different vocabulary
        key = (r["repo"], r["pr_number"])
        if key in is_defect:
            carriers.setdefault(pattern, set()).add(key)
    return is_defect, carriers


def corpus_table(
    is_defect: dict, carriers: dict, min_prs: int = 5
) -> tuple[list[dict], float]:
    """Per-pattern precision and lift, ranked by lift. Returns (rows, base).

    `clears_base` is the column that matters: ranking by lift alone floats
    2-of-3 coincidences to the top. It is uncorrected for multiplicity —
    with ~17 patterns tested, expect roughly one star by chance.
    """
    n = len(is_defect)
    base = sum(is_defect.values()) / n if n else 0.0
    rows = []
    for pattern, prs in carriers.items():
        if len(prs) < min_prs:
            continue
        hits = sum(1 for k in prs if is_defect[k])
        prec = hits / len(prs)
        lo, hi = wilson(hits, len(prs))
        rows.append({
            "pattern": pattern,
            "prs": len(prs),
            "defects": hits,
            "precision": prec,
            "ci_low": lo,
            "ci_high": hi,
            "lift": prec / base if base else 0.0,
            "clears_base": lo > base,
        })
    rows.sort(key=lambda r: -r["lift"])
    return rows, base
