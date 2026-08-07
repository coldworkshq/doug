# M3 60-day outcome backfill implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Atomically start 14- and 60-day clocks for every future merge, safely
create the missing historical 60-day siblings, lock the publication
pre-registration, and verify the production drain.

**Architecture:** The webhook delegates one merge identity to a transactional
multi-window store writer. A focused `doug.outcome_backfill` module owns read-only
analysis, the single `INSERT ... SELECT`, manifest creation, invariants, and guarded
rollback; a thin script owns CLI and GCP connection concerns. The implementation PR
ships code and an executable runbook, production is changed only after merge, and a
second documentation PR records observed rollout receipts.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x, SQLite tests, PostgreSQL 18 production,
pytest, Bash/gcloud, Cloud SQL Auth Proxy, Cloud Run Jobs, Cloud Scheduler.

## Global constraints

- Future merges create windows `(14, 60)` in one database transaction.
- The conflict target is exactly `(installation_id, github_repo_id, pr_number,
  merge_commit_sha, window_days)`; do not suppress other integrity errors.
- `due_at` is always derived from stored `merged_at`, never the wall clock.
- The catch-up population is every 14-day job with a matching `installations` row,
  including active, suspended, and deleted installations, that lacks a 60-day
  sibling.
- CLI, orphaned, and research/sentinel-shaped rows remain excluded.
- Catch-up is one idempotent `INSERT ... SELECT`; it never mutates 14-day jobs,
  verdicts, or existing outcomes.
- Apply requires a matching dry-run count and a new absolute manifest path.
- The manifest is flushed before database commit; manifest failure rolls back the
  transaction.
- Rollback is allowed only for exact manifest rows that remain untouched pending
  jobs.
- Pause and verify the Scheduler before apply; resume and verify it after rollback
  or the observed manual drain.
- Never use `api/scripts/backfill_ledger.py` for this operation.
- Do not claim production completion from local tests or predicted output.
- Every repository change goes through a PR. The implementation PR and the
  production-closure documentation PR are separate because rollout receipts do not
  exist before merge.

## File responsibility map

- `api/doug/store.py` — atomic merge-clock insertion and the compatibility
  single-window wrapper.
- `api/doug/api.py` — webhook calls the atomic `(14, 60)` writer.
- `api/doug/outcome_backfill.py` — typed reports, eligibility queries, invariant
  checks, one transactional insert-select, manifest, and guarded rollback.
- `api/scripts/backfill_outcome_jobs.py` — argparse, GCP database URL resolution,
  JSON output, and exit codes only.
- `api/tests/test_store.py` and `api/tests/test_api.py` — permanent-writer contract.
- `api/tests/test_outcome_backfill.py` — analysis, apply, invariants, manifest,
  rollback, and due-row behavior.
- `api/tests/test_outcome_backfill_script.py` — supported script invocation and CLI
  mode validation.
- `api/deploy/gcp.sh` and `api/tests/test_deploy_gcp.py` — refuse to deploy the Job
  from a mutable pre-registration.
- `docs/design/outcome-loop/60-day-backfill-runbook.md` — exact production commands,
  audits, rollback boundary, and durable receipts.
- `docs/design/outcome-loop/publication-preregistration.md` — locked v8 mechanism
  and structural population predicate.
- `docs/design/outcome-loop/design-lock.md`, `ROADMAP.md`, `architecture.md`,
  `docs/REVIEWING.md`, and `HANDOFF.md` — only claims changed by this slice.

---

### Task 1: Make the live merge writer atomic across both windows

**Files:**

- Modify: `api/doug/store.py:793-852`
- Modify: `api/doug/api.py:1033-1080`
- Modify: `api/tests/test_store.py:836-924`
- Modify: `api/tests/test_api.py:862-908`

**Interfaces:**

- Consumes: the existing `outcome_jobs` unique constraint and webhook merge facts.
- Produces:

```python
def enqueue_outcome_jobs(
    installation_id: int,
    github_repo_id: int,
    pr_number: int,
    merge_commit_sha: str,
    merged_at: datetime,
    base_ref: str,
    *,
    window_days: tuple[int, ...] = (14, 60),
) -> dict[int, int]:
    """Return {window_days: inserted_id}; conflicts are absent from the mapping."""
```

`enqueue_outcome_job` retains its current positional arguments and
`window_days=14` keyword, returning `int | None` as a compatibility wrapper around
the plural operation.

- [ ] **Step 1: Update webhook tests to require both clocks**

Replace the single-row assertions with behavioral assertions like:

```python
jobs = sorted(_table(tmp_path, store.outcome_jobs), key=lambda row: row["window_days"])
assert [job["window_days"] for job in jobs] == [14, 60]
assert {job["installation_id"] for job in jobs} == {150424894}
assert {job["github_repo_id"] for job in jobs} == {987}
assert {job["pr_number"] for job in jobs} == {7}
assert {job["merge_commit_sha"] for job in jobs} == {"c" * 40}
assert {job["base_ref"] for job in jobs} == {"main"}
assert [_utc(job["due_at"]) for job in jobs] == [
    datetime(2020, 3, 15, 12, 0, tzinfo=UTC),
    datetime(2020, 4, 30, 12, 0, tzinfo=UTC),
]
assert all(job["status"] == "pending" for job in jobs)
```

Keep the no-read assertions. Change redelivery to assert exactly two total jobs,
not one. Add a webhook-level healing test: initialize the hook environment, insert
only the payload's 14-day identity, deliver the same `closed` merge, and assert the
ledger contains exactly `[14, 60]`. This proves the production caller uses the
plural operation rather than preserving a legacy gap.

- [ ] **Step 2: Add store tests for healing and transaction atomicity**

Add a plural-writer test that pre-seeds only the 14-day row, calls
`enqueue_outcome_jobs`, and asserts the returned mapping contains only `60` while
the database contains `[14, 60]`.

