"""One claimed job in, one check run out.

The webhook must never review inline, so everything expensive lives here.
These tests cut all five network seams (installation token, PR fetch,
scoring, intent read, check run) and assert on what survives in the
ledger, because the ledger row is the product — the check run is a copy.
"""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select

from doug import app_auth, check_run, ingest, reader, review, store, worker
from doug.models import Band, PRMetadata, Reason, Verdict

JOB = dict(
    installation_id=150424894,
    github_repo_id=987,
    repo_full_name="drewjst/doug",
    pr_number=7,
    head_sha="a" * 40,
)

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
    reasons=[
        Reason(rule="reader:race-condition", label="Cache write is not guarded", weight=0.0)
    ],
)

COV = reader.Coverage(diff_chars=400, sent_chars=400, files_sent=1, files_unseen=[])


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _pr() -> PRMetadata:
    return PRMetadata.model_validate(
        dict(number=7, title="Add cache", author="dev", files=["cache.py"])
    )


def _gh(heads: dict[int, str] | None = None):
    """A client whose pulls.get reports the PR's current head SHA.

    By default that is the head of the newest job queued for the PR — the
    branch has not moved since enqueue, which is the ordinary case and
    keeps every other test free of SHA bookkeeping. `heads` moves it, which
    is how a test simulates a push landing between enqueue and claim.
    """
    heads = heads or {}

    def _get(*, owner, repo, pull_number):
        sha = heads.get(pull_number)
        if sha is None:
            with create_engine(os.environ["DATABASE_URL"]).connect() as conn:
                sha = conn.execute(
                    select(store.review_jobs.c.head_sha)
                    .where(store.review_jobs.c.pr_number == pull_number)
                    .order_by(store.review_jobs.c.id.desc())
                    .limit(1)
                ).scalar_one()
        return SimpleNamespace(parsed_data=SimpleNamespace(head=SimpleNamespace(sha=sha)))

    return SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(get=_get)))


def _wire(monkeypatch, *, tier="reader", intent=None, fetch=None, heads=None) -> list[dict]:
    """Cut every seam that would touch the network. Returns the posted
    check runs, which is what a caller of this pipeline can observe."""
    posted: list[dict] = []
    gh = _gh(heads)
    monkeypatch.setattr(app_auth, "installation_client", lambda i: gh)
    monkeypatch.setattr(review, "fetch_pr", fetch or (lambda gh, o, r, n: (_pr(), "+ x")))
    monkeypatch.setattr(
        review,
        "score_one",
        lambda meta, diff: (
            tier,
            VERDICT.model_copy(deep=True),
            RV if tier == "reader" else None,
            COV if tier == "reader" else None,
        ),
    )
    monkeypatch.setattr(review, "read_intent", lambda gh, o, r, m, d: intent)
    monkeypatch.setattr(
        check_run,
        "post",
        lambda gh, o, r, sha, title, summary: posted.append(
            dict(owner=o, repo=r, head_sha=sha, title=title, summary=summary)
        ),
    )
    return posted


def _rows(url, table):
    with create_engine(url).connect() as conn:
        return [dict(r) for r in conn.execute(select(table)).mappings()]


