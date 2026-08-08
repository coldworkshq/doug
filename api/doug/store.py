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
import sys
import threading
from datetime import UTC, datetime, timedelta

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
    exists,
    func,
    inspect,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from . import migrations
from .models import Band, Verdict
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
    # database and production diverge. Migration 005's partial unique index
    # over App-scored rows is not declared here (create_all would otherwise
    # diverge from production the same way).
    Column("github_repo_id", BigInteger),
    Column("installation_id", BigInteger),
    Column("head_sha", String(64)),
    # app | ci | cli | review:<login> (third-party review ingest, Task 6).
    # 64 wide for the review: case — GitHub logins run to 39 chars.
    Column("source", String(64)),
    # Migration 002, alongside outcomes' new columns below.
    Column("prompt_hash", String(64)),
    # Migration 008. Instrument identity alongside prompt_hash: what budget
    # and tiering this read ran under, so a receipt can distinguish "the
    # prompt changed" from "the same prompt saw a different slice of the
    # diff". Forward-only — NULL on every row scored before this migration.
    Column("diff_budget", Integer),
    Column("read_order", String(16)),
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
    # Migration 007. NULL on historical rows; new adjudicator rows always
    # carry the merge commit so one job identity cannot cast two votes.
    Column("merge_commit_sha", String(64)),
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
    # Migration 007. Coverage already computes both; persisting them is what
    # lets a receipt distinguish prompt truncation from files GitHub omitted.
    Column("changed_files", Integer),
    Column("files_dropped", JSON),
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

# Tenant API keys (spec 2026-08-04). Multiple keys per installation; each
# frozen to a repo selection at mint and intersected against the LIVE ledger
# at resolve — installations.state and installation_repos.state are the
# authority, these rows are the claim. Repo ids only: full_name is display
# everywhere (the MT4 lesson, baked into the schema).
installation_tokens = Table(
    "installation_tokens",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_id", BigInteger, nullable=False, index=True),
    # Plaintext on purpose: the lookup is a key ID, not a secret — O(1)
    # btree resolve, safe in logs and list output. The SECRET is what
    # token_hash covers, and it is never stored in any form but the HMAC.
    Column("token_lookup", String(8), nullable=False, unique=True),
    Column("token_hash", Text, nullable=False),
    Column("hash_version", Integer, nullable=False, server_default="1"),
    Column("last4", String(4), nullable=False),
    Column("label", String(100)),
    Column("repo_selection", String(10), nullable=False),  # all | selected
    Column("scopes", JSON, nullable=False),
    Column("minted_by", String(200), nullable=False),  # audit only, never authority
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),  # NULL = durable
    Column("revoked_at", DateTime(timezone=True)),  # soft revoke; rows never deleted
    Column("last_used_at", DateTime(timezone=True)),
)

