from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError

from doug import reader, review, store
from doug.api import app
from doug.models import Band, PRMetadata, Reason, Verdict

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

VERDICT = Verdict(
    score=0.62,
    band=Band.FLAGGED,
    threshold=0.30,
    reasons=[Reason(rule="reader:race-condition", label="Cache write is not guarded", weight=0.0)],
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


def test_disabled_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert not store.enabled()
    assert store.save_review("o/r", 1, "deterministic", VERDICT) is None


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


def _pr() -> PRMetadata:
    return PRMetadata.model_validate(
        dict(number=7, title="Add cache", author="dev", files=["cache.py"])
    )


def test_review_endpoint_requires_configuration(monkeypatch):
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    r = TestClient(app).post("/v1/review", json={"repo": "o/r", "pr_number": 7})
    assert r.status_code == 503


def test_review_endpoint_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    r = TestClient(app).post(
        "/v1/review", json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "wrong"},
    )
    assert r.status_code == 401


def test_review_endpoint_scores_and_persists(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DOUG_READER", raising=False)
    monkeypatch.setattr(review, "fetch_pr", lambda gh, o, r, n: (_pr(), "+ x"))
    r = TestClient(app).post(
        "/v1/review", json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "secret", "x-github-token": "gh"},
    )
    assert r.status_code == 200
    assert r.json()["band"] in ("cleared", "flagged")
    engine = create_engine(url)
    with engine.connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
        assert v["tier"] == "deterministic" and v["pr_number"] == 7


def test_review_endpoint_stamps_the_prompt_hash_on_reader_tier_verdicts(tmp_path, monkeypatch):
    """The anchor a receipt points at to say 'this verdict used this exact
    prompt' has to actually be written by the live path, not just
    plumbed through save_review and left uncalled."""
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(review, "fetch_pr", lambda gh, o, r, n: (_pr(), "+ x"))
    monkeypatch.setattr(reader, "read_diff", lambda pr, diff, **_: RV)
    TestClient(app).post(
        "/v1/review", json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "secret", "x-github-token": "gh"},
    )
    with create_engine(url).connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
    assert v["tier"] == "reader"
    assert v["prompt_hash"] == reader.PROMPT_HASH


def test_review_endpoint_leaves_prompt_hash_null_on_the_deterministic_tier(tmp_path, monkeypatch):
    """The deterministic tier never opens the diff, so stamping a prompt
    hash on it would claim an instrument that was never actually run."""
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DOUG_READER", raising=False)
    monkeypatch.setattr(review, "fetch_pr", lambda gh, o, r, n: (_pr(), "+ x"))
    TestClient(app).post(
        "/v1/review", json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "secret", "x-github-token": "gh"},
    )
    with create_engine(url).connect() as conn:
        v = conn.execute(select(store.verdicts)).mappings().one()
    assert v["tier"] == "deterministic"
    assert v["prompt_hash"] is None


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


def test_review_repeat_for_same_commit_replays_without_a_second_row(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DOUG_READER", raising=False)
    monkeypatch.setattr(review, "fetch_pr", lambda gh, o, r, n: (_pr_with_sha(), "+ x"))
    scored = []
    real_score_one = review.score_one
    monkeypatch.setattr(
        review,
        "score_one",
        lambda meta, diff, **kw: scored.append(1) or real_score_one(meta, diff, **kw),
    )

    c = TestClient(app)
    first = c.post(
        "/v1/review", json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "secret"},
    ).json()
    with create_engine(url).connect() as conn:
        written = conn.execute(select(store.verdicts.c.head_sha)).scalar_one()
    assert written == "a" * 40
    second = c.post(
        "/v1/review", json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "secret"},
    ).json()

    assert len(scored) == 1, "the repeat must not score (or pay for a read) again"
    assert second["band"] == first["band"] and second["score"] == first["score"]
    assert any(r["rule"] == "idempotent-replay" for r in second["reasons"])
    assert not any(r["rule"] == "idempotent-replay" for r in first["reasons"])
    engine = create_engine(url)
    with engine.connect() as conn:
        assert len(conn.execute(select(store.verdicts)).all()) == 1