def _age_started_at(url: str, job_id: int, seconds: int) -> None:
    """Push a claimed job's started_at into the past, standing in for real
    wall-clock time passing while an instance holds (or crashes with) a
    claim — same helper as test_ingest.py's, kept local since this is the
    only place worker.drain's use of the lease needs it."""
    with create_engine(url).begin() as conn:
        conn.execute(
            store.review_jobs.update()
            .where(store.review_jobs.c.id == job_id)
            .values(started_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )


def test_process_job_persists_with_the_app_identity_columns(tmp_path, monkeypatch):
    """Tenancy identity (Global Constraints): every App-path write carries
    the installation, the numeric repo id and the head SHA. A row keyed
    only on "drewjst/doug" cannot be scoped to a customer and does not
    survive a repo rename — the name is display-only."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    job_id = ingest.enqueue(**JOB)
    verdict_id = worker.process_job(ingest.claim())

    (v,) = _rows(url, store.verdicts)
    (j,) = _rows(url, store.review_jobs)
    assert v["id"] == verdict_id
    assert v["source"] == "app"
    assert v["installation_id"] == JOB["installation_id"]
    assert v["github_repo_id"] == JOB["github_repo_id"]
    assert v["head_sha"] == JOB["head_sha"]
    assert v["repo"] == "drewjst/doug" and v["pr_number"] == 7
    assert v["tier"] == "reader" and v["model"] == reader.MODEL
    assert j["id"] == job_id and j["status"] == "done" and j["verdict_id"] == verdict_id


def test_the_reader_tier_records_the_coverage_it_read_at(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    (r,) = _rows(url, store.reads)
    assert r["diff_chars"] == 400 and r["sent_chars"] == 400


def test_the_deterministic_tier_claims_no_model_and_no_coverage(tmp_path, monkeypatch):
    """model is the reader's provenance. Stamping it on a fallback row
    would make the ledger claim opus-5 scored a PR whose diff was never
    opened, and every precision number computed over tier would be wrong."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch, tier="deterministic")
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    (v,) = _rows(url, store.verdicts)
    assert v["tier"] == "deterministic" and v["model"] is None
    assert _rows(url, store.reads) == []


def test_the_check_run_is_posted_against_the_jobs_head_sha(tmp_path, monkeypatch):
    """Not the PR's current SHA. A push burst means pulls.get already
    returns a newer commit than the one this job was enqueued for, and
    hanging this verdict on it would attach a read of one diff to a
    different one — while that newer SHA has a job of its own."""
    _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    assert posted[0]["head_sha"] == JOB["head_sha"]
    assert (posted[0]["owner"], posted[0]["repo"]) == ("drewjst", "doug")
    assert posted[0]["title"].lower().startswith("flagged")


def _intent(findings=None):
    return review.IntentRead(
        alignment=41,
        refs=["ADR-0002"],
        findings=findings
        if findings is not None
        else [
            reader.DeviationFinding(
                type="contradicts-ticket",
                description="Edits the frozen reader prompt",
                severity="high",
            )
        ],
        coverage=COV,
    )


def test_deviations_are_recorded_against_the_verdict(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch, intent=_intent())
    ingest.enqueue(**JOB)
    verdict_id = worker.process_job(ingest.claim())

    (d,) = _rows(url, store.deviations)
    assert d["verdict_id"] == verdict_id
    assert d["kind"] == "contradicts-ticket" and d["intent_alignment"] == 41
    (v,) = _rows(url, store.verdicts)
    assert v["score"] == 0.62 and v["band"] == "flagged"
    assert "unvalidated" in posted[0]["summary"].lower()


def test_a_failed_deviation_write_does_not_cost_the_verdict(tmp_path, monkeypatch):
    """ADR-0007 makes this a separate write, which is exactly why it must
    not be able to fail the job: retrying would re-run a paid read to
    recover a row the risk verdict does not depend on. It is reported on
    the check run instead of being swallowed silently."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch, intent=_intent())

    def _boom(*a, **k):
        raise RuntimeError("deviations table is gone")

    monkeypatch.setattr(store, "save_deviations", _boom)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())

    (v,) = _rows(url, store.verdicts)
    (j,) = _rows(url, store.review_jobs)
    assert v["score"] == 0.62
    assert j["status"] == "done" and j["verdict_id"] == v["id"]
    assert "deviations-unrecorded" in posted[0]["summary"]


def test_no_intent_read_writes_no_deviation_row(tmp_path, monkeypatch):
    """"No read happened" and "read happened, found nothing" are different
    facts and store.save_deviations already encodes the second as a
    kind='none' row. The worker must not blur them by calling it anyway."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch, intent=None)
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    assert _rows(url, store.deviations) == []


def test_drain_on_an_empty_queue_is_zero(tmp_path, monkeypatch):
    """Every delivery kicks a drain, including the ones that enqueue
    nothing. The common case must cost one claim and return."""
    _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    assert worker.drain() == 0


def test_drain_is_a_safe_no_op_when_storage_is_disabled(monkeypatch):
    """No DATABASE_URL is a deliberate mode (store.py's opt-in design), not
    a broken deployment, and drain must stay a no-op rather than raising —
    every one of the calls it makes unconditionally (reclaim_stalled, then
    claim) already returns empty/None for this case instead of erroring. A
    raise here would turn a background task into a crash on every request
    on a ledger-less deployment."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert worker.drain() == 0


def test_drain_runs_the_queue_and_marks_each_job_done(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    ingest.enqueue(**JOB)
    ingest.enqueue(**{**JOB, "pr_number": 8, "head_sha": "b" * 40})
    assert worker.drain() == 2
    assert {r["status"] for r in _rows(url, store.review_jobs)} == {"done"}
    assert sorted(p["head_sha"] for p in posted) == ["a" * 40, "b" * 40]


def test_a_failing_job_does_not_strand_the_queue(tmp_path, monkeypatch):
    """A poison job — a deleted PR, a revoked token — is claimed before
    every PR opened after it. If its exception escaped the loop, one bad
    job would silently stop reviewing an entire installation."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)

    def _fetch(gh, owner, repo, number):
        if number == 7:
            raise RuntimeError("boom: 404 pull request not found")
        return _pr(), "+ x"

    monkeypatch.setattr(review, "fetch_pr", _fetch)
    ingest.enqueue(**JOB)
    ingest.enqueue(**{**JOB, "pr_number": 8, "head_sha": "b" * 40})

    assert worker.drain() == 2
    rows = {r["pr_number"]: r for r in _rows(url, store.review_jobs)}
    assert rows[7]["status"] == "pending" and rows[7]["attempts"] == 1
    assert "boom" in rows[7]["error"]
    assert rows[8]["status"] == "done"
    assert [p["head_sha"] for p in posted] == ["b" * 40]
    assert _rows(url, store.verdicts)[0]["pr_number"] == 8


def test_a_job_that_keeps_failing_stops_being_retried(tmp_path, monkeypatch):
    """Below the cap a failure is pending (transient: a 502, a token race).
    At the cap it is failed, because re-running a paid read against a PR
    that will never fetch is spend with no possible verdict."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)

    def _fetch(gh, owner, repo, number):
        raise RuntimeError("gone")

    monkeypatch.setattr(review, "fetch_pr", _fetch)
    ingest.enqueue(**JOB)
    for _ in range(3):
        worker.drain()
    (j,) = _rows(url, store.review_jobs)
    assert j["status"] == "failed" and j["attempts"] == 3


def test_drain_stops_at_max_jobs(tmp_path, monkeypatch):
    """The drain runs inside a request's background task. Unbounded, a
    backlog would hold the instance long past the response it belongs to —
    the next delivery kicks it again."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    for n in (7, 8, 9):
        ingest.enqueue(**{**JOB, "pr_number": n, "head_sha": f"{n}" * 40})
    assert worker.drain(max_jobs=2) == 2
    statuses = sorted(r["status"] for r in _rows(url, store.review_jobs))
    assert statuses == ["done", "done", "pending"]


def test_a_failed_job_is_not_retried_inside_the_same_pass(tmp_path, monkeypatch):
    """ingest.fail re-pends a job below the attempt cap, and the drain
    claims whatever is pending — so without a guard one poison job is
    claimed, failed, re-pended and re-claimed until its three attempts are
    gone, inside a single pass lasting under a second. That is not a retry
    policy; nothing has had time to change. Spreading the attempts across
    passes is what makes "transient" a hypothesis worth holding."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)

    def _fetch(gh, owner, repo, number):
        raise RuntimeError("502 from GitHub")

    monkeypatch.setattr(review, "fetch_pr", _fetch)
    ingest.enqueue(**JOB)

    assert worker.drain() == 1
    (j,) = _rows(url, store.review_jobs)
    assert j["attempts"] == 1
    # Released, not left running: the next pass has to be able to claim it.
    assert j["status"] == "pending" and j["started_at"] is None


def test_a_stale_head_is_superseded_and_the_current_one_requeued(tmp_path, monkeypatch):
    """A job can wait behind a backlog, or be re-pended by a retry, long
    enough for the branch to move. fetch_pr would then read the NEW diff
    while the identity columns, the unique index and the check run all
    still said the old SHA — a verdict labelled as evidence about a commit
    it never saw. Losing the read would be better than mislabelling it;
    doing neither is better still."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch, heads={7: "c" * 40})
    ingest.enqueue(**JOB)

    assert worker.process_job(ingest.claim()) is None

    jobs = {j["head_sha"]: j for j in _rows(url, store.review_jobs)}
    assert jobs["a" * 40]["status"] == "superseded"
    assert jobs["c" * 40]["status"] == "pending"
    # Nothing was paid for and nothing was published against the stale SHA.
    assert _rows(url, store.verdicts) == []
    assert posted == []


def test_a_force_push_ping_pong_cannot_spin_the_drain(tmp_path, monkeypatch):
    """The seen-set does double duty, and this is the second job.

    ingest.enqueue REVIVES a superseded row rather than inserting beside it
    (Task 3), so a branch flipping between two SHAs makes each job stale on
    arrival, supersede itself, and revive the other. The two hand the queue
    back and forth with no new rows and no progress — an unbounded spin
    inside a request's background task. Claiming a job this pass already
    ran is the signal that the queue has lapped, whatever the reason.

    The bound rests on _revive updating in place: the row keeps its id, so
    the seen-set recognises it. A revive written as a fresh insert — an
    equally natural way to write it, and one every Task 3 test still
    passes — would hand back a new id each time and quietly restore the
    unbounded loop. Two tasks, one mechanism.
    """
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    flip = iter(["c" * 40, "a" * 40] * 40)

    def _get(**kw):
        return SimpleNamespace(parsed_data=SimpleNamespace(head=SimpleNamespace(sha=next(flip))))

    monkeypatch.setattr(
        app_auth,
        "installation_client",
        lambda i: SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(get=_get))),
    )
    ingest.enqueue(**JOB)

    # Two jobs touched, then the lap is detected — not max_jobs (20) spins.
    assert worker.drain() == 2
    statuses = {j["head_sha"]: j["status"] for j in _rows(url, store.review_jobs)}
    assert statuses == {"a" * 40: "pending", "c" * 40: "superseded"}
    # Nothing was read and nothing was published while the branch thrashed.
    assert _rows(url, store.verdicts) == []
    assert posted == []