Add a real SQLite trigger so the second window fails inside the database:

```python
with engine.begin() as conn:
    conn.exec_driver_sql(
        """
        CREATE TRIGGER reject_sixty_day_job
        BEFORE INSERT ON outcome_jobs
        WHEN NEW.window_days = 60
        BEGIN
          SELECT RAISE(ABORT, 'reject 60-day row');
        END
        """
    )

with pytest.raises(IntegrityError, match="reject 60-day row"):
    store.enqueue_outcome_jobs(
        INSTALL, REPO_ID, 42, "a" * 40, MERGED, "main"
    )

with engine.connect() as conn:
    assert conn.execute(select(store.outcome_jobs)).all() == []
```

This test must fail if the implementation calls two independently committing
single-row helpers.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
cd api
uv run pytest tests/test_store.py -k 'enqueue_outcome' -q
uv run pytest tests/test_api.py \
  -k 'outcome_clock or outcome_window or redelivered_merge' -q
```

Expected: failures because the webhook writes only 14 days and
`enqueue_outcome_jobs` does not exist.

- [ ] **Step 4: Implement the dialect-specific targeted insert**

Import the SQLite and PostgreSQL insert constructors:

```python
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
```

Use the connection dialect to build a multi-value statement and target only the
published identity:

```python
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
```

Build both row dictionaries from one `created_at = datetime.now(UTC)`, execute one
statement inside one `engine.begin()`, add `.returning(id, window_days)`, and return
the inserted mapping. Do not retain the old broad `IntegrityError` string matching;
the targeted database conflict clause now owns only the known dedupe case.

Implement the compatibility wrapper with:

```python
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
```

Change `_record_merge` to call `store.enqueue_outcome_jobs` with its six parsed
merge arguments and the default windows.

- [ ] **Step 5: Run focused and neighboring tests and verify GREEN**

Run:

```bash
cd api
uv run pytest tests/test_store.py -k 'outcome_job' -q
uv run pytest tests/test_api.py \
  -k 'outcome_clock or outcome_window or redelivered_merge or closed_but_unmerged' -q
uv run pytest tests/test_outcome_queue.py -q
uv run ruff check doug/store.py doug/api.py tests/test_store.py tests/test_api.py
```

Expected: all selected tests pass; ruff reports no errors.

- [ ] **Step 6: Commit the permanent writer**

```bash
git add api/doug/store.py api/doug/api.py api/tests/test_store.py api/tests/test_api.py
git commit -m "feat: start both outcome clocks atomically"
```

---

### Task 2: Build the read-only backfill analysis

**Files:**

- Create: `api/doug/outcome_backfill.py`
- Create: `api/tests/test_outcome_backfill.py`

**Interfaces:**

- Consumes: `store.outcome_jobs`, `store.installations`, and a SQLAlchemy
  `Connection`.
- Produces:

```python
@dataclass(frozen=True)
class RepositoryCount:
    installation_id: int
    github_repo_id: int
    missing: int
    overdue: int


@dataclass(frozen=True)
class PairMismatch:
    job_14_id: int
    job_60_id: int
    fields: tuple[str, ...]


@dataclass(frozen=True)
class BackfillReport:
    eligible_14: int
    existing_60: int
    missing: int
    overdue: int
    orphan_60: int
    by_repository: tuple[RepositoryCount, ...]
    mismatches: tuple[PairMismatch, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible_14": self.eligible_14,
            "existing_60": self.existing_60,
            "missing": self.missing,
            "overdue": self.overdue,
            "orphan_60": self.orphan_60,
            "by_repository": [asdict(row) for row in self.by_repository],
            "mismatches": [asdict(row) for row in self.mismatches],
        }
