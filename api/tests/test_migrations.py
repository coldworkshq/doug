from sqlalchemy import create_engine, inspect, select

from doug import migrations, store

APP_COLUMNS = {"github_repo_id", "installation_id", "head_sha", "source"}


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_apply_adds_the_columns_to_a_database_built_by_an_older_schema(tmp_path):
    """The case create_all() cannot handle, and the only reason this module
    exists. Production's `verdicts` was created before the App columns and
    create_all() adds missing tables, never missing columns.

    The table is built by hand rather than from store.metadata on purpose: a
    test that starts from today's metadata can only exercise the path that was
    never broken.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE verdicts (id INTEGER PRIMARY KEY, repo VARCHAR(200) NOT NULL)"
        )
    assert migrations.apply(engine) == [1]
    assert APP_COLUMNS <= _columns(engine, "verdicts")


def test_apply_on_a_freshly_created_schema_records_without_erroring(tmp_path):
    """The same divergence from the other side. A fresh database already has
    the App columns from create_all(), so migration 001 has nothing to do —
    and if "nothing to do" raised, every test run and every new deployment
    would die inside _get_engine on a statement that is only meaningful
    against the older production table.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/fresh.db")
    store.metadata.create_all(engine)
    assert APP_COLUMNS <= _columns(engine, "verdicts")

    assert migrations.apply(engine) == [1]
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == [1]


def test_apply_reports_only_newly_applied_versions(tmp_path):
    """apply() runs on every engine creation, not once at deploy time, so a
    second call re-running migration 001 would raise on the duplicate column
    and take the process down at first ledger use."""
    engine = create_engine(f"sqlite:///{tmp_path}/twice.db")
    store.metadata.create_all(engine)
    assert migrations.apply(engine) == [1]
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


def test_get_engine_applies_migrations(tmp_path, monkeypatch):
    """The hook, not the runner: a migration nobody calls is a comment."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/hooked.db")
    engine = store._get_engine()
    with engine.connect() as conn:
        versions = [r[0] for r in conn.execute(select(migrations.schema_migrations.c.version))]
    assert versions == [v for v, _ in migrations.MIGRATIONS]
