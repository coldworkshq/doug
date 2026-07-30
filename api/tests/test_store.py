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