```

`inspect(conn: Connection, *, now: datetime | None = None) -> BackfillReport` is
the only public read interface.

- [ ] **Step 1: Write fixtures for real, inactive, orphaned, and mismatched rows**

Create local helpers with this exact population:

- active installation: one old 14-day job with an existing correct 60-day sibling,
  plus one young 14-day-only job;
- suspended installation: one old 14-day-only job;
- deleted installation: one old 14-day-only job; and
- orphaned installation ID: one old 14-day-only job, with no `installations` row.

Use fixed UTC values:

```python
NOW = datetime(2026, 8, 7, 18, 0, tzinfo=UTC)
OLD_MERGE = NOW - timedelta(days=90)
YOUNG_MERGE = NOW - timedelta(days=20)
```

- [ ] **Step 2: Write the eligibility and overdue tests**

Assert the report includes all three registered installation states, excludes the
orphan, separates existing from missing, and marks only the 90-day source overdue:

```python
assert report.eligible_14 == 4
assert report.existing_60 == 1
assert report.missing == 3
assert report.overdue == 2
assert report.orphan_60 == 0
assert {row.installation_id for row in report.by_repository} == {
    ACTIVE_INSTALL,
    SUSPENDED_INSTALL,
    DELETED_INSTALL,
}
```

These fixtures make the exact assertions above true. Document why inactive history
remains in the denominator. Capture the full `outcome_jobs` rows before and after
`inspect` and assert equality, proving dry-run analysis cannot mutate state.

- [ ] **Step 3: Write the mismatch test**

Seed a matching identity at both windows but change the 60-day `base_ref` and
`due_at`. Assert:

```python
assert report.mismatches == (
    outcome_backfill.PairMismatch(job_14_id, job_60_id, ("base_ref", "due_at")),
)
```

The field order is fixed as `("merged_at", "base_ref", "due_at")` filtered to
fields that disagree.

- [ ] **Step 4: Run the new test module and verify RED**

```bash
cd api
uv run pytest tests/test_outcome_backfill.py -q
```

Expected: import failure because `doug.outcome_backfill` does not exist.

- [ ] **Step 5: Implement the structural queries**

Alias `outcome_jobs` as `job_14` and `job_60`. Define sibling equality with all
five unique-key columns and fixed window values. Define real installation
membership with `EXISTS`:

```python
real_installation = exists(
    select(1).where(
        store.installations.c.installation_id == job_14.c.installation_id
    )
)
```

Do not filter `installations.state`. Compute the report using executable SQL for
counts, 60-day rows without 14-day siblings, and repository grouping, then load
only existing pairs for mismatch comparison. Normalize SQLite's naive datetimes to
UTC before comparing.

When `now` is omitted, use `clock_timestamp()` on PostgreSQL and
`datetime.now(UTC)` on SQLite, matching `outcome_queue._db_now` semantics.

- [ ] **Step 6: Run tests and lint and verify GREEN**

```bash
cd api
uv run pytest tests/test_outcome_backfill.py -q
uv run ruff check doug/outcome_backfill.py tests/test_outcome_backfill.py
```

Expected: all tests pass; ruff reports no errors.

- [ ] **Step 7: Commit read-only analysis**

```bash
git add api/doug/outcome_backfill.py api/tests/test_outcome_backfill.py
git commit -m "feat: inspect missing 60-day outcome jobs"
```

---

### Task 3: Add transactional apply, manifest, invariants, and rollback

**Files:**

- Modify: `api/doug/outcome_backfill.py`
- Modify: `api/tests/test_outcome_backfill.py`
- Modify: `api/tests/test_outcome_queue.py:77-114`

**Interfaces:**

- Consumes: Task 2's `inspect()` and report types.
- Produces:

`BackfillInvariantError(RuntimeError)` is the failure type for a stale expected
count or any pre/post invariant violation.

`ApplyResult` is a frozen dataclass with `inserted: int`, `manifest_path: str`, and
`report: BackfillReport`. Its `to_dict() -> dict[str, object]` returns those three
fields, with `report` serialized through `BackfillReport.to_dict()`.

The public write interfaces are:

```text
apply(engine: Engine, *, expected_missing: int, manifest_path: Path,
      now: datetime | None = None) -> ApplyResult
