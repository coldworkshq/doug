from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DatabaseError, IntegrityError

from doug import migrations, store

APP_COLUMNS = {"github_repo_id", "installation_id", "head_sha", "source"}
ALL_VERSIONS = [v for v, _ in migrations.MIGRATIONS]

# Hand-built pre-001 verdicts stub for apply-from-older-schema tests.
# pr_number and tier are baseline columns migration 005's index predicate
# names; App-identity columns are absent (migration 001 adds those).
_OLDER_VERDICTS_DDL = (
    "CREATE TABLE verdicts ("
    "id INTEGER PRIMARY KEY, repo VARCHAR(200) NOT NULL, "
    "pr_number INTEGER NOT NULL DEFAULT 0, "
    "tier VARCHAR(20) NOT NULL DEFAULT 'deterministic')"
)

# Migration 005's dedupe deletes from these before creating the unique
# index. Production has them from create_all; hand-built older schemas need
# empty stubs so apply() does not fail on a missing table.
_OLDER_DEPENDENT_DDL = (
    "CREATE TABLE findings (id INTEGER PRIMARY KEY, verdict_id INTEGER)",
    "CREATE TABLE reads (id INTEGER PRIMARY KEY, verdict_id INTEGER)",
    "CREATE TABLE deviations (id INTEGER PRIMARY KEY, verdict_id INTEGER)",
)


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


OUTCOME_COLUMNS = {"github_repo_id", "installation_id", "window_days", "detail"}

M7_COLUMNS = {
    "outcomes": {"merge_commit_sha"},
    "outcome_jobs": {"started_at", "finished_at", "error", "claim_generation"},
    "reads": {"changed_files", "files_dropped"},
}


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
        conn.exec_driver_sql(_OLDER_VERDICTS_DDL)
        conn.exec_driver_sql(
            "CREATE TABLE outcomes (id INTEGER PRIMARY KEY, repo VARCHAR(200) NOT NULL, "
            "pr_number INTEGER NOT NULL DEFAULT 0)"
        )
        # Migration 003 indexes these; production gets the tables from
        # create_all before apply. The hand-built older schema needs stubs.
        conn.exec_driver_sql(
            "CREATE TABLE review_jobs ("
            "id INTEGER PRIMARY KEY, status VARCHAR(12), "
            "enqueued_at DATETIME, started_at DATETIME, verdict_id INTEGER)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE outcome_jobs ("
            "id INTEGER PRIMARY KEY, status VARCHAR(12), due_at DATETIME)"
        )
        for ddl in _OLDER_DEPENDENT_DDL:
            conn.exec_driver_sql(ddl)
        # Migration 6's target: the pre-Task-2 `installations` shape, with the
        # column it drops, so the DROP has real work to do here rather than
        # finding it already gone.
        conn.exec_driver_sql(
            "CREATE TABLE installations (id INTEGER PRIMARY KEY, "
            "installation_id BIGINT NOT NULL UNIQUE, account_login VARCHAR(200), "
            "account_type VARCHAR(20), state VARCHAR(20) NOT NULL, "
            "updated_at TIMESTAMP NOT NULL, token_hash TEXT)"
        )
        # Stub for installation_repos before the per-repo needs-you threshold column.
        conn.exec_driver_sql(
            "CREATE TABLE installation_repos ("
            "id INTEGER PRIMARY KEY, installation_id BIGINT NOT NULL, "
            "github_repo_id BIGINT NOT NULL, full_name VARCHAR(200) NOT NULL, "
            "state VARCHAR(20) NOT NULL, updated_at TIMESTAMP NOT NULL)"
        )
    assert migrations.apply(engine) == ALL_VERSIONS
    assert APP_COLUMNS <= _columns(engine, "verdicts")
    assert {"prompt_hash"} <= _columns(engine, "verdicts")
    assert OUTCOME_COLUMNS <= _columns(engine, "outcomes")
    assert "claim_generation" in _columns(engine, "review_jobs")
    assert "token_hash" not in _columns(engine, "installations")
    for table, columns in M7_COLUMNS.items():
        assert columns <= _columns(engine, table)
    for table, columns in M8_COLUMNS.items():
        assert columns <= _columns(engine, table)
    for table, columns in M9_COLUMNS.items():
        assert columns <= _columns(engine, table)
    for table, columns in M10_COLUMNS.items():
        assert columns <= _columns(engine, table)
    for table, columns in M11_COLUMNS.items():
        assert columns <= _columns(engine, table)


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

    assert migrations.apply(engine) == ALL_VERSIONS
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == ALL_VERSIONS