def test_review_after_app_for_same_commit_scores_a_distinct_ci_verdict(
    tmp_path, monkeypatch
):
    """App and CI are independent soak instruments for the same commit.

    Replaying an App verdict into /v1/review suppresses the entire CI side, so
    the comparison falsely reports a missing baseline even though CI ran.
    """
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DOUG_READER", raising=False)
    sha = "c" * 40
    app_id = store.save_review(
        "o/r",
        7,
        "reader",
        VERDICT,
        RV,
        pr_meta=_pr_with_sha(sha).model_dump(mode="json"),
        installation_id=10,
        github_repo_id=20,
        head_sha=sha,
        source="app",
    )
    monkeypatch.setattr(
        review,
        "fetch_pr",
        lambda gh, o, r, n: (_pr_with_sha(sha), "+ x"),
    )
    scored = []
    real_score_one = review.score_one
    monkeypatch.setattr(
        review,
        "score_one",
        lambda meta, diff, **kw: scored.append(1) or real_score_one(meta, diff, **kw),
    )
    c = TestClient(app)

    response = c.post(
        "/v1/review",
        json={"repo": "o/r", "pr_number": 7},
        headers={"X-Doug-Token": "secret", "X-GitHub-Token": "gh"},
    )
    assert response.status_code == 200
    assert scored == [1], "CI must score instead of replaying the App instrument"
    assert not any(reason["rule"] == "idempotent-replay" for reason in response.json()["reasons"])

    with create_engine(url).connect() as conn:
        rows = conn.execute(select(store.verdicts).order_by(store.verdicts.c.id)).mappings().all()
    assert len(rows) == 2
    assert rows[0]["id"] == app_id
    assert (rows[1]["installation_id"], rows[1]["github_repo_id"], rows[1]["head_sha"]) == (
        None,
        None,
        sha,
    )

    runs = c.get(
        "/v1/comparisons", headers={"X-Doug-Token": "secret"}
    ).json()["runs"]
    assert {run["id"] for run in runs} == {row["id"] for row in rows}
    assert {run["path"] for run in runs} == {"app", "ci"}
    assert {run["head_sha"] for run in runs} == {sha}


def test_review_force_rescore_and_new_commit_both_score_again(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DOUG_READER", raising=False)
    sha = ["a" * 40]
    monkeypatch.setattr(
        review, "fetch_pr", lambda gh, o, r, n: (_pr_with_sha(sha[0]), "+ x")
    )
    c = TestClient(app)
    post = lambda body: c.post(  # noqa: E731
        "/v1/review", json={"repo": "o/r", "pr_number": 7, **body},
        headers={"x-doug-token": "secret"},
    )

    post({})
    post({"force": True})  # deliberate rescore of the same commit
    sha[0] = "b" * 40
    post({})  # a new commit is never a repeat

    engine = create_engine(url)
    with engine.connect() as conn:
        assert len(conn.execute(select(store.verdicts)).all()) == 3


def test_replay_carries_the_recorded_deviations(tmp_path, monkeypatch):
    """The replayed response must be the recorded review, intent tier
    included — a replay that silently dropped deviations would make a
    redelivered webhook look like the decisions read never ran."""
    _db(tmp_path, monkeypatch)
    vid = store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        pr_meta=_pr_with_sha().model_dump(mode="json"),
    )
    store.save_deviations(
        vid,
        [reader.DeviationFinding(type="beyond-ticket", description="adds a flag", severity="low")],
        ["ADR-3"], 72,
    )
    prior = store.find_review("o/r", 7, "a" * 40)
    assert prior is not None and prior["band"] == "flagged"
    assert prior["deviations"] == [
        {"type": "beyond-ticket", "description": "adds a flag", "severity": "low"}
    ]
    assert prior["intent_refs"] == ["ADR-3"] and prior["intent_alignment"] == 72


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