verify_manifest(engine: Engine, *, manifest_path: Path, expected_count: int) -> int
rollback(engine: Engine, *, manifest_path: Path, expected_count: int) -> int
```

Manifest version 1 contains `created_at` and exact rows with `id`,
`installation_id`, `github_repo_id`, `pr_number`, `merge_commit_sha`, and
`window_days`.

- [ ] **Step 1: Write apply, idempotency, and stale-count tests**

Test that apply inserts only missing registered-installation siblings, preserves
all source fields, sets exact 60-day due dates, and returns the inserted count.
Assert every inserted row has untouched pending state.

Then run apply again with `expected_missing=0` and a second new manifest path;
assert `inserted == 0` and row counts do not change.

Call apply against three missing rows with `expected_missing=2`; assert
`BackfillInvariantError("expected 2 missing 60-day jobs; found 3")` and no new rows
or manifest.

Pass `Path("relative-manifest.json")` and assert `ValueError("manifest path must be
absolute")` before opening a database transaction.

- [ ] **Step 2: Write pre-existing mismatch and manifest-failure tests**

Seed one mismatched pair. Assert apply raises before insertion and does not create a
manifest.

Seed one registered-installation 60-day row without a 14-day sibling. Assert
`orphan_60 == 1` in inspection and apply raises before inserting any other missing
sibling.

Monkeypatch the private atomic manifest writer to raise `OSError("disk full")`.
Assert the exception escapes and the database still has only its original 14-day
rows. This proves the manifest write occurs before commit.

Also create the requested manifest path before apply and assert
`FileExistsError` before any database mutation.

- [ ] **Step 3: Write independent manifest verification and guarded rollback tests**

After a successful apply, call `verify_manifest` with the manifest and exact count;
assert it returns that count. Change one inserted row to `status="running"`,
`claim_generation=1`, and `started_at=NOW`; assert verification raises without
mutation. A wrong expected count also raises.

After a successful apply, call rollback with the manifest and exact count; assert
only manifest 60-day rows are deleted and 14-day sources remain.

In a second test, update one inserted row to `status="running"`,
`claim_generation=1`, and `started_at=NOW`. Assert rollback raises and deletes zero
rows, including the other untouched manifest rows.

Test a wrong `expected_count` similarly aborts without deletion.

- [ ] **Step 4: Write the immediate-due integration test**

Apply against one 90-day-old merge and one 20-day-old merge, then assert:

```python
assert outcome_queue.due_repositories() == [
    outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
]
batch = outcome_queue.claim_repository(
    outcome_queue.RepositoryKey(INSTALLATION_ID, REPO_ID)
)
assert [(job["pr_number"], job["window_days"]) for job in batch.jobs] == [
    (OLD_PR, 14),
    (OLD_PR, 60),
    (YOUNG_PR, 14),
]
```

Seed the old merge at `2026-05-09T18:00:00Z` and the young merge at
`2026-07-18T18:00:00Z`. Their due dates make the asserted order exactly old-14,
old-60, young-14; do not sort in the assertion.

Continue the same test through the real settlement boundary:

```python
adjudication = adjudicate(batch.jobs, {}, default_branch="main")
settled, refused = outcome_queue.settle_batch(
    batch,
    adjudication,
    repo_full_name="drewjst/doug",
    observed_at=NOW,
    prereg_hash="f" * 64,
)
assert (settled, refused) == (3, 0)
assert all(row["status"] == "done" for row in _jobs(engine))
assert len(_outcomes(engine)) == 3
```

For each completed job, assert exactly one outcome matches installation,
repository, PR, merge SHA, and window. This is the caller-level proof that mixed
14/60 batches preserve the published identity.

- [ ] **Step 5: Run the focused tests and verify RED**

```bash
cd api
uv run pytest tests/test_outcome_backfill.py tests/test_outcome_queue.py -q
```

Expected: failures because apply, manifest verification, rollback, and manifest
behavior do not exist.

- [ ] **Step 6: Implement one dialect-aware insert-select**

Build the selection from Task 2's missing-source predicate. For PostgreSQL use:

```python
due_at = job_14.c.merged_at + literal_column("INTERVAL '60 days'")
statement = postgresql_insert(store.outcome_jobs)
```

For SQLite use:

```python
due_at = func.datetime(job_14.c.merged_at, "+60 days")
statement = sqlite_insert(store.outcome_jobs)
```

Call `.from_select(_INSERT_COLUMNS, source_query)`, then targeted
`.on_conflict_do_nothing(index_elements=_OUTCOME_IDENTITY)`, then
`.returning(*_MANIFEST_COLUMNS)` for manifest identities. Add a compile-level test using
`postgresql.dialect()` that asserts the PostgreSQL statement contains the interval
and the five-column conflict target; SQLite remains the executed integration path.

- [ ] **Step 7: Implement the transaction and post-insert invariants**

Use `engine.connect()` plus an explicit transaction so the manifest can be flushed
before `transaction.commit()`:

```python
with engine.connect() as conn:
    transaction = conn.begin()
    try:
        before = inspect(conn, now=effective_now)
        _require_clean_before(before, expected_missing)
        inserted_rows = conn.execute(statement).mappings().all()
        after = inspect(conn, now=effective_now)
        _require_clean_after(conn, after, inserted_rows)
        _write_manifest_new(manifest_path, effective_now, inserted_rows)
        transaction.commit()
    except BaseException:
        if transaction.is_active:
            transaction.rollback()
        raise
```

`_require_clean_after` enforces zero missing siblings, zero mismatches,
`orphan_60 == 0`, exact 60-day due dates, and untouched state for every returned
inserted ID.

Reject a non-absolute path and an already-existing final path before connecting.
After the insert and invariants, open the final manifest itself with mode `"x"` so
a concurrent creator cannot be overwritten; write JSON, flush, and call
`os.fsync`. A write failure rolls back the database and may leave a visibly partial
manifest that cannot be mistaken for committed database state. A commit failure
may leave a complete manifest whose rows do not exist, which the independent audit
detects.

- [ ] **Step 8: Implement independent verification and all-or-nothing rollback**

Load and validate manifest version 1. `verify_manifest` opens a new connection,
selects every exact row, and requires both the expected count and untouched-state
predicate for all rows. Rollback repeats those checks inside its own write
transaction, then deletes by both ID and the complete unique identity. If any check
fails, raise before the delete.

- [ ] **Step 9: Run tests and lint and verify GREEN**

```bash
cd api
uv run pytest tests/test_outcome_backfill.py tests/test_outcome_queue.py -q
uv run ruff check doug/outcome_backfill.py tests/test_outcome_backfill.py
```

Expected: all tests pass; ruff reports no errors.

- [ ] **Step 10: Commit the transactional backfill core**

```bash
git add api/doug/outcome_backfill.py api/tests/test_outcome_backfill.py api/tests/test_outcome_queue.py
git commit -m "feat: backfill 60-day outcome jobs safely"
```

---

### Task 4: Add the operator CLI

**Files:**

- Create: `api/scripts/backfill_outcome_jobs.py`
- Create: `api/tests/test_outcome_backfill_script.py`

**Interfaces:**

- Consumes: `outcome_backfill.inspect`, `apply`, `verify_manifest`, `rollback`, and
  `store._get_engine()`.
- Produces: `main(argv: list[str] | None = None) -> int`.

Supported file execution is:

```bash
uv run python scripts/backfill_outcome_jobs.py --dry-run
```

The `scripts` directory is not converted into a package.

- [ ] **Step 1: Write CLI mode-validation tests**

Import the script using the repository's existing supported test pattern:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backfill_outcome_jobs
```

Test these parser contracts:

- exactly one of `--dry-run`, `--apply`, `--verify-manifest`, and `--rollback` is
  required;
- apply requires `--expect-missing` and `--manifest`;
- verification and rollback require `--expect-count` and `--manifest`;
- manifest paths must be absolute; and
- dry-run rejects apply/rollback-only arguments.

- [ ] **Step 2: Write CLI delegation and JSON-output tests**

Monkeypatch the four core functions and assert each mode passes the exact typed
arguments. For dry-run, assert sorted JSON equals `report.to_dict()`. For apply,
assert it prints `ApplyResult.to_dict()`. For verification and rollback, assert:

```json
{"manifest":"/tmp/doug-60-day-test.json","verified_untouched":3}
```

and:

```json
{"manifest":"/tmp/doug-60-day-test.json","rolled_back":3}
```

Test missing `DATABASE_URL` returns exit code 1 and prints
`DATABASE_URL not set` to stderr.

- [ ] **Step 3: Run the script tests and verify RED**

```bash
cd api
uv run pytest tests/test_outcome_backfill_script.py -q
```

Expected: import failure because the script does not exist.

- [ ] **Step 4: Implement the thin script**

Use `argparse`. When `--from-gcp doug-prod0` is present, retrieve
`doug-database-url` with `gcloud secrets versions access latest`, strip it, and
rewrite the Cloud SQL socket URL to `127.0.0.1:5433`, matching the proven
`backfill_ledger.py` convention. Do not start or stop the proxy from Python.

Keep database logic out of the script. Unexpected database and filesystem errors
escape with a traceback and non-zero process exit; they must not be rendered as a
successful JSON report.

- [ ] **Step 5: Verify supported invocation from two working directories**

With `DATABASE_URL` deliberately absent, run:

```bash
cd api
env -u DATABASE_URL uv run python scripts/backfill_outcome_jobs.py --dry-run
cd /tmp
env -u DATABASE_URL \
  /Users/andrew/Projects/doughq/repo/.claude/worktrees/review-quality-audit/api/.venv/bin/python \
  /Users/andrew/Projects/doughq/repo/.claude/worktrees/review-quality-audit/api/scripts/backfill_outcome_jobs.py \
  --dry-run
```

Expected: both exit 1 after imports and print `DATABASE_URL not set`; neither fails
with an import error.

- [ ] **Step 6: Run tests and lint and verify GREEN**

```bash
cd api
uv run pytest tests/test_outcome_backfill_script.py -q
uv run ruff check scripts/backfill_outcome_jobs.py tests/test_outcome_backfill_script.py
```

Expected: all tests pass; ruff reports no errors.

- [ ] **Step 7: Commit the CLI**

```bash
git add api/scripts/backfill_outcome_jobs.py api/tests/test_outcome_backfill_script.py
git commit -m "feat: add the 60-day backfill operator command"
```

---

### Task 5: Lock the pre-registration and write the production runbook

**Files:**

- Modify: `api/deploy/gcp.sh:353-374`
- Modify: `api/tests/test_deploy_gcp.py:176-234`
- Create: `docs/design/outcome-loop/60-day-backfill-runbook.md`
- Modify: `docs/design/outcome-loop/publication-preregistration.md:3-10,135-170,293-300,573-585,785-808,875-889`
- Modify: `docs/design/outcome-loop/design-lock.md:46-47,65`
- Modify: `docs/design/outcome-loop/ROADMAP.md:268-288,399-406`
- Modify: `docs/design/outcome-loop/architecture.md:43-60`
- Modify: `docs/REVIEWING.md:590-603`
- Modify: `HANDOFF.md:3-73`

**Interfaces:**

- Consumes: the Task 4 CLI and current GCP resource names.
- Produces: a `LOCKED v8` pre-registration, a deploy-time lock guard, and an exact
  operator runbook.

- [ ] **Step 1: Add a failing deploy test for mutable pre-registration**

Refactor the test helper only enough to run a copied `gcp.sh` from a temporary
`api/deploy` directory with a sibling temporary `docs/design/outcome-loop` file.
Write that file with:

```markdown
# Publication pre-registration — the outcome loop

**Status:** DRAFT test fixture
```

Execute the copied script's `adjudicator` command with fake gcloud and assert nonzero
plus:

```text
ERROR: publication pre-registration is not LOCKED; refusing adjudicator deploy.
```

The test must observe zero `run jobs deploy doug-adjudicator` calls.

- [ ] **Step 2: Run the deploy test and verify RED**

```bash
cd api
uv run pytest tests/test_deploy_gcp.py -k 'unlocked_preregistration' -q
```

Expected: failure because `adjudicator()` currently hashes and deploys any file,
including a draft.

- [ ] **Step 3: Add the deploy-time lock guard**

In `adjudicator()`, name the document once and reject any status other than the
literal lock marker:

```bash
local api_image prereg_hash prereg_doc
prereg_doc=../docs/design/outcome-loop/publication-preregistration.md
if ! grep -q '^\*\*Status:\*\* LOCKED ' "$prereg_doc"; then
  echo "ERROR: publication pre-registration is not LOCKED; refusing adjudicator deploy." >&2
  return 1
fi
prereg_hash=$(python3 -c \
  "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('$prereg_doc').read_bytes()).hexdigest())")
```

Keep the existing exact-image deployment behavior unchanged.

- [ ] **Step 4: Update and lock publication pre-registration v8**

Make these explicit changes:

- status becomes `**Status:** LOCKED v8 — 2026-08-07`;
- the changelog says v8 changes the mechanism, not the published metric: permanent
  atomic dual-write plus a one-time historical insert-select;
- both sample publication queries replace
  `installation_id <> :RESEARCH_SENTINEL` with an `EXISTS` predicate against
  `installations` using the row's installation ID;
- §2.6 names registry membership as the structural research/CLI exclusion;
- §6.3 states future merges receive both rows atomically and the historical
  backfill only fills missing siblings;
- §11 records migration 007 and the Job/Scheduler as live, and names only the
  production catch-up as the remaining operational gate; and
- the hash command is macOS/Linux portable by using Python, matching deploy code.

Do not change the metric, windows, censoring, cadence, or denominator.

- [ ] **Step 5: Write the exact runbook**

The runbook must include copy-pasteable commands with no Cloud SQL Studio temporary
tables. Its core sequence is:

```bash
cd /Users/andrew/Projects/doughq/repo
git fetch origin main
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD

cd api
PROJECT=doug-prod0 REGION=us-central1 bash deploy/gcp.sh deploy

API_IMAGE=$(gcloud run services describe doug-api \
  --project doug-prod0 --region us-central1 \
  --format='value(spec.template.spec.containers[0].image)')
JOB_JSON=$(mktemp /tmp/doug-adjudicator-job.XXXXXX)
gcloud run jobs describe doug-adjudicator \
  --project doug-prod0 --region us-central1 --format=json > "$JOB_JSON"
JOB_IMAGE=$(jq -er '.spec.template.spec.template.spec.containers[0].image' "$JOB_JSON")
LOCAL_PREREG_HASH=$(python3 -c \
  "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('../docs/design/outcome-loop/publication-preregistration.md').read_bytes()).hexdigest())")
JOB_PREREG_HASH=$(jq -er \
  '.spec.template.spec.template.spec.containers[0].env[] | select(.name=="DOUG_PREREG_HASH") | .value' \
  "$JOB_JSON")
test "$API_IMAGE" = "$JOB_IMAGE"
test "$LOCAL_PREREG_HASH" = "$JOB_PREREG_HASH"
```

Start the proxy in a second terminal:

```bash
cloud-sql-proxy doug-prod0:us-central1:doug-ledger --port 5433
```

Then dry-run, pause, apply, audit, execute, and resume:

```bash
cd /Users/andrew/Projects/doughq/repo/api
DRY_REPORT_PATH=/tmp/doug-60-day-backfill-dry-run.json
APPLY_REPORT_PATH=/tmp/doug-60-day-backfill-apply.json
BACKFILL_MANIFEST_PATH="/tmp/doug-60-day-backfill-$(date -u +%Y%m%dT%H%M%SZ).json"
test ! -e "$BACKFILL_MANIFEST_PATH"

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --dry-run | tee "$DRY_REPORT_PATH"
EXPECTED_MISSING=$(jq -er '.missing' "$DRY_REPORT_PATH")
test "$(jq -er '.mismatches | length' "$DRY_REPORT_PATH")" = 0
test "$(jq -er '.orphan_60' "$DRY_REPORT_PATH")" = 0

test "$(gcloud scheduler jobs describe doug-adjudicator-daily \
  --project doug-prod0 --location us-central1 --format='value(state)')" = ENABLED
gcloud scheduler jobs pause doug-adjudicator-daily \
  --project doug-prod0 --location us-central1
test "$(gcloud scheduler jobs describe doug-adjudicator-daily \
  --project doug-prod0 --location us-central1 --format='value(state)')" = PAUSED

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --apply \
  --expect-missing "$EXPECTED_MISSING" \
  --manifest "$BACKFILL_MANIFEST_PATH" | tee "$APPLY_REPORT_PATH"
test "$(jq -er '.inserted' "$APPLY_REPORT_PATH")" = "$EXPECTED_MISSING"

uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --verify-manifest \
  --expect-count "$EXPECTED_MISSING" \
  --manifest "$BACKFILL_MANIFEST_PATH"
```

Before the manual Job, open a proxy-backed `psql` session with:

```bash
PSQL_DATABASE_URL=$(gcloud secrets versions access latest \
  --secret=doug-database-url --project=doug-prod0 | python3 -c '
import sys
url = sys.stdin.read().strip()
url = url.split("?host=", 1)[0]
url = url.replace("postgresql+psycopg://", "postgresql://")
print(url.replace("@/doug", "@127.0.0.1:5433/doug"))
')
psql "$PSQL_DATABASE_URL" -v ON_ERROR_STOP=1
```

The runbook must include these session-independent violation queries; each must
return zero rows before adjudication:

```sql
-- A registered 14-day job without its 60-day sibling.
SELECT j14.id, j14.installation_id, j14.github_repo_id,
       j14.pr_number, j14.merge_commit_sha
FROM outcome_jobs j14
WHERE j14.window_days = 14
  AND EXISTS (
    SELECT 1 FROM installations i
    WHERE i.installation_id = j14.installation_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM outcome_jobs j60
    WHERE j60.installation_id = j14.installation_id
      AND j60.github_repo_id = j14.github_repo_id
      AND j60.pr_number = j14.pr_number
      AND j60.merge_commit_sha = j14.merge_commit_sha
      AND j60.window_days = 60
  );

-- A registered 60-day job without its 14-day source.
SELECT j60.id, j60.installation_id, j60.github_repo_id,
       j60.pr_number, j60.merge_commit_sha
FROM outcome_jobs j60
WHERE j60.window_days = 60
  AND EXISTS (
    SELECT 1 FROM installations i
    WHERE i.installation_id = j60.installation_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM outcome_jobs j14
    WHERE j14.installation_id = j60.installation_id
      AND j14.github_repo_id = j60.github_repo_id
      AND j14.pr_number = j60.pr_number
      AND j14.merge_commit_sha = j60.merge_commit_sha
      AND j14.window_days = 14
  );

-- A pair whose stored facts or 60-day due date disagree.
SELECT j14.id AS job_14_id, j60.id AS job_60_id,
       j14.merged_at AS merged_at_14, j60.merged_at AS merged_at_60,
       j14.base_ref AS base_ref_14, j60.base_ref AS base_ref_60,
       j60.due_at
FROM outcome_jobs j14
JOIN outcome_jobs j60
  ON j60.installation_id = j14.installation_id
 AND j60.github_repo_id = j14.github_repo_id
 AND j60.pr_number = j14.pr_number
 AND j60.merge_commit_sha = j14.merge_commit_sha
 AND j60.window_days = 60
WHERE j14.window_days = 14
  AND EXISTS (
    SELECT 1 FROM installations i
    WHERE i.installation_id = j14.installation_id
  )
  AND (
    j60.merged_at IS DISTINCT FROM j14.merged_at
    OR j60.base_ref IS DISTINCT FROM j14.base_ref
    OR j60.due_at IS DISTINCT FROM j60.merged_at + INTERVAL '60 days'
  );
```

After the pre-Job queries return zero rows, execute the Job:

```bash
gcloud run jobs execute doug-adjudicator \
  --project doug-prod0 --region us-central1 --wait
```

After it completes, rerun those three queries and the existing complete-identity
audit verbatim from `HANDOFF.md:49-59`. Every query must still return zero rows.
Then run the final CLI audit and resume the Scheduler:

```bash
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --dry-run | tee /tmp/doug-60-day-backfill-after.json
test "$(jq -er '.missing' /tmp/doug-60-day-backfill-after.json)" = 0
test "$(jq -er '.mismatches | length' /tmp/doug-60-day-backfill-after.json)" = 0
test "$(jq -er '.orphan_60' /tmp/doug-60-day-backfill-after.json)" = 0

gcloud scheduler jobs resume doug-adjudicator-daily \
  --project doug-prod0 --location us-central1
SCHEDULER_JSON=$(mktemp /tmp/doug-adjudicator-scheduler.XXXXXX)
gcloud scheduler jobs describe doug-adjudicator-daily \
  --project doug-prod0 --location us-central1 --format=json > "$SCHEDULER_JSON"
test "$(jq -er '.state' "$SCHEDULER_JSON")" = ENABLED
test "$(jq -er '.schedule' "$SCHEDULER_JSON")" = '0 3 * * *'
test "$(jq -er '.timeZone' "$SCHEDULER_JSON")" = Etc/UTC
```

Document the rollback command before manual execution:

```bash
uv run python scripts/backfill_outcome_jobs.py \
  --from-gcp doug-prod0 --rollback \
  --expect-count "$EXPECTED_MISSING" \
  --manifest "$BACKFILL_MANIFEST_PATH"
```

State plainly: after `gcloud run jobs execute`, rollback is forbidden; resume the
Scheduler after either a verified rollback or the audited manual execution.

- [ ] **Step 6: Update only affected architecture and handoff claims**

- Design lock: preserve the one-time insert-select decision and record the approved
  supersession that future merges dual-write atomically.
- Architecture: label merge ingestion as the source of both stored clocks and keep
  `due_at` as the only clock authority.
- Roadmap: code/runbook/lock are built on the branch but production catch-up remains
  unchecked until Task 7.
- Reviewing: distinguish this prospective clock catch-up from research
  `backfill_ledger.py`; require real-installation eligibility, targeted conflict,
  dry-run count, manifest, and Scheduler pause.
- Handoff: point to the implementation branch/runbook and state that production is
  unchanged until merge and Task 7. Do not claim the catch-up or lock hash is live.

- [ ] **Step 7: Run deploy, doc, and focused API verification**

```bash
cd api
uv run pytest \
  tests/test_deploy_gcp.py \
  tests/test_outcome_backfill.py \
  tests/test_outcome_backfill_script.py -q
uv run pytest tests/test_store.py -k 'outcome_job' -q
uv run ruff check doug scripts tests
cd ..
git diff --check
rg -n 'DRAFT v7|SECOND writer|live path writes only the 14-day row|RESEARCH_SENTINEL' \
  docs/design/outcome-loop/publication-preregistration.md \
  docs/design/outcome-loop/design-lock.md \
  docs/design/outcome-loop/60-day-backfill-runbook.md
```

Expected: tests and ruff pass; `git diff --check` is silent; the final `rg` returns
no stale live-contract matches. A nonzero `rg` exit is expected when no matches are
found.

- [ ] **Step 8: Commit the lock and runbook**

```bash
git add \
  api/deploy/gcp.sh \
  api/tests/test_deploy_gcp.py \
  docs/design/outcome-loop/60-day-backfill-runbook.md \
  docs/design/outcome-loop/publication-preregistration.md \
  docs/design/outcome-loop/design-lock.md \
  docs/design/outcome-loop/ROADMAP.md \
  docs/design/outcome-loop/architecture.md \
  docs/REVIEWING.md \
  HANDOFF.md
git commit -m "docs: lock the 60-day outcome rollout"
```

---

### Task 6: Verify the implementation and open the implementation PR

**Files:**

- Verify all files changed in Tasks 1-5.
- Do not modify production or mark rollout complete.

**Interfaces:**

- Consumes: the complete implementation branch.
- Produces: a reviewed PR against `main`, with local evidence and an explicit
  post-merge production gate.

- [ ] **Step 1: Run the full local verification matrix**

```bash
cd api
uv run pytest -q
uv run ruff check doug scripts tests
cd ..
git diff --check origin/main...HEAD
git status --short
```

Expected baseline: at least 785 tests plus the new tests pass; ruff and diff checks
are clean; the worktree has no uncommitted changes.

- [ ] **Step 2: Run the reader budget gate because store/API wiring changed**

```bash
cd api
uv run python scripts/read_budget_gate.py
```

Expected: PASS. This slice should not change reader coverage; a failure is a stop,
not an unrelated skip.

- [ ] **Step 3: Review the complete diff against the approved spec**

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- \
  api/doug/store.py \
  api/doug/api.py \
  api/doug/outcome_backfill.py \
  api/scripts/backfill_outcome_jobs.py \
  api/deploy/gcp.sh
```

Check every global constraint, especially targeted conflict handling,
real-installation eligibility, pre-commit manifest write, all-or-nothing rollback,
and the deploy refusal for mutable pre-registration.

- [ ] **Step 4: Request code review before pushing**

Invoke `superpowers:requesting-code-review`. Independently reproduce every confirmed
finding before changing code. Re-run the affected focused tests after any fix and
repeat the full suite if production code changes.

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin m3-60-day-backfill
gh pr create \
  --base main \
  --head m3-60-day-backfill \
  --title "Backfill and permanently start 60-day outcome clocks" \
  --body-file /tmp/doug-m3-60-day-backfill-pr.md
```

The PR body must state:

- input → transformation → output mechanism;
- the design decision changing future merges from live 14-only to atomic 14+60;
- research `backfill_ledger.py` is unrelated;
- local test and lint receipts;
- production has not changed yet;
- Scheduler pause/apply/manual-run/resume is a post-merge gate; and
- a separate closure PR will record production evidence.

- [ ] **Step 6: Wait for CI and review**

```bash
gh pr checks --watch
```

Expected: every required check passes. Do not merge the PR autonomously. Hand the
PR to Andrew for merge approval.

---

### Task 7: Execute the guarded production catch-up after merge

**Files:**

- Follow: `docs/design/outcome-loop/60-day-backfill-runbook.md`
- Preserve: dry-run JSON, manifest, apply JSON, Job execution name/summary, SQL
  audit output, deployed image, deployed hash, and Scheduler final state.

**Interfaces:**

- Consumes: Andrew-confirmed merged implementation PR and clean updated `main`.
- Produces: completed production 60-day population with observed receipts.

- [ ] **Step 1: Verify merge and clean deployment source**

```bash
cd /Users/andrew/Projects/doughq/repo
git fetch origin main
git switch main
git pull --ff-only origin main
test -z "$(git status --porcelain)"
MERGED_SHA=$(git rev-parse HEAD)
gh pr list --state merged --head m3-60-day-backfill --limit 1 \
  --json state,mergeCommit,url | jq -e 'length == 1 and .[0].state == "MERGED"'
```

Expected: the implementation PR is `MERGED`, `MERGED_SHA` is its merge commit, and
the checkout is clean. If Andrew has not merged it, stop.

- [ ] **Step 2: Deploy and verify immutable image plus locked hash**

Run the runbook's deploy and exact `API_IMAGE`, `JOB_IMAGE`,
`LOCAL_PREREG_HASH`, and `JOB_PREREG_HASH` comparisons. Preserve all four values.

Expected: both image values are byte-for-byte equal; both hash values are
byte-for-byte equal; pre-registration status is `LOCKED v8`.

- [ ] **Step 3: Start proxy and run dry-run**

Run the runbook's proxy and dry-run commands. Inspect the entire per-repository
report, not only the total. Require zero mismatches and `orphan_60 == 0`.

Expected: a nonnegative integer missing count, zero mismatch entries, and zero
registered 60-day orphans. If any invariant fails, stop with the Scheduler still
enabled because apply has not begun.

- [ ] **Step 4: Pause Scheduler and apply**

Run the exact pause/state check, then apply using the dry-run-derived count and a
new manifest path.

Expected: apply's inserted count equals the expected missing count, manifest exists,
and all transaction invariants pass. If apply fails before commit, verify no new
rows and resume Scheduler. If apply commits but an independent audit fails, do not
run the Job; use only the manifest rollback after reviewing the discrepancy.

- [ ] **Step 5: Run independent SQL invariants before adjudication**

Run the runbook SQL through one persistent `psql`/proxy session. Preserve query
text and output. Every violation query must return zero rows.

Expected: every eligible 14-day row has one matching 60-day row; no eligible
60-day orphan exists; paired facts agree; due dates are exact; inserted manifest
rows remain untouched.

- [ ] **Step 6: Execute the Job manually and audit outcomes**

```bash
gcloud run jobs execute doug-adjudicator \
  --project doug-prod0 --region us-central1 --wait
```

Preserve the execution name and JSON summary. Then run the complete-identity audit
and the second CLI dry-run.

Expected: every done job has exactly one matching outcome; final missing and
mismatch counts and `orphan_60` are zero. A repository retry is not a reason to
delete evidence; record it and let the normal ten-day retry contract operate.

- [ ] **Step 7: Resume and verify Scheduler**

Run the runbook resume command even when the manual Job reports a repository-level
retry. Confirm state is exactly `ENABLED`, schedule remains `0 3 * * *`, and time
zone remains `Etc/UTC`.

- [ ] **Step 8: Checkpoint the observed result**

State exactly:

- merged/deployed commit;
- API/Job image digest;
- locked pre-registration hash;
- dry-run and inserted counts;
- overdue count;
- Job execution name and summary;
- invariant-query results;
- final dry-run result; and
- final Scheduler state.

Do not call the rollout complete if any item is unavailable or inferred.

---

### Task 8: Record production evidence in a closure PR

**Files:**

- Modify: `HANDOFF.md:3-73`
- Modify: `docs/design/outcome-loop/ROADMAP.md:268-288,399-406`
- Modify: `docs/design/outcome-loop/60-day-backfill-runbook.md`

**Interfaces:**

- Consumes: Task 7's observed production receipts.
- Produces: a documentation-only PR that distinguishes shipped code from verified
  production state.

- [ ] **Step 1: Start a fresh closure branch from updated main**

```bash
cd /Users/andrew/Projects/doughq/repo/.claude/worktrees/review-quality-audit
git fetch origin main
test -z "$(git branch --list m3-60-day-backfill-live)"
git switch -c m3-60-day-backfill-live origin/main
git status --short --branch
```

Expected: clean branch at the implementation PR's merged `origin/main`.

- [ ] **Step 2: Write only observed receipts**

Update `HANDOFF.md` and `ROADMAP.md` with every Task 7 value. Mark the 60-day
backfill production checkbox complete only if all invariants passed and Scheduler
ended enabled. Add a dated runbook receipt section containing the exact execution
name, counts, image digest, and pre-registration hash.

Do not mark the first real due-row detector gate complete merely because the
backfill inserted zero overdue rows or because a Job no-op succeeded.

- [ ] **Step 3: Verify the documentation diff**

```bash
git diff --check
rg -n 'DRAFT v7|production execution remains|60-day backfill run' \
  HANDOFF.md docs/design/outcome-loop/ROADMAP.md \
  docs/design/outcome-loop/60-day-backfill-runbook.md
git diff -- HANDOFF.md docs/design/outcome-loop/ROADMAP.md \
  docs/design/outcome-loop/60-day-backfill-runbook.md
```

Expected: no stale draft claim; every completion claim has a concrete receipt.

- [ ] **Step 4: Commit, push, and open the closure PR**

```bash
git add HANDOFF.md docs/design/outcome-loop/ROADMAP.md \
  docs/design/outcome-loop/60-day-backfill-runbook.md
git commit -m "docs: record the live 60-day outcome backfill"
git push -u origin m3-60-day-backfill-live
gh pr create \
  --base main \
  --head m3-60-day-backfill-live \
  --title "Record the live 60-day outcome backfill" \
  --body-file /tmp/doug-m3-60-day-backfill-live-pr.md
gh pr checks --watch
```

Expected: documentation PR open with green CI. Do not merge autonomously; hand it
to Andrew.