def test_apply_reports_only_newly_applied_versions(tmp_path):
    """apply() runs on every engine creation, not once at deploy time, so a
    second call re-running a migration would raise on the duplicate column
    and take the process down at first ledger use."""
    engine = create_engine(f"sqlite:///{tmp_path}/twice.db")
    store.metadata.create_all(engine)
    assert migrations.apply(engine) == ALL_VERSIONS
    assert migrations.apply(engine) == []


def test_unapplied_migrations_uses_exact_membership_not_contiguous_versions():
    plan = [
        (1, ("one",)),
        (2, ("two",)),
        (3, ("three",)),
        (4, ("four",)),
        (5, ("five",)),
        (6, ("six",)),
        (7, ("seven",)),
        (8, ("eight",)),
        (10, ("ten",)),
        (9, ("nine",)),
    ]
    applied = {1, 2, 3, 4, 5, 6, 7, 8, 10}

    assert migrations.unapplied_migrations(plan, applied) == [(9, ("nine",))]


def test_apply_fills_version_9_gap_after_version_10_was_recorded(tmp_path):
    """Production may already carry migration 10 because main reserved 9 for
    this branch. apply() must use exact ledger membership, not max(version),
    so the reserved migration still alters the older installations table and
    records 9 after 10 exists."""
    engine = create_engine(f"sqlite:///{tmp_path}/gap-after-10.db")
    migrations.schema_migrations.create(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE installations (id INTEGER PRIMARY KEY, "
            "installation_id BIGINT NOT NULL UNIQUE, account_login VARCHAR(200), "
            "account_type VARCHAR(20), state VARCHAR(20) NOT NULL, "
            "updated_at TIMESTAMP NOT NULL)"
        )
        # Stub for installation_repos before the per-repo needs-you threshold column.
        conn.exec_driver_sql(
            "CREATE TABLE installation_repos ("
            "id INTEGER PRIMARY KEY, installation_id BIGINT NOT NULL, "
            "github_repo_id BIGINT NOT NULL, full_name VARCHAR(200) NOT NULL, "
            "state VARCHAR(20) NOT NULL, updated_at TIMESTAMP NOT NULL)"
        )
        conn.execute(
            migrations.schema_migrations.insert(),
            [
                {"version": version, "applied_at": datetime.now(UTC)}
                for version in [1, 2, 3, 4, 5, 6, 7, 8, 10]
            ],
        )

    assert migrations.apply(engine) == [9, 11, 12]
    assert M9_COLUMNS["installations"] <= _columns(engine, "installations")
    assert M11_COLUMNS["installation_repos"] <= _columns(engine, "installation_repos")
    indexes = {index["name"]: index for index in inspect(engine).get_indexes("installations")}
    assert indexes["ix_installations_workos_org_id"].get("unique")
    with engine.connect() as conn:
        versions = {
            row[0] for row in conn.execute(select(migrations.schema_migrations.c.version))
        }
    assert versions == set(ALL_VERSIONS)


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


M8_COLUMNS = {
    "verdicts": {"diff_budget", "read_order"},
    "outcome_jobs": {"merged_head_sha"},
}

M9_COLUMNS = {
    "installations": {"workos_org_id", "installed_by_github_user_id"},
}
M10_COLUMNS = {"review_jobs": {"base_sha"}}

M11_COLUMNS = {"installation_repos": {"needs_you_threshold"}}

M12_COLUMNS = {
    "installation_repos": {"pr_comment"},
    "installations": {"pr_comment_denied_at"},
}


def test_migration_008_declares_the_same_columns_as_their_tables(tmp_path):
    """Same drift guard migrations 002 and 007 carry: a metadata-only column
    passes on a fresh database and is absent from Cloud SQL."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl8.db")
    store.metadata.create_all(engine)
    assert _statements_by_table(dict(migrations.MIGRATIONS)[8]) == M8_COLUMNS
    for table, columns in M8_COLUMNS.items():
        assert columns <= _columns(engine, table)


def test_migration_009_declares_the_same_columns_as_their_tables(tmp_path):
    """Same drift guard as migrations 002/007/008: a metadata-only column
    passes on a fresh database and is absent from Cloud SQL."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl9.db")
    store.metadata.create_all(engine)
    assert _statements_by_table(dict(migrations.MIGRATIONS)[9]) == M9_COLUMNS
    for table, columns in M9_COLUMNS.items():
        assert columns <= _columns(engine, table)


