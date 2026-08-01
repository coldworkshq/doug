from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
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
        review, "score_one", lambda meta, diff: scored.append(1) or real_score_one(meta, diff)
    )

    c = TestClient(app)
    first = c.post(
        "/v1/review", json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "secret"},
    ).json()
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

    def slow_score(meta, diff):
        scored.append(1)
        time.sleep(0.2)  # hold the race window open
        return real_score_one(meta, diff)

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


# --- Outcome-loop schema (M1 amendment) ---------------------------------------


def test_installations_has_a_nullable_token_hash_column(tmp_path):
    """M2's token-dispense endpoint writes this column; `installations` is
    new on this branch so it ships with the table instead of a migration.
    Nullable because every installation exists before its token is minted."""
    engine = create_engine(f"sqlite:///{tmp_path}/inst.db")
    store.metadata.create_all(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("installations")}
    assert "token_hash" in cols
    assert cols["token_hash"]["nullable"] is True


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
