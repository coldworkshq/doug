"""One claimed job in, one check run out.

The webhook must never review inline, so everything expensive lives here.
These tests cut all five network seams (installation token, PR fetch,
scoring, intent read, check run) and assert on what survives in the
ledger, because the ledger row is the product — the check run is a copy.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select

from doug import (
    app_auth,
    check_run,
    example_pack_capture,
    ingest,
    reader,
    review,
    store,
    worker,
)
from doug.example_pack import ExamplePackV0, FileExamplePackStore
from doug.models import Band, PRMetadata, Reason, Verdict

JOB = dict(
    installation_id=150424894,
    github_repo_id=987,
    repo_full_name="drewjst/doug",
    pr_number=7,
    base_sha="0" * 40,
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

NOW = datetime.now(UTC)


def _db(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _pr() -> PRMetadata:
    return PRMetadata.model_validate(
        dict(number=7, title="Add cache", author="dev", files=["cache.py"])
    )


def _gh(
    heads: dict[int, str] | None = None,
    bases: dict[int, str | None] | None = None,
):
    """A client whose pulls.get reports the PR's current head SHA.

    By default that is the head of the newest job queued for the PR — the
    branch has not moved since enqueue, which is the ordinary case and
    keeps every other test free of SHA bookkeeping. `heads` moves it, which
    is how a test simulates a push landing between enqueue and claim.
    """
    heads = heads or {}
    bases = bases or {}

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
        if pull_number in bases:
            base_sha = bases[pull_number]
        else:
            with create_engine(os.environ["DATABASE_URL"]).connect() as conn:
                base_sha = conn.execute(
                    select(store.review_jobs.c.base_sha)
                    .where(store.review_jobs.c.pr_number == pull_number)
                    .order_by(store.review_jobs.c.id.desc())
                    .limit(1)
                ).scalar_one()
        return SimpleNamespace(
            parsed_data=SimpleNamespace(
                head=SimpleNamespace(sha=sha),
                base=SimpleNamespace(sha=base_sha),
            )
        )

    return SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(get=_get)))


def _wire(
    monkeypatch,
    *,
    tier="reader",
    intent=None,
    fetch=None,
    heads=None,
    bases=None,
    scopes=None,
) -> list[dict]:
    """Cut every seam that would touch the network. Returns the posted
    check runs, which is what a caller of this pipeline can observe.

    `scopes` collects what each paid read was charged to, for the tests
    that care which budget a job spends from."""
    posted: list[dict] = []
    gh = _gh(heads, bases)
    monkeypatch.setattr(app_auth, "installation_client", lambda i: gh)
    monkeypatch.setattr(review, "fetch_pr", fetch or (lambda gh, o, r, n: (_pr(), "+ x")))

    def _score_one(meta, diff, *, scope, resolve_file=None, resolve_schema=None):
        if scopes is not None:
            scopes.append(("risk", scope))
        return (
            tier,
            VERDICT.model_copy(deep=True),
            RV if tier == "reader" else None,
            COV if tier == "reader" else None,
        )

    def _read_intent(gh, o, r, m, d, *, scope):
        if scopes is not None:
            scopes.append(("intent", scope))
        return intent

    monkeypatch.setattr(review, "score_one", _score_one)
    monkeypatch.setattr(review, "read_intent", _read_intent)
    monkeypatch.setattr(
        check_run,
        "post",
        lambda gh, o, r, sha, title, summary: posted.append(
            dict(owner=o, repo=r, head_sha=sha, title=title, summary=summary)
        ),
    )
    return posted


class _ReaderMessages:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(RV.model_dump()))],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1200, output_tokens=340),
        )


class _ReaderClient:
    def __init__(self):
        self.messages = _ReaderMessages()


def _wire_real_reader(monkeypatch, *, heads=None, bases=None):
    posted: list[dict] = []
    gh = _gh(heads, bases)
    client = _ReaderClient()
    monkeypatch.setattr(app_auth, "installation_client", lambda i: gh)
    monkeypatch.setattr(review, "fetch_pr", lambda gh, o, r, n: (_pr(), "+ x"))
    monkeypatch.setattr(reader, "_client", lambda: client)
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.delenv("DOUG_INTENT_INSTALLATIONS", raising=False)
    monkeypatch.setattr(
        check_run,
        "post",
        lambda gh, o, r, sha, title, summary: posted.append(
            dict(owner=o, repo=r, head_sha=sha, title=title, summary=summary)
        ),
    )
    return posted, client


def _captured_packs(root) -> list[ExamplePackV0]:
    directory = root / "packs/sha256"
    if not directory.is_dir():
        return []
    return [
        ExamplePackV0.model_validate_json(path.read_bytes())
        for path in sorted(directory.iterdir())
    ]


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


def test_process_job_scopes_capture_to_claimed_job_identity(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    posted, client = _wire_real_reader(monkeypatch)
    capture_root = tmp_path / "packs"
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_CAPTURE", "1")
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_DIR", str(capture_root))
    monkeypatch.setenv("DOUG_APPLICATION_REVISION", "app-revision")
    monkeypatch.setenv("DOUG_RUNTIME_REVISION", "runtime-revision")
    job_id = ingest.enqueue(**JOB)

    verdict_id = worker.process_job(ingest.claim())

    (pack,) = _captured_packs(capture_root)
    assert pack.run_id == f"review-job:{job_id}:claim:1:risk"
    assert pack.scope.installation_id == JOB["installation_id"]
    assert pack.scope.github_repository_id == JOB["github_repo_id"]
    assert pack.scope.repository_full_name == JOB["repo_full_name"]
    assert pack.scope.pull_number == JOB["pr_number"]
    assert pack.scope.admitted_base_sha == JOB["base_sha"]
    assert pack.scope.admitted_head_sha == JOB["head_sha"]
    assert pack.instrument_manifest.application_revision == "app-revision"
    assert pack.instrument_manifest.runtime_revision == "runtime-revision"
    assert pack.instrument_manifest.read_order == review.READ_ORDER
    assert pack.instrument_manifest.input_policy_version == reader.INPUT_POLICY_VERSION
    assert pack.instrument_manifest.coverage_policy_version == reader.COVERAGE_POLICY_VERSION
    assert client.messages.calls == 1
    (job,) = _rows(url, store.review_jobs)
    assert job["status"] == "done" and job["verdict_id"] == verdict_id
    assert len(posted) == 1


def test_capture_revision_identity_uses_only_explicit_runtime_inputs(monkeypatch):
    job = {
        **JOB,
        "id": 9,
        "claim_generation": 3,
    }
    monkeypatch.delenv("DOUG_APPLICATION_REVISION", raising=False)
    monkeypatch.delenv("DOUG_RUNTIME_REVISION", raising=False)
    monkeypatch.delenv("K_REVISION", raising=False)
    monkeypatch.setenv("GITHUB_SHA", "developer-checkout-must-not-be-used")

    local = worker._example_pack_scope(job)

    assert local.application_revision is None
    assert local.runtime_revision is None

    monkeypatch.setenv("K_REVISION", "cloud-run-revision")
    cloud_run = worker._example_pack_scope(job)
    assert cloud_run.runtime_revision == "cloud-run-revision"

    monkeypatch.setenv("DOUG_RUNTIME_REVISION", "explicit-runtime")
    explicit = worker._example_pack_scope(job)
    assert explicit.runtime_revision == "explicit-runtime"


def test_capture_scope_never_fabricates_a_missing_admitted_base():
    assert worker._example_pack_scope(
        {**JOB, "id": 9, "claim_generation": 1, "base_sha": None}
    ) is None


def test_retry_claim_generation_creates_distinct_stable_run_ids(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _wire_real_reader(monkeypatch)
    capture_root = tmp_path / "packs"
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_CAPTURE", "1")
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_DIR", str(capture_root))
    job_id = ingest.enqueue(**JOB)
    first_claim = ingest.claim()
    real_save = store.save_review

    def fail_after_read(*args, **kwargs):
        raise RuntimeError("after read")

    monkeypatch.setattr(store, "save_review", fail_after_read)

    with pytest.raises(RuntimeError, match="after read"):
        worker.process_job(first_claim)
    assert ingest.fail(
        job_id, "after read", claim_generation=first_claim["claim_generation"]
    )

    monkeypatch.setattr(store, "save_review", real_save)
    second_claim = ingest.claim()
    assert second_claim["claim_generation"] == 2
    worker.process_job(second_claim)

    assert {pack.run_id for pack in _captured_packs(capture_root)} == {
        f"review-job:{job_id}:claim:1:risk",
        f"review-job:{job_id}:claim:2:risk",
    }


def test_existing_verdict_replay_creates_no_example_pack(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    capture_root = tmp_path / "packs"
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_CAPTURE", "1")
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_DIR", str(capture_root))
    job_id = ingest.enqueue(**JOB)
    claimed = ingest.claim()
    verdict_id = store.save_review(
        JOB["repo_full_name"],
        JOB["pr_number"],
        "reader",
        VERDICT.model_copy(deep=True),
        RV,
        model=reader.MODEL,
        prompt_hash=reader.PROMPT_HASH,
        diff_budget=reader.DIFF_BUDGET,
        read_order=review.READ_ORDER,
        pr_meta=_pr().model_dump(mode="json"),
        coverage=COV,
        github_repo_id=JOB["github_repo_id"],
        installation_id=JOB["installation_id"],
        head_sha=JOB["head_sha"],
        source="app",
    )

    assert claimed["id"] == job_id
    assert worker.process_job(claimed) == verdict_id
    assert _captured_packs(capture_root) == []


class _FailingPackStore(FileExamplePackStore):
    def put_pack(self, pack):
        raise RuntimeError("capture storage unavailable")


def test_capture_failure_cannot_fail_the_worker_delivery(
    tmp_path, monkeypatch, capsys
):
    url = _db(tmp_path, monkeypatch)
    posted, client = _wire_real_reader(monkeypatch)
    sink = _FailingPackStore(tmp_path / "failing-packs")
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_CAPTURE", "1")
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_DIR", str(sink.root))
    monkeypatch.setattr(example_pack_capture, "configured_store", lambda environ=None: sink)
    job_id = ingest.enqueue(**JOB)

    verdict_id = worker.process_job(ingest.claim())

    (verdict,) = _rows(url, store.verdicts)
    (job,) = _rows(url, store.review_jobs)
    assert verdict["id"] == verdict_id
    assert job["id"] == job_id and job["status"] == "done"
    assert job["verdict_id"] == verdict_id
    assert client.messages.calls == 1
    assert len(posted) == 1
    assert "example-pack capture failed" in capsys.readouterr().err


def test_disabled_capture_does_not_build_a_worker_scope(tmp_path, monkeypatch):
    """Default-off capture cannot add validation or metadata work to a job."""
    url = _db(tmp_path, monkeypatch)
    posted, client = _wire_real_reader(monkeypatch)
    monkeypatch.delenv("DOUG_EXAMPLE_PACK_CAPTURE", raising=False)
    monkeypatch.delenv("DOUG_EXAMPLE_PACK_DIR", raising=False)
    monkeypatch.setattr(
        worker,
        "_example_pack_scope",
        lambda _job: pytest.fail("disabled capture built a worker scope"),
    )
    job_id = ingest.enqueue(**JOB)

    verdict_id = worker.process_job(ingest.claim())

    (job,) = _rows(url, store.review_jobs)
    assert job["id"] == job_id and job["status"] == "done"
    assert job["verdict_id"] == verdict_id
    assert client.messages.calls == 1
    assert len(posted) == 1


def test_worker_scope_construction_failure_cannot_fail_delivery(
    tmp_path, monkeypatch, capsys
):
    """An enabled optional sink cannot turn malformed capture metadata into job loss."""
    url = _db(tmp_path, monkeypatch)
    posted, client = _wire_real_reader(monkeypatch)
    capture_root = tmp_path / "packs"
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_CAPTURE", "1")
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_DIR", str(capture_root))

    def fail_scope(_job):
        raise ValueError("invalid optional capture scope")

    capture_metadata_calls = 0

    def fail_capture_metadata(_pr, _diff):
        nonlocal capture_metadata_calls
        capture_metadata_calls += 1
        raise RuntimeError("capture metadata should have been suppressed")

    monkeypatch.setattr(worker, "_example_pack_scope", fail_scope)
    monkeypatch.setattr(reader, "_capture_coverage", fail_capture_metadata)
    job_id = ingest.enqueue(**JOB)

    verdict_id = worker.process_job(ingest.claim())

    (job,) = _rows(url, store.review_jobs)
    assert job["id"] == job_id and job["status"] == "done"
    assert job["verdict_id"] == verdict_id
    assert client.messages.calls == 1
    assert len(posted) == 1
    assert _captured_packs(capture_root) == []
    assert capture_metadata_calls == 0
    diagnostics = [
        line
        for line in capsys.readouterr().err.splitlines()
        if "example-pack" in line
    ]
    assert len(diagnostics) == 1
    assert "example-pack capture failed" in diagnostics[0]
    assert "ValueError" in diagnostics[0]


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


def test_the_reader_tier_stamps_the_prompt_hash(tmp_path, monkeypatch):
    """The anchor a receipt points at to say 'this verdict used this exact
    prompt' has to actually be written by the live path, not just plumbed
    through save_review and left uncalled."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)  # tier="reader" default
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    (v,) = _rows(url, store.verdicts)
    assert v["tier"] == "reader"
    assert v["prompt_hash"] == reader.PROMPT_HASH