def test_migration_009_installs_a_unique_index_on_workos_org_id(tmp_path):
    """The bind flow (Tasks 4-8) resolves a session's tenant by this column;
    without a real unique index a session could resolve to either of two
    installations that happen to share an org."""
    engine = create_engine(f"sqlite:///{tmp_path}/workos-idx.db")
    store.metadata.create_all(engine)
    assert 9 in migrations.apply(engine)
    indexes = inspect(engine).get_indexes("installations")
    by_name = {idx["name"]: idx for idx in indexes}
    assert "ix_installations_workos_org_id" in by_name
    assert by_name["ix_installations_workos_org_id"].get("unique")


def test_workos_org_id_unique_constraint_is_enforced_on_a_fresh_database(tmp_path):
    """Column(unique=True) is the DDL a fresh database gets from
    store.metadata. It must reject a duplicate exactly like the migrated
    path's CREATE UNIQUE INDEX does below — the two DDL routes the module
    docstring describes must produce equivalent constraints, not merely
    equivalent-looking columns."""
    engine = create_engine(f"sqlite:///{tmp_path}/fresh-unique.db")
    store.metadata.create_all(engine)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": 1,
                "state": "active",
                "updated_at": now,
                "workos_org_id": "org_123",
            },
        )
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            store.installations.insert(),
            {
                "installation_id": 2,
                "state": "active",
                "updated_at": now,
                "workos_org_id": "org_123",
            },
        )


def test_workos_org_id_unique_index_is_enforced_on_a_migrated_database(tmp_path):
    """The other DDL route: an `installations` table from before this
    migration, upgraded by migration 9's own CREATE UNIQUE INDEX rather than
    the Table's Column(unique=True). Must reject a duplicate the same way
    the fresh-database path above does."""
    engine = create_engine(f"sqlite:///{tmp_path}/migrated-unique.db")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE installations (id INTEGER PRIMARY KEY, "
            "installation_id BIGINT NOT NULL UNIQUE, account_login VARCHAR(200), "
            "account_type VARCHAR(20), state VARCHAR(20) NOT NULL, "
            "updated_at TIMESTAMP NOT NULL)"
        )
    for statement in dict(migrations.MIGRATIONS)[9]:
        migrations._run(engine, statement)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO installations (installation_id, state, updated_at, workos_org_id) "
            f"VALUES (1, 'active', '{now.isoformat()}', 'org_123')"
        )
    with engine.begin() as conn, pytest.raises(DatabaseError):
        conn.exec_driver_sql(
            "INSERT INTO installations (installation_id, state, updated_at, workos_org_id) "
            f"VALUES (2, 'active', '{now.isoformat()}', 'org_123')"
        )