installation_token_repos = Table(
    "installation_token_repos",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("token_id", Integer, nullable=False, index=True),
    Column("github_repo_id", BigInteger, nullable=False),
    UniqueConstraint("token_id", "github_repo_id", name="uq_installation_token_repo"),
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
    # Incremented on every claim(); terminals fence on this integer rather
    # than started_at equality (timezone/precision round-trips can make a
    # live holder's complete() a silent no-op and leave the job stuck).
    Column("claim_generation", Integer, nullable=False, server_default="0"),
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
    # Migration 007. The outcome drain is a separate Cloud Run Job, but its
    # crash/reclaim fence is the same proven contract as review_jobs.
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("error", Text),
    Column("claim_generation", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Migration 008, pre-registration §11 item 7. Does NOT change the locked
    # §2.1 rule, which stays timestamp-matched.
    Column("merged_head_sha", String(64)),
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
# caller-defined (e.g. "installation:150424894") rather than a foreign key
# because not every paid read has a tenant to key on: reader.read_diff and
# reader.read_with_decisions both take a required `scope` and charge it
# through record_deep_read before the Anthropic call, and the un-tenanted
# callers (the CI review path, the /v1/score/read probe, the CLI) charge a
# shared sentinel scope with a ceiling of its own. The App path charges the
# installation that owns the PR. Those two reader functions are the only
# enforcement point, which is what stops a new entry point from spending
# without naming a payer.
#
# It is a real ceiling only where there is a ledger to count in:
# record_deep_read returns True when DATABASE_URL is unset, exactly like
# every other helper in this module, so local dogfooding and the
# open-source path run uncapped by design. The cap is a property of
# deployments that have this table, not of the code.
deep_read_counters = Table(
    "deep_read_counters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("scope", String(80), nullable=False),
    Column("period", String(7), nullable=False),  # "YYYY-MM", UTC
    Column("count", Integer, nullable=False, server_default="0"),
    UniqueConstraint("scope", "period", name="uq_deep_read_period"),
)

# The neutral-grader lane's tier (see save_external_review): a third-party
# reviewer's stance, with no read behind it, no findings, and score 0.0.
#
# Every helper that answers "what does this ledger already say about this
# PR" must exclude these, and the reason is not stylistic. Each of those
# helpers keys on columns an external row also carries — head_sha included,
# because a review names the commit it was left on — so an unfiltered helper
# hands back a score=0.0 row as if it were Doug's own verdict. The four call
# sites below are the whole guard among them.
#
# One other reader of this table exists and is not filtered:
# scripts/backfill_ledger.py counts verdicts filtered on `model == MODEL`,
# and external rows never set `model`. That immunity is incidental, exactly
# like the one find_review has (its pr_meta predicate is NULL for these
# rows) — which this file refused to rely on there, filtering explicitly and
# adding a test that can fail. The asymmetry is deliberate: the backfill is
# a one-shot script over named probe repos, not a live read of a tenant's
# ledger, so it is named here rather than filtered.
EXTERNAL_TIER = "external"

_engine = None
# The raw env string the engine was built from. Compared instead of
# str(_engine.url) because SQLAlchemy masks passwords when rendering a URL
# ("user:***@host"), so that comparison never matches a credentialed
# DATABASE_URL — and rebuilt the engine, pool and all, on every call.
_engine_url = None
_engine_lock = threading.Lock()


def _get_existing_schema_engine():
    """Build an engine without creating or migrating the target schema."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True)


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


def columns_of(table: str) -> frozenset[str] | None:
    """Column names actually present on `table` in the connected database.

    Ground truth for settle.py's schema-dependency filter (REVIEWING.md
    resolution rule): the live schema, not migrations.py's text and not
    this module's Table() declarations, which is the distinction that
    matters — a database can lag either at any point in a rollout. None
    means "cannot tell" (no DATABASE_URL, the table does not exist there
    yet, or introspection failed), and settle.py treats that as "keep the
    finding," never as "the column is absent."

    ENVIRONMENT ASSUMPTION (Doug's review of PR #49, reader:environment-drift,
    low): `DATABASE_URL` is Doug's OWN ledger database (this same table's
    other rows — verdicts, findings, installations, …), not a
    per-target-repo database Doug has no way to reach. Self-review is the
    one case where "Doug's schema" and "the reviewed repo's schema"
    coincide by construction. Against a genuine tenant repo this degrades
    safely rather than wrongly — a tenant table name essentially never
    matches one of Doug's own, so `has_table` returns False and the finding
    stays live — but it is a silent no-op there, not a working check. A
    correct multi-repo version needs a way to reach the REVIEWED repo's
    schema (its own migration state, or a read-only connection scoped to
    it), not Doug's.

    Catches broadly and returns None on failure rather than raising: Doug's
    review of PR #49 (reader:unhandled-exception-path) — this runs on every
    scored PR via review.score_one, whose try/except only names
    SpendCapExceeded and ReaderError, so an uncaught DB error here would
    crash the review job instead of degrading, exactly the failure mode
    this codebase exists to avoid. Same posture as review.head_file_text's
    own catch-all: settlement is advisory, never load-bearing for whether a
    review completes.
    """
    engine = _get_engine()
    if engine is None:
        return None
    try:
        inspector = inspect(engine)
        if not inspector.has_table(table):
            return None
        return frozenset(c["name"] for c in inspector.get_columns(table))
    except Exception as e:  # noqa: BLE001 — settlement is advisory
        print(
            f"doug: columns_of({table!r}) failed ({type(e).__name__}: {e})",
            file=sys.stderr,
        )
        return None


# Postgres names the constraint; sqlite lists the indexed columns (measured
# 2026-08-03: "UNIQUE constraint failed: verdicts.installation_id, …").
# Match the first column, not "verdicts." alone — a future unique constraint
# on any other verdicts column must not become an idempotent return.
# Same shape as ingest._DEDUPE_COLLISION / _OUTCOME_COLLISION.
_APP_IDENTITY_COLLISION = (
    "uq_verdicts_app_identity",
    "unique constraint failed: verdicts.installation_id",
)


def _is_app_identity_collision(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    return any(marker in message for marker in _APP_IDENTITY_COLLISION)


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
    diff_budget: int | None = None,
    read_order: str | None = None,
    *,
    created: list[bool] | None = None,
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

    App-path identity is unique (migration 005). A racing peer that already
    committed the same (installation_id, github_repo_id, pr_number, head_sha)
    makes this insert raise; we return that peer's id rather than failing the
    job. The worker's find_verdict_by_identity pre-read remains the cheap
    path — this is the race floor under it. Pass `created` (a one-element
    list the caller reads after return) to learn whether this call inserted
    the row (`True`) or resolved to a peer (`False`); the worker uses that
    to enter the identity-replay path instead of hanging local deviations
    and a locally rendered check run on the peer's id.
    """
    engine = _get_engine()
    if engine is None:
        return None

    def _mark(was_created: bool) -> None:
        if created is not None:
            created.clear()
            created.append(was_created)

    try:
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
                    "diff_budget": diff_budget,
                    "read_order": read_order,
                },
            ).scalar_one()
            rows = [
                {
                    "verdict_id": row,
                    "rule": r.rule,
                    "label": r.label,
                    "weight": r.weight,
                    "file": None,
                    # The Reason itself may already carry severity (reader
                    # tier sets it in verdict_from_reader); reader_verdict
                    # below only adds `file` and reconfirms the same value
                    # when a match is found.
                    "severity": r.severity,
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
                        "changed_files": coverage.changed_files,
                        "files_dropped": coverage.files_dropped,
                    },
                )
        _mark(True)
        return int(row)
    except IntegrityError as e:
        if not _is_app_identity_collision(e):
            raise
        if installation_id is None or github_repo_id is None or head_sha is None:
            raise
        existing = find_verdict_by_identity(
            installation_id, github_repo_id, pr_number, head_sha
        )
        if existing is None:
            raise
        _mark(False)
        return int(existing["id"])


