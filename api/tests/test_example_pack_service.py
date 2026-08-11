from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from doug.example_pack import (
    CapturedFindingV0,
    ContentCollisionError,
    ContentRefV0,
    CoverageV0,
    EvidenceReceiptV0,
    ExamplePackV0,
    NameVersionV0,
    PackScopeV0,
    UsageV0,
    WholeInstrumentManifestV0,
)
from doug.example_pack_hosted import CohortManifestV0, HostedExamplePackRepository
from doug.example_pack_service import (
    AdjudicationContractError,
    ExamplePackService,
    StaleAdjudicationError,
    UnknownPackError,
)

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
REQUEST = b'{"model":"m"}'
EVIDENCE = b"+guard"
RAW = b'{"findings":[]}'


class MemoryObjects:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def create(self, key: str, data: bytes, *, content_type: str) -> None:
        current = self.objects.get(key)
        if current is None:
            self.objects[key] = (data, content_type)
        elif current != (data, content_type):
            raise ContentCollisionError("different bytes")

    def read(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise FileNotFoundError(key) from None

    def list(self, prefix: str) -> tuple[str, ...]:
        return tuple(sorted(key for key in self.objects if key.startswith(prefix)))


def _manifest() -> CohortManifestV0:
    return CohortManifestV0(
        cohort_id="c1",
        capture_started_at=NOW - timedelta(hours=1),
        capture_until=NOW + timedelta(hours=1),
        installation_ids=(10,),
        github_repository_ids=(20,),
        application_revision="a" * 40,
    )


def _pack(*, pull_number: int = 1, model: str = "m") -> ExamplePackV0:
    instrument = WholeInstrumentManifestV0(
        provider="anthropic",
        pinned_model_id=model,
        max_output_tokens=100,
        effort="medium",
        inference_parameters=(),
        system_prompt_sha256="1" * 64,
        output_schema_sha256="2" * 64,
        diff_budget=1000,
        read_order="tiered",
        input_policy_version="reader-input-v0",
        coverage_policy_version="reader-coverage-v0",
        verifier_versions=(NameVersionV0(name="settle", version="v0"),),
        tool_versions=(),
        failure_policy_version="reader-fallback-v0",
        publication_policy_version="neutral-check-v0",
        application_revision="a" * 40,
        runtime_revision="doug-api-42",
        attempt_kind="risk",
    )
    return ExamplePackV0.build(
        run_id=f"review-job:{40 + pull_number}:claim:1:risk",
        attempt_kind="risk",
        captured_at=NOW,
        scope=PackScopeV0(
            installation_id=10,
            github_repository_id=20,
            repository_full_name="owner/repo",
            pull_number=pull_number,
            admitted_base_sha=f"{pull_number:040x}",
            admitted_head_sha=f"{pull_number + 10:040x}",
        ),
        request=ContentRefV0.from_bytes(REQUEST, media_type="application/json"),
        evidence=ContentRefV0.from_bytes(EVIDENCE, media_type="text/plain"),
        model_call_made=True,
        raw_output=ContentRefV0.from_bytes(RAW, media_type="text/plain"),
        parsed_output={"risk_score": 0, "rationale": "", "findings": []},
        coverage=CoverageV0(
            diff_chars=len(EVIDENCE),
            sent_chars=len(EVIDENCE),
            files_sent=1,
            files_unseen=(),
        ),
        usage=UsageV0(input_tokens=1, output_tokens=1),
        latency_ms=1,
        capture_status="captured",
        failure=None,
        fallback_state="none",
        instrument_manifest=instrument,
        instrument_id=instrument.instrument_id(),
        findings=(),
    )


def _repository() -> tuple[MemoryObjects, HostedExamplePackRepository, ExamplePackV0]:
    objects = MemoryObjects()
    repository = HostedExamplePackRepository(objects, "c1")
    pack = _pack()
    repository.ensure_manifest(_manifest())
    repository.put_blob(REQUEST, media_type="application/json")
    repository.put_blob(EVIDENCE, media_type="text/plain")
    repository.put_blob(RAW, media_type="text/plain")
    repository.put_pack(pack)
    repository.put_membership(pack, review_job_id=41)
    return objects, repository, pack


def _job(pack: ExamplePackV0, *, job_id: int = 41) -> dict[str, object]:
    return {
        "id": job_id,
        "installation_id": pack.scope.installation_id,
        "github_repository_id": pack.scope.github_repository_id,
        "repository_full_name": pack.scope.repository_full_name,
        "pull_number": pack.scope.pull_number,
        "admitted_base_sha": pack.scope.admitted_base_sha,
        "admitted_head_sha": pack.scope.admitted_head_sha,
        "started_at": NOW,
        "finished_at": NOW + timedelta(minutes=1),
    }


def test_complete_cohort_scores_only_durable_matched_members():
    objects, _repository_value, pack = _repository()
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [_job(pack)],
    )

    detail = service.cohort_detail("c1")

    assert detail.availability.status == "complete"
    assert detail.completeness.completed_jobs == 1
    assert detail.completeness.members == 1
    assert detail.completeness.missing == ()
    assert detail.completeness.extra == ()
    assert len(detail.instruments) == 1
    assert detail.instruments[0].scorecard.eligible_prs == 1