def test_migration_010_declares_the_same_columns_as_their_tables(tmp_path):
    """The event-time base must reach production through a migration, while
    remaining nullable for historical jobs whose base cannot be recovered."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl10.db")
    store.metadata.create_all(engine)

    assert _statements_by_table(dict(migrations.MIGRATIONS)[10]) == M10_COLUMNS
    column = store.review_jobs.c.base_sha
    assert column.type.length == 64
    assert column.nullable
    assert M10_COLUMNS["review_jobs"] <= _columns(engine, "review_jobs")


def test_migration_011_declares_the_same_columns_as_their_tables(tmp_path):
    """Two homes (migrations.py docstring): the Table gets a fresh database
    the column; the migration gets production the same column. A drift
    between them is a green suite and a broken production write."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl11.db")
    store.metadata.create_all(engine)
    assert _statements_by_table(dict(migrations.MIGRATIONS)[11]) == M11_COLUMNS
    for table, columns in M11_COLUMNS.items():
        assert columns <= _columns(engine, table)


def test_migration_012_declares_the_same_columns_as_their_tables(tmp_path):
    """Two homes: the Table gets a fresh database the columns; the migration
    gets production the same columns. pr_comments is a NEW table and so is
    create_all()'s alone — asserted present on a fresh schema below."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl12.db")
    store.metadata.create_all(engine)
    assert _statements_by_table(dict(migrations.MIGRATIONS)[12]) == M12_COLUMNS
    for table, columns in M12_COLUMNS.items():
        assert columns <= _columns(engine, table)
    assert "pr_comments" in inspect(engine).get_table_names()


def test_migration_008_backfills_reader_prompt_hash(tmp_path):
    """The one prompt era is recorded, and only on reader rows."""
    engine = create_engine(f"sqlite:///{tmp_path}/m8.db")
    store.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO verdicts (repo, pr_number, tier, score, band, "
            "threshold, scored_at, prompt_hash) VALUES "
            "('o/r', 1, 'reader', 0.5, 'flagged', 0.3, '2026-08-01', NULL),"
            "('o/r', 2, 'deterministic', 0.5, 'flagged', 0.3, '2026-08-01', NULL),"
            "('o/r', 3, 'reader', 0.5, 'flagged', 0.3, '2026-08-01', 'already')"
        )
    migrations.apply(engine)
    with engine.begin() as conn:
        rows = dict(
            conn.exec_driver_sql("SELECT pr_number, prompt_hash FROM verdicts").all()
        )
    assert rows[1] == "8bd26c677a0e087a0b8c14933203cc85e15b65e32b432c10a3ae78009a951cdf"
    assert rows[2] is None, "deterministic verdicts have no prompt"
    assert rows[3] == "already", "an existing hash is never overwritten"


def test_migration_008_backfill_is_idempotent(tmp_path):
    """A second REAL run of migration 8's UPDATE — not a second bare
    apply() — must not disturb a prompt_hash already present.

    apply()'s `done` ledger (migrations.py:316) skips a migration entirely
    once its version is recorded, so calling apply() twice in a row never
    re-executes migration 8's statements the second time; it only proves the
    first run worked. Deleting the schema_migrations row for version 8
    between the two calls is what forces the UPDATE to run again for real.
    Without that, this test cannot fail no matter what the UPDATE's WHERE
    clause says — confirmed by removing `AND prompt_hash IS NULL` from the
    migration and watching this test still pass before this fix.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/m8b.db")
    store.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO verdicts (repo, pr_number, tier, score, band, "
            "threshold, scored_at, prompt_hash) VALUES "
            "('o/r', 1, 'reader', 0.5, 'flagged', 0.3, '2026-08-01', NULL)"
        )
    migrations.apply(engine)
    with engine.begin() as conn:
        # Stand in for a hash set by anything other than this backfill
        # between the two runs (a hand correction, a verdict scored under a
        # later prompt era). A genuinely idempotent rerun must leave it
        # alone; only the `AND prompt_hash IS NULL` guard makes that true.
        conn.exec_driver_sql(
            "UPDATE verdicts SET prompt_hash = 'do-not-touch' WHERE pr_number = 1"
        )
        conn.exec_driver_sql("DELETE FROM schema_migrations WHERE version = 8")
    migrations.apply(engine)
    with engine.begin() as conn:
        rows = dict(
            conn.exec_driver_sql("SELECT pr_number, prompt_hash FROM verdicts").all()
        )
        count = conn.exec_driver_sql(
            "SELECT count(*) FROM verdicts WHERE prompt_hash IS NULL"
        ).scalar()
    assert count == 0
    assert rows[1] == "do-not-touch", "a rerun must never overwrite an existing hash"