def save_external_review(
    installation_id: int,
    github_repo_id: int,
    repo: str,
    pr_number: int,
    head_sha: str,
    source: str,
    band: Band,
    scored_at: datetime,
    raw: dict | None = None,
) -> int | None:
    """Record a third-party review as a verdict nobody scored.

    A sibling of save_review rather than a call into it: save_review owns
    `scored_at` (it hardcodes now()) and takes a Verdict, so using it would
    mean building a scoring type for something that was never scored and
    then overriding the one timestamp it deliberately decides. Here
    `scored_at` is the reviewer's own submitted_at — the row is a dated
    claim about when a stance was taken, and a redelivery a day later must
    not restate it as today's.

    score and threshold are 0.0 and tier is 'external' because no model ran
    and no diff was read. The band is Doug's own vocabulary on purpose: it
    is what lets a human's approval and Doug's verdict be adjudicated
    against the same outcome in the same ledger. Nothing here writes
    findings, reads or pr_meta — there was no read to describe.

    Returns None when this exact stance is already recorded. That check is a
    SELECT rather than a unique index, and the difference is worth stating
    plainly. create_all() never adds a constraint to a table that already
    exists and `verdicts` is live in production, so an index would have to
    come from migrations.py — which runs arbitrary DDL and mechanically
    could, but deliberately carries none: "an index created by create_all()
    but not by a migration is the same divergence in a new place". This is
    that convention, not an impossibility, and what replaces the index is
    weaker in one specific way: two genuinely concurrent deliveries of one
    review can both read before either commits, and both insert.

    The cost when that happens is one reviewer's stance counted twice in any
    agreement measure taken over this ledger — the same harm the dedup
    exists to prevent, on the concurrent pair instead of the ordinary one,
    and nothing downstream repairs it. Small, real, and not free. What this
    check does reliably suppress is the sequential case: a redelivery that
    arrives after the first row committed reads it and stops.

    The read is .first() rather than .scalar_one_or_none() for the same
    reason. It is an existence check against a table with no uniqueness
    guarantee, so it has to survive what the race can leave behind —
    asserting uniqueness there turned a duplicate pair into
    MultipleResultsFound on every later delivery of that review, a 500 out
    of the webhook that GitHub redelivers into the same 500. That is
    strictly worse than the duplicate row it was reacting to.
    """
    engine = _get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        existing = conn.execute(
            select(verdicts.c.id)
            .where(
                verdicts.c.installation_id == installation_id,
                verdicts.c.github_repo_id == github_repo_id,
                verdicts.c.pr_number == pr_number,
                verdicts.c.source == source,
                verdicts.c.head_sha == head_sha,
                verdicts.c.scored_at == scored_at,
            )
            .limit(1)
        ).first()
    if existing is not None:
        return None
    with engine.begin() as conn:
        return int(
            conn.execute(
                verdicts.insert().returning(verdicts.c.id),
                {
                    "repo": repo,
                    "pr_number": pr_number,
                    "scored_at": scored_at,
                    "tier": EXTERNAL_TIER,
                    "score": 0.0,
                    "band": band.value,
                    "threshold": 0.0,
                    "raw": raw,
                    "github_repo_id": github_repo_id,
                    "installation_id": installation_id,
                    "head_sha": head_sha,
                    "source": source,
                },
            ).scalar_one()
        )


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
    installation flips to 'removed'. Its one caller is the
    installation-deleted event, with an empty list: the uninstall is the
    only delivery that can end coverage without naming what it ended, and
    it is the only one whose repo list cannot be stale, because there isn't
    one.

    `replace=False` merges a delta, and the caller says which delta it is:
    the `installation_repositories` webhook sends added and removed in one
    payload, so removals arrive as their own call with state='removed'.
    installation-created merges too, even though it carries a full list —
    that list is authoritative when GitHub generated the event, and a
    redelivery of it would otherwise mark 'removed' every repo granted
    since (see _record_installation).

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


_OUTCOME_IDENTITY = (
    outcome_jobs.c.installation_id,
    outcome_jobs.c.github_repo_id,
    outcome_jobs.c.pr_number,
    outcome_jobs.c.merge_commit_sha,
    outcome_jobs.c.window_days,
)


def _outcome_insert(conn):
    if conn.dialect.name == "postgresql":
        statement = postgresql_insert(outcome_jobs)
    elif conn.dialect.name == "sqlite":
        statement = sqlite_insert(outcome_jobs)
    else:
        raise RuntimeError(f"unsupported outcome_jobs dialect: {conn.dialect.name}")
    return statement.on_conflict_do_nothing(index_elements=_OUTCOME_IDENTITY)


def enqueue_outcome_jobs(
    installation_id: int,
    github_repo_id: int,
    pr_number: int,
    merge_commit_sha: str,
    merged_at: datetime,
    base_ref: str,
    *,
    window_days: tuple[int, ...] = (14, 60),
    merged_head_sha: str | None = None,
) -> dict[int, int]:
    """Start the requested outcome-observation windows for one merged PR.

    Returns ``{window_days: inserted_id}``. Windows already present in the
    outcome ledger are absent, so a redelivery can fill a legacy one-window
    gap without creating a second denominator vote for an existing window.

    Both rows are prepared from the same merge facts and committed by one
    multi-value statement in one transaction: a failure creating either
    window must leave neither new row in the ledger.

    `merged_head_sha` defaults to None and is not part of any caller's
    required-facts check (see _record_merge) — it names the commit a
    receipt can later claim a verdict about, nothing this table's own
    windows or dedup depend on.
    """
    engine = _get_engine()
    if engine is None:
        return {}
    created_at = datetime.now(UTC)
    rows = [
        {
            "installation_id": installation_id,
            "github_repo_id": github_repo_id,
            "pr_number": pr_number,
            "merge_commit_sha": merge_commit_sha,
            "merged_at": merged_at,
            "base_ref": base_ref,
            "window_days": days,
            "due_at": merged_at + timedelta(days=days),
            "created_at": created_at,
            "merged_head_sha": merged_head_sha,
        }
        for days in window_days
    ]
    with engine.begin() as conn:
        result = conn.execute(
            _outcome_insert(conn)
            .values(rows)
            .returning(outcome_jobs.c.id, outcome_jobs.c.window_days)
        )
        return {days: job_id for job_id, days in result}