def test_missing_completed_job_blocks_every_instrument_scorecard():
    objects, _repository_value, pack = _repository()
    missing = _job(_pack(pull_number=2), job_id=42)
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [_job(pack), missing],
    )

    detail = service.cohort_detail("c1")

    assert detail.availability.status == "incomplete"
    assert [identity.pull_number for identity in detail.completeness.missing] == [2]
    assert detail.instruments == ()


def test_member_without_a_completed_job_is_labeled_extra_and_not_scored():
    objects, _repository_value, _pack_value = _repository()
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [],
    )

    detail = service.cohort_detail("c1")

    assert detail.availability.status == "complete"
    assert [identity.pull_number for identity in detail.completeness.extra] == [1]
    assert detail.completeness.extra[0].repository_full_name == "owner/repo"
    assert detail.instruments == ()


def test_manifest_without_attempts_is_empty_not_complete_or_unavailable():
    objects = MemoryObjects()
    HostedExamplePackRepository(objects, "c1").ensure_manifest(_manifest())
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [],
    )

    detail = service.cohort_detail("c1")

    assert detail.availability.status == "empty"
    assert detail.completeness.completed_jobs == 0
    assert detail.completeness.members == 0
    assert detail.instruments == ()


def test_list_results_and_pack_detail_share_validated_exact_evidence():
    objects, _repository_value, pack = _repository()
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [_job(pack)],
    )

    [summary] = service.list_cohorts()
    results = service.results("c1")
    pack_detail = service.pack_detail("c1", pack.pack_hash)

    assert summary.manifest.cohort_id == "c1"
    assert summary.availability.status == "complete"
    assert results.completeness.completed_jobs == 1
    assert results.instruments[0].instrument_id == pack.instrument_id
    assert pack_detail.pack == pack
    assert pack_detail.request == {"model": "m"}
    assert pack_detail.evidence_text == "+guard"
    assert pack_detail.raw_output_text == '{"findings":[]}'
    assert pack_detail.effective_adjudications == ()


def test_unknown_pack_is_not_confused_with_an_empty_cohort():
    objects, _repository_value, pack = _repository()
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [_job(pack)],
    )

    with pytest.raises(UnknownPackError, match="unknown pack"):
        service.pack_detail("c1", "f" * 64)


def test_cohort_list_marks_missing_evidence_invalid_instead_of_looking_empty():
    service = ExamplePackService(
        MemoryObjects(),
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [],
    )

    [summary] = service.list_cohorts()

    assert summary.cohort_id == "c1"
    assert summary.manifest is None
    assert summary.completeness is None
    assert summary.availability.status == "invalid"
    assert summary.availability.reason == "cohort evidence is invalid or unavailable"