def test_the_deterministic_tier_leaves_the_prompt_hash_null(tmp_path, monkeypatch):
    """The deterministic tier never opens the diff, so stamping a prompt
    hash on it would claim an instrument that was never actually run."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch, tier="deterministic")
    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())
    (v,) = _rows(url, store.verdicts)
    assert v["tier"] == "deterministic"
    assert v["prompt_hash"] is None


def _drain_one_reader_job(tmp_path, monkeypatch) -> int:
    """Enqueue and process one job through the reader tier, end to end."""
    _db(tmp_path, monkeypatch)
    _wire(monkeypatch)  # tier="reader" default
    ingest.enqueue(**JOB)
    return worker.process_job(ingest.claim())


def _drain_one_fallback_job(tmp_path, monkeypatch) -> int:
    """Enqueue and process one job through the deterministic fallback tier."""
    _db(tmp_path, monkeypatch)
    _wire(monkeypatch, tier="deterministic")
    ingest.enqueue(**JOB)
    return worker.process_job(ingest.claim())


def test_reader_verdict_records_its_read_configuration(tmp_path, monkeypatch):
    """A receipt cannot claim instrument identity from prompt_hash alone."""
    verdict_id = _drain_one_reader_job(tmp_path, monkeypatch)
    row = store.run_detail(verdict_id)
    assert row["diff_budget"] == reader.DIFF_BUDGET
    assert row["read_order"] == review.READ_ORDER


def test_fallback_verdict_records_no_read_configuration(tmp_path, monkeypatch):
    """The deterministic scorer never opens the diff, so there is no budget."""
    verdict_id = _drain_one_fallback_job(tmp_path, monkeypatch)
    row = store.run_detail(verdict_id)
    assert row["diff_budget"] is None
    assert row["read_order"] is None


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


def test_a_failed_intent_read_reaches_the_verdict_under_its_own_name(tmp_path, monkeypatch):
    """The worker takes the rule name from the failure rather than writing
    one of its own, so an intent read stopped by the cap does not arrive in
    the ledger looking like an intent read that broke. Same weight-0,
    band-untouched treatment either way (ADR-0007) — only the name
    differs, and the name is the whole point."""
    url = _db(tmp_path, monkeypatch)
    capped = review.IntentFailure(detail="installation:1 has spent its cap", rule="intent-capped")
    _wire(monkeypatch, intent=capped)

    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())

    rules = {r["rule"] for r in _rows(url, store.findings)}
    assert "intent-capped" in rules
    assert "intent-unavailable" not in rules
    (row,) = _rows(url, store.verdicts)
    assert row["band"] == VERDICT.band.value  # advisory: the band never moved


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
    posted = _wire(monkeypatch, heads={7: "c" * 40}, bases={7: "2" * 40})
    ingest.enqueue(**JOB)

    assert worker.process_job(ingest.claim()) is None

    jobs = {j["head_sha"]: j for j in _rows(url, store.review_jobs)}
    assert jobs["a" * 40]["status"] == "superseded"
    assert jobs["c" * 40]["status"] == "pending"
    assert jobs["c" * 40]["base_sha"] == "2" * 40
    # Nothing was paid for and nothing was published against the stale SHA.
    assert _rows(url, store.verdicts) == []
    assert posted == []


def test_stale_head_without_a_replacement_base_is_retried_before_supersede(
    tmp_path, monkeypatch
):
    """An incomplete GitHub response must not retire the only durable job
    before Doug can describe its replacement. The ordinary drain failure path
    keeps the original claim retryable and creates no partial-identity row."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch, heads={7: "c" * 40}, bases={7: None})
    ingest.enqueue(**JOB)

    assert worker.drain() == 1

    (job,) = _rows(url, store.review_jobs)
    assert job["head_sha"] == "a" * 40
    assert job["status"] == "pending" and job["attempts"] == 1
    assert _rows(url, store.verdicts) == []
    assert posted == []


