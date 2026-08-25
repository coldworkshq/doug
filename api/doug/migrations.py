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

from collections.abc import Iterable, Sequence
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
    (
        5,
        (
            # App-path ledger identity. The find_verdict_by_identity pre-read
            # is advisory — two claim holders can both miss it and both insert.
            # The fence (#30) stops a superseded holder finishing the job; this
            # index stops the second verdicts row so the published denominator
            # stays honest. Partial: NULL installation_id excludes CI/CLI/
            # pre-App rows; tier <> 'external' lets Task 6 third-party rows
            # share the four columns with Doug's scored row for that SHA
            # (same exclusion as find_verdict_by_identity). Not on the Table —
            # see module docstring / migration 003.
            #
            # Dedupe first: CREATE UNIQUE INDEX fails (and bricks every cold
            # start that runs apply()) if any App-identity duplicates already
            # exist from the advisory-only era. Keep the lowest id per group;
            # re-point review_jobs, drop dependents, then the extras. Nested
            # SELECT wrappers are for sqlite (cannot delete from a table while
            # a subquery reads it directly).
            #
            # Closed FK set to verdicts.id (pinned by test): findings, reads,
            # deviations, review_jobs. outcomes joins by (repo, pr_number) /
            # identity columns — no verdict_id FK. External rows are verdicts
            # themselves (tier='external'), not a dependent table.
            "UPDATE review_jobs SET verdict_id = ("
            "  SELECT MIN(keeper.id) FROM verdicts dup"
            "  JOIN verdicts keeper"
            "    ON keeper.installation_id = dup.installation_id"
            "   AND keeper.github_repo_id = dup.github_repo_id"
            "   AND keeper.pr_number = dup.pr_number"
            "   AND keeper.head_sha = dup.head_sha"
            "   AND keeper.installation_id IS NOT NULL"
            "   AND keeper.tier <> 'external'"
            "  WHERE dup.id = review_jobs.verdict_id"
            "    AND dup.installation_id IS NOT NULL"
            "    AND dup.tier <> 'external'"
            ") WHERE verdict_id IN ("
            "  SELECT id FROM ("
            "    SELECT v.id FROM verdicts v"
            "    WHERE v.installation_id IS NOT NULL AND v.tier <> 'external'"
            "      AND v.id NOT IN ("
            "        SELECT MIN(id) FROM verdicts"
            "        WHERE installation_id IS NOT NULL AND tier <> 'external'"
            "        GROUP BY installation_id, github_repo_id, pr_number, head_sha"
            "      )"
            "  )"
            ")",
            "DELETE FROM findings WHERE verdict_id IN ("
            "  SELECT id FROM ("
            "    SELECT v.id FROM verdicts v"
            "    WHERE v.installation_id IS NOT NULL AND v.tier <> 'external'"
            "      AND v.id NOT IN ("
            "        SELECT MIN(id) FROM verdicts"
            "        WHERE installation_id IS NOT NULL AND tier <> 'external'"
            "        GROUP BY installation_id, github_repo_id, pr_number, head_sha"
            "      )"
            "  )"
            ")",
            "DELETE FROM reads WHERE verdict_id IN ("
            "  SELECT id FROM ("
            "    SELECT v.id FROM verdicts v"
            "    WHERE v.installation_id IS NOT NULL AND v.tier <> 'external'"
            "      AND v.id NOT IN ("
            "        SELECT MIN(id) FROM verdicts"
            "        WHERE installation_id IS NOT NULL AND tier <> 'external'"
            "        GROUP BY installation_id, github_repo_id, pr_number, head_sha"
            "      )"
            "  )"
            ")",
            "DELETE FROM deviations WHERE verdict_id IN ("
            "  SELECT id FROM ("
            "    SELECT v.id FROM verdicts v"
            "    WHERE v.installation_id IS NOT NULL AND v.tier <> 'external'"
            "      AND v.id NOT IN ("
            "        SELECT MIN(id) FROM verdicts"
            "        WHERE installation_id IS NOT NULL AND tier <> 'external'"
            "        GROUP BY installation_id, github_repo_id, pr_number, head_sha"
            "      )"
            "  )"
            ")",
            "DELETE FROM verdicts WHERE id IN ("
            "  SELECT id FROM ("
            "    SELECT v.id FROM verdicts v"
            "    WHERE v.installation_id IS NOT NULL AND v.tier <> 'external'"
            "      AND v.id NOT IN ("
            "        SELECT MIN(id) FROM verdicts"
            "        WHERE installation_id IS NOT NULL AND tier <> 'external'"
            "        GROUP BY installation_id, github_repo_id, pr_number, head_sha"
            "      )"
            "  )"
            ")",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_verdicts_app_identity "
            "ON verdicts (installation_id, github_repo_id, pr_number, head_sha) "
            "WHERE installation_id IS NOT NULL AND tier <> 'external'",
        ),
    ),
    (
        6,
        (
            # Tenant API keys (spec 2026-08-04): the single-column credential
            # moves to the installation_tokens table (a NEW table, so
            # create_all owns it — no DDL for it here). The only change an
            # EXISTING table needs is dropping the retired column. No data
            # migrates: no dispensed token exists in any environment (MT0
            # meant prod dispense 404'd from the day it shipped).
            #
            # On a fresh database create_all() has already built
            # installations WITHOUT token_hash, so this DROP finds its work
            # done and lands in _SATISFIED's third marker below. The table
            # itself always exists by the time apply() runs (create_all made
            # it), so this is never the ALTER-on-missing-TABLE crash-loop
            # PR #48 reverted.
            "ALTER TABLE installations DROP COLUMN token_hash",
        ),
    ),
    (
        7,
        (
            # M3 adjudication identity. Existing outcomes stay NULL and are
            # deliberately outside the partial unique index; only rows written
            # by the live adjudicator carry a job discriminator.
            "ALTER TABLE outcomes ADD COLUMN merge_commit_sha VARCHAR(64)",
            # Durable claim lease and fence for the Cloud Run Job. A crashed
            # execution is reclaimed on the next daily run without letting an
            # old holder complete over a newer claim.
            "ALTER TABLE outcome_jobs ADD COLUMN started_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE outcome_jobs ADD COLUMN finished_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE outcome_jobs ADD COLUMN error TEXT",
            "ALTER TABLE outcome_jobs ADD COLUMN claim_generation INTEGER NOT NULL DEFAULT 0",
            # Coverage already carries these values in memory. Persist them so
            # receipts can prove files were dropped before prompt assembly.
            "ALTER TABLE reads ADD COLUMN changed_files INTEGER",
            "ALTER TABLE reads ADD COLUMN files_dropped JSON",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_outcomes_job_identity "
            "ON outcomes (installation_id, github_repo_id, pr_number, "
            "merge_commit_sha, window_days) WHERE merge_commit_sha IS NOT NULL",
        ),
    ),
    (
        8,
        (
            # Instrument identity. prompt_hash covers SYSTEM + repr(SCHEMA)
            # only, so two verdicts can share it and still have been read at
            # different budgets — DIFF_BUDGET moved 30k->100k and read_order()
            # tiering shipped in #56, neither of which is in the hash. These
            # columns are stamped FORWARD ONLY: merge time is not serving
            # time, so a dated backfill would mislabel every verdict scored in
            # the deploy-lag window. NULL means "not recorded", and the
            # receipt renders it as exactly that.
            "ALTER TABLE verdicts ADD COLUMN diff_budget INTEGER",
            "ALTER TABLE verdicts ADD COLUMN read_order VARCHAR(16)",
            # Pre-registration §11 item 7, closed forward only. Does NOT change
            # the locked §2.1 rule, which stays timestamp-matched.
            "ALTER TABLE outcome_jobs ADD COLUMN merged_head_sha VARCHAR(64)",
            # The prompt hash IS backfillable and this is not an inference:
            # git log -L 45,92:api/doug/reader.py returns exactly one commit
            # (293c19d, 2026-07-29), so SYSTEM+SCHEMA have never changed and
            # there is one era. Checked a second, stronger way that does not
            # depend on line-range tracking catching every edit: SYSTEM+SCHEMA
            # extracted from 293c19d and from HEAD hash identically to each
            # other and to the literal below (verified 2026-08-08) — content
            # equality at both ends of history, not a trace of the lines
            # between. The value is a LITERAL on purpose — a runtime
            # reference to reader.PROMPT_HASH would, after any future prompt
            # change, stamp historical rows with the NEW hash on a fresh
            # replay, relabelling verdicts as the product of a prompt they
            # never saw. IS NULL keeps it idempotent.
            "UPDATE verdicts SET prompt_hash = "
            "'8bd26c677a0e087a0b8c14933203cc85e15b65e32b432c10a3ae78009a951cdf' "
            "WHERE tier = 'reader' AND prompt_hash IS NULL",
        ),
    ),
    (
        9,
        (
            # Front Door Phase 1a. Tasks 4-8 resolve a session's tenant by
            # this column; Task 5's bind endpoint proves "you are the person
            # who installed Doug here" by matching the second one. Both NULL
            # on every existing row, including the operator's own install.
            "ALTER TABLE installations ADD COLUMN workos_org_id VARCHAR(255)",
            "ALTER TABLE installations ADD COLUMN installed_by_github_user_id BIGINT",
            # A unique INDEX rather than a table constraint: sqlite (which
            # the suite runs on) cannot add a UNIQUE column constraint via
            # ALTER TABLE. IF NOT EXISTS matches every other CREATE INDEX in
            # this file (see module docstring) and additionally means this
            # is harmless if it ever runs against a fresh database, where
            # create_all() already gave the column its own UNIQUE constraint
            # under a different, engine-generated name.
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_installations_workos_org_id "
            "ON installations (workos_org_id)",
        ),
    ),
    (
        10,
        (
            # Forward only: the base GitHub reported when historical jobs
            # were admitted is unknowable after the target branch moves.
            # Version 9 is reserved by front-door-phase-1.
            "ALTER TABLE review_jobs ADD COLUMN base_sha VARCHAR(64)",
        ),
    ),
    (
        11,
        (
            # Per-repo needs-you line (spec 2026-08-18). Nullable: NULL is
            # "inherit the defaults", which is every existing row.
            "ALTER TABLE installation_repos ADD COLUMN needs_you_threshold FLOAT",
        ),
    ),
    (
        12,
        (
            # Sticky PR comment (spec 2026-08-19-sticky-pr-comment). Existing
            # repo rows default to TRUE — opted in, matching the Table's
            # server_default (see store.py).
            "ALTER TABLE installation_repos ADD COLUMN pr_comment BOOLEAN NOT NULL DEFAULT TRUE",
            # Last 403 refusal on a PR-comment write; NULL for every existing
            # row (nothing has been denied yet).
            "ALTER TABLE installations ADD COLUMN pr_comment_denied_at TIMESTAMP WITH TIME ZONE",
            # NEW table — create_all() alone would give a fresh database this
            # (see module docstring), but production's existing database
            # needs the same DDL here. IF NOT EXISTS: harmless if this ever
            # runs against a database create_all() already built. No
            # surrogate id: the natural key (installation_id, github_repo_id,
            # pr_number) IS the uniqueness the design wants — same precedent
            # as schema_migrations above (store.py:28-33).
            "CREATE TABLE IF NOT EXISTS pr_comments ("
            "installation_id BIGINT NOT NULL, "
            "github_repo_id BIGINT NOT NULL, "
            "pr_number INTEGER NOT NULL, "
            "comment_id BIGINT, "
            "updated_at TIMESTAMP WITH TIME ZONE NOT NULL, "
            "PRIMARY KEY (installation_id, github_repo_id, pr_number))",
        ),
    ),
    (
        13,
        (
            # The `seq` high-water mark that gates a write through an
            # already-stored comment_id (issue #142). Nullable with no
            # default: NULL is "nothing written yet", which is the honest
            # value for every row that predates this column — the seq those
            # comments carry is knowable only from their bodies, and
            # `pr_comment.upsert` relearns it the next time it lists.
            # Backfilling a 0 would say the same thing less clearly, and no
            # backfill can do better — see store.pr_comments for the residual
            # this leaves and why closing it costs more than it buys.
            "ALTER TABLE pr_comments ADD COLUMN last_seq BIGINT",
        ),
    ),
    (
        14,
        (
            # Walked Out (docs/design/walked-out/; convergence-design.md
            # "Rule 5 replaced"). Both nullable JSON, both meaning "not
            # recorded" when NULL: the classifier abstains on NULL
            # (unknown(no-hunk-index) / unknown(not-reconfirmed)) rather
            # than guessing, so no backfill exists that would be honest.
            # The design docs call this "migration 12"; 12 and 13 were
            # claimed on main between the lock and this commit — the column
            # set, not the number, is what the design binds.
            "ALTER TABLE reads ADD COLUMN hunks JSON",
            "ALTER TABLE findings ADD COLUMN hunks JSON",
        ),
    ),
    (
        15,
        (
            # Per-repo deep read (ADR-0013 amendment). Existing rows default
            # to TRUE — opted in, matching the Table's server_default — and
            # TRUE is the only honest backfill: every repo that existed
            # before this column WAS read whenever DOUG_READER was on, so
            # FALSE would be a claim about the past that is false.
            #
            # It NARROWS ONLY. DOUG_READER stays the master switch and the
            # spend control; a TRUE here does not turn a read on where the
            # service has it off (review.score_one gates on both).
            "ALTER TABLE installation_repos ADD COLUMN deep_read BOOLEAN NOT NULL DEFAULT TRUE",
        ),
    ),
    (
        16,
        (
            # The sticky comment's own outcome, recorded on the job that
            # wrote it (issue #154). Without it a comment lost after
            # ingest.complete returned True — a process death, a 5xx, a
            # dropped connection — is unrecoverable: the row is 'done',
            # REVIVABLE excludes 'done', and nothing retries until a new head
            # SHA makes a new job.
            "ALTER TABLE review_jobs ADD COLUMN pr_comment_outcome VARCHAR(32)",
            "ALTER TABLE review_jobs ADD COLUMN pr_comment_attempts "
            "INTEGER NOT NULL DEFAULT 0",
            # NO BACKFILL, deliberately, and the absence is the design. An
            # earlier draft stamped every existing 'done' row so that NULL
            # could mean "never posted" — which needed one UPDATE over the
            # whole table (on Postgres, a new tuple version per row and a
            # long transaction inside a startup migration) purely to
            # disambiguate an absence. The sweep reads a POSITIVE marker
            # instead: `ingest.complete` stamps `owed`, so a row this
            # migration leaves NULL is invisible to the sweep by
            # construction, and stays invisible until a completion writes the
            # marker. That is also the honest answer for the rollout overlap,
            # where an instance still on the older revision completes jobs
            # without stamping anything: nothing knows whether those
            # commented, and a repair that guesses is a duplicate.
            # (status, finished_at), NOT (status, pr_comment_outcome).
            # Virtually every row in this table is 'done', so an outcome
            # column second buys almost nothing and leaves the planner a
            # range filter and a sort it cannot serve from the index. The
            # sweep's actual selectivity is the twenty-four-hour window on
            # finished_at, which this ordering serves as a range AND as the
            # ORDER BY; the outcome and attempt predicates are then cheap
            # residuals over one day of rows rather than over every job ever
            # run. Not a partial index on the outcome predicate: the LIKE
            # would have to be identical in the index and the query for
            # Postgres to use it, and sqlite's partial-index rules are not
            # the same rules, so the two backends could silently diverge on
            # whether the sweep has an index at all.
            "CREATE INDEX IF NOT EXISTS ix_review_jobs_pr_comment_retry "
            "ON review_jobs (status, finished_at)",
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

# "no such column" is sqlite's voice for a DROP COLUMN whose work is already
# done. Both only ever reach _run from a statement in MIGRATIONS, so the
# blast radius of the broad Postgres string is our own migration list, not
# arbitrary DDL.
_SATISFIED = ("duplicate column name", "already exists", "no such column")


def _satisfied(message: str) -> bool:
    msg = message.lower()
    if any(m in msg for m in _SATISFIED):
        return True
    # Postgres's missing-column voice — 'column "x" of relation "y" does
    # not exist' — shares its tail with the missing-TABLE error
    # ('relation "y" does not exist'), which must never be swallowed
    # (see module docstring; the PR #48 crash-loop lesson). Requiring
    # 'column' alongside the tail keeps DROP COLUMN idempotent without
    # muting a missing table.
    return "does not exist" in msg and "column" in msg


def _run(engine, statement: str) -> None:
    # One transaction per statement: on Postgres a failed statement poisons
    # the whole transaction, and the already-satisfied case has to leave the
    # connection usable for the rest of the migration.
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(statement)
    except DatabaseError as e:
        # str(e) echoes the offending SQL after the driver message ("...does
        # not exist\n\n[SQL: ALTER TABLE ... DROP COLUMN ...]"), so an ALTER
        # statement makes 'column' appear in str(e) even for a missing-TABLE
        # error, defeating _satisfied's missing-table guard. e.orig is the
        # bare driver exception, without the echo; str(e) is kept only as a
        # fallback for the (untested-in-practice) case orig is None.
        if not _satisfied(str(e.orig) if e.orig is not None else str(e)):
            raise


def unapplied_migrations(
    plan: Sequence[tuple[int, tuple[str, ...]]], applied_versions: Iterable[int]
) -> list[tuple[int, tuple[str, ...]]]:
    """Return plan entries whose exact version is absent from the ledger."""
    done = set(applied_versions)
    return [(version, statements) for version, statements in plan if version not in done]


def apply(engine) -> list[int]:
    """Run every unapplied migration in order. Returns the versions applied."""
    schema_migrations.create(engine, checkfirst=True)
    with engine.connect() as conn:
        done = {r[0] for r in conn.execute(select(schema_migrations.c.version))}
    applied: list[int] = []
    for version, statements in unapplied_migrations(MIGRATIONS, done):
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
