"""The outcome ledger — durable verdicts, findings, and (later) outcomes.

This is step 1 of the distillation loop: every scored PR gets a durable
record, findings are stored against PR identity rather than consumed and
discarded, and outcomes join in when they land. The loop's whole claim —
"only findings that predicted real outcomes get distilled" — depends on
this table existing from day one.

Storage is opt-in via DATABASE_URL (Postgres in production, sqlite in
tests). When unset, every call is a cheap no-op so local dogfooding and
the open-source path need no database. Schema is created on first use.

create_all() adds missing *tables* and never adds a column to a table that
already exists, so several facts here live in tables of their own (see
`reads`) rather than as columns on `verdicts`. Columns that must go on an
existing table now go through migrations.apply(), which runs on the same
engine right after create_all(); a column added to the Table definition
alone would appear in every test and in no production row.
"""

import os
import threading
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from . import migrations
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
    # App identity. Added to an existing table, so these four are also
    # migration 001 — the two definitions must stay identical or a fresh
    # database and production diverge. Unindexed on purpose: create_all()
    # would build an index here that no migration builds there.
    Column("github_repo_id", BigInteger),
    Column("installation_id", BigInteger),
    Column("head_sha", String(64)),
    # app | ci | cli | review:<login> (third-party review ingest, Task 6).
    # 64 wide for the review: case — GitHub logins run to 39 chars.
    Column("source", String(64)),
    # Migration 002, alongside outcomes' new columns below.
    Column("prompt_hash", String(64)),
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
    # Outcome-loop identity, migration 002. NULL on every row scored before
    # this migration — `repo` stays their display-only join key, and nothing
    # rewrites it; only new rows carry ids.
    Column("github_repo_id", BigInteger),
    Column("installation_id", BigInteger),
    Column("window_days", Integer),
    # The adjudicator's supporting detail, JSON-encoded. TEXT rather than
    # the JSON type used elsewhere in this file, for sqlite/postgres parity
    # per house style on this column specifically.
    Column("detail", Text),
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

# Who installed Doug where. The webhook is the only writer; a row is never
# deleted, because "this installation was removed on the 3rd" is a fact the
# ledger's verdicts still refer to.
installations = Table(
    "installations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False, unique=True),
    Column("account_login", String(200)),
    Column("account_type", String(20)),  # User | Organization
    Column("state", String(20), nullable=False),  # active | suspended | deleted
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # M2's token-dispense endpoint mints an installation token and writes its
    # hash here — never the token itself. NULL until then; this table is new
    # on this branch, so the column ships with it rather than a migration.
    Column("token_hash", Text),
)

installation_repos = Table(
    "installation_repos",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False, index=True),
    Column("github_repo_id", BigInteger, nullable=False),
    Column("full_name", String(200), nullable=False),  # display only
    Column("state", String(20), nullable=False),  # active | removed
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("installation_id", "github_repo_id", name="uq_installation_repo"),
)