def test_the_stale_head_catch_up_revives_a_failed_job_at_once(tmp_path, monkeypatch):
    """The SHA that overtook a stale job is enqueued on live terms, not the
    sweep's. The branch really moved just now, so the row this catch-up
    collides with must come back at once even if its own review failed
    minutes ago — a force-push back onto a SHA whose review died in an outage
    is exactly the case, and FAILED_REVIVE_COOLOFF_SECONDS is a brake on
    reconcile repeating itself at every cold start, never on a push. Left on
    the sweep's terms this returns None and the PR is silently unreviewed for
    an hour, with the check run never posted and nothing to say why."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch, heads={7: "a" * 40})
    failed_id = ingest.enqueue(**JOB)
    for _ in range(3):
        claimed = ingest.claim()
        assert claimed["id"] == failed_id
        assert ingest.fail(
            failed_id, "reader exploded", claim_generation=claimed["claim_generation"]
        )
    ingest.enqueue(**{**JOB, "head_sha": "b" * 40})  # a push, then a force-push back

    assert worker.process_job(ingest.claim()) is None  # the "b" job, now stale

    jobs = {j["head_sha"]: j for j in _rows(url, store.review_jobs)}
    assert jobs["b" * 40]["status"] == "superseded"
    revived = jobs["a" * 40]
    assert revived["id"] == failed_id  # the failed row itself, back in the queue
    assert revived["status"] == "pending" and revived["attempts"] == 0


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
        return SimpleNamespace(
            parsed_data=SimpleNamespace(
                head=SimpleNamespace(sha=next(flip)),
                base=SimpleNamespace(sha="2" * 40),
            )
        )

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


def test_the_seen_set_catches_a_failed_row_the_catch_up_revived_mid_pass(tmp_path, monkeypatch):
    """The fourth way into the seen-set, and the only one whose row reached
    'failed'.

    process_job's stale-head catch-up enqueues the PR's real head on live
    terms, and live terms revive a row that burned every attempt. When that
    head is the SHA the row gave up on, a job this pass already ran comes
    straight back as pending work with attempts reset to 0 — so without the
    seen-set the drain re-claims it at once and spends the whole restored
    budget on the same fault inside one pass, this time paying for a read
    each time round.

    Two pending rows for one PR cannot be made with two enqueues (the second
    supersedes the first), so the setup is the one the drain itself leaves
    behind: the row was 'running' when the delivery for the other SHA landed,
    and a lapped earlier pass released it with its queue position intact.
    """
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch, heads={7: "a" * 40})  # the PR's real head never left "a"

    def _fetch(gh, owner, repo, number):
        raise RuntimeError("reader exploded")

    monkeypatch.setattr(review, "fetch_pr", _fetch)

    a_id = ingest.enqueue(**JOB)
    for _ in range(2):
        claimed = ingest.claim()
        assert claimed["id"] == a_id
        assert ingest.fail(
            a_id, "reader exploded", claim_generation=claimed["claim_generation"]
        )
    claimed = ingest.claim()  # 'running', so the delivery below cannot supersede it
    assert claimed["id"] == a_id
    ingest.enqueue(**{**JOB, "head_sha": "b" * 40})
    assert ingest.release(a_id, claim_generation=claimed["claim_generation"])

    # Claimed and failed to the cap, then revived by the "b" job's catch-up.
    assert worker.drain() == 2

    jobs = {j["head_sha"]: j for j in _rows(url, store.review_jobs)}
    assert jobs["b" * 40]["status"] == "superseded"
    revived = jobs["a" * 40]
    assert revived["id"] == a_id  # in place, which is what the seen-set keys on
    # Pending with a full budget, and untouched since: re-running it here
    # would have burned that budget (attempts 1..3) inside this same pass.
    assert revived["status"] == "pending" and revived["attempts"] == 0


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
# and the job reaching 'done', the row re-pends and a naive retry would
# re-score from scratch. process_job checks find_verdict_by_identity before
# spending; migration 005's unique index stops a second verdicts row when
# two holders both miss that pre-read.


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
        lambda meta, diff, *, scope: calls.append("score_one")
        or ("reader", VERDICT.model_copy(deep=True), RV, COV),
    )
    monkeypatch.setattr(
        review,
        "read_intent",
        lambda gh, o, r, m, d, *, scope: calls.append("read_intent") or None,
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
    done" state a crash produces. complete runs before the check-run post,
    so the first attempt posts nothing; the second drain() replays without
    re-scoring and posts once."""
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    real_complete = ingest.complete
    armed = {"boom": True}

    def _flaky_complete(job_id, verdict_id, *, claim_generation):
        if armed["boom"]:
            armed["boom"] = False
            raise RuntimeError("db hiccup")
        return real_complete(job_id, verdict_id, claim_generation=claim_generation)

    monkeypatch.setattr(ingest, "complete", _flaky_complete)
    ingest.enqueue(**JOB)

    assert worker.drain() == 1  # save_review lands, complete blows up, fail() re-pends
    assert worker.drain() == 1  # replay: idempotent, no second read

    assert len(_rows(url, store.verdicts)) == 1
    (j,) = _rows(url, store.review_jobs)
    assert j["status"] == "done"
    assert len(posted) == 1  # only the successful complete posts


def test_a_lost_claim_after_save_skips_the_check_run(tmp_path, monkeypatch):
    """When complete() returns False (reclaim handed the row to someone else),
    this worker must not post — the second holder identity-replays and posts
    once. Posting before complete produced duplicate check runs on that path."""
    _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    ingest.enqueue(**JOB)
    job = ingest.claim()
    monkeypatch.setattr(ingest, "complete", lambda *a, **k: False)
    assert worker.process_job(job) is not None
    assert posted == []


# --- reconcile: the healing path for missed deliveries --------------------


def _pull(
    number=1,
    head_sha="a" * 40,
    base_sha="0" * 40,
    draft=False,
    head_repo_id=42,
    base_repo_id=42,
    user=None,
):
    ns = SimpleNamespace(
        number=number,
        draft=draft,
        head=SimpleNamespace(sha=head_sha, repo=SimpleNamespace(id=head_repo_id)),
        base=SimpleNamespace(
            sha=base_sha,
            repo=SimpleNamespace(id=base_repo_id, full_name="o/r"),
        ),
    )
    if user is not None:
        ns.user = user
    return ns


class FakeListGH:
    """Only pulls.list — reconcile must never touch pulls.list_files."""

    def __init__(self, pulls):
        self.rest = SimpleNamespace(
            pulls=SimpleNamespace(list=lambda **kw: SimpleNamespace(parsed_data=pulls))
        )


def _installed(tmp_path, monkeypatch, *, repos=((42, "o/r"),)):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.upsert_installation(1, "o", "Organization", "active")
    store.set_installation_repos(1, list(repos), replace=True)


def test_reconcile_enqueues_open_prs_and_skips_drafts(tmp_path, monkeypatch):
    _installed(tmp_path, monkeypatch)
    gh = FakeListGH([_pull(number=1), _pull(number=2, draft=True)])
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)
    assert worker.reconcile_installation(1) == 1
    job = ingest.claim()
    assert job["pr_number"] == 1 and job["github_repo_id"] == 42
    assert job["base_sha"] == "0" * 40
    assert ingest.claim() is None


def test_reconcile_logs_and_skips_a_pr_without_a_base_sha(tmp_path, monkeypatch, capsys):
    """Reconciliation heals missed deliveries, but it cannot heal one by
    inventing the event-time side of the comparison identity."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.app_auth,
        "installation_client",
        lambda i: FakeListGH([_pull(base_sha=None)]),
    )

    assert worker.reconcile_installation(1) == 0
    assert ingest.claim() is None
    assert "base.sha" in capsys.readouterr().err


def test_reconcile_skips_fork_prs(tmp_path, monkeypatch):
    """A fork's raw diff enters the prompt (_user_text, reader.py:179-187).
    An outside contributor must not be able to drive spend by opening a PR
    during the window when Doug is restarting and reconciling."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(head_repo_id=99)]),
    )
    assert worker.reconcile_installation(1) == 0
    assert ingest.claim() is None


def test_reconcile_skips_bot_authored_prs(tmp_path, monkeypatch):
    """Same-repo Dependabot PRs pass the fork gate. Reconcile must still
    refuse to enqueue them, or a restart would buy the deep read the
    webhook just skipped."""
    _installed(tmp_path, monkeypatch)
    bot = SimpleNamespace(login="dependabot[bot]", type="Bot")
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(user=bot)]),
    )
    assert worker.reconcile_installation(1) == 0
    assert ingest.claim() is None