def test_migration_007_declares_the_same_columns_as_their_tables(tmp_path):
    """The adjudicator writer, its claim lease, and persisted coverage all
    cross existing production tables. A metadata-only column would pass on a
    fresh database and be absent from Cloud SQL."""
    engine = create_engine(f"sqlite:///{tmp_path}/decl7.db")
    store.metadata.create_all(engine)

    assert _statements_by_table(dict(migrations.MIGRATIONS)[7]) == M7_COLUMNS
    for table, columns in M7_COLUMNS.items():
        assert columns <= _columns(engine, table)


def test_migration_007_lease_timestamps_match_postgres_metadata_types():
    """Lease comparisons use aware UTC instants. Production reaches these
    columns through ALTER while fresh databases use metadata; both paths must
    retain the same timezone semantics or reclaim timing depends on origin."""
    statements = dict(migrations.MIGRATIONS)[7]
    for column in ("started_at", "finished_at"):
        ddl = next(stmt for stmt in statements if f"ADD COLUMN {column}" in stmt)
        assert ddl.endswith("TIMESTAMP WITH TIME ZONE")
        assert store.outcome_jobs.c[column].type.compile(
            dialect=postgresql.dialect()
        ) == "TIMESTAMP WITH TIME ZONE"


def test_migration_007_enforces_one_outcome_per_job_identity(tmp_path):
    """A redelivered or reclaimed job must not cast two votes. Historical
    rows have no merge SHA and stay outside the partial index."""
    engine = create_engine(f"sqlite:///{tmp_path}/outcome-identity.db")
    store.metadata.create_all(engine)
    migrations.apply(engine)

    names = {idx["name"] for idx in inspect(engine).get_indexes("outcomes")}
    assert "uq_outcomes_job_identity" in names

    row = {
        "repo": "drewjst/doug",
        "pr_number": 62,
        "kind": "clean",
        "observed_at": datetime.now(UTC),
        "source": "git-labels",
        "github_repo_id": 1,
        "installation_id": 2,
        "window_days": 14,
        "merge_commit_sha": "a" * 40,
    }
    with engine.begin() as conn:
        conn.execute(store.outcomes.insert(), row)
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(store.outcomes.insert(), row)


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
    assert versions == ALL_VERSIONS


