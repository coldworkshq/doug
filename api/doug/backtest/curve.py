"""Capture-curve math.

The curve answers the only question that matters: if Doug flags the
top X% of PRs by score, what share of the defect-inducing ones are in
that set? Scores are coarse, so many PRs tie; flagging is only defined
at distinct-score boundaries and we interpolate linearly between them —
equivalent to random ordering within a tied block, which is the honest
treatment rather than an accidental favorable sort.
"""

from pydantic import BaseModel


class CurvePoint(BaseModel):
    flag_rate: float
    capture_rate: float


class Curve(BaseModel):
    points: list[CurvePoint]
    auc: float

    def capture_at(self, flag_rate: float) -> float:
        pts = self.points
        for (a, b) in zip(pts, pts[1:], strict=False):
            if a.flag_rate <= flag_rate <= b.flag_rate:
                if b.flag_rate == a.flag_rate:
                    return b.capture_rate
                t = (flag_rate - a.flag_rate) / (b.flag_rate - a.flag_rate)
                return a.capture_rate + t * (b.capture_rate - a.capture_rate)
        return 1.0


def capture_curve(scored: list[tuple[float, bool]]) -> Curve:
    """scored: (score, is_defect) per PR. Higher score = flagged earlier."""
    n = len(scored)
    total_defects = sum(1 for _, d in scored if d)
    if n == 0 or total_defects == 0:
        return Curve(points=[CurvePoint(flag_rate=0, capture_rate=0)], auc=0.0)

    by_score = sorted(scored, key=lambda x: x[0], reverse=True)
    points = [CurvePoint(flag_rate=0.0, capture_rate=0.0)]
    flagged = caught = 0
    i = 0
    while i < n:
        j = i
        while j < n and by_score[j][0] == by_score[i][0]:
            caught += by_score[j][1]
            j += 1
        flagged = j
        points.append(
            CurvePoint(flag_rate=flagged / n, capture_rate=caught / total_defects)
        )
        i = j

    auc = 0.0
    for (a, b) in zip(points, points[1:], strict=False):
        auc += (b.flag_rate - a.flag_rate) * (a.capture_rate + b.capture_rate) / 2
    return Curve(points=points, auc=round(auc, 4))


class ClearedBand(BaseModel):
    flag_rate: float
    cleared_prs: int
    cleared_defects: float
    miss_rate: float
    density: float
    density_lift: float


def cleared_band(
    curve: Curve, n: int, total_defects: int, flag_rate: float
) -> ClearedBand:
    """What is left behind when the top `flag_rate` is routed for review.

    Capture measures the flagged band; this measures the other one — and the
    other one is what the product actually sells. "Auto-merge what Doug
    cleared" is a claim about defect density among *cleared* PRs, not about
    recall among flagged ones.

    `density_lift` is the number to watch: cleared-band defect density over
    the population's base rate. Below 1 means clearing carries information;
    at 1 the cleared band is exactly as risky as merging blind, no matter how
    good the capture number looks.
    """
    cleared_prs = round(n * (1 - flag_rate))
    miss_rate = 1 - curve.capture_at(flag_rate)
    cleared_defects = total_defects * miss_rate
    density = cleared_defects / cleared_prs if cleared_prs else 0.0
    base = total_defects / n if n else 0.0
    # Unrounded on purpose: miss_rate is exactly 1 - capture_at, and rounding
    # a field that carries an identity breaks it for callers. Formatting is
    # the CLI's job.
    return ClearedBand(
        flag_rate=flag_rate,
        cleared_prs=cleared_prs,
        cleared_defects=cleared_defects,
        miss_rate=miss_rate,
        density=density,
        density_lift=density / base if base else 0.0,
    )


class RuleStat(BaseModel):
    rule: str
    fired: int
    defects_hit: int
    precision: float
    lift: float


def rule_stats(
    fired_rules: list[list[str]], defects: list[bool]
) -> list[RuleStat]:
    n = len(defects)
    base_rate = sum(defects) / n if n else 0.0
    stats: list[RuleStat] = []
    all_rules = sorted({r for rules in fired_rules for r in rules})
    for rule in all_rules:
        hits = [d for rules, d in zip(fired_rules, defects, strict=False) if rule in rules]
        fired = len(hits)
        defects_hit = sum(hits)
        precision = defects_hit / fired if fired else 0.0
        stats.append(
            RuleStat(
                rule=rule,
                fired=fired,
                defects_hit=defects_hit,
                precision=round(precision, 4),
                lift=round(precision / base_rate, 2) if base_rate else 0.0,
            )
        )
    return sorted(stats, key=lambda s: s.lift, reverse=True)