# --- amendment: reclaim_stalled wired into drain --------------------------
#
# A worker that claims a job and then dies (a deploy, a scale-down, an OOM)
# leaves the row 'running' forever: REVIVABLE deliberately excludes that
# status, so no later enqueue can revive it on its own (double-spend guard).
# drain() has to call ingest.reclaim_stalled() itself, once per pass, or the
# hole never closes on its own.


def test_a_stalled_claim_past_its_lease_is_reclaimed_and_actually_reviewed(tmp_path, monkeypatch):
    """The end-to-end guarantee: a crashed instance loses its claim, not the
    review. Reclaiming alone (a row flipping back to 'pending') would not be
    enough on its own — this asserts the job flows all the way through the
    ordinary claim path and produces a verdict and a check run."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    ingest.enqueue(**JOB)
    stuck = ingest.claim()  # stands in for a worker that claimed and died
    _age_started_at(url, stuck["id"], seconds=ingest.STALL_LEASE_SECONDS + 1)

    assert worker.drain() == 1

    (j,) = _rows(url, store.review_jobs)
    assert j["id"] == stuck["id"] and j["status"] == "done" and j["verdict_id"] is not None
    assert posted[0]["head_sha"] == JOB["head_sha"]
    assert _rows(url, store.verdicts)[0]["installation_id"] == JOB["installation_id"]


def test_a_stalled_claim_within_its_lease_is_left_strictly_alone(tmp_path, monkeypatch):
    """The guarantee that matters more than the first: a claim a live worker
    still holds must never be reclaimed out from under it, or Doug pays
    twice for every slow read. Only wall-clock age past the lease tells a
    crashed worker apart from one still reading; drain must not touch a
    'running' row that is merely young."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    ingest.enqueue(**JOB)
    stuck = ingest.claim()  # freshly claimed — well within the lease

    assert worker.drain() == 0

    (j,) = _rows(url, store.review_jobs)
    assert j["id"] == stuck["id"] and j["status"] == "running"
    assert j["started_at"] is not None
    assert _rows(url, store.verdicts) == []
    assert posted == []