def test_get_engine_applies_migrations(tmp_path, monkeypatch):
    """The hook, not the runner: a migration nobody calls is a comment."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/hooked.db")
    engine = store._get_engine()
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == ALL_VERSIONS


def test_migration_003_installs_the_queue_hot_path_indexes(tmp_path):
    """claim/reclaim/adjudicator drains filter on status + order/cutoff
    columns; a status-only index leaves those as sequential scans once the
    table holds history. Partial indexes are the cheap fix."""
    engine = create_engine(f"sqlite:///{tmp_path}/idx.db")
    store.metadata.create_all(engine)
    applied = migrations.apply(engine)
    assert 3 in applied and 4 in applied
    names = {idx["name"] for idx in inspect(engine).get_indexes("review_jobs")}
    assert "idx_review_jobs_pending_queue" in names
    assert "idx_review_jobs_running_stale" in names
    outcome_names = {idx["name"] for idx in inspect(engine).get_indexes("outcome_jobs")}
    assert "idx_outcome_jobs_pending_due" in outcome_names


def test_migration_004_adds_claim_generation(tmp_path):
    """Integer claim fence token — must exist on production via migration,
    not only on fresh create_all tables."""
    engine = create_engine(f"sqlite:///{tmp_path}/gen.db")
    with engine.begin() as conn:
        # Minimal pre-004 shape: earlier migrations need these tables present.
        conn.exec_driver_sql(_OLDER_VERDICTS_DDL)
        conn.exec_driver_sql(
            "CREATE TABLE outcomes (id INTEGER PRIMARY KEY, repo VARCHAR(200) NOT NULL)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE review_jobs ("
            "id INTEGER PRIMARY KEY, status VARCHAR(12), "
            "enqueued_at DATETIME, started_at DATETIME, verdict_id INTEGER)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE outcome_jobs ("
            "id INTEGER PRIMARY KEY, status VARCHAR(12), due_at DATETIME)"
        )
        for ddl in _OLDER_DEPENDENT_DDL:
            conn.exec_driver_sql(ddl)
        # Migration 6 also runs against this engine (apply() runs every
        # pending migration in order); give it a real `installations` table
        # in the legacy shape so it has actual work to do.
        conn.exec_driver_sql(
            "CREATE TABLE installations (id INTEGER PRIMARY KEY, "
            "installation_id BIGINT NOT NULL UNIQUE, account_login VARCHAR(200), "
            "account_type VARCHAR(20), state VARCHAR(20) NOT NULL, "
            "updated_at TIMESTAMP NOT NULL, token_hash TEXT)"
        )
        # Stub for installation_repos before the per-repo needs-you threshold column.
        conn.exec_driver_sql(
            "CREATE TABLE installation_repos ("
            "id INTEGER PRIMARY KEY, installation_id BIGINT NOT NULL, "
            "github_repo_id BIGINT NOT NULL, full_name VARCHAR(200) NOT NULL, "
            "state VARCHAR(20) NOT NULL, updated_at TIMESTAMP NOT NULL)"
        )
    assert 4 in migrations.apply(engine)
    assert "claim_generation" in _columns(engine, "review_jobs")


def test_migration_005_names_every_foreign_key_to_verdicts():
    """Destructive dedupe must clear or re-point every dependent. outcomes
    joins by identity columns, not verdict_id — Doug's 'unsafe-migration'
    finding named it as an example FK and was wrong; this pin is the check
    that keeps the closed set honest when a real FK is added later.
    """
    fks = {
        (fk.parent.table.name, fk.parent.name)
        for table in store.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "verdicts"
    }
    assert fks == {
        ("findings", "verdict_id"),
        ("reads", "verdict_id"),
        ("deviations", "verdict_id"),
        ("review_jobs", "verdict_id"),
    }


def test_app_identity_collision_markers_match_sqlite_and_not_other_verdicts_uniques():
    """Measured sqlite wording for uq_verdicts_app_identity, plus the
    postgres constraint name. A bare 'verdicts.' substring would also match
    a future unique on any other verdicts column — refuse that."""
    from sqlalchemy.exc import IntegrityError

    from doug.store import _is_app_identity_collision

    class _Orig(Exception):
        pass

    def _exc(msg: str) -> IntegrityError:
        return IntegrityError("stmt", {}, _Orig(msg))

    assert _is_app_identity_collision(
        _exc(
            "UNIQUE constraint failed: verdicts.installation_id, "
            "verdicts.github_repo_id, verdicts.pr_number, verdicts.head_sha"
        )
    )
    assert _is_app_identity_collision(
        _exc('duplicate key value violates unique constraint "uq_verdicts_app_identity"')
    )
    assert not _is_app_identity_collision(
        _exc("UNIQUE constraint failed: verdicts.repo, verdicts.pr_number")
    )


def test_migration_005_installs_app_identity_unique_index(tmp_path):
    """Ledger integrity for the published denominator: two App-path workers
    that both pass the advisory find_verdict_by_identity pre-read must not
    both insert. The index is the constraint; the pre-read stays the cheap
    path. Partial — pre-App/CI rows (NULL installation_id) and external
    grader rows (tier='external') share the same four columns and must keep
    coexisting with Doug's scored row for that SHA.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/uq.db")
    store.metadata.create_all(engine)
    assert 5 in migrations.apply(engine)
    indexes = inspect(engine).get_indexes("verdicts")
    by_name = {idx["name"]: idx for idx in indexes}
    assert "uq_verdicts_app_identity" in by_name
    assert by_name["uq_verdicts_app_identity"].get("unique")
    # Unique + partial: the migration is the only place this shape lives
    # (not on the Table — create_all would diverge from production).
    stmt = dict(migrations.MIGRATIONS)[5][-1]
    assert "UNIQUE" in stmt.upper()
    assert "installation_id IS NOT NULL" in stmt
    assert "tier <> 'external'" in stmt