def enqueue_outcome_job(
    installation_id: int,
    github_repo_id: int,
    pr_number: int,
    merge_commit_sha: str,
    merged_at: datetime,
    base_ref: str,
    *,
    window_days: int = 14,
) -> int | None:
    """Start one outcome-observation window for one merged PR.

    Returns the new row's id, or None when this merge is already queued at
    this window — which is the ordinary case for a webhook redelivery.

    `due_at` is computed from `merged_at` and never from the wall clock. The
    same merge can reach this function seconds after it lands, hours later
    via a redelivery, or months later via a backfill, and the window has to
    mean "fourteen days after this code shipped" in all three. It is stored
    rather than derived at query time because window_days is part of the
    unique key and may differ per row.

    This is a compatibility wrapper around ``enqueue_outcome_jobs`` for
    callers that intentionally schedule a non-default single window.
    """
    inserted = enqueue_outcome_jobs(
        installation_id,
        github_repo_id,
        pr_number,
        merge_commit_sha,
        merged_at,
        base_ref,
        window_days=(window_days,),
    )
    return inserted.get(window_days)


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
                    "changed_files": cov.changed_files,
                    "files_dropped": cov.files_dropped,
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
    """The newest CI verdict already recorded for this exact commit, or None.

    The idempotency read: the review paths consult it before paying for an LLM
    read, so a webhook redelivery or a retried CI job replays the recorded
    verdict instead of double-spending and inserting a duplicate ledger
    row. Matches on the head_sha column (indexed-capable, written by the App
    and CI paths); falls back to pr_meta["head_sha"] for rows scored before
    the column was populated. The null App-id pair keeps this replay scoped
    to CI so an App verdict for the same commit cannot suppress the
    independent CI instrument. Rows with neither SHA simply never match, and
    get rescored once.
    """
    engine = _get_engine()
    if engine is None:
        return None
    from sqlalchemy import or_, select

    q = (
        select(verdicts)
        .where(
            verdicts.c.repo == repo,
            verdicts.c.pr_number == pr_number,
            verdicts.c.installation_id.is_(None),
            verdicts.c.github_repo_id.is_(None),
            or_(
                verdicts.c.head_sha == head_sha,
                verdicts.c.pr_meta["head_sha"].as_string() == head_sha,
            ),
            # Belt and braces. This helper is already immune by accident:
            # external rows write no pr_meta, so the JSON predicate above is
            # NULL for them and never matches. That immunity is incidental,
            # not designed, and evaporates the moment anything writes pr_meta
            # on an external row — so the exclusion is stated rather than
            # relied upon.
            verdicts.c.tier != EXTERNAL_TIER,
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


def _verdict_bundle(conn, v) -> dict:
    """Findings / deviations / coverage for one verdicts row — shared by the
    identity and id lookups so a race-loser holding only the peer's id can
    still render the same check run as the pre-read hit."""
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


def _load_verdict_row(conn, verdict_id: int):
    """The raw `verdicts` row for one id, or None. Shared by every by-id
    lookup so the query itself lives in exactly one place — find_verdict_by_id
    and run_detail both start here, each still checking the None case itself,
    before going their separate ways (bundle-only vs. bundle-plus-provenance)."""
    return conn.execute(
        select(verdicts).where(verdicts.c.id == verdict_id).limit(1)
    ).mappings().first()


def find_verdict_by_identity(
    installation_id: int, github_repo_id: int, pr_number: int, head_sha: str
) -> dict | None:
    """The verdict already recorded for this exact App-identified commit, or
    None. worker.process_job's idempotency read.

    A worker can crash (or ingest.complete can itself raise) anywhere after
    save_review lands and before the job is marked 'done' — mid check-run
    post, or before it ever starts. reclaim_stalled()/ingest.fail() then
    re-pend the row for another full attempt. Without this read, that retry
    re-scores from scratch: a second paid score_one/read_intent. Migration
    005's unique index stops the second verdicts row; this pre-read is still
    the cheap path that avoids buying the second read when the first already
    committed.

    Keyed on (installation_id, github_repo_id, pr_number, head_sha) rather
    than find_review's repo-string + pr_meta JSON match: the Global
    Constraint makes those four columns the uniqueness key everywhere, and
    the worker populates all of them on every App-path row. find_review
    predates the App path and stays keyed the old way; its only caller
    (/v1/review) retired in Task 9 (2026-08-05); CI rows before that date remain.
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
            # An external row carries all four of the columns above — a
            # review names the commit it was left on — so without this a
            # human approving PR #7 at SHA X answers this read, and
            # process_job completes against a verdict nobody scored: no read
            # of that commit ever happens, and the check run renders a
            # score=0.0 row as Doug's own. The ordering is id desc, so that
            # is not a race but the steady state for any PR a person reviews
            # after Doug does.
            verdicts.c.tier != EXTERNAL_TIER,
        )
        .order_by(verdicts.c.id.desc())
        .limit(1)
    )
    with engine.connect() as conn:
        v = conn.execute(q).mappings().first()
        if v is None:
            return None
        return _verdict_bundle(conn, v)


def find_verdict_by_id(verdict_id: int) -> dict | None:
    """Load one verdict by primary key for the race-loser path.

    save_review already resolved the peer's id; if the identity re-read
    misses (should not, but must not 500 a paid attempt), this is the
    durable handle.
    """
    engine = _get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        v = _load_verdict_row(conn, verdict_id)
        if v is None:
            return None
        return _verdict_bundle(conn, v)


def governing_verdict(
    installation_id: int,
    github_repo_id: int,
    pr_number: int,
    merged_at: datetime,
) -> dict | None:
    """The verdict that was standing when a human chose to merge.

    THIS IMPLEMENTS A PRE-REGISTERED METRIC RULE, NOT A DISPLAY CHOICE.
    `docs/design/outcome-loop/publication-preregistration.md` is LOCKED v8;
    §2.1 defines this selection and §2.2 holds the SQL the published quarterly
    miss rate runs. **Editing this function changes a published number.** The
    receipt endpoint and the future publication query must both call it, so
    that a customer's receipt cannot contradict the public table — which is
    the most expensive failure available to this product, because the whole
    claim is that both come from the same ledger.

    Three details come from §2.2's SQL rather than §2.1's prose, and a
    paraphrase of the prose gets each of them wrong:

      * `tier='reader'` filters BEFORE the ranking (it is inside the CTE, not
        the outer query), so a later deterministic fallback cannot displace an
        earlier real read. §2.5 gives the fallback tier its own published row
        precisely so it is never counted as the primary instrument.
      * band is NOT part of selection — §2.2 puts `g.band = 'cleared'` in the
        OUTER query, where it qualifies the published denominator. A flagged
        PR has a governing verdict and gets a receipt; this function neither
        takes band nor filters on it.
      * the installation must still exist (§2.6's structural exclusion), so a
        receipt cannot outlive the ledger row that scopes it, and research /
        un-tenanted CLI rows never reach either artifact.

    `row_number()`, never `DISTINCT ON`: the latter is Postgres-only and every
    test here runs sqlite (`docs/REVIEWING.md:141-143` records that exact
    trap), while production is Postgres. The most load-bearing rule in the
    document has to be exercisable by the suite that guards it.

    Scope, stated in full because it is the ONE place this is narrower than
    §2.2's set query and a silent difference here is the whole risk:

    §2.2 resolves the entire population in one pass, taking `merged_at` from
    the joined `outcome_jobs` row; this takes `merged_at` as an argument and
    answers for one merge identity. `uq_outcome_job` includes
    `merge_commit_sha`, so a PR may carry more than one merge — which is why
    §2.2 counts with `count(DISTINCT j.pr_number)`. On such a PR the two are
    not equivalent: §2.2's `PARTITION BY` does not include the job, so its
    single governing row is the verdict standing at the LATEST `merged_at`,
    while this answers per merge and so reports, for an earlier merge, the
    advice that was actually standing when THAT merge happened. Both name the
    same verdict for the PR's latest merge, which is the one the published
    denominator qualifies on; the receipt additionally shows the earlier
    merge, which is a receipt's job. Pinned by
    test_a_twice_merged_pr_resolves_per_merge_identity, and by the design
    spec's §"One PR can have more than one merge identity".

    Window selection is likewise the caller's: §2.2's `j.window_days = :window`
    picks which JOBS are in scope, not which verdict governs, and the 14- and
    60-day rows of one merge are written atomically from the same merge facts
    (§6.3) — same `merged_at`, therefore necessarily the same governing
    verdict, so the two published rows can never disagree about what Doug said.

    Returns the full verdicts row merged with `_verdict_bundle`'s findings,
    deviations and coverage, or None when no reader verdict was scored at or
    before `merged_at` (§2.4's `fallback_only` / `merged_before_verdict`
    buckets — excluded from the published rate, published as a count).
    """
    engine = _get_engine()
    if engine is None:
        return None
    # §2.2's `ranked` CTE, narrowed to one PR. The window function is
    # evaluated after WHERE, so every predicate here filters *before* the
    # ranking exactly as the document's CTE does — that ordering is the whole
    # point of the first bullet above and is why this cannot be flattened into
    # an ORDER BY ... LIMIT 1 with the tier test bolted on afterwards.
    #
    # The PARTITION BY is redundant under that narrowing (the WHERE already
    # pins all three of its columns) and is kept anyway, so the correspondence
    # to the document is literal rather than argued. It is also what makes the
    # narrowing safe to remove if the publication query ever wants this
    # expression over the whole population.
    ranked = (
        select(
            verdicts,
            func.row_number()
            .over(
                partition_by=(
                    verdicts.c.installation_id,
                    verdicts.c.github_repo_id,
                    verdicts.c.pr_number,
                ),
                order_by=(verdicts.c.scored_at.desc(), verdicts.c.id.desc()),
            )
            .label("rn"),
        )
        .where(
            verdicts.c.installation_id == installation_id,
            verdicts.c.github_repo_id == github_repo_id,
            verdicts.c.pr_number == pr_number,
            verdicts.c.tier == "reader",
            verdicts.c.scored_at <= merged_at,
            exists(select(1).where(installations.c.installation_id == installation_id)),
        )
        .subquery()
    )
    with engine.connect() as conn:
        # one_or_none(), not first(): the partition is pinned to a single PR,
        # so `rn = 1` names exactly one row or none. first() would silently
        # return an arbitrary one if that ever stopped being true, and "the
        # governing verdict was picked arbitrarily" is precisely the failure
        # this rule is written down to prevent. Raising is the correct
        # behaviour here — a receipt and a published number must not be
        # served from a coin flip.
        row = conn.execute(select(ranked).where(ranked.c.rn == 1)).mappings().one_or_none()
        if row is None:
            return None
        # `rn` is the ranking scaffold, not a fact about the verdict; dropped
        # so it cannot travel into a customer-facing receipt as if it were one.
        return {k: v for k, v in row.items() if k != "rn"} | _verdict_bundle(conn, row)


def run_detail(verdict_id: int) -> dict | None:
    """Everything the console's forensic page shows for one run.

    _verdict_bundle deliberately omits provenance — it renders a check run,
    where model and prompt hash are noise. This page has the opposite need:
    those fields ARE the answer to "what did Doug do with this PR". Rather
    than widen the bundle and change what every check run carries, this
    composes it with the columns it drops.
    """
    engine = _get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        v = _load_verdict_row(conn, verdict_id)
        if v is None:
            return None
        detail = _verdict_bundle(conn, v)
        detail.update(
            {
                "repo": v["repo"],
                "pr_number": v["pr_number"],
                "scored_at": v["scored_at"],
                "model": v["model"],
                "prompt_hash": v["prompt_hash"],
                "diff_budget": v["diff_budget"],
                "read_order": v["read_order"],
                "risk_score": v["risk_score"],
                "rationale": v["rationale"],
                "head_sha": v["head_sha"],
                "source": v["source"],
                "installation_id": v["installation_id"],
                "github_repo_id": v["github_repo_id"],
                "pr_meta": v["pr_meta"],
            }
        )
        job = conn.execute(
            select(review_jobs).where(review_jobs.c.verdict_id == verdict_id).limit(1)
        ).mappings().first()
        detail["job"] = (
            {
                "status": job["status"],
                "attempts": job["attempts"],
                "claim_generation": job["claim_generation"],
                "error": job["error"],
                "enqueued_at": job["enqueued_at"],
                "started_at": job["started_at"],
                "finished_at": job["finished_at"],
            }
            if job
            else None
        )
        # Outcomes key on (repo, pr_number), not on the verdict: a PR scored
        # three times has one merge and one set of clocks, shared by all
        # three runs. Both windows travel separately — they are different
        # claims with different dates, and the page shows them side by side.
        detail["outcomes"] = [
            {
                "kind": row["kind"],
                "window_days": row["window_days"],
                "observed_at": row["observed_at"],
                "source": row["source"],
                "detail": row["detail"],
            }
            for row in conn.execute(
                select(outcomes)
                .where(outcomes.c.repo == v["repo"])
                .where(outcomes.c.pr_number == v["pr_number"])
                .order_by(outcomes.c.window_days)
            ).mappings()
        ]
        detail["outcome_jobs"] = [
            {
                "window_days": row["window_days"],
                "status": row["status"],
                "due_at": row["due_at"],
                "merged_at": row["merged_at"],
            }
            for row in conn.execute(
                select(outcome_jobs)
                .where(outcome_jobs.c.github_repo_id == v["github_repo_id"])
                .where(outcome_jobs.c.pr_number == v["pr_number"])
                .order_by(outcome_jobs.c.window_days)
            ).mappings()
        ]
    return detail


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

    # Excluded inside the subquery for the same reason latest_reviews does
    # it there, but the damage here is quieter. An external row winning
    # max(id) leaves its PR in `prs` (the denominator) while contributing no
    # findings to `hits`, because external rows have none — so every pattern
    # that PR really carried silently stops counting as a hit, and the
    # per-pattern precision this feeds is published.
    latest = (
        select(func.max(verdicts.c.id).label("id"))
        .where(verdicts.c.tier != EXTERNAL_TIER)
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


def latest_reviews(
    limit: int = 200,
    repo: str | None = None,
    installation_id: int | None = None,
    repo_ids: set[int] | None = None,
) -> list[dict]:
    """Most recent verdict per (repo, pr) with findings — the live queue.

    `repo` scopes the queue; without it the ledger's every repo mixes
    together, which is an all-repos admin view, not a dashboard.
    `installation_id` scopes the queue to one tenant; without it this is the
    operator view. `repo_ids`, when given, further scopes to a
    'selected'-selection key's live repo set. All three filters are inside
    the grouped subquery — see the comment there before moving any of them.
    """
    engine = _get_engine()
    if engine is None:
        return []
    from sqlalchemy import desc, func, select

    # The tenant filter belongs INSIDE this subquery for exactly the reason
    # the external-tier filter does, spelled out above: a row excluded only
    # on the outer query can still win max(id) for its PR and then be
    # dropped, and the PR disappears instead of falling back. A CI row
    # (installation_id NULL) on a tenant's own PR is precisely that case.
    scoped = verdicts.c.tier != EXTERNAL_TIER
    if installation_id is not None:
        scoped = scoped & (verdicts.c.installation_id == installation_id)
    if repo_ids is not None:
        # Same placement rule as the tenant filter above: INSIDE the grouped
        # subquery, or an out-of-selection row wins max(id) and its PR
        # disappears instead of falling back.
        scoped = scoped & (verdicts.c.github_repo_id.in_(repo_ids))
    latest = (
        select(func.max(verdicts.c.id).label("id"))
        .where(scoped)
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


def run_history(
    limit: int = 100,
    offset: int = 0,
    repo: str | None = None,
    installation_id: int | None = None,
    include_untenanted: bool = False,
) -> list[dict]:
    """Verdict HISTORY, newest first — every run, not one row per PR.

    `latest_reviews` answers "what is the current state of the queue".
    This answers "what has Doug done", which is a different question: a PR
    pushed three times is three runs, and collapsing them hides exactly the
    comparison an operator opens the console to make.

    Untenanted rows (installation_id IS NULL) are excluded by default. That
    is the filter migrations.py:211 names as the correct one — real
    installation ids rather than a label — and it is what keeps backfilled
    probe corpora, CLI rows and the research quarantine out of a console
    that is meant to show tenant traffic.

    Each row carries `coverage`, `finding_counts`, `job` and `outcome_14`.
    Every child join goes through an id-picking subquery because a plain
    outerjoin duplicates the verdict row whenever two children match, and a
    duplicated run reads as a real second review rather than as a bug.
    """
    engine = _get_engine()
    if engine is None or limit < 1 or offset < 0:
        return []
    from sqlalchemy import case, desc, func, select

    query = select(verdicts).where(verdicts.c.tier != EXTERNAL_TIER)
    if not include_untenanted:
        query = query.where(verdicts.c.installation_id.is_not(None))
    if repo:
        query = query.where(verdicts.c.repo == repo)
    if installation_id is not None:
        query = query.where(verdicts.c.installation_id == installation_id)
    query = (
        query.order_by(desc(verdicts.c.scored_at), desc(verdicts.c.id))
        .limit(limit)
        .offset(offset)
    )

    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query).mappings()]
        if not rows:
            return rows
        ids = [r["id"] for r in rows]

        # One read per verdict: newest by id. A verdict can carry more than
        # one (a retried read writes a second row), and both are real.
        read_ids = (
            select(reads.c.verdict_id, func.max(reads.c.id).label("read_id"))
            .where(reads.c.verdict_id.in_(ids))
            .group_by(reads.c.verdict_id)
            .subquery()
        )
        cov_by_verdict = {
            row["verdict_id"]: {
                "diff_chars": row["diff_chars"],
                "sent_chars": row["sent_chars"],
                "files_sent": row["files_sent"],
                "files_unseen": row["files_unseen"],
                "file_cut": row["file_cut"],
            }
            for row in conn.execute(
                select(reads).join(read_ids, read_ids.c.read_id == reads.c.id)
            ).mappings()
        }

        counts_by_verdict = {
            row["verdict_id"]: {
                "total": row["total"],
                "high": row["high"],
                "medium": row["medium"],
                "low": row["low"],
            }
            for row in conn.execute(
                select(
                    findings.c.verdict_id,
                    func.count().label("total"),
                    func.sum(case((findings.c.severity == "high", 1), else_=0)).label("high"),
                    func.sum(case((findings.c.severity == "medium", 1), else_=0)).label(
                        "medium"
                    ),
                    func.sum(case((findings.c.severity == "low", 1), else_=0)).label("low"),
                )
                .where(findings.c.verdict_id.in_(ids))
                .group_by(findings.c.verdict_id)
            ).mappings()
        }

        # Newest-attempts-last if a verdict is ever referenced by more than
        # one job row (not enforced today — uq_review_job scopes uniqueness
        # to (installation_id, github_repo_id, pr_number, head_sha), not to
        # verdict_id). The dict below keeps whichever comes last in
        # iteration order, the same last-observation-wins rule as
        # outcome_by_pr just below.
        job_by_verdict = {
            row["verdict_id"]: {
                "status": row["status"],
                "attempts": row["attempts"],
                "error": row["error"],
                "enqueued_at": row["enqueued_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in conn.execute(
                select(review_jobs)
                .where(review_jobs.c.verdict_id.in_(ids))
                .order_by(review_jobs.c.id)
            ).mappings()
        }

        # 14-day only. Both windows exist for a merged PR, and carrying both
        # into a list column is what fans one run out into two. Filtered on
        # both halves of the key — repo alone would fetch every 14-day
        # outcome for every repo on the page, not just the PRs on it.
        #
        # `outcomes` carries no unique constraint on (repo, pr_number,
        # window_days), so if a PR is ever re-graded the dict below keeps
        # the highest-id (most recent) row — last-observation-wins. That is
        # a different reduction than find_scored_prs_with_outcomes uses on
        # this same table (store.py:1240-1241), which fans a multi-outcome
        # PR out into several rows and leaves the reduction to its caller.
        # The difference is deliberate: outcome_14 is a single list-column
        # value here, so there is no caller-side reduction to defer to.
        keys = {(r["repo"], r["pr_number"]) for r in rows}
        outcome_by_pr = {
            (row["repo"], row["pr_number"]): row["kind"]
            for row in conn.execute(
                select(outcomes)
                .where(outcomes.c.window_days == 14)
                .where(outcomes.c.repo.in_({k[0] for k in keys}))
                .where(outcomes.c.pr_number.in_({k[1] for k in keys}))
                .order_by(outcomes.c.id)
            ).mappings()
        }

    zero = {"total": 0, "high": 0, "medium": 0, "low": 0}
    for row in rows:
        row["coverage"] = cov_by_verdict.get(row["id"])
        row["finding_counts"] = counts_by_verdict.get(row["id"], dict(zero))
        row["job"] = job_by_verdict.get(row["id"])
        row["outcome_14"] = outcome_by_pr.get((row["repo"], row["pr_number"]))
    return rows


def active_installations() -> list[int]:
    """Installation ids in state 'active'. [] when storage is disabled."""
    engine = _get_engine()
    if engine is None:
        return []
    from sqlalchemy import select

    with engine.connect() as conn:
        return [
            int(r.installation_id)
            for r in conn.execute(
                select(installations.c.installation_id).where(
                    installations.c.state == "active"
                )
            )
        ]


def active_repos(installation_id: int) -> list[tuple[int, str]]:
    """(github_repo_id, full_name) for this installation's active repos.

    A repo removed from an installation keeps state='removed' rather than
    being deleted, so this filters rather than trusting the table's
    contents — the history of what Doug was once installed on is worth
    keeping, and reviewing a removed repo is not.
    """
    engine = _get_engine()
    if engine is None:
        return []
    from sqlalchemy import select

    with engine.connect() as conn:
        return [
            (int(r.github_repo_id), r.full_name)
            for r in conn.execute(
                select(
                    installation_repos.c.github_repo_id,
                    installation_repos.c.full_name,
                ).where(
                    (installation_repos.c.installation_id == installation_id)
                    & (installation_repos.c.state == "active")
                )
            )
        ]


def count_installations_referenced_by_verdicts() -> int:
    """How many distinct installations the verdicts ledger names. Compared
    against active_installations() at startup: verdicts referencing tenants
    the installations table has never heard of is the MT0 signature — a
    webhook that never arrived — and reconcile_all is silently dead."""
    engine = _get_engine()
    if engine is None:
        return 0
    from sqlalchemy import func

    with engine.connect() as conn:
        return int(
            conn.execute(
                select(func.count(func.distinct(verdicts.c.installation_id))).where(
                    verdicts.c.installation_id.is_not(None)
                )
            ).scalar_one()
        )


def count_verdict_repos_missing_from_ledger() -> int:
    """How many distinct (installation_id, github_repo_id) pairs verdicts
    names that installation_repos has no row for at all — regardless of
    state.

    Task 10 made tenant queue reads join through installation_repos by id,
    so a repo whose repositories_added delivery never arrived is now
    invisible to its own tenant's queue while the operator's unscoped queue
    (keyed on installation_id alone) still shows it — a second, per-repo
    drift mode the ledger-emptiness check above cannot see: that check only
    fires when installations is empty outright, and this table can be
    entirely absent for one repo while every other repo on the same
    installation is fine.

    A 'removed' row does NOT count here — that is a delivery that DID
    arrive, recording deliberate coverage-ending, the opposite of what this
    counts. Only a row's total absence is the MT0-class signature.
    """
    engine = _get_engine()
    if engine is None:
        return 0
    from sqlalchemy import func

    with engine.connect() as conn:
        pairs = (
            select(verdicts.c.installation_id, verdicts.c.github_repo_id)
            .where(
                verdicts.c.installation_id.is_not(None),
                verdicts.c.github_repo_id.is_not(None),
            )
            .distinct()
            .subquery()
        )
        covered = select(installation_repos.c.id).where(
            installation_repos.c.installation_id == pairs.c.installation_id,
            installation_repos.c.github_repo_id == pairs.c.github_repo_id,
        )
        return int(
            conn.execute(
                select(func.count()).select_from(pairs).where(~covered.exists())
            ).scalar_one()
        )


def _utc(dt):
    """sqlite hands back naive datetimes for DateTime(timezone=True) columns;
    every stored value is UTC, so naive means 'UTC, badly labelled'."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def insert_installation_token(
    installation_id: int,
    *,
    token_lookup: str,
    token_hash: str,
    hash_version: int,
    last4: str,
    label: str | None,
    repo_selection: str,
    scopes: list[str],
    minted_by: str,
    expires_at: datetime | None,
) -> int | None:
    """A new key row, appended — NEVER an update of an existing one. Returns
    None when storage is off or the installation has no row (no row means
    Doug was never installed there; the absence is a refusal)."""
    engine = _get_engine()
    if engine is None:
        return None
    with engine.begin() as conn:
        known = conn.execute(
            select(installations.c.id).where(
                installations.c.installation_id == installation_id
            )
        ).scalar_one_or_none()
        if known is None:
            return None
        return conn.execute(
            installation_tokens.insert().returning(installation_tokens.c.id),
            {
                "installation_id": installation_id,
                "token_lookup": token_lookup,
                "token_hash": token_hash,
                "hash_version": hash_version,
                "last4": last4,
                "label": label,
                "repo_selection": repo_selection,
                "scopes": scopes,
                "minted_by": minted_by,
                "created_at": datetime.now(UTC),
                "expires_at": expires_at,
            },
        ).scalar_one()


def set_installation_token_repos(token_id: int, repo_ids: list[int]) -> None:
    engine = _get_engine()
    if engine is None or not repo_ids:
        return
    with engine.begin() as conn:
        conn.execute(
            installation_token_repos.insert(),
            [{"token_id": token_id, "github_repo_id": rid} for rid in repo_ids],
        )


def installation_token_by_lookup(token_lookup: str) -> dict | None:
    """The key row plus the LIVE installation state, in one query. The JOIN
    (not a LEFT JOIN) makes a key whose installation row is missing resolve
    to nothing — fail closed, same direction as everything else here."""
    engine = _get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(
                    installation_tokens,
                    installations.c.state.label("installation_state"),
                )
                .join(
                    installations,
                    installations.c.installation_id
                    == installation_tokens.c.installation_id,
                )
                .where(installation_tokens.c.token_lookup == token_lookup)
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    out = dict(row)
    out["expires_at"] = _utc(out["expires_at"])
    out["revoked_at"] = _utc(out["revoked_at"])
    out["last_used_at"] = _utc(out["last_used_at"])
    return out


def installation_token_repo_ids(token_id: int) -> set[int]:
    engine = _get_engine()
    if engine is None:
        return set()
    with engine.connect() as conn:
        return {
            int(r.github_repo_id)
            for r in conn.execute(
                select(installation_token_repos.c.github_repo_id).where(
                    installation_token_repos.c.token_id == token_id
                )
            )
        }


def count_installation_tokens_minted_since(
    installation_id: int, since: datetime
) -> int | None:
    """None on ANY failure, including storage-off. The daily mint cap is
    fail-open by spec: a counting error must log-and-allow at the caller,
    never refuse a legitimate mint because a SELECT hiccuped."""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        from sqlalchemy import func

        with engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(installation_tokens)
                    .where(
                        (installation_tokens.c.installation_id == installation_id)
                        & (installation_tokens.c.created_at >= since)
                    )
                ).scalar_one()
            )
    except Exception:  # noqa: BLE001 — fail-open is the contract
        return None