# --- fix: idempotent replay for a job whose verdict already landed -------
#
# The amendment above made reclaim_stalled() reachable from drain, which
# reopened a path save_review never defended: if the worker dies (or
# ingest.complete itself raises) anywhere between save_review committing
# and the job reaching 'done', the row re-pends and a naive retry re-scores
# from scratch — a second paid score_one/read_intent, and a second verdicts
# row for the same commit, since verdicts carries no unique constraint.
# process_job now checks store.find_verdict_by_identity before spending
# anything, and replays the durable verdict instead.


def test_a_reclaimed_job_with_an_already_saved_verdict_replays_without_a_second_read(
    tmp_path, monkeypatch
):
    """Stands in for a crash between save_review landing and ingest.complete
    ever running — the earliest possible point in that window, so a replay
    here has to render and post the check run for the first time, not just
    skip re-scoring. Model-call counters, not just row counts, because a
    duplicate verdicts row and a repeated paid call are two different
    failures and this guards both."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        review, "fetch_pr", lambda gh, o, r, n: calls.append("fetch_pr") or (_pr(), "+ x")
    )
    monkeypatch.setattr(
        review,
        "score_one",
        lambda meta, diff: calls.append("score_one")
        or ("reader", VERDICT.model_copy(deep=True), RV, COV),
    )
    monkeypatch.setattr(
        review, "read_intent", lambda gh, o, r, m, d: calls.append("read_intent") or None
    )

    ingest.enqueue(**JOB)
    claimed = ingest.claim()
    # The worker reached save_review and then died — before render, before
    # the check-run post, before ingest.complete. The job row is left
    # 'running' with no verdict_id, exactly as a real crash would leave it.
    verdict_id = store.save_review(
        JOB["repo_full_name"],
        JOB["pr_number"],
        "reader",
        VERDICT.model_copy(deep=True),
        RV,
        model=reader.MODEL,
        pr_meta=_pr().model_dump(mode="json"),
        coverage=COV,
        github_repo_id=JOB["github_repo_id"],
        installation_id=JOB["installation_id"],
        head_sha=JOB["head_sha"],
        source="app",
    )
    _age_started_at(url, claimed["id"], seconds=ingest.STALL_LEASE_SECONDS + 1)

    assert worker.drain() == 1

    assert calls == []  # no model call was repeated
    assert len(_rows(url, store.verdicts)) == 1  # no duplicate row
    (j,) = _rows(url, store.review_jobs)
    assert j["status"] == "done" and j["verdict_id"] == verdict_id
    assert posted[0]["head_sha"] == JOB["head_sha"]
    assert posted[0]["title"].lower().startswith("flagged")


def test_ingest_complete_raising_after_a_saved_verdict_does_not_double_score_on_retry(
    tmp_path, monkeypatch
):
    """The idempotency read guards more than the reclaim path: ingest.fail
    re-pends a job whenever process_job raises for any reason, including
    ingest.complete itself blowing up after save_review already landed — no
    wall-clock wait needed to reach the same "verdict durable, job not
    done" state a crash produces. The second drain() pass must not re-score
    and does post a second, harmless, check run — the crash-after-post case
    the fix report calls out as acceptable."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    real_complete = ingest.complete
    armed = {"boom": True}

    def _flaky_complete(job_id, verdict_id):
        if armed["boom"]:
            armed["boom"] = False
            raise RuntimeError("db hiccup")
        real_complete(job_id, verdict_id)

    monkeypatch.setattr(ingest, "complete", _flaky_complete)
    ingest.enqueue(**JOB)

    assert worker.drain() == 1  # save_review lands, complete blows up, fail() re-pends
    assert worker.drain() == 1  # replay: idempotent, no second read

    assert len(_rows(url, store.verdicts)) == 1
    (j,) = _rows(url, store.review_jobs)
    assert j["status"] == "done"
    assert len(posted) == 2  # both attempts post; the second is the harmless duplicate
