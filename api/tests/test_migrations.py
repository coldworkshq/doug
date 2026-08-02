from sqlalchemy import create_engine, inspect, select

from doug import migrations, store

APP_COLUMNS = {"github_repo_id", "installation_id", "head_sha", "source"}


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


OUTCOME_COLUMNS = {"github_repo_id", "installation_id", "window_days", "detail"}


def test_apply_adds_the_columns_to_a_database_built_by_an_older_schema(tmp_path):
    """The case create_all() cannot handle, and the only reason this module
    exists. Production's `verdicts` and `outcomes` were both created before
    their outcome-loop columns, and create_all() adds missing tables, never
    missing columns.

    The tables are built by hand rather than from store.metadata on purpose:
    a test that starts from today's metadata can only exercise the path that
    was never broken.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE verdicts (id INTEGER PRIMARY KEY, repo VARCHAR(200) NOT NULL)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE outcomes (id INTEGER PRIMARY KEY, repo VARCHAR(200) NOT NULL)"
        )
        # Migration 003 indexes these; production gets the tables from
        # create_all before apply. The hand-built older schema needs stubs.
        conn.exec_driver_sql(
            "CREATE TABLE review_jobs ("
            "id INTEGER PRIMARY KEY, status VARCHAR(12), "
            "enqueued_at DATETIME, started_at DATETIME)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE outcome_jobs ("
            "id INTEGER PRIMARY KEY, status VARCHAR(12), due_at DATETIME)"
        )
    assert migrations.apply(engine) == [1, 2, 3]
    assert APP_COLUMNS <= _columns(engine, "verdicts")
    assert {"prompt_hash"} <= _columns(engine, "verdicts")
    assert OUTCOME_COLUMNS <= _columns(engine, "outcomes")


def test_apply_on_a_freshly_created_schema_records_without_erroring(tmp_path):
    """The same divergence from the other side. A fresh database already has
    every migrated column from create_all(), so neither migration has
    anything to do — and if "nothing to do" raised, every test run and every
    new deployment would die inside _get_engine on a statement that is only
    meaningful against the older production tables.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/fresh.db")
    store.metadata.create_all(engine)
    assert APP_COLUMNS <= _columns(engine, "verdicts")

    assert migrations.apply(engine) == [1, 2, 3]
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == [1, 2, 3]


def test_apply_reports_only_newly_applied_versions(tmp_path):
    """apply() runs on every engine creation, not once at deploy time, so a
    second call re-running a migration would raise on the duplicate column
    and take the process down at first ledger use."""
    engine = create_engine(f"sqlite:///{tmp_path}/twice.db")
    store.metadata.create_all(engine)
    assert migrations.apply(engine) == [1, 2, 3]
    assert migrations.apply(engine) == []


def test_migration_001_declares_the_same_columns_as_the_verdicts_table(tmp_path):
    """The App columns are written down twice — in store.verdicts, which is
    what a fresh database gets, and in migration 001, which is what production
    gets. Nothing else stops the two from drifting, and drift is invisible
    until a production INSERT names a column that is not there."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl.db")
    store.metadata.create_all(engine)
    altered = {s.split("ADD COLUMN ")[1].split()[0] for s in dict(migrations.MIGRATIONS)[1]}
    assert altered == APP_COLUMNS
    assert altered <= _columns(engine, "verdicts")


def test_migration_001_source_ddl_matches_the_widened_column():
    """`source` was widened to 64 chars (`review:<login>` runs to 46) after
    migration 001 first shipped. The width lives in two places same as the
    column names do, and sqlite silently ignores VARCHAR length so only the
    declared type — not a round-trip write — can catch the two drifting."""
    stmt = next(s for s in dict(migrations.MIGRATIONS)[1] if "source" in s)
    assert "VARCHAR(64)" in stmt
    assert store.verdicts.c.source.type.length == 64


def _statements_by_table(statements: tuple[str, ...]) -> dict[str, set[str]]:
    """Column adds only — CREATE INDEX migrations are not column drift."""
    by_table: dict[str, set[str]] = {}
    for stmt in statements:
        if "ADD COLUMN" not in stmt.upper():
            continue
        table = stmt.split("ALTER TABLE ")[1].split()[0]
        column = stmt.split("ADD COLUMN ")[1].split()[0]
        by_table.setdefault(table, set()).add(column)
    return by_table


def test_migration_002_declares_the_same_columns_as_their_tables(tmp_path):
    """Migration 002 touches two existing tables (outcomes, verdicts) instead
    of one. Same drift risk as migration 001, doubled: each column has to
    match both its table definition and its own ALTER TABLE statement, or a
    fresh database and production can diverge on either table."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl2.db")
    store.metadata.create_all(engine)
    by_table = _statements_by_table(dict(migrations.MIGRATIONS)[2])
    assert by_table["outcomes"] == OUTCOME_COLUMNS
    assert by_table["verdicts"] == {"prompt_hash"}
    for table, cols in by_table.items():
        assert cols <= _columns(engine, table)