def test_migration_005_dedupes_existing_app_identity_rows_before_indexing(tmp_path):
    """CREATE UNIQUE INDEX would fail (and brick apply-on-boot) if any
    App-identity duplicates already exist. The migration must collapse them
    to the lowest id first, keep dependents pointed at the survivor, and
    leave external / CI rows alone.
    """
    from datetime import UTC, datetime

    engine = create_engine(f"sqlite:///{tmp_path}/dedupe.db")
    store.metadata.create_all(engine)
    migrations.schema_migrations.create(engine, checkfirst=True)
    # Apply 1–4 only, then seed duplicates, then let 5 land.
    for version, statements in migrations.MIGRATIONS:
        if version >= 5:
            break
        for statement in statements:
            migrations._run(engine, statement)
        with engine.begin() as conn:
            conn.execute(
                migrations.schema_migrations.insert(),
                {"version": version, "applied_at": datetime.now(UTC)},
            )
    sha = "a" * 40
    with engine.begin() as conn:
        for _ in range(2):
            conn.exec_driver_sql(
                "INSERT INTO verdicts ("
                "repo, pr_number, scored_at, tier, score, band, threshold, "
                "installation_id, github_repo_id, head_sha, source"
                ") VALUES ("
                f"'o/r', 7, '2026-08-01', 'reader', 0.5, 'flagged', 0.3, "
                f"10, 20, '{sha}', 'app')"
            )
        conn.exec_driver_sql(
            "INSERT INTO verdicts ("
            "repo, pr_number, scored_at, tier, score, band, threshold, "
            "installation_id, github_repo_id, head_sha, source"
            ") VALUES ("
            f"'o/r', 7, '2026-08-01', 'external', 0.0, 'cleared', 0.0, "
            f"10, 20, '{sha}', 'review:alice')"
        )
        for _ in range(2):
            conn.exec_driver_sql(
                "INSERT INTO verdicts ("
                "repo, pr_number, scored_at, tier, score, band, threshold, "
                "head_sha, source"
                ") VALUES ("
                f"'o/r', 7, '2026-08-01', 'reader', 0.5, 'flagged', 0.3, "
                f"'{sha}', 'ci')"
            )
        ids = [
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT id FROM verdicts WHERE installation_id = 10 "
                "AND tier = 'reader' ORDER BY id"
            )
        ]
        keeper, duplicate = ids[0], ids[1]
        conn.exec_driver_sql(
            f"INSERT INTO findings (verdict_id, rule, label, weight) "
            f"VALUES ({duplicate}, 'r', 'l', 0.0)"
        )
        conn.exec_driver_sql(
            f"INSERT INTO review_jobs ("
            f"installation_id, github_repo_id, repo_full_name, pr_number, "
            f"head_sha, status, attempts, claim_generation, enqueued_at, verdict_id"
            f") VALUES ("
            f"10, 20, 'o/r', 7, '{sha}', 'done', 1, 1, '2026-08-01', {duplicate})"
        )

    # store.metadata.create_all() above already built the current table shapes,
    # so migrations 6 through 12 all find their ALTER/CREATE work satisfied
    # and still record their versions alongside migration 5.
    assert migrations.apply(engine) == [5, 6, 7, 8, 9, 10, 11, 12]
    with engine.connect() as conn:
        app_ids = [
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT id FROM verdicts WHERE installation_id = 10 "
                "AND tier = 'reader' ORDER BY id"
            )
        ]
        assert app_ids == [keeper]
        assert (
            conn.exec_driver_sql(
                "SELECT COUNT(*) FROM verdicts WHERE tier = 'external'"
            ).scalar()
            == 1
        )
        assert (
            conn.exec_driver_sql(
                "SELECT COUNT(*) FROM verdicts WHERE installation_id IS NULL"
            ).scalar()
            == 2
        )
        assert (
            conn.exec_driver_sql(
                f"SELECT COUNT(*) FROM findings WHERE verdict_id = {duplicate}"
            ).scalar()
            == 0
        )
        assert (
            conn.exec_driver_sql("SELECT verdict_id FROM review_jobs").scalar()
            == keeper
        )
        names = {idx["name"] for idx in inspect(engine).get_indexes("verdicts")}
        assert "uq_verdicts_app_identity" in names