def touch_installation_token_last_used(token_id: int) -> None:
    """Best-effort convenience timestamp, throttled to one write per key per
    60s. Deliberately NOT part of the resolve contract: a failure here must
    never fail a request, and the throttle keeps the hot path from writing
    on every call."""
    engine = _get_engine()
    if engine is None:
        return
    try:
        now = datetime.now(UTC)
        with engine.begin() as conn:
            conn.execute(
                update(installation_tokens)
                .where(
                    (installation_tokens.c.id == token_id)
                    & (
                        (installation_tokens.c.last_used_at.is_(None))
                        | (installation_tokens.c.last_used_at < now - timedelta(seconds=60))
                    )
                )
                .values(last_used_at=now)
            )
    except Exception:  # noqa: BLE001 — convenience, not audit
        pass


def list_installation_tokens(installation_id: int) -> list[dict]:
    """Masked list for the management endpoint: everything but the hash.
    Revoked rows stay listed — they are the audit trail, and 'when did that
    key die' is a question this table exists to answer."""
    engine = _get_engine()
    if engine is None:
        return []
    cols = [c for c in installation_tokens.c if c.name != "token_hash"]
    with engine.connect() as conn:
        rows = conn.execute(
            select(*cols)
            .where(installation_tokens.c.installation_id == installation_id)
            .order_by(installation_tokens.c.id.desc())
        ).mappings().all()
    out = []
    for row in rows:
        d = dict(row)
        for key in ("expires_at", "revoked_at", "last_used_at", "created_at"):
            d[key] = _utc(d[key])
        out.append(d)
    return out


def revoke_installation_token(token_id: int, installation_id: int) -> bool:
    """Soft revoke, idempotent, ownership INSIDE the where: a foreign
    token_id matches nothing and is indistinguishable from a missing one."""
    engine = _get_engine()
    if engine is None:
        return False
    from sqlalchemy import func

    with engine.begin() as conn:
        result = conn.execute(
            update(installation_tokens)
            .where(
                (installation_tokens.c.id == token_id)
                & (installation_tokens.c.installation_id == installation_id)
            )
            .values(revoked_at=func.coalesce(installation_tokens.c.revoked_at, datetime.now(UTC)))
        )
    return result.rowcount > 0


def revoke_all_installation_tokens(installation_id: int) -> int:
    """The uninstall webhook's bulk stamp. Belt-and-braces on top of
    resolve's live state check — the audit trail is the point."""
    engine = _get_engine()
    if engine is None:
        return 0
    with engine.begin() as conn:
        result = conn.execute(
            update(installation_tokens)
            .where(
                (installation_tokens.c.installation_id == installation_id)
                & (installation_tokens.c.revoked_at.is_(None))
            )
            .values(revoked_at=datetime.now(UTC))
        )
    return result.rowcount