def test_reconcile_does_not_requeue_a_reviewed_head_sha(tmp_path, monkeypatch):
    """The property that makes startup reconcile free rather than a full
    re-review: the unique index carries no status, so a head SHA already
    taken to 'done' collides on insert exactly like a pending one."""
    _installed(tmp_path, monkeypatch)
    job_id = ingest.enqueue(1, 42, "o/r", 1, "a" * 40, base_sha="0" * 40)
    claimed = ingest.claim()
    assert claimed["id"] == job_id
    assert ingest.complete(job_id, None, claim_generation=claimed["claim_generation"])
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=1, head_sha="a" * 40)]),
    )
    assert worker.reconcile_installation(1) == 0


def test_reconcile_all_covers_only_active_installations(tmp_path, monkeypatch):
    """A suspended or deleted installation still has rows in the table —
    reconciling it would mint tokens for an App the account revoked."""
    _installed(tmp_path, monkeypatch)
    store.upsert_installation(2, "gone", "User", "suspended")
    store.set_installation_repos(2, [(43, "gone/r")], replace=True)
    seen = []

    def client(installation_id):
        seen.append(installation_id)
        return FakeListGH([_pull(number=installation_id)])

    monkeypatch.setattr(worker.app_auth, "installation_client", client)
    assert worker.reconcile_all() == 1
    assert seen == [1]


def test_reconcile_all_survives_one_failing_installation(tmp_path, monkeypatch):
    """Reconcile runs at startup for every tenant at once, so one revoked or
    rate-limited installation raising would leave every other tenant's
    missed PRs unqueued until the next restart."""
    _installed(tmp_path, monkeypatch)
    store.upsert_installation(2, "ok", "User", "active")
    store.set_installation_repos(2, [(43, "ok/r")], replace=True)

    def client(installation_id):
        if installation_id == 1:
            raise RuntimeError("401 bad installation")
        # Installation 2's repo is (43, "ok/r") — the base repo id must
        # agree, or the new base-repo-id guard (added in review) would skip
        # this PR for the wrong reason and mask what this test checks.
        return FakeListGH([_pull(number=5, head_repo_id=43, base_repo_id=43)])

    monkeypatch.setattr(worker.app_auth, "installation_client", client)
    assert worker.reconcile_all() == 1


# --- amendment: reconcile_all heals crash-stranded claims ------------------
#
# reconcile_installation heals a *missed* PR via ingest.enqueue, but a
# crash-stranded claim is left 'running' — REVIVABLE deliberately excludes
# that status, so enqueue collides and returns None forever. reconcile_all
# must call ingest.reclaim_stalled() once, before the enqueue sweep, or the
# case Task 7 is named for ("a deploy killed the instance mid-review") is
# never actually healed by a restart.


def test_reconcile_all_heals_a_crash_stranded_claim_end_to_end(tmp_path, monkeypatch):
    """The amendment's 'test for intent': a 'running' job stranded past its
    lease is, after reconcile_all, back in a state where its PR actually
    gets reviewed — not merely a row whose status flipped. This scenario
    alone (no head SHA change while the claim was stranded) converges to
    the same final row state whichever side of the sweep reclaim runs on —
    enqueue's collision with a still-'running' zombie and its collision
    with an already-reclaimed 'pending' row both resolve to None, since
    REVIVABLE excludes both. So it does not, by itself, prove reclaim runs
    first; see test_reconcile_all_supersedes_a_stranded_claim_whose_pr_moved_on
    (where the head SHA does change and ordering has a real behavioral
    effect) and test_reconcile_all_calls_reclaim_stalled_before_the_enqueue_sweep
    (which pins call order directly, for this test's own scenario) for
    that."""
    url = f"sqlite:///{tmp_path}/doug.db"
    _installed(tmp_path, monkeypatch)
    job_id = ingest.enqueue(1, 42, "o/r", 1, "a" * 40, base_sha="0" * 40)
    stuck = ingest.claim()
    assert stuck["id"] == job_id
    _age_started_at(url, stuck["id"], seconds=ingest.STALL_LEASE_SECONDS + 1)

    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=1, head_sha="a" * 40)]),
    )

    assert worker.reconcile_all() == 0  # reclaimed, not (re)enqueued — no new job minted
    (job,) = _rows(url, store.review_jobs)
    assert job["id"] == job_id and job["status"] == "pending"
    # The reclaimed row is claimable again — a worker will actually review it.
    claimed = ingest.claim()
    assert claimed["id"] == job_id and claimed["head_sha"] == "a" * 40


def test_reconcile_all_supersedes_a_stranded_claim_whose_pr_moved_on(tmp_path, monkeypatch):
    """The case where reclaim-before-sweep has a real, observable effect on
    end state, not just on call order: enqueue's supersede-after-insert
    step (ingest.py) only retires rows that are already 'pending' at this
    (installation, repo, pr) with a different head_sha — it has no effect
    on a row that is still 'running'. A claim stranded at sha A whose PR
    force-pushed to sha B while it was stuck needs reclaim to run first, so
    the sweep's insert of B can supersede A in the same pass. Reclaiming
    after would leave both A and B 'pending' — A as live work a worker
    would claim and then have to supersede itself, instead of the sweep
    having already retired it."""
    url = f"sqlite:///{tmp_path}/doug.db"
    _installed(tmp_path, monkeypatch)
    job_id = ingest.enqueue(1, 42, "o/r", 1, "a" * 40, base_sha="0" * 40)
    stuck = ingest.claim()
    assert stuck["id"] == job_id
    _age_started_at(url, stuck["id"], seconds=ingest.STALL_LEASE_SECONDS + 1)

    # The PR moved on while the claim was stranded: it now reports "b" * 40.
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=1, head_sha="b" * 40)]),
    )

    assert worker.reconcile_all() == 1  # b*40 is genuinely new work
    jobs = {j["head_sha"]: j["status"] for j in _rows(url, store.review_jobs)}
    assert jobs["a" * 40] == "superseded"
    assert jobs["b" * 40] == "pending"


def test_reconcile_all_calls_reclaim_stalled_before_the_enqueue_sweep(tmp_path, monkeypatch):
    """Pins the amendment's ordering requirement directly against call
    order. test_reconcile_all_supersedes_a_stranded_claim_whose_pr_moved_on
    already catches a swap behaviorally for the force-push case; this one
    catches it even when no head SHA changes — the scenario
    test_reconcile_all_heals_a_crash_stranded_claim_end_to_end documents as
    converging to the same final state under either ordering. Tracking
    which of ingest.reclaim_stalled / ingest.enqueue fires first is what
    does that."""
    order: list[str] = []
    real_reclaim = ingest.reclaim_stalled
    real_enqueue = ingest.enqueue
    monkeypatch.setattr(
        ingest,
        "reclaim_stalled",
        lambda *a, **k: order.append("reclaim") or real_reclaim(*a, **k),
    )
    monkeypatch.setattr(
        ingest,
        "enqueue",
        lambda *a, **k: order.append("enqueue") or real_enqueue(*a, **k),
    )
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=1)]),
    )

    worker.reconcile_all()

    assert "enqueue" in order  # sanity: the sweep did run
    assert order[0] == "reclaim"


def test_reconcile_all_calls_reclaim_stalled_not_reconcile_installation(tmp_path, monkeypatch):
    """Scope note from the amendment: reclaim_stalled sweeps the whole queue
    by lease age, not by tenant, so it belongs in the startup path
    (reconcile_all), not per-installation — a per-installation call would
    sweep other tenants' rows as a side effect of one installation's event.
    Pinned directly against the function object rather than behaviourally,
    since reconcile_installation alone has no stalled row in scope to prove
    it either way."""
    calls = []
    real = ingest.reclaim_stalled
    monkeypatch.setattr(ingest, "reclaim_stalled", lambda *a, **k: calls.append(1) or real())
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: FakeListGH([]))

    worker.reconcile_installation(1)
    assert calls == []

    worker.reconcile_all()
    assert calls == [1]


# --- fix: pagination, tenancy identity, and the dedupe/revive comment -----
#
# A code review ran probes rather than reading, and found three Important
# gaps and three cheap Minors in the reconcile implementation above:
#   1. the ordering-equivalence claim in reconcile_all's docstring (and the
#      test docstring that repeated it) was false for the force-push case —
#      fixed above, by adding the supersede test and correcting both
#      docstrings, rather than down here.
#   2. gh.rest.pulls.list(..., per_page=50) fetched one page, silently
#      capping "every open PR" at 50 on a busy repo.
#   3. the dedupe comment claimed a 'done' row and a 'failed' row collide
#      identically; a 'failed' row is instead revived and spent again.
# Plus three minors: _skip_reason's return value was computed and
# discarded; the draft gate didn't apply its own "unknown means skip"
# principle; and full_name-based reconcile trusted a possibly-stale name
# instead of checking the base repo id GitHub actually reports.


