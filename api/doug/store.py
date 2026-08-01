"""The outcome ledger — durable verdicts, findings, and (later) outcomes.

This is step 1 of the distillation loop: every scored PR gets a durable
record, findings are stored against PR identity rather than consumed and
discarded, and outcomes join in when they land. The loop's whole claim —
"only findings that predicted real outcomes get distilled" — depends on
this table existing from day one.

Storage is opt-in via DATABASE_URL (Postgres in production, sqlite in
tests). When unset, every call is a cheap no-op so local dogfooding and
the open-source path need no database. Schema is created on first use.

There is still no migration framework, which is a real constraint and not
just a deferral: create_all() adds missing *tables* and never adds a column
to a table that already exists. New facts therefore arrive as new tables
(see `reads`) until that changes. A column added to `verdicts` today would
appear in every test and in no production row.
"""

import os
import threading
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
from .reader import Coverage, ReaderVerdict

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
    # PR metadata as scored — the queue dashboard reads verdicts alone.
    Column("pr_meta", JSON),
)

findings = Table(
    "findings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("verdict_id", Integer, ForeignKey("verdicts.id"), nullable=False, index=True),
    Column("rule", String(120), nullable=False),
    Column("label", Text, nullable=False),
    Column("weight", Float, nullable=False, default=0.0),
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

# How much of each PR the reader was actually shown. Its own table, not
# columns on verdicts, for a boring operational reason: create_all() creates
# missing *tables* and never adds columns to an existing one, so new columns
# here would exist in tests and silently not in production Postgres — the
# same shape of green-checkmark no-op that has already cost this project a
# day. A new table is the migration-free option.
#
# Only reader-tier verdicts get a row; the deterministic tier never opens
# the diff, so it has no coverage to report.
reads = Table(
    "reads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("verdict_id", Integer, ForeignKey("verdicts.id"), nullable=False, index=True),
    Column("diff_chars", Integer, nullable=False),
    Column("sent_chars", Integer, nullable=False),
    Column("files_sent", Integer, nullable=False),
    Column("files_unseen", JSON, nullable=False),
    Column("file_cut", Text),
)

# Intent-tier output, kept in its own table on purpose (ADR-0007). A
# deviation is a judgment about a change against a recorded decision; it
# has no outcome-precision evaluation, and folding it into verdicts.score
# would silently change what every score in this ledger means.
deviations = Table(
    "deviations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("verdict_id", Integer, ForeignKey("verdicts.id"), nullable=False, index=True),
    # missing-from-pr | beyond-ticket | contradicts-ticket, or "none" for a
    # read that completed and found nothing.
    Column("kind", String(24), nullable=False),
    Column("description", Text, nullable=False),
    Column("severity", String(10), nullable=False),
    # Which records the read was given, so a finding can be checked against
    # the record rather than taken on faith.
    Column("intent_refs", JSON),
    Column("intent_alignment", Integer),
)

_engine = None
# The raw env string the engine was built from. Compared instead of
# str(_engine.url) because SQLAlchemy masks passwords when rendering a URL
# ("user:***@host"), so that comparison never matches a credentialed
# DATABASE_URL — and rebuilt the engine, pool and all, on every call.
_engine_url = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine, _engine_url
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    with _engine_lock:
        # Locked check-then-act: two first-requests racing here used to both
        # build an engine and orphan one of the connection pools.
        if _engine is None or _engine_url != url:
            engine = create_engine(url, pool_pre_ping=True)
            metadata.create_all(engine)
            if _engine is not None:
                _engine.dispose()
            _engine = engine
            _engine_url = url
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
    pr_meta: dict | None = None,
    coverage: Coverage | None = None,
) -> int | None:
    """Persist one scoring event. Returns the verdict id, or None when
    storage is disabled — callers never branch on persistence.

    `coverage`, when given, commits in the same transaction as the verdict
    and its findings — the reader-tier hot path used to pay a second
    sequential commit for it via a standalone save_read() call; nothing
    about writing it needed to be a separate round trip.
    """
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
                "pr_meta": pr_meta,
            },
        ).scalar_one()
        rows = [
            {
                "verdict_id": row,
                "rule": r.rule,
                "label": r.label,
                "weight": r.weight,
                "file": None,
                "severity": None,
            }
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
        if coverage is not None:
            conn.execute(
                reads.insert(),
                {
                    "verdict_id": row,
                    "diff_chars": coverage.diff_chars,
                    "sent_chars": coverage.sent_chars,
                    "files_sent": coverage.files_sent,
                    "files_unseen": coverage.files_unseen,
                    "file_cut": coverage.file_cut,
                },
            )
    return int(row)


def save_read(verdict_id: int | None, cov: Coverage) -> int:
    """Record how much of the diff this verdict was based on.

    Written for complete reads too, not only truncated ones. Precision
    measured over this ledger has to be able to condition on coverage, and
    "no row" would be ambiguous between a full read and an unrecorded one —
    the same trap save_deviations avoids with its kind="none" row.
    """
    engine = _get_engine()
    if engine is None or verdict_id is None:
        return 0
    with engine.begin() as conn:
        conn.execute(
            reads.insert(),
            [
                {
                    "verdict_id": verdict_id,
                    "diff_chars": cov.diff_chars,
                    "sent_chars": cov.sent_chars,
                    "files_sent": cov.files_sent,
                    "files_unseen": cov.files_unseen,
                    "file_cut": cov.file_cut,
                }
            ],
        )
    return 1


def save_deviations(
    verdict_id: int | None,
    findings: list,
    intent_refs: list[str],
    intent_alignment: int,
) -> int:
    """Persist the intent read's output against an existing verdict.

    Deliberately writes nothing to `verdicts` — not the score, not the
    band, not the raw column. The separation is the point (ADR-0007), and
    it is enforced here rather than trusted to callers.

    A read that found no deviations still records one row carrying the
    alignment score, so "read happened, nothing found" stays
    distinguishable from "no read happened" when precision is eventually
    measured over this table.
    """
    engine = _get_engine()
    if engine is None or verdict_id is None:
        return 0
    rows = [
        {
            "verdict_id": verdict_id,
            "kind": f.type,
            "description": f.description,
            "severity": f.severity,
            "intent_refs": intent_refs,
            "intent_alignment": intent_alignment,
        }
        for f in findings
    ] or [
        {
            "verdict_id": verdict_id,
            "kind": "none",
            "description": "",
            "severity": "low",
            "intent_refs": intent_refs,
            "intent_alignment": intent_alignment,
        }
    ]
    with engine.begin() as conn:
        conn.execute(deviations.insert(), rows)
    return len(rows)


def find_review(repo: str, pr_number: int, head_sha: str) -> dict | None:
    """The newest verdict already recorded for this exact commit, or None.

    The idempotency read: /v1/review consults it before paying for an LLM
    read, so a webhook redelivery or a retried CI job replays the recorded
    verdict instead of double-spending and inserting a duplicate ledger
    row. Matches on the head_sha key inside pr_meta — a JSON key rather
    than a column for the same reason `reads` is its own table: create_all
    never adds columns to a live table. Rows scored before head_sha
    existed simply never match, and get rescored once.
    """
    engine = _get_engine()
    if engine is None:
        return None
    from sqlalchemy import select

    q = (
        select(verdicts)
        .where(
            verdicts.c.repo == repo,
            verdicts.c.pr_number == pr_number,
            verdicts.c.pr_meta["head_sha"].as_string() == head_sha,
        )
        .order_by(verdicts.c.id.desc())
        .limit(1)
    )
    with engine.connect() as conn:
        v = conn.execute(q).mappings().first()
        if v is None:
            return None
        reason_rows = (
            conn.execute(
                select(findings)
                .where(findings.c.verdict_id == v["id"])
                .order_by(findings.c.id)
            )
            .mappings()
            .all()
        )
        dev_rows = (
            conn.execute(
                select(deviations)
                .where(deviations.c.verdict_id == v["id"])
                .order_by(deviations.c.id)
            )
            .mappings()
            .all()
        )
    return {
        "tier": v["tier"],
        "score": v["score"],
        "band": v["band"],
        "threshold": v["threshold"],
        "reasons": [
            {"rule": r["rule"], "label": r["label"], "weight": r["weight"]}
            for r in reason_rows
        ],
        # kind="none" is the "read happened, found nothing" storage marker
        # (see save_deviations) — it was never a response finding.
        "deviations": [
            {"type": d["kind"], "description": d["description"], "severity": d["severity"]}
            for d in dev_rows
            if d["kind"] != "none"
        ],
        "intent_alignment": dev_rows[0]["intent_alignment"] if dev_rows else None,
        "intent_refs": (dev_rows[0]["intent_refs"] or []) if dev_rows else [],
    }


def pattern_join(repo: str | None = None) -> dict[str, list[dict]]:
    """The findings x outcomes join — step 2 of the distillation loop.

    Returns two aligned row sets, read in one transaction so the base rate
    and the per-pattern hits describe the same snapshot:

      prs  — every scored PR whose outcome is known, with that outcome.
              This is the denominator; PRs that produced zero findings
              belong in it, which is why it is not derived from `hits`.
      hits — every (PR, finding rule) pair on those PRs, deduplicated.
              One PR emitting the same rule twice is one hit, because the
              unit of prediction is the PR, not the finding.

    Only the newest verdict per PR counts: a rescored PR would otherwise
    contribute its superseded findings to precision as well.

    Aggregation is left to the caller — slug normalisation happens after
    this join (synonymous rules collapse to one pattern, and two merged
    rules on one PR must not count twice), and the statistics that matter
    depend on the sampling design of the rows in the ledger.
    """
    engine = _get_engine()
    if engine is None:
        return {"prs": [], "hits": []}
    from sqlalchemy import func, select

    latest = (
        select(func.max(verdicts.c.id).label("id"))
        .group_by(verdicts.c.repo, verdicts.c.pr_number)
        .scalar_subquery()
    )
    scored = select(verdicts.c.id, verdicts.c.repo, verdicts.c.pr_number).where(
        verdicts.c.id.in_(latest)
    )
    if repo:
        scored = scored.where(verdicts.c.repo == repo)
    scored = scored.subquery()

    on_outcome = (outcomes.c.repo == scored.c.repo) & (
        outcomes.c.pr_number == scored.c.pr_number
    )
    # A PR with several outcome rows yields several rows here; the caller
    # decides how to reduce them (any non-clean outcome makes it a defect).
    pr_q = (
        select(scored.c.repo, scored.c.pr_number, outcomes.c.kind)
        .select_from(scored.join(outcomes, on_outcome))
        .distinct()
    )
    hit_q = (
        select(scored.c.repo, scored.c.pr_number, findings.c.rule)
        .select_from(
            scored.join(findings, findings.c.verdict_id == scored.c.id).join(
                outcomes, on_outcome
            )
        )
        .distinct()
    )
    with engine.connect() as conn:
        return {
            "prs": [dict(r) for r in conn.execute(pr_q).mappings()],
            "hits": [dict(r) for r in conn.execute(hit_q).mappings()],
        }


def latest_reviews(limit: int = 200, repo: str | None = None) -> list[dict]:
    """Most recent verdict per (repo, pr) with findings — the live queue.

    `repo` scopes the queue; without it the ledger's every repo mixes
    together, which is an all-repos admin view, not a dashboard.
    """
    engine = _get_engine()
    if engine is None:
        return []
    from sqlalchemy import desc, func, select

    latest = (
        select(func.max(verdicts.c.id).label("id"))
        .group_by(verdicts.c.repo, verdicts.c.pr_number)
        .scalar_subquery()
    )
    query = select(verdicts).where(verdicts.c.id.in_(latest))
    if repo:
        query = query.where(verdicts.c.repo == repo)
    out = []
    with engine.connect() as conn:
        for v in conn.execute(query.order_by(desc(verdicts.c.score))).mappings():
            fs = conn.execute(
                select(findings).where(findings.c.verdict_id == v["id"])
            ).mappings().all()
            out.append({**v, "findings": [dict(f) for f in fs]})
            if len(out) >= limit:
                break
    return out