def test_satisfied_never_swallows_a_missing_table():
    """Postgres phrases missing-column and missing-TABLE errors with the
    same tail. The first is 'work already done'; the second is the PR #48
    crash-loop and must raise."""
    assert migrations._satisfied('column "token_hash" of relation "installations" does not exist')
    assert migrations._satisfied("no such column: token_hash")
    assert not migrations._satisfied('relation "installations" does not exist')
    assert not migrations._satisfied("no such table: installations")


def test_satisfied_against_the_bare_driver_message_ignores_the_sql_echo():
    """SQLAlchemy's DatabaseError str() appends the offending statement
    ('...does not exist\\n\\n[SQL: ALTER TABLE installations DROP COLUMN
    token_hash]'), so 'column' shows up for EVERY ALTER regardless of what
    actually went missing — _satisfied has no way to tell the echo from a
    real mention of 'column' in the driver's own message. That is exactly
    why _run evaluates e.orig (the bare driver exception, without the
    echo) rather than str(e): evaluated against only the driver part of
    these two realistic shapes, the missing-table string must not satisfy
    and the missing-column string must.
    """
    missing_table_full = (
        '(psycopg2.errors.UndefinedTable) relation "installations" does not exist\n\n'
        "[SQL: ALTER TABLE installations DROP COLUMN token_hash]"
    )
    missing_column_full = (
        '(psycopg2.errors.UndefinedColumn) column "token_hash" of relation '
        '"installations" does not exist\n\n'
        "[SQL: ALTER TABLE installations DROP COLUMN token_hash]"
    )
    driver_part_table = missing_table_full.split("\n\n[SQL:")[0]
    driver_part_column = missing_column_full.split("\n\n[SQL:")[0]
    assert not migrations._satisfied(driver_part_table)
    assert migrations._satisfied(driver_part_column)
    # The trap itself, made concrete: evaluated against the FULL string
    # (what str(e) gives you, echo included) the missing-table case wrongly
    # satisfies — this is what _run must never hand to _satisfied.
    assert migrations._satisfied(missing_table_full)


def test_run_evaluates_the_driver_message_not_the_sql_echoing_str():
    """_run-level proof, not just _satisfied: SQLAlchemy's own DatabaseError
    constructor produces the SQL-echoing str() (verified — it appends '[SQL:
    ...]' to the driver message), so a stubbed DatabaseError built the real
    way already carries the trap. If _run evaluated str(e) instead of
    str(e.orig), the SQL echo's 'column' would satisfy the missing-TABLE
    case too, and a genuinely missing table would be swallowed instead of
    raising — the PR #48 crash-loop, reintroduced silently."""

    class _Orig(Exception):
        pass

    statement = "ALTER TABLE installations DROP COLUMN token_hash"
    missing_table_orig = _Orig('relation "installations" does not exist')
    missing_column_orig = _Orig(
        'column "token_hash" of relation "installations" does not exist'
    )

    class _FakeConn:
        def __init__(self, orig):
            self._orig = orig

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def exec_driver_sql(self, stmt):
            raise DatabaseError(stmt, {}, self._orig)

    class _FakeEngine:
        def __init__(self, orig):
            self._orig = orig

        def begin(self):
            return _FakeConn(self._orig)

    with pytest.raises(DatabaseError):
        migrations._run(_FakeEngine(missing_table_orig), statement)
    migrations._run(_FakeEngine(missing_column_orig), statement)  # must not raise
