"""/healthz/queues — the per-lane oldest-pending-age contradiction as a
status code (#121, Gate A).

The route exists because the 2026-08-16 adjudicator outage was invisible:
`adjudicated 0` is the designed empty state and identical to the broken one.
Every test here encodes which side of that line a queue state falls on —
a wrong answer in either direction recreates the outage (silent when broken)
or mutes the alert (paging on designed behaviour until someone turns it off).
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from doug import api, store
from doug.api import app


def _db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    assert store.enabled()


def _insert_review(status="pending", attempts=0, age_seconds=0):
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            store.review_jobs.insert().values(
                installation_id=99,
                github_repo_id=1,
                repo_full_name="o/r",
                pr_number=1,
                head_sha="a" * 40,
                status=status,
                attempts=attempts,
                enqueued_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
            )
        )


def _insert_outcome(due_delta_seconds):
    """due_delta_seconds < 0 puts due_at in the past (overdue)."""
    engine = store._get_engine()
    with engine.begin() as conn:
        conn.execute(
            store.outcome_jobs.insert().values(
                installation_id=99,
                github_repo_id=1,
                pr_number=7,
                merge_commit_sha="b" * 40,
                merged_at=datetime.now(UTC) - timedelta(days=14),
                base_ref="main",
                window_days=14,
                status="pending",
                due_at=datetime.now(UTC) + timedelta(seconds=due_delta_seconds),
                created_at=datetime.now(UTC) - timedelta(days=14),
            )
        )


def test_503s_without_a_ledger(monkeypatch):
    """503, never a zeroed payload: zeros render as 'nothing is wrong' on a
    deployment that cannot answer the question at all — which is the exact
    shape of the outage this route exists to end."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert TestClient(app).get("/healthz/queues").status_code == 503


def test_needs_no_token(tmp_path, monkeypatch):
    """The whole point is an external poller: a gated liveness check dies
    with the credential rotation nobody alerts on."""
    _db(tmp_path, monkeypatch)
    res = TestClient(app).get("/healthz/queues")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["review"]["oldest_age_seconds"] is None
    assert body["outcome"]["oldest_age_seconds"] is None


def test_exposes_no_tenant_fields(tmp_path, monkeypatch):
    """Unauthenticated by design, so the payload may carry ages and bars
    only. A repo name or installation id appearing here is a leak, not a
    feature request."""
    _db(tmp_path, monkeypatch)
    _insert_review(age_seconds=10)
    body = TestClient(app).get("/healthz/queues").json()
    flat = {k for k in body} | {k for lane in ("review", "outcome") for k in body[lane]}
    assert flat == {"ok", "review", "outcome", "as_of", "oldest_age_seconds", "bar_seconds"}


def test_fresh_pending_inside_the_bar_is_healthy(tmp_path, monkeypatch):
    """A row enqueued moments ago is the normal gap between webhook and
    drain, not a contradiction."""
    _db(tmp_path, monkeypatch)
    _insert_review(age_seconds=60)
    res = TestClient(app).get("/healthz/queues")
    assert res.status_code == 200
    assert res.json()["review"]["ok"] is True


def test_fresh_pending_past_the_bar_is_the_contradiction(tmp_path, monkeypatch):
    """A fresh-pending row only ever waits for the drain that follows the
    webhook response that enqueued it. Half an hour later, that drain
    provably never ran — this is the review lane's silent-death signal."""
    _db(tmp_path, monkeypatch)
    _insert_review(age_seconds=api.REVIEW_PENDING_LIVENESS_SECONDS + 300)
    res = TestClient(app).get("/healthz/queues")
    assert res.status_code == 503
    body = res.json()
    assert body["ok"] is False and body["review"]["ok"] is False
    assert body["review"]["oldest_age_seconds"] > body["review"]["bar_seconds"]


def test_old_retry_is_not_a_contradiction(tmp_path, monkeypatch):
    """A pending row with attempts > 0 legitimately waits for the next drain
    trigger on a quiet service. Paging on it would train the operator to
    mute the policy — and a muted policy is the 2026-08-16 state again."""
    _db(tmp_path, monkeypatch)
    _insert_review(attempts=2, age_seconds=3 * 24 * 3600)
    res = TestClient(app).get("/healthz/queues")
    assert res.status_code == 200
    assert res.json()["review"]["ok"] is True


def test_future_due_outcome_is_a_schedule_not_an_alarm(tmp_path, monkeypatch):
    """A pending outcome job before its due_at is the 14-day window working
    as designed."""
    _db(tmp_path, monkeypatch)
    _insert_outcome(due_delta_seconds=7 * 24 * 3600)
    res = TestClient(app).get("/healthz/queues")
    assert res.status_code == 200
    assert res.json()["outcome"]["ok"] is True
    assert res.json()["outcome"]["oldest_age_seconds"] is None


def test_overdue_inside_the_cadence_is_healthy(tmp_path, monkeypatch):
    """Overdue by an hour means the daily sweep has not come around yet —
    that is the cadence, not an outage."""
    _db(tmp_path, monkeypatch)
    _insert_outcome(due_delta_seconds=-3600)
    res = TestClient(app).get("/healthz/queues")
    assert res.status_code == 200
    assert res.json()["outcome"]["ok"] is True


def test_overdue_past_the_cadence_is_the_contradiction(tmp_path, monkeypatch):
    """26 hours past due means the daily adjudicator demonstrably missed a
    run. This is precisely the two-day outage's signature, caught on day
    one instead of read off Cloud Run by hand on day three."""
    _db(tmp_path, monkeypatch)
    _insert_outcome(due_delta_seconds=-(api.OUTCOME_OVERDUE_LIVENESS_SECONDS + 3600))
    res = TestClient(app).get("/healthz/queues")
    assert res.status_code == 503
    body = res.json()
    assert body["ok"] is False and body["outcome"]["ok"] is False


def test_bars_are_reported_not_hardcodable(tmp_path, monkeypatch):
    """The alert policy and any console rendering must read the bars from
    the response — the same no-hardcoding rule /v1/health enforces for its
    lease constants."""
    _db(tmp_path, monkeypatch)
    body = TestClient(app).get("/healthz/queues").json()
    assert body["review"]["bar_seconds"] == api.REVIEW_PENDING_LIVENESS_SECONDS
    assert body["outcome"]["bar_seconds"] == api.OUTCOME_OVERDUE_LIVENESS_SECONDS