def test_reconcile_installation_paginates_past_the_first_page(tmp_path, monkeypatch):
    """gh.rest.pulls.list caps a single response at 100 results. Before this
    fix, one unpaginated call meant a repo with more than 50 open PRs (or,
    after bumping per_page, 100) was healed only in part — permanently and
    silently, under a docstring that promised 'every reviewable open PR'.
    This fakes a two-page repo (100 + 1) and asserts both pages' PRs are
    enqueued, not just the first."""
    _installed(tmp_path, monkeypatch)
    page1 = [_pull(number=n, head_sha=f"{n:040d}") for n in range(1, 101)]
    page2 = [_pull(number=101, head_sha=f"{101:040d}")]

    def _list(*, page=1, **kw):
        data = {1: page1, 2: page2}.get(page, [])
        return SimpleNamespace(parsed_data=data)

    gh = SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(list=_list)))
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    url = f"sqlite:///{tmp_path}/doug.db"
    assert worker.reconcile_installation(1) == 101
    seen = {j["pr_number"] for j in _rows(url, store.review_jobs)}
    assert seen == set(range(1, 102))


def test_reconcile_installation_caps_and_logs_a_pathological_repo(tmp_path, monkeypatch, capsys):
    """The pagination loop still needs a ceiling: an unbounded loop against
    a repo with thousands of open PRs would hang reconcile_all() for every
    other tenant queued behind it. Hitting the cap must be loud, not a
    silent truncation of the same kind Finding 2 exists to fix."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "_MAX_OPEN_PRS_PER_REPO", 150)

    def _list(*, page=1, **kw):
        # Every page comes back full — an unbounded repo, capped by us, not
        # by GitHub running out of pages.
        start = (page - 1) * 100 + 1
        return SimpleNamespace(
            parsed_data=[_pull(number=n, head_sha=f"{n:040d}") for n in range(start, start + 100)]
        )

    gh = SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(list=_list)))
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    count = worker.reconcile_installation(1)
    assert count == 150  # capped, not 200 (two full pages) and not unbounded
    assert "capped at 150" in capsys.readouterr().err


def _closed_pull(
    number=1,
    *,
    merged_at=None,
    updated_at=None,
    merge_commit_sha="c" * 40,
    base_ref="main",
    base_repo_id=42,
    head_sha="a" * 40,
):
    """A closed PR as pulls.list returns it (PullRequestSimple) — no
    merge_commit_sha field, by design (see reconcile_outcomes' docstring);
    a FakeReconcileGH pairs this with a FakeGetGH that supplies it separately,
    the same split the real githubkit schema forces."""
    return SimpleNamespace(
        number=number,
        updated_at=updated_at or (merged_at or NOW),
        merged_at=merged_at,
        base=SimpleNamespace(
            ref=base_ref,
            repo=SimpleNamespace(id=base_repo_id, full_name="o/r"),
        ),
        head=SimpleNamespace(sha=head_sha),
    )


class FakeReconcileGH:
    """pulls.list (no merge_commit_sha) + pulls.get (raw_response.json()
    carries it) — the two-call shape reconcile_outcomes actually uses."""

    def __init__(self, pulls, merge_shas):
        self._merge_shas = merge_shas

        def _get(*, owner, repo, pull_number):
            body = {"merge_commit_sha": self._merge_shas.get(pull_number)}
            return SimpleNamespace(raw_response=SimpleNamespace(json=lambda: body))

        self.rest = SimpleNamespace(
            pulls=SimpleNamespace(
                list=lambda **kw: SimpleNamespace(parsed_data=pulls),
                get=_get,
            )
        )


def test_reconcile_outcomes_enqueues_a_missed_merge(tmp_path, monkeypatch):
    _installed(tmp_path, monkeypatch)
    pull = _closed_pull(number=5, merged_at=NOW - timedelta(days=1))
    gh = FakeReconcileGH([pull], {5: "c" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 2  # 14- and 60-day windows

    url = f"sqlite:///{tmp_path}/doug.db"
    (row_14, row_60) = sorted(
        _rows(url, store.outcome_jobs), key=lambda r: r["window_days"]
    )
    assert row_14["window_days"] == 14 and row_60["window_days"] == 60
    assert row_14["pr_number"] == 5 and row_14["github_repo_id"] == 42
    assert row_14["merge_commit_sha"] == "c" * 40
    assert row_14["base_ref"] == "main"
    assert row_14["merged_head_sha"] == "a" * 40


def test_reconcile_outcomes_skips_a_pr_closed_without_merging(tmp_path, monkeypatch):
    _installed(tmp_path, monkeypatch)
    pull = _closed_pull(number=6, merged_at=None, updated_at=NOW)
    gh = FakeReconcileGH([pull], {})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []


def test_reconcile_outcomes_is_a_no_op_against_a_merge_the_webhook_already_recorded(
    tmp_path, monkeypatch
):
    """The dedup proof: seed the row _record_merge would have written, then
    run reconcile over the same merge, and nothing doubles."""
    _installed(tmp_path, monkeypatch)
    merged_at = NOW - timedelta(days=1)
    store.enqueue_outcome_jobs(1, 42, 5, "c" * 40, merged_at, "main")
    pull = _closed_pull(number=5, merged_at=merged_at)
    gh = FakeReconcileGH([pull], {5: "c" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    rows = _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs)
    assert len(rows) == 2  # still exactly the 14/60-day pair, not four


def test_reconcile_outcomes_ignores_a_merge_outside_the_lookback_window(
    tmp_path, monkeypatch
):
    _installed(tmp_path, monkeypatch)
    stale = _closed_pull(
        number=7, merged_at=NOW - timedelta(days=40), updated_at=NOW - timedelta(days=40)
    )
    gh = FakeReconcileGH([stale], {7: "d" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []


def test_reconcile_outcomes_ignores_an_old_merge_that_was_touched_recently(
    tmp_path, monkeypatch
):
    """updated_at bounds pagination; the lookback window is about the MERGE.
    A comment or label on a years-old merged PR bumps updated_at back inside
    the listing window, and enqueueing it would hand the adjudicator a row
    whose due_at is already long past — an instant verdict on a merge Doug
    never reviewed."""
    _installed(tmp_path, monkeypatch)
    touched = _closed_pull(
        number=9, merged_at=NOW - timedelta(days=400), updated_at=NOW
    )
    gh = FakeReconcileGH([touched], {9: "9" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []


def test_reconcile_outcomes_skips_a_branch_name_too_long_for_the_column(
    tmp_path, monkeypatch, capsys
):
    """outcome_jobs.base_ref is VARCHAR(200) and GitHub allows a longer
    branch name; Postgres answers an over-long INSERT with
    StringDataRightTruncation. _record_merge guards this on the webhook's
    copy of the same fact (_text with the column) — unguarded here the
    exception escapes both try blocks and unwinds the installation, so every
    repo after this one is skipped on this pass and every later one. sqlite
    stores the long value happily, which is why this asserts the skip
    directly rather than trusting the suite's own database to raise.
    """
    _installed(tmp_path, monkeypatch)
    long_ref = "b" * (store.outcome_jobs.c.base_ref.type.length + 1)
    pull = _closed_pull(number=11, merged_at=NOW, base_ref=long_ref)
    gh = FakeReconcileGH([pull], {11: "b" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []
    assert "longer than the column" in capsys.readouterr().err


def test_reconcile_outcomes_skips_a_pr_whose_base_repo_disagrees_with_the_ledger(
    tmp_path, monkeypatch, capsys
):
    _installed(tmp_path, monkeypatch)
    wrong_repo = _closed_pull(number=8, merged_at=NOW, base_repo_id=999)
    gh = FakeReconcileGH([wrong_repo], {8: "e" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    err = capsys.readouterr().err
    assert "base repo id 999" in err and "installation_repos' 42" in err


def test_reconcile_outcomes_survives_an_unparseable_pulls_get_response(
    tmp_path, monkeypatch, capsys
):
    """detail.raw_response.json().get("merge_commit_sha") used to sit OUTSIDE
    the try/except that wraps pulls.get — a response body that failed to
    parse into something .get()-able propagated straight out of
    reconcile_outcomes instead of being treated as one unreadable PR, the
    same way a pulls.get() call that raises outright already was."""
    _installed(tmp_path, monkeypatch)
    pull = _closed_pull(number=9, merged_at=NOW)

    def _get(*, owner, repo, pull_number):
        # A parsed body that is not a dict: .get() raises AttributeError,
        # the same failure mode a malformed real response would produce.
        return SimpleNamespace(raw_response=SimpleNamespace(json=lambda: ["not", "a", "dict"]))

    gh = SimpleNamespace(
        rest=SimpleNamespace(
            pulls=SimpleNamespace(
                list=lambda **kw: SimpleNamespace(parsed_data=[pull]),
                get=_get,
            )
        )
    )
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []
    err = capsys.readouterr().err
    assert "o/r#9" in err and "pulls.get failed" in err


def test_reconcile_outcomes_skips_a_pr_whose_merged_at_is_not_a_datetime(tmp_path, monkeypatch):
    """merged_at went straight from a None check to _aware(), which calls
    .tzinfo with no type check. updated_at a few lines above already guards
    the same call with isinstance(updated_at, datetime); merged_at now gets
    the same guard, so a githubkit UNSET sentinel or another non-datetime,
    non-None value is skipped instead of raising
    AttributeError: '...' object has no attribute 'tzinfo'."""
    _installed(tmp_path, monkeypatch)
    pull = _closed_pull(number=10, merged_at="not-a-datetime", updated_at=NOW)
    gh = FakeReconcileGH([pull], {10: "b" * 40})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 0
    assert _rows(f"sqlite:///{tmp_path}/doug.db", store.outcome_jobs) == []


def test_reconcile_all_outcomes_sums_every_active_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.upsert_installation(1, "o1", "Organization", "active")
    store.set_installation_repos(1, [(42, "o1/r")], replace=True)
    store.upsert_installation(2, "o2", "Organization", "active")
    store.set_installation_repos(2, [(43, "o2/r")], replace=True)

    def _client(installation_id):
        pulls = [
            _closed_pull(number=1, merged_at=NOW, base_repo_id=42 if installation_id == 1 else 43)
        ]
        shas = {1: f"{installation_id}" * 40}
        return FakeReconcileGH(pulls, shas)

    monkeypatch.setattr(worker.app_auth, "installation_client", _client)
    assert worker.reconcile_all_outcomes() == 4  # 2 installations * 2 windows each


def test_reconcile_all_outcomes_survives_one_bad_installation(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    store.upsert_installation(1, "o1", "Organization", "active")
    store.set_installation_repos(1, [(42, "o1/r")], replace=True)
    store.upsert_installation(2, "o2", "Organization", "active")
    store.set_installation_repos(2, [(43, "o2/r")], replace=True)

    def _client(installation_id):
        if installation_id == 1:
            raise RuntimeError("github said no")
        return FakeReconcileGH(
            [_closed_pull(number=1, merged_at=NOW, base_repo_id=43)], {1: "f" * 40}
        )

    monkeypatch.setattr(worker.app_auth, "installation_client", _client)
    assert worker.reconcile_all_outcomes() == 2  # installation 2 still ran
    err = capsys.readouterr().err
    assert "outcome reconcile failed for installation 1" in err and "github said no" in err


def test_reconcile_outcomes_paginates_past_the_first_page(tmp_path, monkeypatch):
    """pulls.list caps a single response at 100 results, the same ceiling
    test_reconcile_installation_paginates_past_the_first_page pins for the
    review lane. sort=updated,direction=desc means the 101st-newest closed
    PR is still inside the lookback window and must not be silently
    dropped for want of a second page."""
    _installed(tmp_path, monkeypatch)
    page1 = [_closed_pull(number=n, merged_at=NOW, updated_at=NOW) for n in range(1, 101)]
    page2 = [_closed_pull(number=101, merged_at=NOW, updated_at=NOW)]
    merge_shas = {n: f"{n:040d}" for n in range(1, 102)}

    def _list(*, page=1, **kw):
        data = {1: page1, 2: page2}.get(page, [])
        return SimpleNamespace(parsed_data=data)

    def _get(*, owner, repo, pull_number):
        body = {"merge_commit_sha": merge_shas[pull_number]}
        return SimpleNamespace(raw_response=SimpleNamespace(json=lambda: body))

    gh = SimpleNamespace(rest=SimpleNamespace(pulls=SimpleNamespace(list=_list, get=_get)))
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 202  # 101 merges * 2 windows each
    url = f"sqlite:///{tmp_path}/doug.db"
    seen = {r["pr_number"] for r in _rows(url, store.outcome_jobs)}
    assert seen == set(range(1, 102))


def test_reconcile_outcomes_caps_and_logs_a_pathological_repo(tmp_path, monkeypatch, capsys):
    """The outcome lane's sibling of
    test_reconcile_installation_caps_and_logs_a_pathological_repo — same
    monkeypatch-the-constant-down technique, same log-and-truncate shape."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "_MAX_CLOSED_PRS_PER_REPO", 3)
    pulls = [_closed_pull(number=n, merged_at=NOW, updated_at=NOW) for n in range(1, 5)]
    gh = FakeReconcileGH(pulls, {n: f"{n:040d}" for n in range(1, 5)})
    monkeypatch.setattr(worker.app_auth, "installation_client", lambda i: gh)

    assert worker.reconcile_outcomes(1) == 6  # capped at 3 PRs * 2 windows
    err = capsys.readouterr().err
    assert "capped at 3 closed PRs for o/r" in err


def test_reconcile_all_revives_a_pr_that_burned_all_its_attempts(tmp_path, monkeypatch):
    """A PR that burned every retry is not dead forever — ingest._revive
    resets a 'failed' row to 'pending' with attempts=0, which is how a
    review lost to a real outage heals on a later restart.

    The cost of that, which Doug's own review of this PR flagged: reconcile
    runs at every startup, so without a brake a permanently-broken PR
    re-arms max_attempts paid reads on each one, and the bill scales with
    how often the service cold-starts rather than with anything the
    customer did. FAILED_REVIVE_COOLOFF_SECONDS is the brake. This pins
    both halves through reconcile_all — not just ingest.enqueue, which
    test_ingest.py covers directly — because the startup path is where the
    repetition actually comes from.
    """
    url = f"sqlite:///{tmp_path}/doug.db"
    _installed(tmp_path, monkeypatch)
    job_id = ingest.enqueue(1, 42, "o/r", 1, "a" * 40, base_sha="0" * 40)
    for _ in range(3):
        claimed = ingest.claim()
        assert claimed["id"] == job_id
        assert ingest.fail(
            job_id, "credentials missing", claim_generation=claimed["claim_generation"]
        )
    (failed,) = _rows(url, store.review_jobs)
    assert failed["id"] == job_id and failed["status"] == "failed" and failed["attempts"] == 3

    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=1, head_sha="a" * 40)]),
    )
    # A restart inside the cooloff re-arms nothing, however many times it happens.
    assert worker.reconcile_all() == 0
    assert worker.reconcile_all() == 0
    (still_failed,) = _rows(url, store.review_jobs)
    assert still_failed["status"] == "failed" and still_failed["attempts"] == 3

    with create_engine(url).begin() as conn:
        conn.execute(
            store.review_jobs.update()
            .where(store.review_jobs.c.id == job_id)
            .values(
                finished_at=datetime.now(UTC)
                - timedelta(seconds=ingest.FAILED_REVIVE_COOLOFF_SECONDS + 60)
            )
        )

    assert worker.reconcile_all() == 1  # counted: a revive, not a fresh insert
    (revived,) = _rows(url, store.review_jobs)
    assert revived["id"] == job_id  # same row, in place
    assert revived["status"] == "pending" and revived["attempts"] == 0