# The durable gap between a delivery and a review. The unique constraint is
# the deduplication mechanism, not an integrity afterthought: two deliveries
# of one push race often enough that a check-then-insert would pay for the
# same model read twice.
review_jobs = Table(
    "review_jobs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False),
    Column("github_repo_id", BigInteger, nullable=False),
    Column("repo_full_name", String(200), nullable=False),  # display only
    Column("pr_number", Integer, nullable=False),
    Column("head_sha", String(64), nullable=False),
    # pending | running | done | failed | superseded
    Column("status", String(12), nullable=False, index=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("enqueued_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("error", Text),
    Column("verdict_id", Integer, ForeignKey("verdicts.id")),
    UniqueConstraint(
        "installation_id", "github_repo_id", "pr_number", "head_sha", name="uq_review_job"
    ),
)

# Merged PRs waiting out their outcome-observation window before the M3
# adjudicator scores them. Written when a pull_request 'closed' event is a
# merge (Task 6's amendment); drained by the adjudicator once due_at
# passes. The unique constraint is the dedup against GitHub webhook
# redelivery, same role as review_jobs' — a replayed 'closed' event for a PR
# already queued must not create a second job with its own due date.
outcome_jobs = Table(
    "outcome_jobs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False),
    Column("github_repo_id", BigInteger, nullable=False),
    Column("pr_number", Integer, nullable=False),
    Column("merge_commit_sha", String(64), nullable=False),
    Column("merged_at", DateTime(timezone=True), nullable=False),
    # Branch the PR merged into. The adjudicator censors anything merged to
    # a non-default branch rather than trusting this table to only hold them.
    Column("base_ref", String(200), nullable=False),
    Column("window_days", Integer, nullable=False, server_default="14"),
    # merged_at + window_days, computed and stored at enqueue time rather
    # than derived at query time — Postgres is the only clock this ledger
    # trusts, and a derived value would drift if window_days ever changed
    # after the row was written.
    Column("due_at", DateTime(timezone=True), nullable=False),
    # pending | running | done | failed
    Column("status", String(12), nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "installation_id",
        "github_repo_id",
        "pr_number",
        "merge_commit_sha",
        "window_days",
        name="uq_outcome_job",
    ),
)

# Deep-read spend cap, metered per scope per UTC calendar month. `scope` is
# caller-defined (e.g. "installation:150424894") rather than a foreign key —
# the reader's two model-call sites take no installation parameter yet
# (score_one/read_intent's signatures are locked by the in-flight step-2
# worker task), so this is the tested primitive a future caller wires in
# once that context reaches reader.py, not an already-enforced cap.
deep_read_counters = Table(
    "deep_read_counters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("scope", String(80), nullable=False),
    Column("period", String(7), nullable=False),  # "YYYY-MM", UTC
    Column("count", Integer, nullable=False, server_default="0"),
    UniqueConstraint("scope", "period", name="uq_deep_read_period"),
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
            # create_all() cannot add a column to a table that already
            # exists. Production's `verdicts` predates the App columns, so
            # the two paths only agree if this runs on every engine, not
            # just the new ones.
            migrations.apply(engine)
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
    github_repo_id: int | None = None,
    installation_id: int | None = None,
    head_sha: str | None = None,
    source: str | None = None,
    prompt_hash: str | None = None,
) -> int | None:
    """Persist one scoring event. Returns the verdict id, or None when
    storage is disabled — callers never branch on persistence.

    `coverage`, when given, commits in the same transaction as the verdict
    and its findings — the reader-tier hot path used to pay a second
    sequential commit for it via a standalone save_read() call; nothing
    about writing it needed to be a separate round trip.

    The identity kwargs are None for every pre-App row and for the CLI, which
    has no installation. `github_repo_id` is the only stable repo identity —
    `repo` is a display string that changes when a repo is renamed.
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
                "github_repo_id": github_repo_id,
                "installation_id": installation_id,
                "head_sha": head_sha,
                "source": source,
                "prompt_hash": prompt_hash,
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


def upsert_installation(
    installation_id: int, account_login: str, account_type: str, state: str
) -> None:
    """Record an installation's current state. Never deletes: a suspended or
    deleted installation is a state the verdicts it produced still point at."""
    engine = _get_engine()
    if engine is None:
        return
    values = {
        "account_login": account_login,
        "account_type": account_type,
        "state": state,
        "updated_at": datetime.now(UTC),
    }
    with engine.connect() as conn:
        row = conn.execute(
            select(installations.c.id).where(installations.c.installation_id == installation_id)
        ).scalar_one_or_none()
    if row is None:
        try:
            with engine.begin() as conn:
                conn.execute(
                    installations.insert(), {"installation_id": installation_id, **values}
                )
            return
        except IntegrityError:
            # Two concurrent deliveries for a new installation (redelivery,
            # or two webhook workers) can both see `row is None` and race to
            # insert. The loser's own transaction is the only one that
            # aborts (a separate engine.begin() from the read above), so it
            # falls through to the update below instead of raising — same
            # "already done, not failed" case migrations.apply() handles for
            # the schema-version race.
            pass
    with engine.begin() as conn:
        conn.execute(
            update(installations)
            .where(installations.c.installation_id == installation_id)
            .values(**values)
        )


def set_installation_repos(
    installation_id: int,
    repos: list[tuple[int, str]],
    *,
    replace: bool,
    state: str = "active",
) -> None:
    """Record which repos an installation covers.

    `replace=True` treats `repos` as authoritative — anything else on this
    installation flips to 'removed'. That is the installation-created event,
    which carries the full list. `replace=False` merges a delta, and the
    caller says which delta it is: the `installation_repositories` webhook
    sends added and removed in one payload, so removals arrive as their own
    call with state='removed'.

    Rows are never DELETEd. A removed repo's verdicts stay in the ledger and
    the join that explains them has to keep resolving.
    """
    engine = _get_engine()
    if engine is None:
        return
    now = datetime.now(UTC)
    ids = [r[0] for r in repos]
    with engine.begin() as conn:
        if replace:
            stale = (
                update(installation_repos)
                .where(installation_repos.c.installation_id == installation_id)
                .values(state="removed", updated_at=now)
            )
            if ids:
                stale = stale.where(installation_repos.c.github_repo_id.notin_(ids))
            conn.execute(stale)
        known = {
            r.github_repo_id: r.id
            for r in conn.execute(
                select(installation_repos.c.id, installation_repos.c.github_repo_id).where(
                    installation_repos.c.installation_id == installation_id
                )
            )
        }
        for repo_id, full_name in repos:
            values = {"full_name": full_name, "state": state, "updated_at": now}
            if repo_id in known:
                conn.execute(
                    update(installation_repos)
                    .where(installation_repos.c.id == known[repo_id])
                    .values(**values)
                )
            else:
                result = conn.execute(
                    installation_repos.insert(),
                    {"installation_id": installation_id, "github_repo_id": repo_id, **values},
                )
                # A duplicate github_repo_id later in this same `repos` list must
                # update, not insert again — `known` only reflects rows that
                # existed before this call started.
                known[repo_id] = result.inserted_primary_key[0]


def record_deep_read(scope: str, cap: int, *, now: datetime | None = None) -> bool:
    """Attempt to spend one deep read against `scope`'s monthly cap.

    Returns True and increments the counter if under cap; returns False
    and leaves the counter unchanged if `scope` already has `cap` reads
    recorded for the current UTC calendar month (or the month `now`
    falls in, for tests). The caller must check this BEFORE making the
    model call it would meter — a cap enforced after paying for the call
    is not spend control, just a receipt.

    The increment is a single `UPDATE ... WHERE count < cap` statement,
    not a read-then-write pair: two concurrent callers racing the last
    unit of cap must not both win. This ledger has hit that exact
    check-then-act bug before (the review dedup lookup, fixed in the
    reliability sweep) — the fix here is structural, not a lock.
    """
    engine = _get_engine()
    if engine is None:
        return True
    period = (now or datetime.now(UTC)).strftime("%Y-%m")
    try:
        with engine.begin() as conn:
            conn.execute(
                deep_read_counters.insert(), {"scope": scope, "period": period, "count": 0}
            )
    except IntegrityError:
        # Another caller already created this scope/period row — expected
        # under concurrency, same shape as upsert_installation's race.
        pass
    with engine.begin() as conn:
        result = conn.execute(
            update(deep_read_counters)
            .where(
                deep_read_counters.c.scope == scope,
                deep_read_counters.c.period == period,
                deep_read_counters.c.count < cap,
            )
            .values(count=deep_read_counters.c.count + 1)
        )
        return result.rowcount > 0


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
        read_row = (
            conn.execute(select(reads).where(reads.c.verdict_id == v["id"]).limit(1))
            .mappings()
            .first()
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
        # The recorded risk-read coverage. Both reads truncate the same diff
        # at the same DIFF_BUDGET, so this is also what the intent read saw —
        # a replay rebuilds intent_notice from it instead of dropping the
        # partial-read hedge the first response carried.
        "coverage": (
            {
                "diff_chars": read_row["diff_chars"],
                "sent_chars": read_row["sent_chars"],
                "files_sent": read_row["files_sent"],
                "files_unseen": read_row["files_unseen"],
                "file_cut": read_row["file_cut"],
            }
            if read_row
            else None
        ),
    }


def find_verdict_by_identity(
    installation_id: int, github_repo_id: int, pr_number: int, head_sha: str
) -> dict | None:
    """The verdict already recorded for this exact App-identified commit, or
    None. worker.process_job's idempotency read.

    A worker can crash (or ingest.complete can itself raise) anywhere after
    save_review lands and before the job is marked 'done' — mid check-run
    post, or before it ever starts. reclaim_stalled()/ingest.fail() then
    re-pend the row for another full attempt. Without this read, that retry
    re-scores from scratch: a second paid score_one/read_intent, and a
    second verdicts row for the same commit, because verdicts carries no
    unique constraint of its own to stop it.

    Keyed on (installation_id, github_repo_id, pr_number, head_sha) rather
    than find_review's repo-string + pr_meta JSON match: the Global
    Constraint makes those four columns the uniqueness key everywhere, and
    the worker populates all of them on every App-path row. find_review
    predates the App path and stays keyed the old way; its only caller
    (/v1/review) retires in Task 9.
    """
    engine = _get_engine()
    if engine is None:
        return None
    q = (
        select(verdicts)
        .where(
            verdicts.c.installation_id == installation_id,
            verdicts.c.github_repo_id == github_repo_id,
            verdicts.c.pr_number == pr_number,
            verdicts.c.head_sha == head_sha,
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
                select(findings).where(findings.c.verdict_id == v["id"]).order_by(findings.c.id)
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
        read_row = (
            conn.execute(select(reads).where(reads.c.verdict_id == v["id"]).limit(1))
            .mappings()
            .first()
        )
    return {
        "id": v["id"],
        "tier": v["tier"],
        "score": v["score"],
        "band": v["band"],
        "threshold": v["threshold"],
        "reasons": [
            {
                "rule": r["rule"],
                "label": r["label"],
                "weight": r["weight"],
                "severity": r["severity"],
            }
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
        "coverage": (
            {
                "diff_chars": read_row["diff_chars"],
                "sent_chars": read_row["sent_chars"],
                "files_sent": read_row["files_sent"],
                "files_unseen": read_row["files_unseen"],
                "file_cut": read_row["file_cut"],
            }
            if read_row
            else None
        ),
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
