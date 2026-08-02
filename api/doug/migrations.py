"""Ordered DDL for changes create_all() cannot make.

store.py's create_all() adds missing *tables* and never adds a column to a
table that already exists. Every new column on an existing table therefore
has two homes that must agree: the Table definition (which is what a fresh
database gets) and a migration here (which is what production's existing
database gets). apply() runs after create_all() on every engine, so both
paths end at the same schema instead of diverging into a green test suite
and a broken production write.

A statement that finds its work already done is satisfied, not failed: on a
fresh database create_all() has already produced the post-migration shape,
so an already-applied ALTER is a no-op there and must not raise. Anything
else propagates.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, select
from sqlalchemy.exc import DatabaseError, IntegrityError

# Its own MetaData: this table has to exist before store.metadata is created
# and must never be dropped alongside it.
_meta = MetaData()

schema_migrations = Table(
    "schema_migrations",
    _meta,
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)

# Plain DDL strings, valid on both sqlite and Postgres. No IF NOT EXISTS on
# ADD COLUMN: sqlite rejects it there, so idempotency comes from the version
# table plus _SATISFIED below. Indexes are CREATE INDEX IF NOT EXISTS so a
# fresh create_all()+apply and an older production DB both converge without
# putting the same Index() on Table definitions (which would reintroduce
# create_all-only drift for anything not also migrated).
MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            "ALTER TABLE verdicts ADD COLUMN github_repo_id BIGINT",
            "ALTER TABLE verdicts ADD COLUMN installation_id BIGINT",
            "ALTER TABLE verdicts ADD COLUMN head_sha VARCHAR(64)",
            # 64 wide: Task 6 ingests third-party review verdicts as
            # source='review:<login>', and a GitHub login runs to 39 chars
            # ('review:' + 39 = 46).
            "ALTER TABLE verdicts ADD COLUMN source VARCHAR(64)",
        ),
    ),
    (
        2,
        (
            # outcomes predates the outcome-loop (ADR-0001) and gets the
            # same identity columns verdicts got in migration 001, plus the
            # window this PR was observed under and the adjudicator's
            # supporting detail. Existing rows keep NULLs here — outcomes.repo
            # stays the display-only join key for anything scored before
            # this migration; nothing rewrites it.
            "ALTER TABLE outcomes ADD COLUMN github_repo_id BIGINT",
            "ALTER TABLE outcomes ADD COLUMN installation_id BIGINT",
            "ALTER TABLE outcomes ADD COLUMN window_days INTEGER",
            "ALTER TABLE outcomes ADD COLUMN detail TEXT",
            "ALTER TABLE verdicts ADD COLUMN prompt_hash VARCHAR(64)",
        ),
    ),
    (
        3,
        (
            # Hot-path partial indexes for claim/reclaim (Task 5) and the M3
            # adjudicator drain. Not declared on the Table() objects — see
            # module docstring — so production only gets them here.
            # IF NOT EXISTS: apply() records the version only after every
            # statement in the tuple succeeds, so a mid-tuple failure leaves
            # the version unrecorded and the next apply retries; IF NOT
            # EXISTS makes the already-applied statements no-ops on retry.
            "CREATE INDEX IF NOT EXISTS idx_review_jobs_pending_queue "
            "ON review_jobs (enqueued_at, id) WHERE status = 'pending'",
            "CREATE INDEX IF NOT EXISTS idx_review_jobs_running_stale "
            "ON review_jobs (started_at) WHERE status = 'running'",
            "CREATE INDEX IF NOT EXISTS idx_outcome_jobs_pending_due "
            "ON outcome_jobs (due_at) WHERE status = 'pending'",
        ),
    ),
    (
        4,
        (
            # Claim-holder fence token. Integer equality survives sqlite/Postgres
            # timestamp round-trips that made started_at-based fencing fragile.
            "ALTER TABLE review_jobs ADD COLUMN claim_generation INTEGER NOT NULL DEFAULT 0",
        ),
    ),
]

# Research-corpus quarantine convention (no data change — no research rows
# exist in the app database today): public-corpus / research rows are
# written under a reserved sentinel installation id and carry
# source='research' at insert time, in the same insert that would otherwise
# carry a real installation_id. Every tenant-facing counter therefore stays
# correct by filtering on real installation ids rather than by excluding a
# label after the fact.

_SATISFIED = ("duplicate column name", "already exists")


def _run(engine, statement: str) -> None:
    # One transaction per statement: on Postgres a failed statement poisons
    # the whole transaction, and the already-satisfied case has to leave the
    # connection usable for the rest of the migration.
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(statement)
    except DatabaseError as e:
        if not any(m in str(e).lower() for m in _SATISFIED):
            raise


def apply(engine) -> list[int]:
    """Run every unapplied migration in order. Returns the versions applied."""
    schema_migrations.create(engine, checkfirst=True)
    with engine.connect() as conn:
        done = {r[0] for r in conn.execute(select(schema_migrations.c.version))}
    applied: list[int] = []
    for version, statements in MIGRATIONS:
        if version in done:
            continue
        for statement in statements:
            _run(engine, statement)
        try:
            with engine.begin() as conn:
                conn.execute(
                    schema_migrations.insert(),
                    {"version": version, "applied_at": datetime.now(UTC)},
                )
        except IntegrityError:
            # Two instances cold-starting together can both read `done` as
            # not containing this version, both run the ALTERs above (each
            # individually idempotent), and then race to record it here.
            # The migration itself already landed under either instance —
            # the loser's insert hitting the version primary key is the same
            # "already done, not failed" case _run's _SATISFIED handles for
            # DDL, just for the ledger row instead of a column.
            continue
        applied.append(version)
    return applied