def test_reconcile_installation_takes_live_terms_unless_the_sweep_asks_otherwise(
    tmp_path, monkeypatch
):
    """Which caller repeats itself is a property of the caller, not of
    reconciling one installation.

    FAILED_REVIVE_COOLOFF_SECONDS is a brake on a caller that re-derives the
    whole world whether or not anything changed, and this function cannot know
    whether its caller is one: hardcoding the sweep's terms one function deeper
    would hand the brake to a future caller reacting to a single head change,
    which has one event's worth of spend behind it and nothing to brake.

    Both halves are asserted here — the default revives, and an explicit
    'reconcile' still does not — because a default that revived everything on
    both paths would pass the first assertion while deleting the cooloff.

    This is the function's own contract, not any call site's. Every caller
    today asks for 'reconcile' out loud, api.py's installation.created handler
    included (test_api.py's
    test_the_installation_created_handler_asks_for_the_sweeps_terms), so the
    default below is exercised here rather than in production — deliberately,
    since the direction it fails in is what a mistyped or forgotten trigger
    inherits.
    """
    url = f"sqlite:///{tmp_path}/doug.db"
    _installed(tmp_path, monkeypatch)
    job_id = ingest.enqueue(1, 42, "o/r", 1, "a" * 40, base_sha="0" * 40)
    for _ in range(3):
        claimed = ingest.claim()
        assert claimed["id"] == job_id
        assert ingest.fail(
            job_id, "credentials missing", claim_generation=claimed["claim_generation"]
        )
    (failed,) = _rows(url, store.review_jobs)
    # Inside the cooloff, with a real finished_at: the terms the caller claims
    # are the only thing that can decide the revival below.
    assert failed["status"] == "failed" and failed["finished_at"] is not None

    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=1, head_sha="a" * 40)]),
    )

    # The sweep's terms, asked for explicitly: the brake still applies.
    assert worker.reconcile_installation(1, trigger="reconcile") == 0
    assert _rows(url, store.review_jobs)[0]["status"] == "failed"

    # The default: what a caller that names no terms at all gets.
    assert worker.reconcile_installation(1) == 1
    (revived,) = _rows(url, store.review_jobs)
    assert revived["id"] == job_id  # the same row, healed in place
    assert revived["status"] == "pending" and revived["attempts"] == 0


