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
def default_threshold() -> float:
    return float(os.environ.get("DOUG_THRESHOLD", DEFAULT_THRESHOLD))


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
    elif f.migration:
        reasons.append(
            Reason(
                rule="migration",
                label="Touches a schema migration",
                weight=0.20,
            )
        )

    # Runtime dep bumps only — tooling bumps (eslint/jest/…) dominated the
    # false-alarm head of the sentry queue and almost never reverted.
    if (
        (f.lockfile or f.manifest)
        and f.test_files == 0
        and f.runtime_dep
        and not f.dev_tool_dep
    ):
        reasons.append(
            Reason(
                rule="dep-change-no-test-delta",
                label="Runtime dependency change with zero test delta",
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

    # days_since_last_human_commit is usually unknown in the backtest
    # (and often live); bot authorship alone is the reachable signal.
    # Skip pure dep-only bumps — already covered by dep-change. Mixed
    # bot PRs (code + lockfile) still get this signal.
    if f.agent_authored and not f.dep_only:
        reasons.append(
            Reason(
                rule="agent-authored",
                label="Authored by a bot / agent account",
                weight=0.12,
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

    if f.hotspot_path:
        reasons.append(
            Reason(
                rule="hotspot-path",
                label="Touches a historically high-revert area (preprod, grouping, infra…)",
                weight=0.20,
            )
        )

    if f.config_flag:
        reasons.append(
            Reason(
                rule="config-flag",
                label="Touches feature flags or runtime options defaults",
                weight=0.15,
            )
        )

    return reasons


def score(
    pr: PRMetadata,
    threshold: float | None = None,
    extra_hotspots: set[str] | None = None,
) -> Verdict:
    thr = default_threshold() if threshold is None else threshold
    reasons = _rules(extract_features(pr, extra_hotspots=extra_hotspots))
    total = min(0.99, BASE_SCORE + sum(r.weight for r in reasons))
    band = Band.FLAGGED if total >= thr else Band.CLEARED
    return Verdict(score=round(total, 2), band=band, threshold=thr, reasons=reasons)
