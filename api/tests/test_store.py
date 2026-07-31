from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

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


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


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


def test_queue_serves_ledger_when_enabled(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    store.save_review(
        "o/r", 7, "reader", VERDICT, RV,
        model=reader.MODEL, pr_meta=_pr().model_dump(mode="json"),
    )
    r = TestClient(app).get("/v1/queue")
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
    assert c.get("/v1/queue").json()["summary"]["open"] == 2
    assert c.get("/v1/queue", params={"repo": "a/x"}).json()["summary"]["open"] == 1


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
    body = TestClient(app).get("/v1/queue").json()
    assert body["summary"]["threshold"] == VERDICT.threshold == 0.30
    assert body["items"][0]["verdict"]["band"] == "flagged"


def test_queue_falls_back_to_the_default_when_there_are_no_rows(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from doug.scoring import default_threshold

    body = TestClient(app).get("/v1/queue", params={"repo": "nobody/here"}).json()
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
    body = TestClient(app).get("/v1/queue", params={"threshold": 0.9}).json()
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
    item = TestClient(app).get("/v1/queue").json()["items"][0]
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
    reasons = TestClient(app).get("/v1/queue").json()["items"][0]["verdict"]["reasons"]
    assert reasons[0]["severity"] == "high"
    assert reasons[0]["weight"] == 0.0
