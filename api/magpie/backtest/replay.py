"""Replay: harvested history through the live scoring path.

This must call the same extract/score functions the webhook uses —
that continuity is the whole point of the backtest.
"""

from datetime import datetime

from ..models import AuthorType, PRMetadata
from ..scoring import score
from .harvest import HarvestedPR


def _latency_s(pr: HarvestedPR) -> int | None:
    if pr.first_approval_at is None:
        return None
    opened = datetime.fromisoformat(pr.created_at)
    approved = datetime.fromisoformat(pr.first_approval_at)
    return max(0, int((approved - opened).total_seconds()))


def to_metadata(pr: HarvestedPR) -> PRMetadata:
    return PRMetadata(
        number=pr.number,
        title=pr.title,
        author=pr.author,
        # Historical data can't distinguish agent-assisted humans; bots are
        # the only authorship signal we can honestly claim.
        author_type=AuthorType.AGENT if pr.author_is_bot else AuthorType.HUMAN,
        additions=pr.additions,
        deletions=pr.deletions,
        files=pr.files,
        approvals=pr.approvals,
        approval_latency_s=_latency_s(pr),
        days_since_last_human_commit=None,
    )


def replay(prs: list[HarvestedPR]) -> list[tuple[HarvestedPR, float, list[str]]]:
    """Score each harvested PR. Returns (pr, score, fired rule ids)."""
    out = []
    for pr in prs:
        verdict = score(to_metadata(pr))
        out.append((pr, verdict.score, [r.rule for r in verdict.reasons]))
    return out