def test_reconcile_logs_why_a_pr_was_skipped(tmp_path, monkeypatch, capsys):
    """_skip_reason's return value used to be computed and discarded at its
    only call site — an unreadable repo got a log line, but the spend gate
    itself (draft/fork) left no audit trail. The one thing worth being able
    to check after the fact is exactly why a given PR was not reviewed."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(number=9, draft=True)]),
    )
    assert worker.reconcile_installation(1) == 0
    err = capsys.readouterr().err
    assert "#9" in err and "draft" in err


def test_reconcile_logs_a_pr_the_cooloff_held_back_but_not_an_ordinary_dedupe(
    tmp_path, monkeypatch, capsys
):
    """The last reconcile skip with no audit trail.

    test_reconcile_logs_why_a_pr_was_skipped states the principle: what is
    worth being able to check after the fact is exactly why a given PR was not
    reviewed. Draft/fork and the base-repo-id mismatch both log; the cooloff
    did not, because enqueue returns None both when it deduped a row already
    reviewed and when it held back a 'failed' one — an operator watching a PR
    that Doug is silently waiting an hour on saw the same empty trace as one
    that had already been reviewed.

    The second half is why this is a log line and not noise: the boring case
    is nearly every open PR on every sweep, and logging those would bury the
    interesting one.
    """
    url = f"sqlite:///{tmp_path}/doug.db"
    _installed(tmp_path, monkeypatch)
    held = ingest.enqueue(1, 42, "o/r", 1, "a" * 40, base_sha="0" * 40)
    for _ in range(3):
        claimed = ingest.claim()
        assert claimed["id"] == held
        assert ingest.fail(
            held, "reader exploded", claim_generation=claimed["claim_generation"]
        )
    reviewed = ingest.enqueue(1, 42, "o/r", 2, "b" * 40, base_sha="0" * 40)
    claimed = ingest.claim()
    assert claimed["id"] == reviewed
    assert ingest.complete(reviewed, None, claim_generation=claimed["claim_generation"])
    assert {j["id"]: j["status"] for j in _rows(url, store.review_jobs)} == {
        held: "failed", reviewed: "done",
    }

    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([
            _pull(number=1, head_sha="a" * 40),
            _pull(number=2, head_sha="b" * 40),
        ]),
    )
    assert worker.reconcile_all() == 0  # neither is new work

    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if "o/r#" in ln]
    assert len(lines) == 1, f"expected exactly one PR-level line, got {lines}"
    assert "o/r#1" in lines[0] and "cooloff" in lines[0]


def test_skip_reason_treats_missing_or_unset_draft_as_skip():
    """The docstring's whole UNSET rationale was previously unexercised: the
    old check (`getattr(p, "draft", False) is True`) let anything that
    wasn't the literal `True` — including UNSET and a genuinely missing
    field — fall through to "review it". Only an explicit draft=False
    should do that; True, UNSET, and missing must all skip, the same
    direction the fork check already treats its own UNSET/missing case."""
    from githubkit.utils import UNSET

    ready = SimpleNamespace(
        draft=False,
        head=SimpleNamespace(sha="a" * 40, repo=SimpleNamespace(id=42)),
        base=SimpleNamespace(repo=SimpleNamespace(id=42, full_name="o/r")),
    )
    assert worker._skip_reason(ready) is None

    unset = SimpleNamespace(
        draft=UNSET,
        head=ready.head,
        base=ready.base,
    )
    assert worker._skip_reason(unset) == "draft"

    missing = SimpleNamespace(head=ready.head, base=ready.base)  # no draft attribute at all
    assert worker._skip_reason(missing) == "draft"


def test_skip_reason_treats_missing_or_unset_repo_ids_as_fork():
    """Same UNSET rationale, the branch that was already correct — pinned
    with a real UNSET value and a genuinely missing attribute, not just the
    isinstance reasoning in the comment above it."""
    from githubkit.utils import UNSET

    unset_head_id = SimpleNamespace(
        draft=False,
        head=SimpleNamespace(sha="a" * 40, repo=SimpleNamespace(id=UNSET)),
        base=SimpleNamespace(repo=SimpleNamespace(id=42, full_name="o/r")),
    )
    assert worker._skip_reason(unset_head_id) == "fork"

    missing_head = SimpleNamespace(draft=False, head=SimpleNamespace(sha="a" * 40))
    assert worker._skip_reason(missing_head) == "fork"


def test_skip_reason_returns_bot_for_a_bot_user():
    """The webhook and reconcile share this gate. A GitHub App author is
    not a draft and not a fork — without this branch, Dependabot buys a
    deep read on every open PR the App can see."""
    bot = SimpleNamespace(
        draft=False,
        head=SimpleNamespace(sha="a" * 40, repo=SimpleNamespace(id=42)),
        base=SimpleNamespace(repo=SimpleNamespace(id=42, full_name="o/r")),
        user=SimpleNamespace(login="dependabot[bot]", type="Bot"),
    )
    assert worker._skip_reason(bot) == "bot"

    suffix_only = SimpleNamespace(
        draft=False,
        head=bot.head,
        base=bot.base,
        user=SimpleNamespace(login="renovate[bot]", type="User"),
    )
    assert worker._skip_reason(suffix_only) == "bot"

    human = SimpleNamespace(
        draft=False,
        head=bot.head,
        base=bot.base,
        user=SimpleNamespace(login="alice", type="User"),
    )
    assert worker._skip_reason(human) is None

    missing = SimpleNamespace(
        draft=False,
        head=bot.head,
        base=bot.base,
    )
    assert worker._skip_reason(missing) is None


def test_reconcile_skips_a_pr_whose_base_repo_id_disagrees_with_the_store(tmp_path, monkeypatch):
    """installation_repos' full_name can go stale: a repo can be deleted and
    its name picked up by an unrelated one. github_repo_id is the fact the
    store's tenancy actually keys on and the only one GitHub still
    guarantees, so a PR whose base repo id disagrees with it belongs to a
    different repo than the one this installation was granted, and must
    not be reconciled — or paid for — under this installation's identity.
    head_repo_id is set equal to base_repo_id here so this isn't just the
    fork check firing for the wrong reason."""
    _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.app_auth, "installation_client",
        lambda i: FakeListGH([_pull(head_repo_id=999, base_repo_id=999)]),
    )
    assert worker.reconcile_installation(1) == 0
    assert ingest.claim() is None


# --- observability: make a successful review visible in the log -----------
#
# process_job wrote nothing on any outcome that succeeded, so "the review
# ran" and "the job was never claimed at all" were indistinguishable from
# the logs — the only lines it could produce were drain's failure line and
# the reclaim/skip lines. That was survivable only while doug-review.yml
# still posted a job summary for every PR; Task 9 deleted that workflow, and
# the check run is now the sole observable.
#
# Three outcomes returned silently, and the fresh-vs-replay pair is the
# reason these tests are worded the way they are. A fresh review buys a
# model read; a replay re-renders a verdict already in the ledger and buys
# nothing. One line that covers both would be worse than no line, because an
# operator counting reviews would be counting spend that never happened.


def _pr_lines(capsys) -> list[str]:
    """The process_job outcome lines for JOB's PR, in the order emitted.

    Filtered on the repo#pr the line leads with, which is what keeps drain's
    `doug: job N failed` line and the reclaim line (neither of which names a
    PR) out of the assertions below."""
    return [ln for ln in capsys.readouterr().err.splitlines() if "drewjst/doug#7" in ln]


def test_a_fresh_review_logs_the_read_it_paid_for(tmp_path, monkeypatch, capsys):
    """Outcome 1 of 3: score_one ran, a row landed, a check run posted.

    This is the only one of the three that spent money, and the line has to
    say so in its own words rather than leaving it inferable from the
    absence of some other line. Carries what identifies the review — repo,
    PR, short head SHA, tier, band, score, verdict id — and none of the
    model's prose, which belongs on the check run and not in a log."""
    _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    ingest.enqueue(**JOB)
    verdict_id = worker.process_job(ingest.claim())

    (line,) = _pr_lines(capsys)
    assert "reviewed" in line
    assert "paid read" in line
    assert f"tier=reader band=flagged risk=0.62 verdict={verdict_id}" in line
    # Short SHA, not the whole 40 — enough to identify the commit by eye.
    assert "@" + "a" * 12 in line
    assert "a" * 40 not in line
    # Nothing sensitive: the finding's model-authored label stays on the
    # check run. A log line is not a place to launder prompt output into.
    assert "Cache write is not guarded" not in line