# The pre-Task-2 shape of the two migrated tables, exactly as they were at
# commit 240caf5 (the base this branch built on) — not a copy of anything in
# store.py today. This is the independent ground truth the reverse-drift
# test below needs: "today's definition" is derived from store.metadata,
# and comparing metadata against itself could never fail, so the baseline
# has to come from somewhere else.
_BASELINE_DDL = {
    "verdicts": """
        CREATE TABLE verdicts (
            id INTEGER PRIMARY KEY,
            repo VARCHAR(200) NOT NULL,
            pr_number INTEGER NOT NULL,
            scored_at DATETIME NOT NULL,
            tier VARCHAR(20) NOT NULL,
            score FLOAT NOT NULL,
            band VARCHAR(10) NOT NULL,
            threshold FLOAT NOT NULL,
            model VARCHAR(60),
            risk_score INTEGER,
            rationale TEXT,
            raw TEXT,
            pr_meta TEXT
        )
    """,
    "outcomes": """
        CREATE TABLE outcomes (
            id INTEGER PRIMARY KEY,
            repo VARCHAR(200) NOT NULL,
            pr_number INTEGER NOT NULL,
            kind VARCHAR(20) NOT NULL,
            observed_at DATETIME NOT NULL,
            source VARCHAR(40) NOT NULL
        )
    """,
}


def test_no_migrated_table_has_a_column_unaccounted_for_by_baseline_or_migration(tmp_path):
    """The forward drift tests above (migration 001, migration 002) only
    catch a migration column missing from the table definition. This is the
    other direction: a bare `Column(...)` added to `verdicts` or `outcomes`
    with no matching migration would leave every test green here — and the
    column silently absent from production Postgres — which is exactly the
    failure the migration framework exists to prevent.

    baseline (pre-Task-2 columns) + every migration's added columns must
    equal store.metadata's column set for that table, exactly. Anything in
    the definition but not in that union is a column with no migration;
    anything in that union but not the definition is already caught by the
    forward tests.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/reverse.db")
    with engine.begin() as conn:
        for ddl in _BASELINE_DDL.values():
            conn.exec_driver_sql(ddl)

    added: dict[str, set[str]] = {}
    for _version, statements in migrations.MIGRATIONS:
        for table, cols in _statements_by_table(statements).items():
            added.setdefault(table, set()).update(cols)

    for table in _BASELINE_DDL:
        baseline = _columns(engine, table)
        expected = baseline | added.get(table, set())
        actual = {c.name for c in store.metadata.tables[table].columns}
        assert actual == expected, (
            f"{table}: definition has {actual - expected or '{}'} with no migration, "
            f"or a migration adds {expected - actual or '{}'} missing from the definition"
        )


def test_apply_does_not_raise_when_two_racers_insert_the_same_version(tmp_path, monkeypatch):
    """Two Cloud Run instances cold-starting together can both read
    `done = {}` before either has recorded anything, both run a version's
    (idempotent) ALTERs, and then both try to INSERT the version row. The
    ALTERs landed either way — only one of the two inserts can win the
    primary key, and the loser's insert failure must not escape apply() and
    turn into a 500 on that instance's first ledger-touching request.
    """
    import threading
    import time

    engine = create_engine(f"sqlite:///{tmp_path}/race.db")
    store.metadata.create_all(engine)
    # Created up front so the two racers' first move is the `done` read this
    # test means to race, not an unrelated checkfirst-create race on the
    # ledger table itself.
    migrations.schema_migrations.create(engine, checkfirst=True)

    real_run = migrations._run

    def slow_run(engine, statement):
        time.sleep(0.02)  # hold the window open past both racers' done-read
        return real_run(engine, statement)

    monkeypatch.setattr(migrations, "_run", slow_run)

    errors = []

    def racer():
        try:
            migrations.apply(engine)
        except Exception as e:  # noqa: BLE001 — the assertion is that nothing escapes
            errors.append(e)

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    with engine.connect() as conn:
        versions = sorted(
            r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))
        )
    assert versions == [v for v, _ in migrations.MIGRATIONS]


def test_get_engine_applies_migrations(tmp_path, monkeypatch):
    """The hook, not the runner: a migration nobody calls is a comment."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/hooked.db")
    engine = store._get_engine()
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == [v for v, _ in migrations.MIGRATIONS]


def test_migration_003_installs_the_queue_hot_path_indexes(tmp_path):
    """claim/reclaim/adjudicator drains filter on status + order/cutoff
    columns; a status-only index leaves those as sequential scans once the
    table holds history. Partial indexes are the cheap fix."""
    engine = create_engine(f"sqlite:///{tmp_path}/idx.db")
    store.metadata.create_all(engine)
    assert 3 in migrations.apply(engine)
    names = {idx["name"] for idx in inspect(engine).get_indexes("review_jobs")}
    assert "idx_review_jobs_pending_queue" in names
    assert "idx_review_jobs_running_stale" in names
    outcome_names = {idx["name"] for idx in inspect(engine).get_indexes("outcome_jobs")}
    assert "idx_outcome_jobs_pending_due" in outcome_names
