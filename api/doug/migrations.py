"""Ordered DDL for changes create_all() cannot make.

store.py's create_all() adds missing *tables* and never adds a column to a
table that already exists. Every new column on `verdicts` therefore has two
homes that must agree: the Table definition (which is what a fresh database
gets) and a migration here (which is what production's existing database
gets). apply() runs after create_all() on every engine, so both paths end at
the same schema instead of diverging into a green test suite and a broken
production write.

A statement that finds its work already done is satisfied, not failed: on a
fresh database create_all() has already produced the post-migration shape,
so migration 001's ALTERs are no-ops there and must not raise. Anything else
propagates.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, select
from sqlalchemy.exc import DatabaseError

# Its own MetaData: this table has to exist before store.metadata is created
# and must never be dropped alongside it.
_meta = MetaData()

schema_migrations = Table(
    "schema_migrations",
    _meta,
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)

# Plain DDL strings, valid on both sqlite and Postgres. No IF NOT EXISTS:
# sqlite rejects it on ADD COLUMN, so idempotency comes from the version
# table plus _SATISFIED below. No indexes here either — an index created by
# create_all() but not by a migration is the same divergence in a new place.
MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            "ALTER TABLE verdicts ADD COLUMN github_repo_id BIGINT",
            "ALTER TABLE verdicts ADD COLUMN installation_id BIGINT",
            "ALTER TABLE verdicts ADD COLUMN head_sha VARCHAR(64)",
            "ALTER TABLE verdicts ADD COLUMN source VARCHAR(20)",
        ),
    ),
]

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
        with engine.begin() as conn:
            conn.execute(
                schema_migrations.insert(),
                {"version": version, "applied_at": datetime.now(UTC)},
            )
        applied.append(version)
    return applied