def _finding_repository():
    objects = MemoryObjects()
    repository = HostedExamplePackRepository(objects, "c1")
    exact_finding = {
        "category_slug": "race-condition",
        "description": "write is not guarded",
        "file": "cache.py",
        "severity": "high",
    }
    raw = (
        b'{"findings":[{"category_slug":"race-condition",'
        b'"description":"write is not guarded","file":"cache.py",'
        b'"severity":"high"}]}'
    )
    finding = CapturedFindingV0.build(
        raw_output_sha256=ContentRefV0.from_bytes(raw, media_type="text/plain").sha256,
        attempt_kind="risk",
        ordinal=0,
        finding=exact_finding,
    )
    base = _pack()
    payload = base.model_dump(
        mode="python", exclude={"pack_hash", "raw_output", "parsed_output", "findings"}
    )
    pack = ExamplePackV0.build(
        **payload,
        raw_output=ContentRefV0.from_bytes(raw, media_type="text/plain"),
        parsed_output={"findings": [exact_finding]},
        findings=(finding,),
    )
    repository.ensure_manifest(_manifest())
    repository.put_blob(REQUEST, media_type="application/json")
    repository.put_blob(EVIDENCE, media_type="text/plain")
    repository.put_blob(raw, media_type="text/plain")
    repository.put_pack(pack)
    repository.put_membership(pack, review_job_id=41)
    return objects, pack


def test_adjudication_is_append_only_and_correction_names_the_observed_head():
    objects, pack = _finding_repository()
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [_job(pack)],
        adjudication_lock=lambda *_args: nullcontext(),
    )

    first = service.adjudicate(
        "c1",
        pack.pack_hash,
        pack.findings[0].finding_id,
        disposition="unknown",
        evidence=(),
        verifier_receipts=(),
        expected_current_adjudication_id=None,
        adjudicator="andrew",
        adjudicated_at=NOW,
    )
    correction = service.adjudicate(
        "c1",
        pack.pack_hash,
        pack.findings[0].finding_id,
        disposition="disproved",
        evidence=(
            EvidenceReceiptV0(
                kind="source",
                locator="cache.py:10",
                detail="the write is guarded by the lock above",
            ),
        ),
        verifier_receipts=(),
        expected_current_adjudication_id=first.adjudication_id,
        adjudicator="andrew",
        adjudicated_at=NOW + timedelta(seconds=1),
    )

    assert correction.supersedes == first.adjudication_id
    detail = service.pack_detail("c1", pack.pack_hash)
    assert detail.effective_adjudications == (correction,)


def test_stale_or_receipt_free_conclusive_adjudication_fails_without_a_write():
    objects, pack = _finding_repository()
    service = ExamplePackService(
        objects,
        cohort_ids=("c1",),
        completed_jobs=lambda **_kwargs: [_job(pack)],
        adjudication_lock=lambda *_args: nullcontext(),
    )
    first = service.adjudicate(
        "c1",
        pack.pack_hash,
        pack.findings[0].finding_id,
        disposition="unknown",
        evidence=(),
        verifier_receipts=(),
        expected_current_adjudication_id=None,
        adjudicator="andrew",
        adjudicated_at=NOW,
    )

    with pytest.raises(StaleAdjudicationError, match="stale"):
        service.adjudicate(
            "c1",
            pack.pack_hash,
            pack.findings[0].finding_id,
            disposition="unknown",
            evidence=(),
            verifier_receipts=(),
            expected_current_adjudication_id=None,
            adjudicator="andrew",
            adjudicated_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(AdjudicationContractError, match="receipt"):
        service.adjudicate(
            "c1",
            pack.pack_hash,
            pack.findings[0].finding_id,
            disposition="verified_actionable",
            evidence=(),
            verifier_receipts=(),
            expected_current_adjudication_id=first.adjudication_id,
            adjudicator="andrew",
            adjudicated_at=NOW + timedelta(seconds=2),
        )