def test_concurrent_deliveries_for_one_commit_pay_once(tmp_path, monkeypatch):
    """find_review-then-score is a check-then-act spanning a whole paid
    read, so two overlapping webhook deliveries both missed the lookup and
    both paid — the exact double-spend the dedup exists to prevent. The
    per-(repo, pr, sha) in-flight lock makes the second delivery wait,
    then replay. (In-process only: a cross-instance duplicate is still
    possible and tolerated.)
    """
    import threading
    import time

    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    monkeypatch.delenv("DOUG_READER", raising=False)
    monkeypatch.setattr(review, "fetch_pr", lambda gh, o, r, n: (_pr_with_sha(), "+ x"))
    scored = []
    real_score_one = review.score_one

    def slow_score(meta, diff, **kw):
        scored.append(1)
        time.sleep(0.2)  # hold the race window open
        return real_score_one(meta, diff, **kw)

    monkeypatch.setattr(review, "score_one", slow_score)

    c = TestClient(app)
    results = []

    def hit():
        results.append(
            c.post(
                "/v1/review", json={"repo": "o/r", "pr_number": 7},
                headers={"x-doug-token": "secret"},
            ).json()
        )

    threads = [threading.Thread(target=hit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(scored) == 1, "the overlapping delivery must wait and replay, not pay"
    replays = [
        r for r in results
        if any(x["rule"] == "idempotent-replay" for x in r["reasons"])
    ]
    assert len(replays) == 1
    engine = create_engine(url)
    with engine.connect() as conn:
        assert len(conn.execute(select(store.verdicts)).all()) == 1


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


def _comparison_review(
    repo: str,
    pr_number: int,
    sha: str,
    *,
    app: bool,
    legacy_ci: bool = False,
    coverage: reader.Coverage | None = None,
) -> int:
    identity = (
        {"installation_id": 10, "github_repo_id": 20, "head_sha": sha, "source": "app"}
        if app
        else {} if legacy_ci else {"head_sha": sha}
    )
    verdict_id = store.save_review(
        repo,
        pr_number,
        "reader",
        VERDICT,
        RV,
        pr_meta={**_pr().model_dump(mode="json"), "number": pr_number, "head_sha": sha},
        coverage=coverage,
        **identity,
    )
    assert verdict_id is not None
    return verdict_id


def test_comparison_reviews_keeps_both_paths_duplicates_and_coverage(
    tmp_path, monkeypatch
):
    """The comparison read must preserve every qualifying App and CI run.

    Dropping the CI-side predicate, collapsing CI duplicates, or failing to
    load a reader receipt makes the App-versus-CI dashboard claim a
    comparison it cannot actually show. App-path rows for one SHA are unique
    (migration 005); CI duplicates and App+CI coexistence are what remain.
    """
    _db(tmp_path, monkeypatch)
    coverage = reader.Coverage(
        diff_chars=20,
        sent_chars=10,
        files_sent=1,
        files_unseen=["second.py"],
        file_cut="first.py",
    )
    app_one = _comparison_review("o/r", 7, "a" * 40, app=True, coverage=coverage)
    # Same App identity: ledger keeps one row; the second save is idempotent.
    assert _comparison_review("o/r", 7, "a" * 40, app=True) == app_one
    current_ci = _comparison_review("o/r", 7, "a" * 40, app=False)
    legacy_ci = _comparison_review("o/r", 7, "a" * 40, app=False, legacy_ci=True)
    _external()
    one_app_id = store.save_review(
        "o/r",
        7,
        "reader",
        VERDICT,
        RV,
        pr_meta={**_pr().model_dump(mode="json"), "head_sha": "a" * 40},
        installation_id=10,
    )
    github_repo_id_only = store.save_review(
        "o/r",
        7,
        "reader",
        VERDICT,
        RV,
        pr_meta={**_pr().model_dump(mode="json"), "head_sha": "a" * 40},
        github_repo_id=20,
    )
    app_without_head = store.save_review(
        "o/r",
        7,
        "reader",
        VERDICT,
        RV,
        pr_meta={**_pr().model_dump(mode="json"), "head_sha": "a" * 40},
        installation_id=10,
        github_repo_id=20,
    )

    rows = store.comparison_reviews(repo="o/r")
    assert {row["id"] for row in rows} == {
        app_one,
        current_ci,
        legacy_ci,
    }
    assert one_app_id not in {row["id"] for row in rows}
    assert github_repo_id_only not in {row["id"] for row in rows}
    assert app_without_head not in {row["id"] for row in rows}
    by_id = {row["id"]: row for row in rows}
    assert by_id[app_one]["coverage"]["sent_chars"] == 10
    assert by_id[app_one]["coverage"]["file_cut"] == "first.py"
    assert by_id[current_ci]["coverage"] is None
    assert by_id[legacy_ci]["coverage"] is None


def test_comparison_reviews_loads_all_coverage_in_one_select(tmp_path, monkeypatch):
    """Adding another verdict must not add another database round trip.

    The dashboard can request 200 PR groups and duplicates are deliberately
    preserved. A SELECT inside the verdict loop turns that honest ledger read
    into hundreds of sequential queries.
    """
    _db(tmp_path, monkeypatch)
    coverage = reader.Coverage(
        diff_chars=20,
        sent_chars=10,
        files_sent=1,
        files_unseen=["second.py"],
        file_cut="first.py",
    )
    covered = _comparison_review("o/r", 7, "a" * 40, app=True, coverage=coverage)
    assert store.save_read(
        covered,
        reader.Coverage(
            diff_chars=20,
            sent_chars=18,
            files_sent=2,
            files_unseen=[],
            file_cut=None,
        ),
    ) == 1
    _comparison_review("o/r", 7, "a" * 40, app=False)
    _comparison_review("o/r", 7, "a" * 40, app=True)
    engine = store._get_engine()
    assert engine is not None
    selects: list[str] = []

    def record_select(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", record_select)
    try:
        rows = store.comparison_reviews(repo="o/r")
    finally:
        event.remove(engine, "before_cursor_execute", record_select)

    assert len(selects) == 1
    by_id = {row["id"]: row for row in rows}
    assert by_id[covered]["coverage"]["sent_chars"] == 18
    assert by_id[covered]["coverage"]["file_cut"] is None


def test_current_ci_review_is_visible_in_comparisons_with_its_exact_head(
    tmp_path, monkeypatch
):
    """The CI endpoint writes head_sha for idempotency, without App ids.

    Treating any row with a head column as App or malformed hides every new
    CI result from the soak dashboard even though the review completed.
    """
    url = _db(tmp_path, monkeypatch)
    sha = "c" * 40
    monkeypatch.delenv("DOUG_READER", raising=False)
    monkeypatch.setattr(
        review,
        "fetch_pr",
        lambda gh, o, r, n: (_pr_with_sha(sha), "+ x"),
    )
    c = TestClient(app)

    reviewed = c.post(
        "/v1/review",
        json={"repo": "o/r", "pr_number": 7},
        headers={**AUTH, "X-GitHub-Token": "gh"},
    )
    assert reviewed.status_code == 200
    with create_engine(url).connect() as conn:
        verdict_id = conn.execute(select(store.verdicts.c.id)).scalar_one()

    runs = c.get("/v1/comparisons", headers=AUTH).json()["runs"]
    assert [run["id"] for run in runs] == [verdict_id]
    assert runs[0]["path"] == "ci"
    assert runs[0]["head_sha"] == sha


def test_comparison_reviews_limits_pr_groups_without_cutting_their_runs(
    tmp_path, monkeypatch
):
    """The limit counts scored PR groups, never one side of a comparison."""
    _db(tmp_path, monkeypatch)
    _comparison_review("o/r", 1, "a" * 40, app=True)
    _comparison_review("o/r", 1, "a" * 40, app=False)
    newest_app = _comparison_review("o/r", 2, "b" * 40, app=True)
    newest_ci = _comparison_review("o/r", 2, "b" * 40, app=False)

    rows = store.comparison_reviews(limit=1)
    assert {row["id"] for row in rows} == {newest_app, newest_ci}
    assert {row["pr_number"] for row in rows} == {2}


def test_comparison_reviews_scopes_repo_and_is_empty_without_storage(
    tmp_path, monkeypatch
):
    """A repo view cannot leak another repo, and disabled storage stays inert."""
    _db(tmp_path, monkeypatch)
    wanted = _comparison_review("a/x", 1, "a" * 40, app=True)
    _comparison_review("b/y", 2, "b" * 40, app=True)
    assert [row["id"] for row in store.comparison_reviews(repo="a/x")] == [wanted]

    monkeypatch.delenv("DATABASE_URL")
    assert store.comparison_reviews() == []


def _scored(repo, pr, installation_id, score=0.5):
    """One verdict row, App-identified or CI-identified (installation None)."""
    return store.save_review(
        repo,
        pr,
        "reader",
        Verdict(score=score, band=Band.FLAGGED, threshold=0.30, reasons=[]),
        pr_meta=_pr().model_dump(),
        installation_id=installation_id,
        github_repo_id=1 if installation_id else None,
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
    # apply() always runs after create_all() in production (see this module's
    # docstring), so by the time migration 6 runs an `installations` table
    # always exists and migrations 1-5's target tables (verdicts, outcomes,
    # review_jobs, ...) are already there too. This engine only ever built
    # `installations` by hand, so migrations 1-5 are seeded as already-done
    # here to isolate the one thing this test means to exercise: migration 6
    # against a real legacy `installations` shape.
    migrations.schema_migrations.create(engine, checkfirst=True)
    with engine.begin() as conn:
        conn.execute(
            migrations.schema_migrations.insert(),
            [{"version": v, "applied_at": datetime.now(UTC)} for v in range(1, 6)],
        )
    migrations.apply(engine)
    assert "token_hash" not in {c["name"] for c in inspect(engine).get_columns("installations")}