def test_both_reads_of_a_job_charge_that_installations_own_budget(tmp_path, monkeypatch):
    """The one paid entry point that has tenancy, so the one that charges a
    real tenant. Both reads name the same scope — one PR costs two units
    against one knob — and neither falls back to the sentinel the
    un-tenanted callers share, or a busy customer would exhaust the CI
    path's budget and vice versa."""
    _db(tmp_path, monkeypatch)
    scopes: list[tuple[str, str]] = []
    _wire(monkeypatch, scopes=scopes)

    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())

    owner = reader.installation_scope(JOB["installation_id"])
    assert scopes == [("risk", owner), ("intent", owner)]
    assert owner != reader.SENTINEL_SCOPE


def test_a_capped_review_renders_as_the_deterministic_fallback_it_is(tmp_path, monkeypatch):
    """ADR-0010's honesty rule, carried through the path this branch adds.

    A capped verdict came from the deterministic scorer, which never opened
    the diff, so the check run's title — the only part of Doug visible from
    a PR's checks list — has to say so. A fallback rendered as a read is the
    one thing that surface must never do, and a spend ceiling is a new way
    to produce one.

    Nothing is stubbed between the counter and the title: a real ledger with
    this installation's ceiling at zero, the real read_diff, the real
    score_one, the real renderer. _client is booby-trapped, so the test also
    fails if the cap is ever consulted after the model call rather than
    before it.
    """
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.delenv("DOUG_INTENT", raising=False)
    monkeypatch.setattr(reader, "INSTALLATION_MONTHLY_READ_CAP", 0)

    def _no_client():
        raise AssertionError("a client was built for a read the cap refused")

    monkeypatch.setattr(reader, "_client", _no_client)

    posted: list[dict] = []
    gh = _gh()
    monkeypatch.setattr(app_auth, "installation_client", lambda i: gh)
    monkeypatch.setattr(review, "fetch_pr", lambda gh, o, r, n: (_pr(), "+ x"))
    monkeypatch.setattr(
        check_run,
        "post",
        lambda gh, o, r, sha, title, summary: posted.append(dict(title=title, summary=summary)),
    )

    ingest.enqueue(**JOB)
    worker.process_job(ingest.claim())

    (run,) = posted
    assert run["title"].startswith("Deterministic fallback")
    assert "diff read" not in run["title"]
    assert check_run.FALLBACK_NOTE in run["summary"]
    # Named as a ceiling, not as a broken reader: the two need different
    # responses from whoever reads it.
    assert "reader-capped" in run["summary"]
    assert "reader-unavailable" not in run["summary"]

    (row,) = _rows(url, store.verdicts)
    assert row["tier"] == "deterministic"
    # A model column filled in for a read that never happened would put a
    # capped verdict in the reader tier's evidence base.
    assert row["model"] is None


def test_an_idempotent_replay_says_it_bought_nothing(tmp_path, monkeypatch, capsys):
    """Outcome 2 of 3: find_verdict_by_identity answered, so the check run
    is re-rendered from the stored row and no read was bought.

    Same setup as the reclaim-replay test above — a worker that died between
    save_review committing and ingest.complete running. The line reports the
    same verdict the fresh line would, which is exactly why it cannot use
    the same words for it."""
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    ingest.enqueue(**JOB)
    claimed = ingest.claim()
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

    (line,) = _pr_lines(capsys)
    assert "replayed" in line
    assert "paid read" not in line  # the whole point: no money changed hands
    assert f"tier=reader band=flagged risk=0.62 verdict={verdict_id}" in line
    assert "@" + "a" * 12 in line


def test_a_race_loser_replays_the_peer_and_does_not_attach_local_deviations(
    tmp_path, monkeypatch, capsys
):
    """Migration 005 race floor: both holders miss the pre-read and both pay;
    save_review returns the peer's id. The loser must post the peer's check
    run (not a locally rendered one) and must not write its intent findings
    onto the peer's row.
    """
    url = _db(tmp_path, monkeypatch)
    posted = _wire(monkeypatch)
    peer_id = store.save_review(
        JOB["repo_full_name"],
        JOB["pr_number"],
        "deterministic",
        Verdict(score=0.01, band=Band.CLEARED, threshold=0.30, reasons=[]),
        github_repo_id=JOB["github_repo_id"],
        installation_id=JOB["installation_id"],
        head_sha=JOB["head_sha"],
        source="app",
    )
    calls = {"n": 0}
    real = store.find_verdict_by_identity

    def miss_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "find_verdict_by_identity", miss_once)
    ingest.enqueue(**JOB)

    assert worker.process_job(ingest.claim()) == peer_id

    (line,) = _pr_lines(capsys)
    assert "raced" in line and "paid read discarded" in line
    assert "replayed" not in line  # that wording means nothing was bought
    assert f"verdict={peer_id}" in line
    with create_engine(url).connect() as conn:
        assert (
            conn.execute(
                select(store.verdicts).where(store.verdicts.c.id == peer_id)
            )
            .mappings()
            .one()["tier"]
            == "deterministic"
        )
        assert (
            conn.execute(
                select(store.deviations).where(store.deviations.c.verdict_id == peer_id)
            )
            .mappings()
            .all()
            == []
        )
    # Peer was deterministic/cleared 0.01 — not the locally scored reader 0.62.
    assert len(posted) == 1
    assert "0.01" in posted[0]["title"] or "Cleared" in posted[0]["title"]


def test_a_superseded_job_says_it_read_nothing(tmp_path, monkeypatch, capsys):
    """Outcome 3 of 3: the branch moved while the job sat in the queue, so
    the job is retired and the PR's real head is enqueued in its place.

    Nothing was read, so there is no verdict to name — and naming one would
    be a lie about a commit this job never opened. Both SHAs appear, because
    "which commit overtook it" is the only question this line is asked."""
    _db(tmp_path, monkeypatch)
    _wire(monkeypatch, heads={7: "c" * 40})
    ingest.enqueue(**JOB)

    assert worker.process_job(ingest.claim()) is None

    (line,) = _pr_lines(capsys)
    assert "superseded" in line
    assert "paid read" not in line
    assert "verdict=" not in line  # there is no verdict; do not invent one
    assert "@" + "a" * 12 in line and "c" * 12 in line


def test_a_replay_never_reads_like_the_fresh_review_it_replays(tmp_path, monkeypatch, capsys):
    """The reason this change exists, pinned directly.

    A fresh review and a replay of it agree on every field worth logging —
    same repo, same PR, same head SHA, same tier, band, score and verdict
    id. The single thing they disagree about is whether a model read was
    bought, so that difference has to live in the wording or it does not
    exist at all: a line reporting both identically would make spend
    unauditable from the logs, with an operator counting reviews counting
    replays as paid reads.

    So this asserts the identifying fields are the SAME on both lines and
    the paid-read claim appears on exactly one of them, in that order. A
    test that only checked "both logged something" would survive the defect
    it exists to catch.

    The setup is ingest.complete raising after save_review already landed,
    which is also why the fresh line is emitted before that call: the read
    is paid for and the verdict durable by then, and the one failure that
    re-pends a job in that state must not erase the record of what it cost.
    """
    url = _db(tmp_path, monkeypatch)
    _wire(monkeypatch)
    real_complete = ingest.complete
    armed = {"boom": True}

    def _flaky_complete(job_id, verdict_id, *, claim_generation):
        if armed["boom"]:
            armed["boom"] = False
            raise RuntimeError("db hiccup")
        return real_complete(
            job_id, verdict_id, claim_generation=claim_generation
        )

    monkeypatch.setattr(ingest, "complete", _flaky_complete)
    ingest.enqueue(**JOB)

    assert worker.drain() == 1  # scores, saves, posts — then complete blows up
    assert worker.drain() == 1  # replays the durable verdict, buying nothing

    (v,) = _rows(url, store.verdicts)
    lines = _pr_lines(capsys)
    assert len(lines) == 2, f"expected one outcome line per pass, got {lines}"

    # Identical facts on both lines, so nothing incidental can be doing the
    # distinguishing for the wording.
    for ln in lines:
        assert f"tier=reader band=flagged risk=0.62 verdict={v['id']}" in ln

    assert lines[0] != lines[1]
    # Exactly one paid read happened, and it is countable: the first pass.
    assert [("paid read" in ln) for ln in lines] == [True, False]
