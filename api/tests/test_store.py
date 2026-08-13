import datetime as _dt
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from doug import ingest, outcome_queue, reader, store
from doug.api import app
from doug.models import Band, PRMetadata, Reason, Verdict

BASE_SHA = "0" * 40


def _enqueue(*args, base_sha=BASE_SHA, **kwargs):
    return ingest.enqueue(*args, base_sha=base_sha, **kwargs)

RV = reader.ReaderVerdict.model_validate(
    {
        "risk_score": 62,
        "rationale": "Unlocked cache write.",
        "findings": [
            {
                "category_slug": "race-condition",
                "description": "Cache write is not guarded",
                "file": "cache.py",
                "severity": "high",
            }
        ],
    }
)

# What reader.verdict_from_reader(RV) produces, written out rather than
# called so the fixture stays a literal and cannot pick up an ambient
# DOUG_READER_THRESHOLD at import. test_reader_verdict_fixture_matches_the
# _production_builder below pins the two together; they were allowed to
# drift once, and the missing severity/file here is what made save_review's
# description-matching rebuild look load-bearing instead of redundant.
VERDICT = Verdict(
    score=0.62,
    band=Band.FLAGGED,
    threshold=0.30,
    reasons=[
        Reason(
            rule="reader:race-condition",
            label="Cache write is not guarded",
            weight=0.0,
            severity="high",
            file="cache.py",
        )
    ],
)


# /v1/queue is token-gated on the shared DOUG_API_TOKEN, so every queue
# test needs both a ledger and a token. _db sets the token because every
# one of those tests already calls it.
AUTH = {"X-Doug-Token": "t0ken"}


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DOUG_API_TOKEN", "t0ken")
    return url


def _utc(dt: datetime) -> datetime:
    """sqlite hands a DateTime(timezone=True) column back naive; Postgres
    hands it back aware. The stored instant is UTC either way."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def test_example_pack_completed_jobs_use_terminal_start_and_membership_not_mutable_enqueue(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    engine = store._get_engine()
    started = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            store.review_jobs.insert(),
            [
                {
                    "id": 901,
                    "installation_id": 10,
                    "github_repo_id": 20,
                    "repo_full_name": "owner/repo",
                    "pr_number": 1,
                    "base_sha": "a" * 40,
                    "head_sha": "b" * 40,
                    "status": "done",
                    "attempts": 2,
                    "claim_generation": 3,
                    "enqueued_at": started + timedelta(days=30),
                    "started_at": started,
                    "finished_at": started + timedelta(minutes=1),
                    "verdict_id": 1001,
                },
                {
                    "id": 902,
                    "installation_id": 10,
                    "github_repo_id": 20,
                    "repo_full_name": "owner/repo",
                    "pr_number": 2,
                    "base_sha": "c" * 40,
                    "head_sha": "d" * 40,
                    "status": "done",
                    "attempts": 3,
                    "claim_generation": 4,
                    "enqueued_at": started + timedelta(days=2),
                    "started_at": started + timedelta(days=2),
                    "finished_at": started + timedelta(days=2, minutes=1),
                    "verdict_id": 1002,
                },
                {
                    "id": 903,
                    "installation_id": 10,
                    "github_repo_id": 20,
                    "repo_full_name": "owner/repo",
                    "pr_number": 3,
                    "base_sha": "e" * 40,
                    "head_sha": "f" * 40,
                    "status": "done",
                    "attempts": 1,
                    "claim_generation": 1,
                    "enqueued_at": started,
                    "started_at": started + timedelta(days=2),
                    "finished_at": started + timedelta(days=2, minutes=1),
                    "verdict_id": 1003,
                },
            ],
        )

    rows = store.completed_example_pack_jobs(
        installation_ids=(10,),
        github_repository_ids=(20,),
        capture_started_at=started - timedelta(hours=1),
        capture_until=started + timedelta(hours=1),
        membership_job_ids=(902,),
    )

    assert [row["id"] for row in rows] == [901, 902]
    assert _utc(rows[0]["enqueued_at"]) == started + timedelta(days=30)


def test_example_pack_adjudication_lock_serializes_one_finding_on_sqlite(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    first_entered = Event()
    release_first = Event()
    second_started = Event()
    second_entered = Event()

    def first():
        with store.example_pack_adjudication_lock("c1", "a" * 64, "b" * 64):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def second():
        assert first_entered.wait(timeout=2)
        second_started.set()
        with store.example_pack_adjudication_lock("c1", "a" * 64, "b" * 64):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first)
        second_future = pool.submit(second)
        assert second_started.wait(timeout=2)
        assert not second_entered.is_set()
        release_first.set()
        first_future.result(timeout=2)
        second_future.result(timeout=2)

    assert second_entered.is_set()


def test_disabled_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert not store.enabled()
    assert store.save_review("o/r", 1, "deterministic", VERDICT) is None


def test_columns_of_returns_none_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.columns_of("verdicts") is None


def test_columns_of_returns_none_for_an_unknown_table(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review("o/r", 1, "deterministic", VERDICT)  # forces create_all()
    assert store.columns_of("no_such_table") is None


def test_columns_of_returns_the_live_columns_of_a_known_table(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review("o/r", 1, "deterministic", VERDICT)  # forces create_all()
    columns = store.columns_of("verdicts")
    assert columns is not None
    assert {"id", "repo", "pr_number", "prompt_hash"} <= columns


def test_columns_of_reads_the_connected_database_not_the_current_table_object(
    tmp_path, monkeypatch
):
    """The property that makes this a settlement, not a restatement of
    store.py: a database can lag the current Table() definitions (an
    unmigrated production instance is exactly that case), and columns_of
    must report what is actually there, not what the running code declares.

    `_get_engine()` always self-migrates on first use, so a genuinely
    older schema can only be observed by handing columns_of a raw engine
    directly — same hand-built-older-schema shape test_migrations.py uses,
    routed in via monkeypatch instead of through DATABASE_URL.
    """
    url = f"sqlite:///{tmp_path}/older.db"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE verdicts (id INTEGER PRIMARY KEY, repo VARCHAR(200))"
        )
    monkeypatch.setattr(store, "_get_engine", lambda: engine)
    assert store.columns_of("verdicts") == {"id", "repo"}
    assert "prompt_hash" not in store.columns_of("verdicts")


def test_columns_of_returns_none_when_inspection_raises(monkeypatch):
    """Doug's review of PR #49 (reader:unhandled-exception-path): a
    transient DB failure during introspection must degrade to "cannot
    tell" — the same as no DATABASE_URL — not crash the whole review job.
    settle.py's caller has no except clause for this; the guard belongs
    here, same posture as review.head_file_text's own catch-all.
    """
    monkeypatch.setattr(store, "_get_engine", lambda: object())

    def _boom(engine):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(store, "inspect", _boom)
    assert store.columns_of("verdicts") is None


def test_save_review_persists_verdict_and_findings(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    vid = store.save_review("o/r", 7, "reader", VERDICT, RV, model=reader.MODEL)
    assert vid is not None

    engine = create_engine(url)
    with engine.connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
        assert v["repo"] == "o/r" and v["pr_number"] == 7
        assert v["risk_score"] == 62 and v["model"] == reader.MODEL
        assert v["raw"]["findings"][0]["category_slug"] == "race-condition"
        f = conn.execute(select(store.findings)).mappings().one()
        assert f["verdict_id"] == vid
        assert f["severity"] == "high" and f["file"] == "cache.py"


def test_reader_verdict_fixture_matches_the_production_builder():
    """VERDICT must stay what the reader tier actually emits for RV.

    Every save_review test below feeds this pair in together, so a fixture
    that drifts from verdict_from_reader silently changes what those tests
    are about. It had drifted — the Reason carried neither severity nor
    file, which no reader-tier verdict does — and that is what let a rebuild
    keyed on model-authored description text look necessary.
    """
    assert reader.verdict_from_reader(RV).reasons == VERDICT.reasons


def test_save_review_keeps_each_findings_own_file_when_two_share_a_description(
    tmp_path, monkeypatch
):
    """Two findings can word one defect identically and differ only by file.

    `file` is half of convergence's identity (convergence.py:174-179), so a
    row that takes its neighbour's file does not merely lose information: it
    retires an identity that is still live and invents one that never
    existed — a false `resolved` beside a false `new` on the next round.
    That is the failure mode the whole abstention ladder exists to prevent,
    arriving through the write path instead of the rules.

    Goes through verdict_from_reader rather than a hand-built Verdict on
    purpose: the deleted join sat between those two, so a test that skips
    either end cannot reach the collapse this pins.
    """
    url = _db(tmp_path, monkeypatch)
    rv = reader.ReaderVerdict.model_validate(
        {
            "risk_score": 62,
            "rationale": "The same guard is missing in two places.",
            "findings": [
                {
                    "category_slug": "missing-null-check",
                    "description": "Response is dereferenced without a guard",
                    "file": "a.py",
                    "severity": "high",
                },
                {
                    "category_slug": "missing-null-check",
                    "description": "Response is dereferenced without a guard",
                    "file": "b.py",
                    "severity": "low",
                },
            ],
        }
    )

    vid = store.save_review("o/r", 11, "reader", reader.verdict_from_reader(rv), rv)
    assert vid is not None

    engine = create_engine(url)
    with engine.connect() as conn:
        rows = (
            conn.execute(select(store.findings).order_by(store.findings.c.id))
            .mappings()
            .all()
        )
    assert [r["file"] for r in rows] == ["a.py", "b.py"]
    assert [r["severity"] for r in rows] == ["high", "low"]


def test_save_review_persists_reason_severity_without_a_reader_verdict(tmp_path, monkeypatch):
    """reader_verdict is optional on save_review's own signature — callers
    that build a Verdict directly (run_history's own test suite among them)
    are a legitimate use of it, not a misuse. Severity must survive on that
    path too, not only when a matching reader_verdict also happens to be
    passed and label-matches each reason."""
    url = _db(tmp_path, monkeypatch)
    verdict = Verdict(
        score=0.62,
        band=Band.FLAGGED,
        threshold=0.30,
        reasons=[
            Reason(
                rule="reader:race-condition",
                label="Cache write is not guarded",
                weight=0.0,
                severity="high",
            )
        ],
    )
    vid = store.save_review("o/r", 7, "reader", verdict)

    engine = create_engine(url)
    with engine.connect() as conn:
        f = conn.execute(select(store.findings)).mappings().one()
    assert f["verdict_id"] == vid
    assert f["severity"] == "high"


def _pr() -> PRMetadata:
    return PRMetadata.model_validate(
        dict(number=7, title="Add cache", author="dev", files=["cache.py"])
    )


def test_queue_serves_ledger_when_enabled(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL, pr_meta=_pr().model_dump(mode="json"),
    )
    r = TestClient(app).get("/v1/queue", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["open"] == 1
    assert body["items"][0]["pr"]["number"] == 7
    assert body["items"][0]["verdict"]["band"] == "flagged"


def test_queue_repo_scoping(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review("a/x", 1, "reader", VERDICT, RV, pr_meta=_pr().model_dump(mode="json"))
    store.save_review("b/y", 2, "reader", VERDICT, RV, pr_meta=_pr().model_dump(mode="json"))
    c = TestClient(app)
    assert c.get("/v1/queue", headers=AUTH).json()["summary"]["open"] == 2
    assert c.get("/v1/queue", params={"repo": "a/x"}, headers=AUTH).json()["summary"]["open"] == 1


def _outcome(url, repo, pr_number, kind, source="git-labels"):
    from datetime import UTC, datetime

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(store.outcomes.insert(), {
            "repo": repo, "pr_number": pr_number, "kind": kind,
            "observed_at": datetime.now(UTC), "source": source,
        })


def _v(slugs, score=0.62):
    """A verdict carrying one finding per slug."""
    rv = reader.ReaderVerdict.model_validate({
        "risk_score": int(score * 100),
        "rationale": "x",
        "findings": [
            {"category_slug": s, "description": f"d-{i}", "file": "a.py", "severity": "high"}
            for i, s in enumerate(slugs)
        ],
    })
    return reader.verdict_from_reader(rv, threshold=30), rv


def test_pattern_join_pairs_findings_with_outcomes(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    verdict, rv = _v(["race-condition", "unsafe-migration"])
    store.save_review("o/r", 1, "reader", verdict, rv)
    _outcome(url, "o/r", 1, "revert")

    join = store.pattern_join()
    assert join["prs"] == [{"repo": "o/r", "pr_number": 1, "kind": "revert"}]
    assert sorted(h["rule"] for h in join["hits"]) == [
        "reader:race-condition", "reader:unsafe-migration",
    ]


def test_pattern_join_excludes_prs_without_outcomes(tmp_path, monkeypatch):
    """A scored PR whose fate is unknown is not evidence either way — it
    must not land in the precision denominator as an implicit clean."""
    _db(tmp_path, monkeypatch)
    verdict, rv = _v(["race-condition"])
    store.save_review("o/r", 1, "reader", verdict, rv)
    join = store.pattern_join()
    assert join["prs"] == [] and join["hits"] == []


def test_pattern_join_keeps_finding_free_prs_in_the_denominator(tmp_path, monkeypatch):
    """The base rate is over every PR the reader looked at, not just the
    ones it flagged. Dropping quiet PRs would inflate every lift."""
    url = _db(tmp_path, monkeypatch)
    verdict, rv = _v([])
    store.save_review("o/r", 2, "reader", verdict, rv)
    _outcome(url, "o/r", 2, "clean")
    join = store.pattern_join()
    assert join["prs"] == [{"repo": "o/r", "pr_number": 2, "kind": "clean"}]
    assert join["hits"] == []


def test_pattern_join_counts_only_the_latest_verdict(tmp_path, monkeypatch):
    """A rescored PR would otherwise contribute its superseded findings to
    precision alongside the current ones."""
    url = _db(tmp_path, monkeypatch)
    old_v, old_rv = _v(["race-condition"])
    store.save_review("o/r", 3, "reader", old_v, old_rv)
    new_v, new_rv = _v(["unsafe-migration"])
    store.save_review("o/r", 3, "reader", new_v, new_rv)
    _outcome(url, "o/r", 3, "revert")

    join = store.pattern_join()
    assert [h["rule"] for h in join["hits"]] == ["reader:unsafe-migration"]
    assert len(join["prs"]) == 1


def test_pattern_join_scopes_by_repo(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    for repo in ("a/x", "b/y"):
        verdict, rv = _v(["race-condition"])
        store.save_review(repo, 1, "reader", verdict, rv)
        _outcome(url, repo, 1, "clean")
    assert len(store.pattern_join()["prs"]) == 2
    assert store.pattern_join(repo="a/x")["prs"] == [
        {"repo": "a/x", "pr_number": 1, "kind": "clean"}
    ]


def test_pattern_join_is_empty_without_storage(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.pattern_join() == {"prs": [], "hits": []}


def test_patterns_endpoint_requires_token(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    assert TestClient(app).get("/v1/patterns").status_code == 401


def test_patterns_endpoint_serves_the_join_with_its_caveat(tmp_path, monkeypatch):
    """The caveat ships inside the payload on purpose: a precision number
    lifted out of this endpoint without it is the enriched-sample error."""
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    for i in range(4):
        verdict, rv = _v(["race-condition"])
        store.save_review("o/r", i, "reader", verdict, rv)
        _outcome(url, "o/r", i, "revert" if i < 3 else "clean")

    r = TestClient(app).get(
        "/v1/patterns", params={"min_prs": 2}, headers={"x-doug-token": "secret"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prs"] == 4 and body["defects"] == 3
    assert body["base_rate"] == 0.75
    row = body["rows"][0]
    assert row["pattern"] == "race-condition" and row["prs"] == 4
    assert row["precision"] == 0.75 and row["lift"] == 1.0
    assert "enriched sample" in body["caveat"]


def test_queue_reports_the_threshold_rows_were_banded_at(tmp_path, monkeypatch):
    """The summary threshold drives the dashboard's cut line. Reporting the
    deterministic default while every row was banded by the reader drew the
    line above PRs the same response showed as flagged."""
    _db(tmp_path, monkeypatch)
    monkeypatch.delenv("DOUG_THRESHOLD", raising=False)
    store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL, pr_meta=_pr().model_dump(mode="json"),
    )
    body = TestClient(app).get("/v1/queue", headers=AUTH).json()
    assert body["summary"]["threshold"] == VERDICT.threshold == 0.30
    assert body["items"][0]["verdict"]["band"] == "flagged"


def test_queue_falls_back_to_the_default_when_there_are_no_rows(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from doug.scoring import default_threshold

    body = TestClient(app).get("/v1/queue", params={"repo": "nobody/here"}, headers=AUTH).json()
    assert body["summary"]["open"] == 0
    assert body["summary"]["threshold"] == default_threshold()


def test_explicit_threshold_rebands_the_rows(tmp_path, monkeypatch):
    """Passing a threshold used to change only the reported number while the
    rows kept their stored bands — the parameter contradicted its own
    response."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL, pr_meta=_pr().model_dump(mode="json"),
    )
    body = TestClient(app).get("/v1/queue", params={"threshold": 0.9}, headers=AUTH).json()
    assert body["summary"]["threshold"] == 0.9
    assert body["summary"]["flagged"] == 0
    item = body["items"][0]
    assert item["verdict"]["band"] == "cleared"       # 0.62 < 0.9
    assert item["verdict"]["threshold"] == 0.9        # and it says so


