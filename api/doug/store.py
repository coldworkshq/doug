"""The outcome ledger — durable verdicts, findings, and (later) outcomes.

This is step 1 of the distillation loop: every scored PR gets a durable
record, findings are stored against PR identity rather than consumed and
discarded, and outcomes join in when they land. The loop's whole claim —
"only findings that predicted real outcomes get distilled" — depends on
this table existing from day one.

Storage is opt-in via DATABASE_URL (Postgres in production, sqlite in
tests). When unset, every call is a cheap no-op so local dogfooding and
the open-source path need no database. Schema is created on first use —
three tables do not need a migration framework yet.
"""

import os
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)

from .models import Verdict
from .reader import ReaderVerdict

metadata = MetaData()

verdicts = Table(
    "verdicts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repo", String(200), nullable=False, index=True),
    Column("pr_number", Integer, nullable=False, index=True),
    Column("scored_at", DateTime(timezone=True), nullable=False),
    Column("tier", String(20), nullable=False),  # reader | deterministic
    Column("score", Float, nullable=False),
    Column("band", String(10), nullable=False),
    Column("threshold", Float, nullable=False),
    Column("model", String(60)),  # reader tier only
    Column("risk_score", Integer),
    Column("rationale", Text),
    # Full reader output, verbatim — reprocessable when the distillation
    # pipeline wants more than the typed columns carried at write time.
    Column("raw", JSON),
)

findings = Table(
    "findings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("verdict_id", Integer, ForeignKey("verdicts.id"), nullable=False, index=True),
    Column("rule", String(120), nullable=False),
    Column("label", Text, nullable=False),
    Column("file", Text),
    Column("severity", String(10)),
)

# Written by the outcome-sync job (revert/hotfix anchoring), joined against
# verdicts by (repo, pr_number). Created now so the join target exists.
outcomes = Table(
    "outcomes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repo", String(200), nullable=False, index=True),
    Column("pr_number", Integer, nullable=False, index=True),
    Column("kind", String(20), nullable=False),  # revert | hotfix | clean
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("source", String(40), nullable=False),  # git-labels | manual | ...
)

_engine = None


def _get_engine():
    global _engine
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    if _engine is None or str(_engine.url) != url:
        _engine = create_engine(url, pool_pre_ping=True)
        metadata.create_all(_engine)
    return _engine


def enabled() -> bool:
    return _get_engine() is not None


def save_review(
    repo: str,
    pr_number: int,
    tier: str,
    verdict: Verdict,
    reader_verdict: ReaderVerdict | None = None,
    model: str | None = None,
) -> int | None:
    """Persist one scoring event. Returns the verdict id, or None when
    storage is disabled — callers never branch on persistence."""
    engine = _get_engine()
    if engine is None:
        return None
    with engine.begin() as conn:
        row = conn.execute(
            verdicts.insert().returning(verdicts.c.id),
            {
                "repo": repo,
                "pr_number": pr_number,
                "scored_at": datetime.now(UTC),
                "tier": tier,
                "score": verdict.score,
                "band": verdict.band.value,
                "threshold": verdict.threshold,
                "model": model,
                "risk_score": reader_verdict.risk_score if reader_verdict else None,
                "rationale": reader_verdict.rationale if reader_verdict else None,
                "raw": reader_verdict.model_dump() if reader_verdict else None,
            },
        ).scalar_one()
        rows = [
            {"verdict_id": row, "rule": r.rule, "label": r.label, "file": None, "severity": None}
            for r in verdict.reasons
        ]
        if reader_verdict:
            by_desc = {f.description: f for f in reader_verdict.findings}
            for r in rows:
                f = by_desc.get(r["label"])
                if f:
                    r["file"] = f.file
                    r["severity"] = f.severity
        if rows:
            conn.execute(findings.insert(), rows)
    return int(row)
