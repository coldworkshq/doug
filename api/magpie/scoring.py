"""Deterministic scoring: feature vector -> verdict.

Every rule is legible and carries its own weight, because the product's
posture is "here is exactly why this one needs you". Diff size is never
weighted alone — the literature says it predicts poorly once the
interactions below are controlled for — it only appears inside
interaction rules.
"""

import os

from .features import extract_features
from .models import Band, Features, PRMetadata, Reason, Verdict

BASE_SCORE = 0.04
DEFAULT_THRESHOLD = 0.62

_FAST_APPROVAL_S = 5 * 60
_LARGE_DIFF = 400
_MEDIUM_DIFF = 300
_STALE_MODULE_DAYS = 30


def default_threshold() -> float:
    return float(os.environ.get("MAGPIE_THRESHOLD", DEFAULT_THRESHOLD))


def _rules(f: Features) -> list[Reason]:
    reasons: list[Reason] = []

    if f.migration and f.sensitive_path:
        reasons.append(
            Reason(
                rule="boundary-plus-migration",
                label="Sensitive area and a migration in the same diff",
                weight=0.35,
            )
        )

    if (f.lockfile or f.manifest) and f.test_files == 0:
        reasons.append(
            Reason(
                rule="dep-change-no-test-delta",
                label="Dependency change with zero test delta — green CI is anti-signal here",
                weight=0.25,
            )
        )

    if (
        f.approvals == 1
        and f.approval_latency_s is not None
        and f.approval_latency_s < _FAST_APPROVAL_S
        and f.size > _LARGE_DIFF
    ):
        reasons.append(
            Reason(
                rule="rubber-stamp",
                label="Approved in under five minutes by one reviewer on a large diff",
                weight=0.25,
            )
        )

    if f.test_files == 0 and f.size > _MEDIUM_DIFF:
        reasons.append(
            Reason(
                rule="no-test-delta",
                label="Sizeable change, no test files touched",
                weight=0.20,
            )
        )

    if (
        f.agent_authored
        and f.days_since_last_human_commit is not None
        and f.days_since_last_human_commit > _STALE_MODULE_DAYS
    ):
        reasons.append(
            Reason(
                rule="agent-in-stale-module",
                label="Agent-authored change in a module without recent human commits",
                weight=0.15,
            )
        )

    if f.sensitive_path:
        reasons.append(
            Reason(
                rule="sensitive-path",
                label="Touches an auth, billing, or security path",
                weight=0.15,
            )
        )

    return reasons


def score(pr: PRMetadata, threshold: float | None = None) -> Verdict:
    thr = default_threshold() if threshold is None else threshold
    reasons = _rules(extract_features(pr))
    total = min(0.99, BASE_SCORE + sum(r.weight for r in reasons))
    band = Band.FLAGGED if total >= thr else Band.CLEARED
    return Verdict(score=round(total, 2), band=band, threshold=thr, reasons=reasons)