def test_queue_links_rows_written_before_url_was_captured(tmp_path, monkeypatch):
    """Every backfilled probe row and everything scored before today has no
    url. The ledger knows the repo and the number, which is all a GitHub PR
    link needs, so they are repaired on read rather than by rewriting 654
    rows."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL, pr_meta=_pr().model_dump(mode="json"),
    )
    item = TestClient(app).get("/v1/queue", headers=AUTH).json()["items"][0]
    assert item["pr"]["url"] == "https://github.com/o/r/pull/7"


def test_queue_carries_finding_severity(tmp_path, monkeypatch):
    """Reader findings have weight 0 by construction, so the queue showed
    '+0.00' beside every one of them. Severity is the field that actually
    varies."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL, pr_meta=_pr().model_dump(mode="json"),
    )
    body = TestClient(app).get("/v1/queue", headers=AUTH).json()
    reasons = body["items"][0]["verdict"]["reasons"]
    assert reasons[0]["severity"] == "high"
    assert reasons[0]["weight"] == 0.0


def test_engine_is_not_rebuilt_when_the_url_carries_a_password(monkeypatch):
    """str(engine.url) masks passwords ("user:***@host"), so comparing it
    against a credentialed DATABASE_URL never matches — which meant every
    single ledger call built a fresh engine and connection pool against
    prod Postgres and orphaned the old one. The cache must key on the raw
    env string, not the engine's self-description.
    """
    from unittest.mock import MagicMock

    built = []
    monkeypatch.setattr(store, "create_engine", lambda url, **kw: built.append(url) or MagicMock())
    monkeypatch.setattr(store.metadata, "create_all", lambda engine: None)
    monkeypatch.setattr(store, "_engine", None)
    monkeypatch.setattr(store, "_engine_url", None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://doug:s3cret@db.internal/doug")

    first = store._get_engine()
    second = store._get_engine()
    assert built == ["postgresql://doug:s3cret@db.internal/doug"]
    assert first is second


def test_concurrent_first_requests_build_exactly_one_engine(tmp_path, monkeypatch):
    """Unsynchronized check-then-act let two racing first-requests each
    build an engine; the loser's connection pool leaked until Postgres ran
    out of connections. The lock makes first-touch build exactly once.
    """
    import threading

    url = f"sqlite:///{tmp_path}/race.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(store, "_engine", None)
    monkeypatch.setattr(store, "_engine_url", None)

    real_create = store.create_engine
    built = []
    barrier = threading.Barrier(8)

    def slow_create(u, **kw):
        built.append(u)
        return real_create(u, **kw)

    monkeypatch.setattr(store, "create_engine", slow_create)

    def hit():
        barrier.wait()
        store._get_engine()

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(built) == 1


# --- /v1/review idempotency --------------------------------------------------
# A webhook redelivery or a retried CI job used to re-run the whole paid
# read and insert a second verdicts row for the same commit — doubling LLM
# spend and giving precision two "independent" scoring events that were one.


def _pr_with_sha(sha="a" * 40) -> PRMetadata:
    return PRMetadata.model_validate(
        dict(number=7, title="Add cache", author="dev", files=["cache.py"], head_sha=sha)
    )


def test_deviation_none_marker_is_storage_only_never_replayed(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        pr_meta=_pr_with_sha().model_dump(mode="json"),
    )
    store.save_deviations(vid, [], ["ADR-3"], 95)
    prior = store.find_review("o/r", 7, "a" * 40)
    assert prior["deviations"] == []  # kind="none" is bookkeeping, not a finding
    assert prior["intent_alignment"] == 95  # but the read's alignment survives


def test_pre_sha_rows_never_match_and_get_rescored_once(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review("o/r", 7, "reader", VERDICT, RV, pr_meta=_pr().model_dump(mode="json"))
    assert store.find_review("o/r", 7, "a" * 40) is None


def test_find_review_matches_the_head_sha_column_without_pr_meta(tmp_path, monkeypatch):
    """The column is what App/CI writes for identity; JSON fallback is for
    legacy rows only. A lookup that required pr_meta would leave the
    migrated column dead weight and block a future unique index."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        head_sha="a" * 40,
        pr_meta={"title": "no head here"},
    )
    prior = store.find_review("o/r", 7, "a" * 40)
    assert prior is not None and prior["band"] == "flagged"


def test_replay_keeps_the_partial_read_hedge_on_deviations(tmp_path, monkeypatch):
    """PR #12 added intent_notice so a client rendering deviations alone
    knows to hedge a partial read. Both reads truncate the same diff at
    the same budget, so the recorded risk-read coverage is the intent
    read's too — a replay must rebuild the hedge, not silently present
    truncated findings as complete on the second delivery.
    """
    _db(tmp_path, monkeypatch)
    cov = reader.Coverage(
        diff_chars=100_000, sent_chars=30_000, files_sent=3,
        files_unseen=["big_migration.sql"], file_cut="server.py",
    )
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        pr_meta=_pr_with_sha().model_dump(mode="json"), coverage=cov,
    )
    store.save_deviations(
        vid,
        [reader.DeviationFinding(type="beyond-ticket", description="adds a flag", severity="low")],
        ["ADR-3"], 72,
    )
    prior = store.find_review("o/r", 7, "a" * 40)
    assert prior["coverage"]["sent_chars"] == 30_000
    notice = reader.truncation_reason(reader.Coverage(**prior["coverage"]))
    assert notice is not None and "Partial read" in notice.label


# --- App identity on verdicts -------------------------------------------------

INSTALL = 150424894
REPO_ID = 900001


def test_save_review_records_app_identity(tmp_path, monkeypatch):
    """`repo` is a display string that changes the moment a repo is renamed,
    and every tenancy question this ledger will be asked — which installation,
    which repo, which commit — has to survive that rename. The identity
    columns are the only answer that does."""
    url = _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL,
        github_repo_id=REPO_ID,
        installation_id=INSTALL,
        head_sha="a" * 40,
        source="app",
    )
    engine = create_engine(url)
    with engine.connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
    assert v["id"] == vid
    assert v["github_repo_id"] == REPO_ID and v["installation_id"] == INSTALL
    assert v["head_sha"] == "a" * 40 and v["source"] == "app"


def test_save_review_leaves_identity_null_for_the_ci_path(tmp_path, monkeypatch):
    """Every row written before the App existed has no installation, and the
    CLI still writes rows that never had one. Null has to mean that rather
    than being backfilled with a guess."""
    url = _db(tmp_path, monkeypatch)
    store.save_review("o/r", 7, "deterministic", VERDICT)
    with create_engine(url).connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
    assert v["installation_id"] is None and v["source"] is None


def test_save_review_returns_existing_id_on_duplicate_app_identity(tmp_path, monkeypatch):
    """Migration 005 makes the App identity unique. The advisory pre-read in
    the worker still races: two holders can both miss it, both pay, and both
    call save_review. The loser's insert must resolve to the winner's id —
    not raise — or a lost claim after a successful peer write looks like a
    hard failure and the denominator grows a second paid ghost on retry.
    """
    url = _db(tmp_path, monkeypatch)
    sha = "a" * 40
    created_first: list[bool] = []
    first = store.save_review(
        "o/r",
        7,
        "reader",
        VERDICT,
        RV,
        model=reader.MODEL,
        github_repo_id=REPO_ID,
        installation_id=INSTALL,
        head_sha=sha,
        source="app",
        created=created_first,
    )
    created_second: list[bool] = []
    second = store.save_review(
        "o/r",
        7,
        "deterministic",
        Verdict(score=0.01, band=Band.CLEARED, threshold=0.30, reasons=[]),
        github_repo_id=REPO_ID,
        installation_id=INSTALL,
        head_sha=sha,
        source="app",
        created=created_second,
    )
    assert second == first
    assert created_first == [True]
    assert created_second == [False]
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.verdicts)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["tier"] == "reader"


def test_app_and_external_verdicts_share_a_sha_under_the_unique_index(
    tmp_path, monkeypatch
):
    """The unique index must not treat an external row as Doug's scored
    commit. Same four identity columns, different tier — both stay.
    """
    url = _db(tmp_path, monkeypatch)
    sha = "a" * 40
    doug = store.save_review(
        "o/r",
        7,
        "reader",
        VERDICT,
        RV,
        model=reader.MODEL,
        github_repo_id=REPO_ID,
        installation_id=INSTALL,
        head_sha=sha,
        source="app",
    )
    external = store.save_external_review(
        INSTALL,
        REPO_ID,
        "o/r",
        7,
        sha,
        "review:alice",
        Band.CLEARED,
        datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert doug is not None and external is not None and doug != external
    with create_engine(url).connect() as conn:
        tiers = {
            r["tier"]
            for r in conn.execute(select(store.verdicts)).mappings().all()
        }
    assert tiers == {"reader", store.EXTERNAL_TIER}


def test_ci_path_duplicates_are_still_allowed(tmp_path, monkeypatch):
    """Partial index: NULL installation_id rows are outside the constraint.
    The CI dual-run path has no installation and must keep writing.
    """
    url = _db(tmp_path, monkeypatch)
    store.save_review("o/r", 7, "deterministic", VERDICT)
    store.save_review("o/r", 7, "deterministic", VERDICT)
    with create_engine(url).connect() as conn:
        assert len(conn.execute(select(store.verdicts)).mappings().all()) == 2


# --- Installation helpers -----------------------------------------------------


def test_upsert_installation_updates_state_in_place(tmp_path, monkeypatch):
    """Suspend and unsuspend arrive as repeated events for one installation.
    Inserting a second row would leave two answers to "is this tenant active"
    and no rule for picking one."""
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")
    store.upsert_installation(INSTALL, "drewjst", "User", "suspended")
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installations)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["state"] == "suspended" and rows[0]["account_login"] == "drewjst"


def test_upsert_installation_does_not_raise_when_two_racers_insert_the_same_id(
    tmp_path, monkeypatch
):
    """Two concurrent deliveries for one new installation (redelivery, or two
    webhook workers) can both read `row is None` before either has inserted,
    then race to INSERT. The loser's insert hits installations' unique
    constraint on installation_id — that must fall through to an update, the
    same "already done, not failed" case migrations.apply() handles for the
    schema-version race, not escape as an uncaught IntegrityError. Uses real
    thread concurrency (mirroring test_migrations.py's version-race test)
    rather than a mocked transaction boundary, so the test exercises
    upsert_installation's actual behavior and would fail against any
    implementation shape that reintroduces the race — not just this one."""
    import threading
    import time

    from sqlalchemy.engine import Connection

    url = _db(tmp_path, monkeypatch)
    engine = create_engine(url)
    store.metadata.create_all(engine)
    monkeypatch.setattr(store, "_get_engine", lambda: engine)

    real_execute = Connection.execute

    def slow_execute(self, statement, *args, **kwargs):
        result = real_execute(self, statement, *args, **kwargs)
        text = str(statement)
        if "installations" in text and text.strip().upper().startswith("SELECT"):
            time.sleep(0.02)  # hold the window open past both racers' select-read
        return result

    monkeypatch.setattr(Connection, "execute", slow_execute)

    errors = []

    def racer():
        try:
            store.upsert_installation(INSTALL, "drewjst", "User", "active")
        except Exception as e:  # noqa: BLE001 — the assertion is that nothing escapes
            errors.append(e)

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    with engine.connect() as conn:
        rows = conn.execute(select(store.installations)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["installation_id"] == INSTALL and rows[0]["state"] == "active"


def test_installations_carries_a_unique_workos_org_id(tmp_path, monkeypatch):
    """One WorkOS organization maps to exactly one installation. Without the
    unique constraint, two installations could claim the same org and a
    session would resolve to whichever row the database returned first."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    cols = {c.name: c for c in store.installations.columns}
    assert "workos_org_id" in cols, "column missing"
    assert cols["workos_org_id"].unique is True, "must be unique"
    assert cols["workos_org_id"].nullable is True, "existing rows have no org yet"


def test_installations_carries_a_non_unique_installer_id(tmp_path, monkeypatch):
    """One GitHub user can install Doug on many accounts/orgs — a unique
    constraint here would make every install after their first one fail."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    cols = {c.name: c for c in store.installations.columns}
    assert "installed_by_github_user_id" in cols, "column missing"
    assert cols["installed_by_github_user_id"].unique is not True, "must not be unique"
    assert cols["installed_by_github_user_id"].nullable is True
    assert isinstance(cols["installed_by_github_user_id"].type, BigInteger)


def test_consumed_install_flows_is_a_digest_only_create_all_table(tmp_path, monkeypatch):
    """The browser nonce is an authentication factor during the flow. The
    ledger needs only its one-way lookup key; persisting the nonce itself
    would turn a database read into a replay credential."""
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")

    cols = {column.name: column for column in store.consumed_install_flows.columns}
    assert set(cols) == {
        "nonce_digest",
        "workos_user_id",
        "installation_id",
        "consumed_at",
    }
    assert cols["nonce_digest"].primary_key is True
    assert "consumed_install_flows" in inspect(create_engine(url)).get_table_names()


def test_install_flow_lock_engine_is_bounded_cached_and_disposed_on_url_change(
    monkeypatch,
):
    assert store.INSTALL_FLOW_LOCK_POOL_TIMEOUT_SECONDS == 240

    class FakeEngine:
        def __init__(self, url):
            self.url = url
            self.disposed = 0

        def dispose(self):
            self.disposed += 1

    built = []

    def build(url, **options):
        engine = FakeEngine(url)
        built.append((engine, options))
        return engine

    monkeypatch.setattr(store, "create_engine", build)
    monkeypatch.setattr(store, "_install_flow_lock_engine", None, raising=False)
    monkeypatch.setattr(store, "_install_flow_lock_engine_url", None, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/first")

    first = store._get_install_flow_lock_engine()
    assert store._get_install_flow_lock_engine() is first
    assert built == [
        (
            first,
            {
                "pool_pre_ping": True,
                "pool_size": 1,
                "max_overflow": 0,
                "pool_timeout": 240,
            },
        )
    ]

    monkeypatch.setenv("DATABASE_URL", "postgresql://db/second")
    second = store._get_install_flow_lock_engine()
    assert second is not first
    assert first.disposed == 1
    assert built[1] == (
        second,
        {
            "pool_pre_ping": True,
            "pool_size": 1,
            "max_overflow": 0,
            "pool_timeout": 240,
        },
    )

    monkeypatch.delenv("DATABASE_URL")
    assert store._get_install_flow_lock_engine() is None
    assert second.disposed == 1


def test_install_flow_lock_checkout_timeout_becomes_the_named_store_error(
    monkeypatch,
):
    class ExhaustedEngine:
        def connect(self):
            raise SQLAlchemyTimeoutError("purpose pool exhausted")

    monkeypatch.setattr(
        store, "_get_install_flow_lock_engine", lambda: ExhaustedEngine()
    )

    with pytest.raises(
        store.InstallFlowLockUnavailable,
        match="^install flow temporarily unavailable$",
    ) as raised:
        with store.install_flow_bind_lock("0" * 64, 1001):
            pytest.fail("checkout exhaustion must not enter the authority body")

    assert isinstance(raised.value.__cause__, SQLAlchemyTimeoutError)


def test_install_flow_lock_checkout_does_not_hide_unrelated_errors(monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("programmer bug")

    monkeypatch.setattr(store, "_get_install_flow_lock_engine", lambda: BrokenEngine())

    with pytest.raises(RuntimeError, match="^programmer bug$"):
        with store.install_flow_bind_lock("0" * 64, 1001):
            pytest.fail("a failed checkout must not enter the authority body")


def test_direct_installation_bind_lock_uses_only_the_purpose_lock_pool(
    monkeypatch,
):
    """A slow advisory wait and the WorkOS work inside the lock must not
    occupy a connection needed by normal ledger reads and writes."""
    events = []

    class RecordingConnection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def execution_options(self, **options):
            events.append(("options", options))
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement, params):
            events.append((str(statement), params["key"]))

    class LockEngine:
        def connect(self):
            return RecordingConnection()

    monkeypatch.setattr(store, "_get_install_flow_lock_engine", lambda: LockEngine())

    def main_pool_forbidden():
        raise AssertionError("direct bind lock reached the main ledger pool")

    monkeypatch.setattr(store, "_get_engine", main_pool_forbidden)
    with pytest.raises(RuntimeError, match="body failure"):
        with store.installation_bind_lock(1001):
            events.append(("body", None))
            raise RuntimeError("body failure")

    assert events == [
        ("options", {"isolation_level": "AUTOCOMMIT"}),
        ("SELECT pg_advisory_lock(:key)", 1001),
        ("body", None),
        ("SELECT pg_advisory_unlock(:key)", 1001),
    ]


def test_direct_installation_bind_lock_checkout_timeout_is_named(monkeypatch):
    class ExhaustedEngine:
        def connect(self):
            raise SQLAlchemyTimeoutError("purpose pool exhausted with a secret")

    monkeypatch.setattr(
        store, "_get_install_flow_lock_engine", lambda: ExhaustedEngine()
    )

    with pytest.raises(
        store.InstallationBindLockUnavailable,
        match="^installation bind temporarily unavailable$",
    ) as raised:
        with store.installation_bind_lock(1001):
            pytest.fail("checkout exhaustion must not enter the authority body")

    assert isinstance(raised.value.__cause__, SQLAlchemyTimeoutError)


def test_direct_installation_bind_lock_checkout_does_not_hide_unrelated_errors(
    monkeypatch,
):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("programmer bug")

    monkeypatch.setattr(store, "_get_install_flow_lock_engine", lambda: BrokenEngine())

    with pytest.raises(RuntimeError, match="^programmer bug$"):
        with store.installation_bind_lock(1001):
            pytest.fail("a failed checkout must not enter the authority body")


def test_combined_install_flow_lock_uses_only_lock_pool_and_releases_in_reverse(
    monkeypatch,
):
    digest = hashlib.sha256(b"combined-lock-call-site").hexdigest()
    nonce_key = store._install_flow_advisory_key(digest)
    events = []

    class RecordingConnection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def execution_options(self, **options):
            events.append(("options", options))
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement, params):
            events.append((str(statement), params["key"]))

    class LockEngine:
        def connect(self):
            return RecordingConnection()

    monkeypatch.setattr(store, "_get_install_flow_lock_engine", lambda: LockEngine())

    def main_pool_forbidden():
        raise AssertionError("combined lock reached the main ledger pool")

    monkeypatch.setattr(store, "_get_engine", main_pool_forbidden)
    with pytest.raises(RuntimeError, match="body failure"):
        with store.install_flow_bind_lock(digest, 1001):
            events.append(("body", None))
            raise RuntimeError("body failure")

    assert events == [
        ("options", {"isolation_level": "AUTOCOMMIT"}),
        ("SELECT pg_advisory_lock(:key)", nonce_key),
        ("SELECT pg_advisory_lock(:key)", 1001),
        ("body", None),
        ("SELECT pg_advisory_unlock(:key)", 1001),
        ("SELECT pg_advisory_unlock(:key)", nonce_key),
    ]
    assert nonce_key < 0


def test_install_flow_consumption_is_inserted_before_the_authority_write(
    tmp_path, monkeypatch
):
    """If the authority write happened first, a crash in between would bind
    an installation while leaving its replay credential reusable. Both writes
    belong to one transaction, with consumption first."""
    from sqlalchemy.engine import Connection

    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")
    raw_nonce = b"raw-install-flow-nonce-32-byte!"
    digest = hashlib.sha256(raw_nonce).hexdigest()
    statements = []
    real_execute = Connection.execute

    def record_execute(self, statement, *args, **kwargs):
        statements.append(str(statement))
        return real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", record_execute)
    result = store.consume_install_flow_and_bind(
        digest,
        "user_01ABC",
        INSTALL,
        "org_01ABC",
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert result == "bound"
    insert_at = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("INSERT INTO consumed_install_flows")
    )
    update_at = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("UPDATE installations")
    )
    assert insert_at < update_at
    with create_engine(url).connect() as conn:
        [consumed] = conn.execute(select(store.consumed_install_flows)).mappings().all()
        bound = conn.execute(
            select(store.installations.c.workos_org_id).where(
                store.installations.c.installation_id == INSTALL
            )
        ).scalar_one()
    assert consumed["nonce_digest"] == digest
    assert consumed["workos_user_id"] == "user_01ABC"
    assert consumed["installation_id"] == INSTALL
    assert bound == "org_01ABC"
    assert raw_nonce not in (tmp_path / "doug.db").read_bytes()


def test_install_flow_bind_conflict_rolls_back_the_consumption(tmp_path, monkeypatch):
    """A nonce is spent only by a successful authority write. If the target
    WorkOS organization belongs to another installation, both the attempted
    consumption and bind must roll back so the legitimate retry is possible."""
    _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")
    store.upsert_installation(INSTALL + 1, "other", "Organization", "active")
    assert store.bind_installation_org(INSTALL + 1, "org_taken") == "org_taken"
    digest = hashlib.sha256(b"conflicting-flow").hexdigest()

    assert (
        store.consume_install_flow_and_bind(
            digest, "user_01ABC", INSTALL, "org_taken"
        )
        == "conflict"
    )
    assert store.install_flow_consumption(digest) is None
    assert store.installation_bind_row(INSTALL)["workos_org_id"] is None


def test_same_flow_replay_returns_success_without_a_second_authority_write(
    tmp_path, monkeypatch
):
    """A network retry after a successful response was lost is safe, but it
    must stop at the consumed record rather than repeat the bind side effect."""
    from sqlalchemy.engine import Connection

    _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")
    digest = hashlib.sha256(b"one-flow").hexdigest()
    assert (
        store.consume_install_flow_and_bind(
            digest, "user_01ABC", INSTALL, "org_01ABC"
        )
        == "bound"
    )
    statements = []
    real_execute = Connection.execute

    def record_execute(self, statement, *args, **kwargs):
        statements.append(str(statement))
        return real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", record_execute)
    assert (
        store.consume_install_flow_and_bind(
            digest, "user_01ABC", INSTALL, "org_01ABC"
        )
        == "replay"
    )
    assert not any(statement.startswith("UPDATE installations") for statement in statements)
    assert not any(
        statement.startswith("INSERT INTO consumed_install_flows")
        for statement in statements
    )


def test_consumed_nonce_cannot_be_replayed_for_another_subject_or_installation(
    tmp_path, monkeypatch
):
    """The digest is globally single-use. Replaying it with different
    authority claims is an attack, not idempotency."""
    _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")
    store.upsert_installation(INSTALL + 1, "other", "Organization", "active")
    digest = hashlib.sha256(b"identity-bound-flow").hexdigest()
    assert (
        store.consume_install_flow_and_bind(
            digest, "user_01ABC", INSTALL, "org_01ABC"
        )
        == "bound"
    )

    assert (
        store.consume_install_flow_and_bind(
            digest, "user_attacker", INSTALL, "org_01ABC"
        )
        == "mismatch"
    )
    assert (
        store.consume_install_flow_and_bind(
            digest, "user_01ABC", INSTALL + 1, "org_other"
        )
        == "mismatch"
    )
    assert store.installation_bind_row(INSTALL + 1)["workos_org_id"] is None


def test_upsert_installation_records_the_installer_on_first_insert(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(
        INSTALL, "drewjst", "User", "active", installed_by_github_user_id=42
    )
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installations)).mappings().all()
    assert rows[0]["installed_by_github_user_id"] == 42


def test_upsert_installation_default_omits_the_installer(tmp_path, monkeypatch):
    """Callers that pass no installer (every existing call site) must still
    insert cleanly, with the column left NULL."""
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "drewjst", "User", "active")
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installations)).mappings().all()
    assert rows[0]["installed_by_github_user_id"] is None


def test_upsert_installation_leaves_the_installer_untouched_when_not_given(
    tmp_path, monkeypatch
):
    """Suspend/unsuspend/deleted deliveries call upsert_installation with no
    installer to report; that must not blank out the one recorded at install
    time — the bind endpoint (Task 5) needs it to survive every state change
    in between."""
    url = _db(tmp_path, monkeypatch)
    store.upsert_installation(
        INSTALL, "drewjst", "User", "active", installed_by_github_user_id=42
    )
    store.upsert_installation(INSTALL, "drewjst", "User", "suspended")
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installations)).mappings().all()
    assert rows[0]["installed_by_github_user_id"] == 42
    assert rows[0]["state"] == "suspended"


def test_session_entitlement_lookup_uses_both_user_and_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.replace_session_entitlements(
        "user_selected", [(INSTALL, [11]), (INSTALL + 1, [22])]
    )
    store.replace_session_entitlements("user_other", [(INSTALL, [12])])

    selected = store.session_entitlement_for("user_selected", INSTALL)

    assert selected is not None
    assert selected["installation_id"] == INSTALL
    assert selected["repo_ids"] == frozenset({11})
    assert store.session_entitlement_for("user_missing", INSTALL) is None


def test_session_connection_projection_intersects_claims_with_live_rows(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    store.upsert_installation(INSTALL, "acme", "Organization", "active")
    store.set_installation_repos(
        INSTALL, [(11, "acme/one"), (12, "acme/two")], replace=True
    )
    store.replace_session_entitlements("user_selected", [(INSTALL, [11, 999])])
    with store._get_engine().begin() as conn:
        conn.execute(
            store.installations.update()
            .where(store.installations.c.installation_id == INSTALL)
            .values(workos_org_id="org_acme")
        )

    rows = store.session_connections_for("user_selected")

    assert len(rows) == 1
    assert rows[0]["organization_id"] == "org_acme"
    assert rows[0]["claimed_repo_ids"] == frozenset({11, 999})
    assert rows[0]["repositories"] == [{"id": 11, "full_name": "acme/one"}]


def test_installation_created_replaces_the_whole_repo_list(tmp_path, monkeypatch):
    """The installation payload carries the authoritative list. A reinstall
    that dropped a repo must not leave it active — Doug would keep reviewing a
    repo the customer removed it from."""
    url = _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALL, [(1, "o/a"), (2, "o/b")], replace=True)
    store.set_installation_repos(INSTALL, [(2, "o/b")], replace=True)
    with create_engine(url).connect() as conn:
        rows = {
            r["github_repo_id"]: r["state"]
            for r in conn.execute(select(store.installation_repos)).mappings()
        }
    assert rows == {1: "removed", 2: "active"}


def test_repo_deltas_merge_without_touching_the_rest(tmp_path, monkeypatch):
    """installation_repositories events are deltas, not snapshots. Treating
    one as authoritative would remove every repo it did not mention."""
    url = _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALL, [(1, "o/a"), (2, "o/b")], replace=True)
    store.set_installation_repos(INSTALL, [(3, "o/c")], replace=False)
    store.set_installation_repos(INSTALL, [(1, "o/a")], replace=False, state="removed")
    with create_engine(url).connect() as conn:
        rows = {
            r["github_repo_id"]: r["state"]
            for r in conn.execute(select(store.installation_repos)).mappings()
        }
    assert rows == {1: "removed", 2: "active", 3: "active"}


def test_a_removed_repo_keeps_its_row(tmp_path, monkeypatch):
    """Verdicts outlive access. Deleting the row would break the join that
    explains where a stored verdict came from, and uninstall-then-reinstall is
    a support case that needs the history."""
    url = _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALL, [(1, "o/a")], replace=True)
    store.set_installation_repos(INSTALL, [], replace=True)
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installation_repos)).mappings().all()
    assert len(rows) == 1 and rows[0]["state"] == "removed"


def test_a_duplicate_repo_id_in_one_call_updates_not_double_inserts(tmp_path, monkeypatch):
    """`known` is read once before the loop; a naive implementation never
    updates it as rows are inserted, so a second occurrence of the same
    github_repo_id in one `repos` list would see it as still-unseen and
    insert again, violating uq_installation_repo. Not a hypothetical
    payload shape — the caller controls `repos`, and this must degrade to
    an update, not an unhandled IntegrityError."""
    url = _db(tmp_path, monkeypatch)
    store.set_installation_repos(INSTALL, [(1, "o/a"), (1, "o/a")], replace=True)
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.installation_repos)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["github_repo_id"] == 1 and rows[0]["state"] == "active"


# --- Outcome-loop schema (M1 amendment) ---------------------------------------


def _outcome_job(**overrides) -> dict:
    now = datetime.now(UTC)
    base = {
        "installation_id": INSTALL,
        "github_repo_id": REPO_ID,
        "pr_number": 42,
        "merge_commit_sha": "a" * 40,
        "merged_at": now,
        "base_ref": "main",
        "due_at": now,
        "created_at": now,
    }
    base.update(overrides)
    return base


def test_outcome_jobs_unique_constraint_rejects_a_duplicate(tmp_path, monkeypatch):
    """The unique key is the dedup against GitHub webhook redelivery — a
    replayed 'closed' event for a PR that is already queued must not create a
    second job with its own independent due date."""
    url = _db(tmp_path, monkeypatch)
    store.enabled()  # triggers create_all() before the raw insert below
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(store.outcome_jobs.insert(), _outcome_job())
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(store.outcome_jobs.insert(), _outcome_job())


def test_outcome_jobs_server_defaults_are_the_real_unquoted_values(tmp_path, monkeypatch):
    """A server_default passed as an already-quoted string literal
    ("'pending'") renders as DEFAULT ''pending'' — SQLAlchemy quotes the
    Python string itself, so double-quoting stores the literal characters
    'pending' (with quote marks) as the value instead of the word. Only a
    real round-trip through the DB's own default clause catches that."""
    url = _db(tmp_path, monkeypatch)
    store.enabled()
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(store.outcome_jobs.insert(), _outcome_job())
    with engine.connect() as conn:
        row = conn.execute(select(store.outcome_jobs)).mappings().one()
    assert row["window_days"] == 14
    assert row["status"] == "pending"
    assert row["attempts"] == 0


def test_outcome_jobs_permits_the_same_pr_with_a_different_window(tmp_path, monkeypatch):
    """`window_days` is part of the unique key on purpose — a future change
    to the default observation window must not collide with jobs already
    queued under the old one."""
    url = _db(tmp_path, monkeypatch)
    store.enabled()  # triggers create_all() before the raw insert below
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(store.outcome_jobs.insert(), _outcome_job(window_days=14))
        conn.execute(store.outcome_jobs.insert(), _outcome_job(window_days=30))
    with engine.connect() as conn:
        rows = conn.execute(select(store.outcome_jobs)).mappings().all()
    assert len(rows) == 2


MERGED = datetime(2020, 3, 1, 12, 0, tzinfo=UTC)


def _enqueue_outcome(**overrides) -> int | None:
    kwargs = {
        "installation_id": INSTALL,
        "github_repo_id": REPO_ID,
        "pr_number": 42,
        "merge_commit_sha": "a" * 40,
        "merged_at": MERGED,
        "base_ref": "main",
    }
    kwargs.update(overrides)
    return store.enqueue_outcome_job(**kwargs)


def test_enqueue_outcome_job_dates_the_window_from_the_merge(tmp_path, monkeypatch):
    """The three tests above are about the Table; this is about the function
    that writes it, which nothing covered directly.

    due_at is merged_at + window_days and never now(): the same merge can
    reach this seconds after it lands, hours later via a redelivery, or
    months later via a backfill, and the window has to mean "fourteen days
    after this code shipped" in all three."""
    url = _db(tmp_path, monkeypatch)
    assert _enqueue_outcome() is not None
    with create_engine(url).connect() as conn:
        row = conn.execute(select(store.outcome_jobs)).mappings().one()
    assert _utc(row["merged_at"]) == MERGED
    assert _utc(row["due_at"]) == datetime(2020, 3, 15, 12, 0, tzinfo=UTC)
    assert row["window_days"] == 14
    assert row["status"] == "pending"


def test_enqueue_outcome_job_honours_a_per_row_window(tmp_path, monkeypatch):
    """window_days is stored rather than derived at query time because it is
    part of the unique key and "may differ per row" — a claim the kwarg has
    to actually support, since the same merge queued under two windows is
    two legitimate rows with two due dates. Nothing reached this parameter
    before: the webhook only ever calls the default."""
    url = _db(tmp_path, monkeypatch)
    assert _enqueue_outcome(window_days=30) is not None
    assert _enqueue_outcome() is not None
    with create_engine(url).connect() as conn:
        rows = conn.execute(
            select(store.outcome_jobs).order_by(store.outcome_jobs.c.window_days)
        ).mappings().all()
    assert [r["window_days"] for r in rows] == [14, 30]
    assert [_utc(r["due_at"]) for r in rows] == [
        datetime(2020, 3, 15, 12, 0, tzinfo=UTC),
        datetime(2020, 3, 31, 12, 0, tzinfo=UTC),
    ]


def test_enqueue_outcome_job_reads_a_redelivery_as_already_queued(tmp_path, monkeypatch):
    """Dedup is the unique index rather than a check-then-insert: two
    deliveries racing a SELECT would both miss it and both insert, giving
    one merge two independent due dates and two votes in a published
    denominator. The collision comes back as None, not as an exception the
    webhook would 500 on."""
    url = _db(tmp_path, monkeypatch)
    assert _enqueue_outcome() is not None
    assert _enqueue_outcome() is None
    with create_engine(url).connect() as conn:
        assert len(conn.execute(select(store.outcome_jobs)).mappings().all()) == 1


def test_enqueue_outcome_jobs_heals_a_legacy_one_window_gap(tmp_path, monkeypatch):
    """A duplicate 14-day identity must not suppress the missing 60-day
    identity. Treating the merge as a single all-or-nothing collision would
    leave the M3 catch-up cohort permanently incomplete on redelivery."""
    url = _db(tmp_path, monkeypatch)
    assert _enqueue_outcome() is not None

    inserted = store.enqueue_outcome_jobs(
        INSTALL, REPO_ID, 42, "a" * 40, MERGED, "main"
    )

    assert set(inserted) == {60}
    with create_engine(url).connect() as conn:
        rows = conn.execute(
            select(store.outcome_jobs).order_by(store.outcome_jobs.c.window_days)
        ).mappings().all()
    assert [row["window_days"] for row in rows] == [14, 60]


def test_enqueue_outcome_jobs_rolls_back_both_windows_when_one_insert_fails(
    tmp_path, monkeypatch
):
    """A 60-day failure must roll back the 14-day insert too; independently
    committed single-row helpers would leave a half-cohort in the ledger."""
    url = _db(tmp_path, monkeypatch)
    store.enabled()
    engine = create_engine(url)
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
        store.enqueue_outcome_jobs(INSTALL, REPO_ID, 42, "a" * 40, MERGED, "main")

    with engine.connect() as conn:
        assert conn.execute(select(store.outcome_jobs)).all() == []


def test_enqueue_outcome_job_re_raises_an_integrity_error_it_did_not_cause(
    tmp_path, monkeypatch
):
    """Only the dedup collision is read as "already queued". Any other
    IntegrityError is a real integrity problem this function did not cause,
    and swallowing it would drop a merge out of the denominator silently —
    the same rule ingest._DEDUPE_COLLISION states, which has a marker test
    and this one did not.

    NOT NULL on base_ref stands in for that class: it is an IntegrityError
    from the same INSERT that is not a uniqueness collision."""
    _db(tmp_path, monkeypatch)
    with pytest.raises(IntegrityError):
        _enqueue_outcome(base_ref=None)


def test_enqueue_outcome_job_is_a_noop_without_a_ledger(monkeypatch):
    """Matches every other webhook-written helper: no database, no row, no
    exception. The webhook's own 503 is what stops that silence from being
    answered as "queued"."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _enqueue_outcome() is None


# --- Deep-read spend cap -------------------------------------------------

def test_record_deep_read_allows_reads_under_the_cap(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert store.record_deep_read("installation:1", cap=3) is True
    assert store.record_deep_read("installation:1", cap=3) is True
    assert store.record_deep_read("installation:1", cap=3) is True


def test_record_deep_read_refuses_once_the_cap_is_reached(tmp_path, monkeypatch):
    """The read that would put a scope over its monthly cap must be refused
    — and refused *before* any model call, since the whole point is COGS
    control, not a receipt that says "over budget" after paying for one
    more read anyway."""
    _db(tmp_path, monkeypatch)
    for _ in range(2):
        assert store.record_deep_read("installation:1", cap=2) is True
    assert store.record_deep_read("installation:1", cap=2) is False
    # And it stays refused — this isn't a one-shot trip.
    assert store.record_deep_read("installation:1", cap=2) is False


def test_record_deep_read_scopes_are_independent(tmp_path, monkeypatch):
    """One installation's spend must never count against another's cap —
    the whole reason this is keyed by scope and not a single global
    counter."""
    _db(tmp_path, monkeypatch)
    for _ in range(2):
        assert store.record_deep_read("installation:1", cap=2) is True
    assert store.record_deep_read("installation:1", cap=2) is False
    assert store.record_deep_read("installation:2", cap=2) is True


def test_record_deep_read_resets_on_a_new_period(tmp_path, monkeypatch):
    """A cap that never resets is not a monthly cap, it's a lifetime ban."""
    _db(tmp_path, monkeypatch)
    jan = datetime(2026, 1, 15, tzinfo=UTC)
    feb = datetime(2026, 2, 1, tzinfo=UTC)
    for _ in range(2):
        assert store.record_deep_read("installation:1", cap=2, now=jan) is True
    assert store.record_deep_read("installation:1", cap=2, now=jan) is False
    assert store.record_deep_read("installation:1", cap=2, now=feb) is True


def test_record_deep_read_is_a_noop_without_a_ledger(tmp_path, monkeypatch):
    """Every other store.py helper degrades to a harmless no-op when
    DATABASE_URL is unset, so local dogfooding needs no database. A cap
    that could never be satisfied without a ledger would silently break
    every uncapped local run — the no-op here has to mean "allowed",
    matching every other disabled-ledger helper's default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.record_deep_read("installation:1", cap=0) is True


def test_record_deep_read_does_not_overshoot_the_cap_under_repeated_calls(tmp_path, monkeypatch):
    """The atomicity that matters: a single `UPDATE ... WHERE count < cap`
    statement, not a read-then-write pair — the same class of
    check-then-act bug this ledger has hit before (the review dedup lookup,
    fixed in the reliability sweep). Calling well past the cap must never
    let the stored count exceed it."""
    _db(tmp_path, monkeypatch)
    results = [store.record_deep_read("installation:1", cap=5) for _ in range(20)]
    assert results == [True] * 5 + [False] * 15
    engine = create_engine(_db(tmp_path, monkeypatch))
    with engine.connect() as conn:
        row = conn.execute(select(store.deep_read_counters)).mappings().one()
    assert row["count"] == 5


def test_save_review_records_the_prompt_hash(tmp_path, monkeypatch):
    """The anchor a receipt or the pre-registration document points at to
    say 'this verdict came from this exact instrument'. Missing it is the
    same class of gap as missing github_repo_id — a fact about the row
    that nothing else on it can reconstruct."""
    url = _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, RV, model=reader.MODEL, prompt_hash=reader.PROMPT_HASH,
    )
    engine = create_engine(url)
    with engine.connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
    assert v["id"] == vid
    assert v["prompt_hash"] == reader.PROMPT_HASH


def test_deep_read_counters_needs_no_migration_on_a_database_that_predates_it(tmp_path):
    """New tables never need a migration entry in this codebase — only new
    columns on an existing table do, because create_all() adds missing
    tables and only migrations.apply() can add a column to one that
    already exists. This proves the mechanism directly: a database built
    before deep_read_counters existed still gets it, the same way
    review_jobs/installations/outcome_jobs did when each was added."""
    from sqlalchemy import create_engine

    from doug import migrations

    url = f"sqlite:///{tmp_path}/pre-existing.db"
    engine = create_engine(url)
    # Simulate "yesterday's" schema: every table but the one this test is
    # about, built the same way store._get_engine() builds a fresh one.
    old_tables = [t for t in store.metadata.sorted_tables if t.name != "deep_read_counters"]
    for table in old_tables:
        table.create(engine, checkfirst=True)
    migrations.schema_migrations.create(engine, checkfirst=True)
    assert "deep_read_counters" not in inspect(engine).get_table_names()

    store.metadata.create_all(engine)  # what _get_engine() does on every call
    assert "deep_read_counters" in inspect(engine).get_table_names()


# --- The neutral-grader lane: third-party reviews as external verdicts -------

SUBMITTED = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)


def _external(**overrides) -> int | None:
    kwargs = {
        "installation_id": INSTALL,
        "github_repo_id": REPO_ID,
        "repo": "o/r",
        "pr_number": 7,
        "head_sha": "a" * 40,
        "source": "review:someone",
        "band": Band.CLEARED,
        "scored_at": SUBMITTED,
        "raw": {"review_id": 1, "state": "approved"},
    }
    kwargs.update(overrides)
    return store.save_external_review(**kwargs)


def test_an_external_review_is_recorded_without_anything_being_scored(
    tmp_path, monkeypatch
):
    """A third-party stance enters the same ledger as Doug's own verdicts so
    the two are adjudicable side by side — but nothing was read and nothing
    was spent, so score and threshold are 0.0 and the tier says so.

    scored_at is the reviewer's submitted_at, not now(): the row is a dated
    claim about when that stance was taken, and a redelivery days later must
    not restate it as today's."""
    url = _db(tmp_path, monkeypatch)
    vid = _external()
    with create_engine(url).connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
        assert conn.execute(select(store.findings)).mappings().all() == []
        assert conn.execute(select(store.reads)).mappings().all() == []
    assert v["id"] == vid
    assert v["tier"] == "external"
    assert v["score"] == 0.0 and v["threshold"] == 0.0
    assert v["band"] == "cleared"
    assert v["source"] == "review:someone"
    assert v["installation_id"] == INSTALL and v["github_repo_id"] == REPO_ID
    assert v["head_sha"] == "a" * 40 and v["pr_number"] == 7
    assert _utc(v["scored_at"]) == SUBMITTED
    assert v["raw"]["review_id"] == 1
    # No pr_meta: an external row describes a stance, not a PR that was read.
    assert v["pr_meta"] is None


def test_a_redelivered_review_is_not_recorded_twice(tmp_path, monkeypatch):
    """GitHub redelivers. The same reviewer, head and timestamp is the same
    stance restated, and counting it twice would double one person's weight
    in any agreement measure taken over this ledger."""
    url = _db(tmp_path, monkeypatch)
    assert _external() is not None
    assert _external() is None
    with create_engine(url).connect() as conn:
        assert len(conn.execute(select(store.verdicts)).mappings().all()) == 1


def test_a_duplicate_left_by_the_tolerated_race_does_not_poison_that_review(
    tmp_path, monkeypatch
):
    """The dedup read is an existence check, not a uniqueness assertion.

    The race this function tolerates — two concurrent deliveries of one
    review both reading before either commits — leaves two rows for one
    identity. `.scalar_one_or_none()` then raised MultipleResultsFound on
    every LATER delivery of that same review, so the tolerated cost was not
    one duplicate row: it was that review's identity 500ing out of the
    webhook, and a 500 is what GitHub redelivers, into the same 500,
    forever. Tolerating a race means surviving what it leaves behind."""
    url = _db(tmp_path, monkeypatch)
    assert _external() is not None
    # Exactly what the race produces: a second row for one identity,
    # written by a delivery that read the table before the first committed.
    with create_engine(url).begin() as conn:
        row = dict(conn.execute(select(store.verdicts)).mappings().one())
        del row["id"]
        conn.execute(store.verdicts.insert(), row)

    assert _external() is None
    with create_engine(url).connect() as conn:
        assert len(conn.execute(select(store.verdicts)).mappings().all()) == 2


def test_save_external_review_is_a_noop_without_a_ledger(monkeypatch):
    """Its siblings — upsert_installation, set_installation_repos,
    enqueue_outcome_job — all degrade to a no-op without DATABASE_URL, and
    the webhook's 503 is what stops that silence from being read as
    "queued". Raising here instead would make the review lane the one
    handler that cannot run on a ledger-less deployment."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _external() is None


def test_a_reviewer_changing_their_mind_appends_rather_than_replacing(
    tmp_path, monkeypatch
):
    """approve then changes_requested on the same commit is two real stances
    at two times, not a correction of one. The ledger is append-only dated
    claims, so both rows stay — which is also what makes the dedup above
    key on scored_at rather than on the reviewer alone."""
    url = _db(tmp_path, monkeypatch)
    _external()
    later = SUBMITTED.replace(hour=11)
    _external(band=Band.FLAGGED, scored_at=later, raw={"review_id": 2})
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.verdicts).order_by(store.verdicts.c.id)).mappings().all()
    assert [r["band"] for r in rows] == ["cleared", "flagged"]


def test_two_reviewers_on_one_commit_are_two_rows(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _external(source="review:alice")
    _external(source="review:bob")
    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.verdicts)).mappings().all()
    assert sorted(r["source"] for r in rows) == ["review:alice", "review:bob"]


# --- External rows must never displace Doug's own verdict --------------------


def _doug_verdict(**overrides) -> int | None:
    kwargs = {
        "repo": "o/r",
        "pr_number": 7,
        "tier": "reader",
        "verdict": VERDICT,
        "reader_verdict": RV,
        "model": reader.MODEL,
        "github_repo_id": REPO_ID,
        "installation_id": INSTALL,
        "head_sha": "a" * 40,
        "source": "app",
        "pr_meta": {"number": 7, "title": "t", "author": "a", "files": [], "head_sha": "a" * 40},
    }
    kwargs.update(overrides)
    return store.save_review(**kwargs)


def test_an_external_review_never_answers_the_workers_idempotency_read(
    tmp_path, monkeypatch
):
    """find_verdict_by_identity keys on exactly the four columns an external
    row also carries — head_sha included, because a review names the commit
    it was left on. Without the tier filter, a human approving PR #7 at SHA
    X makes worker.process_job believe SHA X was already reviewed: Doug
    never reads that commit, and the check run renders a score=0.0 row as if
    it were Doug's own verdict.

    Ordering is id desc, so this is not a race — it is the steady state for
    any PR a person reviews after Doug does."""
    _db(tmp_path, monkeypatch)
    _doug_verdict()
    _external()
    found = store.find_verdict_by_identity(INSTALL, REPO_ID, 7, "a" * 40)
    assert found is not None
    assert found["tier"] == "reader"
    assert found["score"] == VERDICT.score


def test_an_external_review_arriving_first_does_not_suppress_dougs_review(
    tmp_path, monkeypatch
):
    """The other direction: a reviewer who approves before Doug's job runs
    must not make that job think its work is already done. The job would be
    completed against a verdict nobody scored."""
    _db(tmp_path, monkeypatch)
    _external()
    assert store.find_verdict_by_identity(INSTALL, REPO_ID, 7, "a" * 40) is None


# find_verdict_by_id itself has no direct caller in this suite — it is
# worker.py's race-loser fallback, reached only when find_verdict_by_identity
# misses twice in the same job (pre-read, then the post-collision re-check).
# test_a_race_loser_replays_the_peer_and_does_not_attach_local_deviations in
# test_worker.py exercises that branch, but the identity re-check there
# always resolves before falling through, so find_verdict_by_id's own query
# is never actually invoked by any existing test (confirmed empirically: a
# call counter placed inside it stayed at zero across the whole worker and
# store suites). The two tests below pin it directly — required by the
# _load_verdict_row extraction, which must not change what this returns.


def test_find_verdict_by_id_returns_the_bundle_for_a_known_id(tmp_path, monkeypatch):
    """The durable handle worker.py falls back to when the identity re-read
    misses. Must return the same check-run bundle find_verdict_by_identity
    would — tier/score/reasons — and, being the check-run path, none of the
    provenance run_detail exists to add back."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    found = store.find_verdict_by_id(vid)
    assert found["tier"] == "reader"
    assert found["score"] == VERDICT.score
    assert found["reasons"][0]["rule"] == "reader:race-condition"
    # the check-run bundle's deliberate omission — this is what run_detail
    # exists to add back for the forensic page, not what this path returns
    assert "model" not in found


def test_find_verdict_by_id_returns_none_for_an_unknown_id(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert store.find_verdict_by_id(4242) is None


def test_an_external_review_does_not_take_a_pr_off_the_queue(tmp_path, monkeypatch):
    """latest_reviews groups by (repo, pr) and takes max(id). An external row
    is newer than Doug's, so filtering only the outer query would drop the PR
    from /v1/queue entirely rather than falling back — the subquery has to
    exclude external rows before the max is taken."""
    _db(tmp_path, monkeypatch)
    _doug_verdict()
    _external()
    rows = store.latest_reviews()
    assert [r["pr_number"] for r in rows] == [7]
    assert rows[0]["tier"] == "reader"
    assert rows[0]["score"] == VERDICT.score


def test_find_review_ignores_external_rows(tmp_path, monkeypatch):
    """Belt and braces. find_review matches pr_meta['head_sha'] as a JSON
    key and external rows write no pr_meta, so it is already immune —
    incidentally, not by design. The exclusion is explicit so that immunity
    does not evaporate the day someone writes pr_meta on an external row."""
    _db(tmp_path, monkeypatch)
    _doug_verdict(installation_id=None, github_repo_id=None, source=None)
    _external(raw={"review_id": 3})
    prior = store.find_review("o/r", 7, "a" * 40)
    assert prior is not None and prior["tier"] == "reader"


def test_find_review_still_ignores_an_external_row_that_carries_pr_meta(
    tmp_path, monkeypatch
):
    """The test above cannot fail if find_review's tier filter is deleted —
    external rows write no pr_meta, so its JSON predicate is NULL for them
    and never matches either way. That makes the filter's value invisible to
    every other test here, which is how a guard gets "cleaned up" later.

    So this one writes the row the incidental immunity does not cover: an
    external verdict carrying CI identity and pr_meta with a matching
    head_sha. Only the explicit tier exclusion keeps the CI verdict winning,
    and deleting it fails exactly this test."""
    url = _db(tmp_path, monkeypatch)
    _doug_verdict(installation_id=None, github_repo_id=None, source=None)
    with create_engine(url).begin() as conn:
        conn.execute(
            store.verdicts.insert(),
            {
                "repo": "o/r",
                "pr_number": 7,
                "scored_at": SUBMITTED,
                "tier": "external",
                "score": 0.0,
                "band": "cleared",
                "threshold": 0.0,
                "installation_id": None,
                "github_repo_id": None,
                "head_sha": "a" * 40,
                "source": "review:someone",
                "pr_meta": {"head_sha": "a" * 40},
            },
        )
    prior = store.find_review("o/r", 7, "a" * 40)
    assert prior is not None and prior["tier"] == "reader"


def test_an_external_review_does_not_erase_a_prs_findings_from_precision(
    tmp_path, monkeypatch
):
    """pattern_join takes the same max(id) per (repo, pr) that latest_reviews
    does, and feeds the published per-pattern precision. An external row
    winning that max leaves the PR in the denominator while contributing no
    findings to the numerator — every pattern that PR actually carried would
    silently stop counting as a hit."""
    url = _db(tmp_path, monkeypatch)
    _doug_verdict()
    _external()
    with create_engine(url).begin() as conn:
        conn.execute(
            store.outcomes.insert(),
            {
                "repo": "o/r",
                "pr_number": 7,
                "kind": "revert",
                "observed_at": datetime.now(UTC),
                "source": "git-labels",
            },
        )
    joined = store.pattern_join()
    assert [(p["repo"], p["pr_number"]) for p in joined["prs"]] == [("o/r", 7)]
    assert [h["rule"] for h in joined["hits"]] == ["reader:race-condition"]


def _scored(repo, pr, installation_id, score=0.5, github_repo_id=None):
    """One verdict row, App-identified or CI-identified (installation None)."""
    return store.save_review(
        repo,
        pr,
        "reader",
        Verdict(score=score, band=Band.FLAGGED, threshold=0.30, reasons=[]),
        pr_meta=_pr().model_dump(),
        installation_id=installation_id,
        github_repo_id=(
            github_repo_id if github_repo_id is not None else (1 if installation_id else None)
        ),
        head_sha=("a" * 40) if installation_id else None,
        source="app" if installation_id else "ci",
    )


def test_latest_reviews_scopes_to_one_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _scored("drewjst/doug", 1, 150424894)
    _scored("someone/else", 2, 777)
    rows = store.latest_reviews(installation_id=150424894)
    assert [r["repo"] for r in rows] == ["drewjst/doug"]


def test_latest_reviews_unscoped_still_sees_everything(tmp_path, monkeypatch):
    """The operator path must not change at all — doug-web and the soak
    both read through it."""
    _db(tmp_path, monkeypatch)
    _scored("drewjst/doug", 1, 150424894)
    _scored("someone/else", 2, 777)
    assert len(store.latest_reviews()) == 2


def test_scoped_queue_falls_back_to_the_app_row_under_a_newer_ci_row(tmp_path, monkeypatch):
    """THE regression test for this change.

    latest_reviews picks max(id) GROUP BY (repo, pr_number) in a subquery.
    Filter installation_id OUTSIDE that subquery and the CI row — written
    second, so higher id, and carrying installation_id NULL — wins max(id)
    for the PR and is then dropped, so the PR VANISHES from the tenant's
    queue instead of falling back to their own App verdict. Disappearing is
    a strictly worse failure than the one being fixed, and the function's
    own docstring already records this exact trap for the external-tier
    filter. If this test fails, the filter moved outside the subquery.
    """
    _db(tmp_path, monkeypatch)
    app_id = _scored("drewjst/doug", 1, 150424894, score=0.61)
    ci_id = _scored("drewjst/doug", 1, None, score=0.42)
    assert ci_id > app_id, "the CI row must be the newer one for this test to mean anything"

    rows = store.latest_reviews(installation_id=150424894)
    assert len(rows) == 1, "the PR vanished — the filter is outside the subquery"
    assert rows[0]["id"] == app_id
    assert rows[0]["score"] == 0.61


def test_latest_reviews_repo_ids_filter_is_inside_the_grouped_subquery(tmp_path, monkeypatch):
    """latest_reviews picks max(id) GROUP BY (repo, pr_number) in a subquery.
    Filter repo_ids OUTSIDE that subquery and an out-of-selection row on the
    SAME (repo, pr_number) — written second, so higher id — wins max(id) for
    the PR and is then dropped, so the PR VANISHES instead of falling back
    to the in-scope row. Same trap, same shape, as
    test_scoped_queue_falls_back_to_the_app_row_under_a_newer_ci_row above.
    If this test fails, the filter moved outside the subquery.
    """
    _db(tmp_path, monkeypatch)
    in_scope_id = _scored("drewjst/doug", 1, 150424894, score=0.61, github_repo_id=111)
    out_of_scope_id = _scored("drewjst/doug", 1, 150424894, score=0.42, github_repo_id=222)
    assert out_of_scope_id > in_scope_id, "the out-of-selection row must be the newer one"

    rows = store.latest_reviews(installation_id=150424894, repo_ids={111})
    assert len(rows) == 1, "the PR vanished — the filter is outside the subquery"
    assert rows[0]["id"] == in_scope_id
    assert rows[0]["score"] == 0.61


def test_run_history_returns_every_run_for_a_pr_not_just_the_latest(tmp_path, monkeypatch):
    """The defining difference from latest_reviews. A PR pushed three times
    is three runs; a console that collapses them cannot answer "what did
    Doug do on this push" — which is the whole point of the page."""
    _db(tmp_path, monkeypatch)
    for sha in ("a" * 40, "b" * 40, "c" * 40):
        store.save_review(
            "o/r", 7, "reader", VERDICT,
            github_repo_id=1, installation_id=99, head_sha=sha, source="app",
        )
    rows = store.run_history()
    assert len(rows) == 3
    assert {r["head_sha"] for r in rows} == {"a" * 40, "b" * 40, "c" * 40}
    assert store.latest_reviews() and len(store.latest_reviews()) == 1


def test_run_history_carries_repo_and_installation(tmp_path, monkeypatch):
    """The field latest_reviews drops. Without it the console cannot group
    per repo, which is the reported gap."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    row = store.run_history()[0]
    assert row["repo"] == "o/r"
    assert row["installation_id"] == 99
    assert row["github_repo_id"] == 1


def test_run_history_excludes_untenanted_rows_by_default(tmp_path, monkeypatch):
    """Backfilled probe corpora, CLI rows and the research quarantine all
    carry no installation_id. Including them would flood the console with
    thousands of rows that are not tenant traffic — the exact failure
    DOUG_QUEUE_REPO exists to paper over on doug-web."""
    _db(tmp_path, monkeypatch)
    store.save_review("o/r", 1, "reader", VERDICT)  # no installation — CLI/backfill
    store.save_review(
        "o/r", 2, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    assert [r["pr_number"] for r in store.run_history()] == [2]
    assert {r["pr_number"] for r in store.run_history(include_untenanted=True)} == {1, 2}


def test_run_history_excludes_external_tier(tmp_path, monkeypatch):
    """External rows are other reviewers' verdicts, not Doug's runs."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, store.EXTERNAL_TIER, VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40,
    )
    assert store.run_history() == []


def test_run_history_scopes_by_repo_and_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/one", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=11, head_sha="a" * 40, source="app",
    )
    store.save_review(
        "o/two", 2, "reader", VERDICT,
        github_repo_id=2, installation_id=22, head_sha="b" * 40, source="app",
    )
    assert [r["repo"] for r in store.run_history(repo="o/one")] == ["o/one"]
    assert [r["installation_id"] for r in store.run_history(installation_id=22)] == [22]


def test_run_history_paginates_newest_first(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    base = datetime(2026, 8, 1, tzinfo=UTC)
    for n in range(5):
        vid = store.save_review(
            "o/r", n, "reader", VERDICT,
            github_repo_id=1, installation_id=99, head_sha=str(n) * 40, source="app",
        )
        engine = store._get_engine()
        with engine.begin() as conn:
            conn.execute(
                store.verdicts.update()
                .where(store.verdicts.c.id == vid)
                .values(scored_at=base + timedelta(hours=n))
            )
    assert [r["pr_number"] for r in store.run_history(limit=2)] == [4, 3]
    assert [r["pr_number"] for r in store.run_history(limit=2, offset=2)] == [2, 1]


def test_run_history_attaches_coverage_without_duplicating_runs(tmp_path, monkeypatch):
    """Two reads on one verdict must not become two runs. A plain outerjoin
    fans out here, and a duplicated run reads as a real second review."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
        coverage=store.Coverage(
            diff_chars=1000, sent_chars=170, files_sent=4,
            files_unseen=["tenancy.py"], file_cut="api.py",
        ),
    )
    store.save_read(vid, store.Coverage(
        diff_chars=1200, sent_chars=900, files_sent=20,
        files_unseen=[], file_cut=None,
    ))
    rows = store.run_history()
    assert len(rows) == 1
    assert rows[0]["coverage"]["files_sent"] == 20
    assert rows[0]["coverage"]["diff_chars"] == 1200


def test_run_history_coverage_is_none_for_the_deterministic_tier(tmp_path, monkeypatch):
    """No read happened, so there is no coverage. This must be None and
    render as "no read" — never as 0%, which would read as a total miss."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, "deterministic", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    assert store.run_history()[0]["coverage"] is None


def test_run_history_counts_findings_by_severity(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    verdict = Verdict(
        score=0.8, band=Band.FLAGGED, threshold=0.62,
        reasons=[
            Reason(rule="reader:a", label="a", weight=0.0, severity="high"),
            Reason(rule="reader:b", label="b", weight=0.0, severity="low"),
            Reason(rule="reader:c", label="c", weight=0.0, severity="low"),
        ],
    )
    store.save_review(
        "o/r", 1, "reader", verdict,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    counts = store.run_history()[0]["finding_counts"]
    assert counts == {"total": 3, "high": 1, "medium": 0, "low": 2}


def test_run_history_attaches_the_review_job(tmp_path, monkeypatch):
    """The job row is the "what did Doug do" record: attempts and error are
    the only place a failed run explains itself."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.review_jobs.insert().values(
            installation_id=99, github_repo_id=1, repo_full_name="o/r",
            pr_number=1, head_sha="a" * 40, status="done", attempts=2,
            enqueued_at=datetime(2026, 8, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 1, 0, 0, 41, tzinfo=UTC),
            verdict_id=vid,
        ))
    job = store.run_history()[0]["job"]
    assert job["status"] == "done"
    assert job["attempts"] == 2


def test_run_history_reports_only_the_14_day_outcome(tmp_path, monkeypatch):
    """Both windows exist for a merged PR. The list column is the 14d one;
    joining both would fan the run out into two rows."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        for window, kind in ((14, "clean"), (60, "revert")):
            conn.execute(store.outcomes.insert().values(
                repo="o/r", pr_number=1, kind=kind, window_days=window,
                observed_at=datetime(2026, 8, 15, tzinfo=UTC), source="git-labels",
                github_repo_id=1, installation_id=99,
            ))
    rows = store.run_history()
    assert len(rows) == 1
    assert rows[0]["outcome_14"] == "clean"


def test_run_history_outcome_is_none_before_the_window_closes(tmp_path, monkeypatch):
    """Ungraded is not clean. The console must render these differently."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 1, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    assert store.run_history()[0]["outcome_14"] is None


def test_run_history_scoped_row_uses_only_its_installation_and_repo_outcome(
    tmp_path, monkeypatch
):
    """Same display repo/PR is not identity. A session row must not borrow the
    newest outcome from another installation or a sibling repository id."""
    _db(tmp_path, monkeypatch)
    store.save_review(
        "shared/repo", 7, "reader", VERDICT,
        github_repo_id=11, installation_id=101, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        for installation_id, github_repo_id, kind in (
            (101, 11, "clean"),
            (202, 11, "revert"),
            (101, 12, "hotfix"),
        ):
            conn.execute(store.outcomes.insert().values(
                repo="shared/repo", pr_number=7, kind=kind, window_days=14,
                observed_at=datetime(2026, 8, 17, tzinfo=UTC), source="manual",
                github_repo_id=github_repo_id, installation_id=installation_id,
            ))

    rows = store.run_history(
        installation_id=101, repo_ids=frozenset({11})
    )

    assert len(rows) == 1
    assert rows[0]["outcome_14"] == "clean"


# --- run_detail (the forensic bundle for one run) ---


def test_run_detail_carries_the_fields_the_check_run_bundle_drops(tmp_path, monkeypatch):
    """_verdict_bundle serves the check run and omits provenance on purpose.
    The forensic page is the opposite need: model, prompt hash and rationale
    ARE the answer to "what did Doug do"."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, reader_verdict=RV, model="claude-opus-5",
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
        prompt_hash="a3f9e2c1",
    )
    detail = store.run_detail(vid)
    assert detail["repo"] == "o/r"
    assert detail["pr_number"] == 7
    assert detail["model"] == "claude-opus-5"
    assert detail["prompt_hash"] == "a3f9e2c1"
    assert detail["risk_score"] == 62
    assert detail["rationale"] == "Unlocked cache write."
    assert detail["source"] == "app"
    assert detail["head_sha"] == "a" * 40
    # and still everything the bundle already gave
    assert detail["reasons"][0]["rule"] == "reader:race-condition"


def test_run_detail_returns_none_for_an_unknown_id(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert store.run_detail(4242) is None


def test_run_detail_attaches_the_job_including_its_error(tmp_path, monkeypatch):
    """A failed run explains itself nowhere else."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.review_jobs.insert().values(
            installation_id=99, github_repo_id=1, repo_full_name="o/r",
            pr_number=7, head_sha="a" * 40, status="failed", attempts=3,
            claim_generation=3, error="reader timeout after 60s",
            enqueued_at=datetime(2026, 8, 1, tzinfo=UTC), verdict_id=vid,
        ))
    job = store.run_detail(vid)["job"]
    assert job["status"] == "failed"
    assert job["attempts"] == 3
    assert job["claim_generation"] == 3
    assert job["error"] == "reader timeout after 60s"


def test_run_detail_returns_both_outcome_windows_separately(tmp_path, monkeypatch):
    """The 14d and 60d clocks are different claims with different dates, and
    the page shows them side by side. Collapsing them loses the censoring
    story."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(store.outcomes.insert().values(
            repo="o/r", pr_number=7, kind="clean", window_days=14,
            observed_at=datetime(2026, 8, 17, tzinfo=UTC), source="git-labels",
            github_repo_id=1, installation_id=99,
        ))
        conn.execute(store.outcome_jobs.insert().values(
            installation_id=99, github_repo_id=1, pr_number=7,
            merge_commit_sha="b" * 40, merged_at=datetime(2026, 8, 3, tzinfo=UTC),
            base_ref="main", window_days=60,
            due_at=datetime(2026, 10, 2, tzinfo=UTC), status="pending",
            created_at=datetime(2026, 8, 3, tzinfo=UTC),
        ))
    detail = store.run_detail(vid)
    assert [o["window_days"] for o in detail["outcomes"]] == [14]
    assert detail["outcomes"][0]["kind"] == "clean"
    assert [j["window_days"] for j in detail["outcome_jobs"]] == [60]
    assert detail["outcome_jobs"][0]["status"] == "pending"


def test_run_detail_scopes_outcomes_and_jobs_to_the_verdict_identity(
    tmp_path, monkeypatch
):
    """Same display repo/PR and even the same numeric repo id can exist under
    another installation. Child evidence must use the verdict's full identity
    before any row is assembled."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "shared/repo", 7, "reader", VERDICT,
        github_repo_id=11, installation_id=101, head_sha="a" * 40, source="app",
    )
    engine = store._get_engine()
    with engine.begin() as conn:
        for installation_id, github_repo_id, kind, window in (
            (101, 11, "clean", 14),
            (202, 11, "revert", 60),
            (101, 12, "hotfix", 30),
        ):
            conn.execute(store.outcomes.insert().values(
                repo="shared/repo", pr_number=7, kind=kind, window_days=window,
                observed_at=datetime(2026, 8, 17, tzinfo=UTC), source="manual",
                github_repo_id=github_repo_id, installation_id=installation_id,
            ))
            conn.execute(store.outcome_jobs.insert().values(
                installation_id=installation_id, github_repo_id=github_repo_id,
                pr_number=7, merge_commit_sha=str(window) * 20,
                merged_at=datetime(2026, 8, 3, tzinfo=UTC), base_ref="main",
                window_days=window, due_at=datetime(2026, 10, 2, tzinfo=UTC),
                status="pending", created_at=datetime(2026, 8, 3, tzinfo=UTC),
            ))

    detail = store.run_detail(
        vid, installation_id=101, repo_ids=frozenset({11})
    )

    assert detail is not None
    assert [(row["kind"], row["window_days"]) for row in detail["outcomes"]] == [
        ("clean", 14)
    ]
    assert [row["window_days"] for row in detail["outcome_jobs"]] == [14]


def test_run_detail_never_surfaces_the_no_deviations_marker(tmp_path, monkeypatch):
    """save_deviations writes a kind="none" row to record "the read ran and
    found nothing". It is a storage marker, never a finding. If it reached
    the page it would render as a deviation named "none" — Doug reporting a
    problem it explicitly did not find."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    # signature: (verdict_id, findings, intent_refs, intent_alignment)
    store.save_deviations(vid, [], intent_refs=[], intent_alignment=100)
    detail = store.run_detail(vid)
    assert detail["deviations"] == []
    # The row exists — "read happened, found nothing" stays distinguishable
    # from "no read happened", which is why the marker is written at all.
    assert detail["intent_alignment"] == 100


def test_run_detail_exposes_pr_meta_for_the_coverage_denominator(tmp_path, monkeypatch):
    """changed_files lives on pr_meta and is the only correct denominator.
    Without it on the detail payload the page would fall back to
    len(files_unseen) + files_sent, which is not the true file count."""
    _db(tmp_path, monkeypatch)
    meta = PRMetadata(
        number=7, title="t", author="a", files=["one.py"], changed_files=23,
        files_dropped=["uv.lock"],
    )
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, pr_meta=meta.model_dump(),
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    detail = store.run_detail(vid)
    assert detail["pr_meta"]["changed_files"] == 23
    assert detail["pr_meta"]["files_dropped"] == ["uv.lock"]


def test_run_detail_reports_no_job_and_no_outcomes_as_empty_not_missing(
    tmp_path, monkeypatch
):
    """A run with no review_jobs row and no outcomes/outcome_jobs rows is the
    common case (most PRs are still open, most jobs are pre-Task-6 CI rows).
    "no job" must stay None and "no outcomes yet" must stay [] — 'empty is
    not zero' is a standing constraint, and a job silently defaulting to {}
    or an outcome list silently gaining a phantom row would both pass any
    assertion that only checks truthiness."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    detail = store.run_detail(vid)
    assert detail["job"] is None
    assert detail["outcomes"] == []
    assert detail["outcome_jobs"] == []


def test_run_detail_carries_scored_at_and_app_identity(tmp_path, monkeypatch):
    """The remaining passthrough columns _verdict_bundle also drops: when
    the run happened and which installation/repo id it belongs to. Task 5
    serialises this bundle whole, so a dropped or misspelled key here would
    otherwise pass silently — the brief's own carries-the-fields test does
    not touch these three."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    detail = store.run_detail(vid)
    assert detail["scored_at"] is not None
    assert detail["installation_id"] == 99
    assert detail["github_repo_id"] == 1


def test_run_detail_tolerates_a_null_pr_meta(tmp_path, monkeypatch):
    """save_review defaults pr_meta to None (CLI callers, pre-App rows). A
    task earlier in this build crashed on exactly this column being null;
    run_detail must pass it through as None, not assume it can be indexed."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT,
        github_repo_id=1, installation_id=99, head_sha="a" * 40, source="app",
    )
    assert store.run_detail(vid)["pr_meta"] is None


# --- installation_tokens (tenant API keys spec, 2026-08-04) ---


def _seed_install(installation_id=150424894):
    store.upsert_installation(installation_id, "drewjst", "User", "active")


def test_insert_installation_token_requires_an_installation_row(tmp_path, monkeypatch):
    """No installations row means Doug was never installed there — a key
    minted anyway would resolve to an id no tenancy backs (PR #48 semantics,
    kept)."""
    _db(tmp_path, monkeypatch)
    assert (
        store.insert_installation_token(
            999,
            token_lookup="AAAAAAAA",
            token_hash="ab" * 32,
            hash_version=1,
            last4="wxyz",
            label=None,
            repo_selection="all",
            scopes=["queue:read"],
            minted_by="drewjst",
            expires_at=None,
        )
        is None
    )


def test_token_row_round_trips_with_installation_state(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install()
    token_id = store.insert_installation_token(
        150424894,
        token_lookup="AAAAAAAA",
        token_hash="ab" * 32,
        hash_version=1,
        last4="wxyz",
        label="ci",
        repo_selection="selected",
        scopes=["queue:read"],
        minted_by="drewjst",
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )
    assert isinstance(token_id, int)
    store.set_installation_token_repos(token_id, [111, 222])
    row = store.installation_token_by_lookup("AAAAAAAA")
    assert row["id"] == token_id
    assert row["installation_state"] == "active"
    assert row["repo_selection"] == "selected"
    assert row["hash_version"] == 1
    assert row["expires_at"].tzinfo is not None, "sqlite naive datetimes must be normalized"
    assert store.installation_token_repo_ids(token_id) == {111, 222}
    assert store.installation_token_by_lookup("NOPENOPE") is None


def test_second_token_does_not_disturb_the_first(tmp_path, monkeypatch):
    """Mint appends. The single-column model's silent rotation was half of
    MT5; two rows must coexist."""
    _db(tmp_path, monkeypatch)
    _seed_install()
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    a = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    b = store.insert_installation_token(150424894, token_lookup="BBBBBBBB", **kw)
    assert a != b
    assert store.installation_token_by_lookup("AAAAAAAA")["id"] == a
    assert store.installation_token_by_lookup("BBBBBBBB")["id"] == b


def test_mint_count_since_counts_only_this_installation(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install(150424894)
    _seed_install(999999999)
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    store.insert_installation_token(999999999, token_lookup="BBBBBBBB", **kw)
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    assert store.count_installation_tokens_minted_since(150424894, midnight) == 1


def test_mint_count_returns_none_when_storage_off(monkeypatch):
    """None, not 0: the caller treats None as 'cannot count' and allows —
    the cap is fail-open by spec."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.count_installation_tokens_minted_since(150424894, datetime.now(UTC)) is None


def test_migration_6_applies_on_fresh_and_legacy_shapes(tmp_path, monkeypatch):
    """Fresh DB: create_all builds installations WITHOUT token_hash, so the
    DROP finds its work done and must not raise (the 'satisfied, not failed'
    rule). Legacy DB: the column exists and is dropped."""
    from sqlalchemy import create_engine

    from doug import migrations

    _db(tmp_path, monkeypatch)
    store._get_engine()  # create_all + apply on the fresh path — must not raise
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE installations (id INTEGER PRIMARY KEY, "
            "installation_id BIGINT NOT NULL UNIQUE, account_login VARCHAR(200), "
            "account_type VARCHAR(20), state VARCHAR(20) NOT NULL, "
            "updated_at TIMESTAMP NOT NULL, token_hash TEXT)"
        )
    # Production calls create_all before migrations.apply. It leaves the
    # legacy installations table untouched while creating every other table
    # later migrations legitimately reference.
    store.metadata.create_all(engine)
    migrations.apply(engine)
    assert "token_hash" not in {c["name"] for c in inspect(engine).get_columns("installations")}


def test_list_tokens_masks_the_hash_and_orders_newest_first(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install()
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    a = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    b = store.insert_installation_token(150424894, token_lookup="BBBBBBBB", **kw)
    rows = store.list_installation_tokens(150424894)
    assert [r["id"] for r in rows] == [b, a]
    assert all("token_hash" not in r for r in rows)


def test_revoke_is_ownership_scoped_and_idempotent(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install(150424894)
    _seed_install(999999999)
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    token_id = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    # Foreign installation id in the WHERE → no match, indistinguishable from absent.
    assert store.revoke_installation_token(token_id, 999999999) is False
    assert store.installation_token_by_lookup("AAAAAAAA")["revoked_at"] is None
    assert store.revoke_installation_token(token_id, 150424894) is True
    first_stamp = store.installation_token_by_lookup("AAAAAAAA")["revoked_at"]
    assert store.revoke_installation_token(token_id, 150424894) is True  # idempotent
    assert store.installation_token_by_lookup("AAAAAAAA")["revoked_at"] == first_stamp


def test_revoke_all_stamps_only_live_keys(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _seed_install()
    kw = dict(
        token_hash="ab" * 32, hash_version=1, last4="wxyz", label=None,
        repo_selection="all", scopes=["queue:read"], minted_by="drewjst",
        expires_at=None,
    )
    a = store.insert_installation_token(150424894, token_lookup="AAAAAAAA", **kw)
    store.insert_installation_token(150424894, token_lookup="BBBBBBBB", **kw)
    store.revoke_installation_token(a, 150424894)
    stamp_a = store.installation_token_by_lookup("AAAAAAAA")["revoked_at"]
    assert store.revoke_all_installation_tokens(150424894) == 1  # only B was live
    assert store.installation_token_by_lookup("AAAAAAAA")["revoked_at"] == stamp_a
    assert store.installation_token_by_lookup("BBBBBBBB")["revoked_at"] is not None


# --- Startup drift diagnostics (Task 11) ------------------------------------


def test_count_installations_referenced_by_verdicts(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _scored("drewjst/a", 1, 150424894, github_repo_id=111)
    _scored("drewjst/a", 2, 150424894, github_repo_id=111)
    _scored("ci/x", 3, None)  # installation_id and github_repo_id both NULL
    assert store.count_installations_referenced_by_verdicts() == 1


def test_missing_from_ledger_is_zero_when_the_pair_is_covered(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(150424894, [(111, "drewjst/a")], replace=False)
    _scored("drewjst/a", 1, 150424894, github_repo_id=111)
    assert store.count_verdict_repos_missing_from_ledger() == 0


def test_missing_from_ledger_counts_a_repo_the_ledger_never_heard_of(tmp_path, monkeypatch):
    """No installation_repos row at all for this (installation, repo) pair —
    the repositories_added webhook never arrived. Two verdicts on the same
    pair (two PRs) must still count as one missing pair, not two."""
    _db(tmp_path, monkeypatch)
    _scored("drewjst/gone", 1, 150424894, github_repo_id=333)
    _scored("drewjst/gone", 2, 150424894, github_repo_id=333)
    assert store.count_verdict_repos_missing_from_ledger() == 1


def test_missing_from_ledger_ignores_ci_rows(tmp_path, monkeypatch):
    """A CI verdict carries installation_id=None and github_repo_id=None —
    neither identifies a tenant repo, so it must not be read as a missing
    pair."""
    _db(tmp_path, monkeypatch)
    _scored("ci/x", 1, None)
    assert store.count_verdict_repos_missing_from_ledger() == 0


def test_missing_from_ledger_treats_a_removed_row_as_covered(tmp_path, monkeypatch):
    """A 'removed' installation_repos row is deliberate coverage-ending,
    recorded by a delivery that DID arrive — the opposite of the MT0-class
    drift this helper exists to catch. Only a row's total absence counts."""
    _db(tmp_path, monkeypatch)
    store.set_installation_repos(
        150424894, [(111, "drewjst/a")], replace=False, state="removed"
    )
    _scored("drewjst/a", 1, 150424894, github_repo_id=111)
    assert store.count_verdict_repos_missing_from_ledger() == 0


# --- store.job_health — the console strip's only data source. Every test here
# pins a way the aggregate could claim something the ledger does not say.


def _health(url, **kw):
    """Call job_health with the real lane constants, the way api.py does."""
    return store.job_health(
        review_lease_seconds=ingest.STALL_LEASE_SECONDS,
        review_max_attempts=ingest.MAX_ATTEMPTS,
        outcome_lease_seconds=outcome_queue.STALL_LEASE_SECONDS,
        outcome_max_attempts=outcome_queue.MAX_ATTEMPTS,
        **kw,
    )


def test_job_health_excludes_superseded_from_every_count(tmp_path, monkeypatch):
    """A superseded job is neither done nor failed and nothing went wrong —
    ingest.supersede() lands it revivable on purpose. Counting it is the
    single easiest way to make the strip cry wolf, so it must appear in no
    count at all."""
    _db(tmp_path, monkeypatch)
    job_id = _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.supersede(job_id, claim_generation=claimed["claim_generation"])

    health = _health(None)

    assert health["review"]["pending"] == 0
    assert health["review"]["running"] == 0
    assert health["review"]["failed"] == 0
    assert health["review"]["retrying"] == 0


def test_job_health_does_not_report_a_retried_job_as_freshly_pending(
    tmp_path, monkeypatch
):
    """ingest.fail() below the cap sets enqueued_at = now, deliberately, so
    the retry goes to the BACK of the queue instead of burning every attempt
    in one pass. A naive MIN(enqueued_at) over all pending rows therefore
    reports a twice-failed job as brand new — blind to exactly the jobs most
    likely to be in trouble. oldest_pending_at must see attempts = 0 only."""
    _db(tmp_path, monkeypatch)
    _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.fail(claimed["id"], "boom", claim_generation=claimed["claim_generation"])

    health = _health(None)

    # It is pending, and it is retrying, and those are different facts.
    assert health["review"]["pending"] == 1
    assert health["review"]["retrying"] == 1
    # No fresh-pending row exists, so there is no fresh-pending age to report.
    assert health["review"]["oldest_pending_at"] is None
    # The retry has its own age, which means "when the last attempt gave up".
    assert health["review"]["oldest_retry_at"] is not None


def test_job_health_measures_each_lane_against_its_own_lease(
    tmp_path, monkeypatch
):
    """ingest's lease is 900s; outcome_queue's is 7200s. A claim 20 minutes
    old is stalled in the review lane and perfectly healthy in the outcome
    lane. One shared lease constant would alarm on the healthy one."""
    _db(tmp_path, monkeypatch)
    twenty_min_ago = _dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=20)

    _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    _force_started_at(store.review_jobs, claimed["id"], twenty_min_ago)

    outcome_id = store.enqueue_outcome_jobs(
        99, 1, 7, "b" * 40, twenty_min_ago, "main", window_days=(14,)
    )[14]
    _force_running(store.outcome_jobs, outcome_id, twenty_min_ago)

    health = _health(None)

    assert health["review"]["stalled"] == 1
    assert health["outcome"]["stalled"] == 0


def test_job_health_reports_the_lane_constants_it_measured_with(
    tmp_path, monkeypatch
):
    """The console renders 'attempts 4/10' and computes nothing against a
    lease it holds locally. If a constant moves, the UI must follow rather
    than silently disagree with the sweep that enforces it."""
    _db(tmp_path, monkeypatch)

    health = _health(None)

    assert health["review"]["stall_lease_seconds"] == ingest.STALL_LEASE_SECONDS
    assert health["review"]["max_attempts"] == ingest.MAX_ATTEMPTS
    assert health["outcome"]["stall_lease_seconds"] == outcome_queue.STALL_LEASE_SECONDS
    assert health["outcome"]["max_attempts"] == outcome_queue.MAX_ATTEMPTS


def test_job_health_separates_overdue_from_next_due(tmp_path, monkeypatch):
    """next_due_at is the earliest clock still in the future;
    oldest_overdue_due_at is the earliest already past. Blending them would
    make 'the next clock' read as an alarm or an alarm read as a schedule."""
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    # Merged 20 days ago: its 14-day clock is 6 days overdue, its 60-day
    # clock is still 40 days out.
    store.enqueue_outcome_jobs(
        99, 1, 7, "c" * 40, now - _dt.timedelta(days=20), "main"
    )

    health = _health(None)

    assert health["outcome"]["overdue"] == 1
    assert health["outcome"]["oldest_overdue_due_at"] is not None
    assert health["outcome"]["next_due_at"] is not None
    assert health["outcome"]["next_due_at"] > health["outcome"]["oldest_overdue_due_at"]


def test_job_health_timestamps_are_all_timezone_aware(tmp_path, monkeypatch):
    """Every timestamp this endpoint emits must carry a zone, including the
    four MIN()-derived ones.

    `as_of` comes from `_db_now` and is always aware, but the MIN() results
    are read straight back off the column — naive on sqlite, where
    DateTime(timezone=True) round-trips without a designator. Serialised, an
    aware `as_of` and a naive `oldest_pending_at` cross the wire in different
    formats, and a client subtracting one from the other is off by its own
    local offset (7h in this repo's timezone). The console happens to be safe
    because `lib/runs.ts`'s parseUtc appends the Z, but that makes the
    endpoint's correctness a property of one caller's discipline rather than
    of the endpoint. Any second consumer mis-renders every age.

    All four are asserted, not a sample: they come from four separate
    queries and a fix that normalised only the two obvious ones would leave
    the other two wrong with nothing to catch it."""
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)

    # A fresh pending job (oldest_pending_at) and a retried one
    # (oldest_retry_at) in the review lane.
    _enqueue(99, 1, "o/r", 7, "a" * 40)
    _enqueue(99, 1, "o/r", 8, "b" * 40)
    claimed = ingest.claim()
    ingest.fail(claimed["id"], "boom", claim_generation=claimed["claim_generation"])

    # Merged 20 days ago: the 14-day clock is overdue
    # (oldest_overdue_due_at), the 60-day one is still ahead (next_due_at).
    store.enqueue_outcome_jobs(99, 1, 7, "c" * 40, now - _dt.timedelta(days=20), "main")

    health = _health(None)

    for lane, field in (
        ("review", "oldest_pending_at"),
        ("review", "oldest_retry_at"),
        ("outcome", "next_due_at"),
        ("outcome", "oldest_overdue_due_at"),
    ):
        value = health[lane][field]
        assert value is not None, f"{lane}.{field} not seeded by this fixture"
        assert value.tzinfo is not None, f"{lane}.{field} crossed the wire naive"

    assert health["as_of"].tzinfo is not None


def test_job_health_returns_none_without_a_ledger(tmp_path, monkeypatch):
    """None, never a dict of zeros. A zeroed health payload would render as
    'nothing is wrong' on a deployment that cannot answer the question.

    store._get_engine() re-reads DATABASE_URL on every call and returns None
    when it is unset, so unsetting the variable is the whole fixture — there
    is no engine-reset helper in this codebase and none is needed."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _health(None) is None


def test_job_health_scopes_by_repo(tmp_path, monkeypatch):
    """An operator curling /v1/health?repo=o/a must see only o/a's jobs.

    outcome_jobs carries no repo name column — only github_repo_id — so
    _scope_outcome resolves the name through installation_repos. A test that
    only seeded the review lane would miss that join entirely and still pass
    even if the outcome scope silently matched every repo; both lanes get
    an unhealthy row here for exactly that reason, and both must exclude the
    other repo's."""
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    twenty_min_ago = now - _dt.timedelta(minutes=20)
    store.set_installation_repos(99, [(1, "o/a"), (2, "o/b")], replace=True)

    # Repo A: one stalled review claim, one overdue outcome window.
    _enqueue(99, 1, "o/a", 7, "a" * 40)
    claimed_a = ingest.claim()
    _force_started_at(store.review_jobs, claimed_a["id"], twenty_min_ago)
    store.enqueue_outcome_jobs(
        99, 1, 7, "c" * 40, now - _dt.timedelta(days=20), "main", window_days=(14,)
    )

    # Repo B: the same unhealthy shapes. Must not leak into o/a's scoped view.
    _enqueue(99, 2, "o/b", 8, "b" * 40)
    claimed_b = ingest.claim()
    _force_started_at(store.review_jobs, claimed_b["id"], twenty_min_ago)
    store.enqueue_outcome_jobs(
        99, 2, 8, "d" * 40, now - _dt.timedelta(days=20), "main", window_days=(14,)
    )

    health = _health(None, repo="o/a")

    assert health["review"]["running"] == 1
    assert health["review"]["stalled"] == 1
    assert health["outcome"]["pending"] == 1
    assert health["outcome"]["overdue"] == 1


def test_job_health_scopes_by_installation(tmp_path, monkeypatch):
    """Two tenants' unhealthy jobs must not blur into one installation's
    count — an operator debugging installation 11 must not see installation
    22's stalled claims or overdue windows counted against it, in either
    lane."""
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    twenty_min_ago = now - _dt.timedelta(minutes=20)

    _enqueue(11, 1, "o/a", 7, "a" * 40)
    claimed_a = ingest.claim()
    _force_started_at(store.review_jobs, claimed_a["id"], twenty_min_ago)
    store.enqueue_outcome_jobs(
        11, 1, 7, "c" * 40, now - _dt.timedelta(days=20), "main", window_days=(14,)
    )

    _enqueue(22, 2, "o/b", 8, "b" * 40)
    claimed_b = ingest.claim()
    _force_started_at(store.review_jobs, claimed_b["id"], twenty_min_ago)
    store.enqueue_outcome_jobs(
        22, 2, 8, "d" * 40, now - _dt.timedelta(days=20), "main", window_days=(14,)
    )

    health = _health(None, installation_id=11)

    assert health["review"]["running"] == 1
    assert health["review"]["stalled"] == 1
    assert health["outcome"]["pending"] == 1
    assert health["outcome"]["overdue"] == 1


# --- store.job_rows — the failure list backing the /jobs page. Every test
# here pins a way the row-level query could disagree with job_health's count.


def test_job_rows_defaults_to_unhealthy_only(tmp_path, monkeypatch):
    """The page exists to answer 'what is wrong'. A raw job list is
    overwhelmingly done and superseded, so the default filter is the RED and
    AMBER states and nothing else."""
    _db(tmp_path, monkeypatch)
    # One healthy done job.
    done_id = _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.complete(done_id, None, claim_generation=claimed["claim_generation"])
    # One failed job: three attempts exhausts ingest.MAX_ATTEMPTS.
    _enqueue(99, 1, "o/r", 8, "b" * 40)
    for _ in range(ingest.MAX_ATTEMPTS):
        c = ingest.claim()
        ingest.fail(c["id"], "boom", claim_generation=c["claim_generation"])

    rows = store.job_rows(lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS)

    assert [r["pr_number"] for r in rows] == [8]
    assert rows[0]["status"] == "failed"


def test_job_rows_never_returns_superseded_as_unhealthy(tmp_path, monkeypatch):
    """Same reason job_health excludes it: nothing went wrong."""
    _db(tmp_path, monkeypatch)
    job_id = _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.supersede(job_id, claim_generation=claimed["claim_generation"])

    rows = store.job_rows(lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS)

    assert rows == []


def test_job_rows_shows_everything_when_unhealthy_only_is_off(
    tmp_path, monkeypatch
):
    """'The job I expected does not exist at all' is a real diagnosis, and
    only a complete list reaches it."""
    _db(tmp_path, monkeypatch)
    job_id = _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.supersede(job_id, claim_generation=claimed["claim_generation"])

    rows = store.job_rows(
        lane="review",
        lease_seconds=ingest.STALL_LEASE_SECONDS,
        unhealthy_only=False,
    )

    assert [r["status"] for r in rows] == ["superseded"]


def test_job_rows_carries_the_derived_flag_it_was_selected_by(
    tmp_path, monkeypatch
):
    """The page renders the REASON a row is unhealthy without recomputing it
    against a lease constant it would have to hold locally — which is how the
    list and the strip drift apart."""
    _db(tmp_path, monkeypatch)
    _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    _force_started_at(
        store.review_jobs,
        claimed["id"],
        _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=1000),
    )

    rows = store.job_rows(lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS)

    assert rows[0]["stalled"] is True
    assert rows[0]["retrying"] is False


def test_job_rows_renders_no_repo_name_when_the_ledger_has_none(
    tmp_path, monkeypatch
):
    """outcome_jobs carries only github_repo_id. The display name comes from
    installation_repos, which worker.py documents as able to go stale and
    which count_verdict_repos_missing_from_ledger proves can be absent. A
    miss must return None so the caller renders the bare id — never a guess,
    never a blank."""
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    store.enqueue_outcome_jobs(
        99, 4242, 7, "c" * 40, now - _dt.timedelta(days=20), "main",
        window_days=(14,),
    )

    rows = store.job_rows(
        lane="outcome", lease_seconds=outcome_queue.STALL_LEASE_SECONDS
    )

    assert rows[0]["repo"] is None
    assert rows[0]["github_repo_id"] == 4242
    assert rows[0]["overdue"] is True


def test_job_rows_resolves_the_outcome_repo_name_when_the_ledger_has_it(
    tmp_path, monkeypatch
):
    _db(tmp_path, monkeypatch)
    now = _dt.datetime.now(_dt.UTC)
    # set_installation_repos takes (github_repo_id, full_name) tuples — the
    # same call the installation_repositories webhook tests already use.
    store.set_installation_repos(99, [(4242, "o/r")], replace=True)
    store.enqueue_outcome_jobs(
        99, 4242, 7, "c" * 40, now - _dt.timedelta(days=20), "main",
        window_days=(14,),
    )

    rows = store.job_rows(
        lane="outcome", lease_seconds=outcome_queue.STALL_LEASE_SECONDS
    )

    assert rows[0]["repo"] == "o/r"


def test_job_rows_does_not_treat_a_skipped_done_job_as_unhealthy(
    tmp_path, monkeypatch
):
    """ingest.complete() takes verdict_id: int | None — 'a skipped PR is
    finished, not failed'. A healthy done job can carry a NULL verdict, so
    unlinkable does not mean unhealthy. Surfacing it as a failure would
    invent an incident out of Doug correctly declining to review."""
    _db(tmp_path, monkeypatch)
    job_id = _enqueue(99, 1, "o/r", 7, "a" * 40)
    claimed = ingest.claim()
    ingest.complete(job_id, None, claim_generation=claimed["claim_generation"])

    unhealthy = store.job_rows(
        lane="review", lease_seconds=ingest.STALL_LEASE_SECONDS
    )
    everything = store.job_rows(
        lane="review",
        lease_seconds=ingest.STALL_LEASE_SECONDS,
        unhealthy_only=False,
    )

    assert unhealthy == []
    assert everything[0]["status"] == "done"
    assert everything[0]["verdict_id"] is None


def _force_started_at(table, job_id, when):
    """Age a claim's lease without waiting for one. reclaim_stalled compares
    started_at to the DB clock, so this is the only way to test the stalled
    branch in under 900 seconds."""
    from sqlalchemy import update as _update

    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            _update(table).where(table.c.id == job_id).values(started_at=when)
        )


def _force_running(table, job_id, when):
    from sqlalchemy import update as _update

    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            _update(table)
            .where(table.c.id == job_id)
            .values(status="running", started_at=when)
        )
