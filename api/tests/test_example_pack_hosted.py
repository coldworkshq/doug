import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from doug.example_pack import (
    ContentCollisionError,
    ContentRefV0,
    CoverageV0,
    ExamplePackError,
    ExamplePackV0,
    NameVersionV0,
    PackScopeV0,
    UsageV0,
    WholeInstrumentManifestV0,
)
from doug.example_pack_hosted import (
    CohortManifestV0,
    EvaluationIdentityV0,
    HostedExamplePackRepository,
)

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
REQUEST = b'{"model":"claude-opus-5"}'
EVIDENCE = b"+guard the write"
RAW = b'{"findings":[]}'


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def create(self, key: str, data: bytes, *, content_type: str) -> None:
        existing = self.objects.get(key)
        if existing is None:
            self.objects[key] = (data, content_type)
            return
        if existing != (data, content_type):
            raise ContentCollisionError("different bytes already exist")

    def read(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise FileNotFoundError(key) from None

    def list(self, prefix: str) -> tuple[str, ...]:
        return tuple(sorted(key for key in self.objects if key.startswith(prefix)))


def _instrument(*, model: str = "claude-opus-5") -> WholeInstrumentManifestV0:
    return WholeInstrumentManifestV0(
        provider="anthropic",
        pinned_model_id=model,
        max_output_tokens=6000,
        effort="medium",
        inference_parameters=(NameVersionV0(name="temperature", version="provider-default"),),
        mechanical_parameters= (
            NameVersionV0(name="verify_finding.model", version="claude-sonnet-5"),
        ),
        system_prompt_sha256="1" * 64,
        output_schema_sha256="2" * 64,
        diff_budget=100_000,
        read_order="tiered",
        input_policy_version="reader-input-v0",
        coverage_policy_version="reader-coverage-v0",
        verifier_versions=(NameVersionV0(name="settle", version="v0"),),
        tool_versions=(NameVersionV0(name="anthropic-sdk", version="0.70.0"),),
        failure_policy_version="reader-fallback-v0",
        publication_policy_version="neutral-check-v0",
        application_revision="a" * 40,
        runtime_revision="doug-api-00042",
        attempt_kind="risk",
    )


def _pack(
    *,
    run_id: str = "review-job:41:claim:1:risk",
    raw: bytes = RAW,
    captured_at: datetime = NOW,
    instrument: WholeInstrumentManifestV0 | None = None,
) -> ExamplePackV0:
    selected = instrument or _instrument()
    return ExamplePackV0.build(
        run_id=run_id,
        attempt_kind="risk",
        captured_at=captured_at,
        scope=PackScopeV0(
            installation_id=150424894,
            github_repository_id=987,
            repository_full_name="drewjst/doug",
            pull_number=84,
            admitted_base_sha="b" * 40,
            admitted_head_sha="c" * 40,
        ),
        request=ContentRefV0.from_bytes(REQUEST, media_type="application/json"),
        evidence=ContentRefV0.from_bytes(EVIDENCE, media_type="text/plain; charset=utf-8"),
        model_call_made=True,
        raw_output=ContentRefV0.from_bytes(raw, media_type="text/plain; charset=utf-8"),
        parsed_output={"risk_score": 0, "rationale": "", "findings": []},
        coverage=CoverageV0(
            diff_chars=len(EVIDENCE),
            sent_chars=len(EVIDENCE),
            files_sent=1,
            files_unseen=(),
            changed_files=1,
        ),
        usage=UsageV0(input_tokens=100, output_tokens=10),
        latency_ms=12,
        capture_status="captured",
        failure=None,
        fallback_state="none",
        instrument_manifest=selected,
        instrument_id=selected.instrument_id(),
        findings=(),
    )


def _manifest(**changes: object) -> CohortManifestV0:
    values: dict[str, object] = {
        "cohort_id": "doug-dogfood-2026-08",
        "capture_started_at": NOW,
        "capture_until": NOW + timedelta(days=7),
        "installation_ids": (150424894,),
        "github_repository_ids": (987,),
        "attempt_kinds": ("risk",),
        "finding_cap": 3,
        "raw_retention_days": 90,
        "application_revision": "a" * 40,
    }
    values.update(changes)
    return CohortManifestV0(**values)


def _write_pack(repository: HostedExamplePackRepository, pack: ExamplePackV0) -> None:
    repository.put_blob(REQUEST, media_type="application/json")
    repository.put_blob(EVIDENCE, media_type="text/plain; charset=utf-8")
    retry_raw = b'{"findings":[],"retry":true}'
    repository.put_blob(
        RAW
        if pack.raw_output and pack.raw_output.sha256 == hashlib.sha256(RAW).hexdigest()
        else retry_raw,
        media_type="text/plain; charset=utf-8",
    )
    repository.put_pack(pack)


def test_manifest_rejects_an_ambiguous_or_mutable_cohort_contract():
    with pytest.raises(ValueError):
        _manifest(installation_ids=(200, 100))
    with pytest.raises(ValueError):
        _manifest(github_repository_ids=(987, 987))
    with pytest.raises(ValueError):
        _manifest(attempt_kinds=("risk", "intent"))
    with pytest.raises(ValueError):
        _manifest(application_revision="dirty")
    with pytest.raises(ValueError):
        _manifest(capture_until=NOW)


def test_evaluation_identity_hashes_only_the_six_admitted_identity_fields():
    pack = _pack()
    identity = EvaluationIdentityV0.from_pack(pack)
    literal = {
        "admitted_base_sha": "b" * 40,
        "admitted_head_sha": "c" * 40,
        "github_repository_id": 987,
        "installation_id": 150424894,
        "instrument_id": pack.instrument_id,
        "pull_number": 84,
    }
    expected = hashlib.sha256(
        json.dumps(literal, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert identity.eligibility_hash() == expected


def test_first_persisted_pack_wins_membership_without_hiding_retry_pack():
    store = MemoryObjectStore()
    repository = HostedExamplePackRepository(store, "doug-dogfood-2026-08")
    manifest = _manifest()
    first = _pack()
    retry_raw = b'{"findings":[],"retry":true}'
    retry = _pack(
        run_id="review-job:41:claim:2:risk",
        raw=retry_raw,
        captured_at=NOW + timedelta(seconds=5),
    )
    repository.ensure_manifest(manifest)
    _write_pack(repository, first)
    _write_pack(repository, retry)

    first_claim = repository.put_membership(first, review_job_id=41)
    retry_claim = repository.put_membership(retry, review_job_id=41)
    validated = repository.validate()

    assert first_claim.member is True
    assert retry_claim.member is False
    assert retry_claim.membership.pack_hash == first.pack_hash
    assert {pack.pack_hash for pack in validated.packs} == {first.pack_hash, retry.pack_hash}
    assert validated.memberships[0].pack_hash == first.pack_hash


def test_validation_fails_the_whole_cohort_when_a_referenced_blob_is_missing():
    store = MemoryObjectStore()
    repository = HostedExamplePackRepository(store, "doug-dogfood-2026-08")
    pack = _pack()
    repository.ensure_manifest(_manifest())
    _write_pack(repository, pack)
    repository.put_membership(pack, review_job_id=41)
    del store.objects[
        f"cohorts/doug-dogfood-2026-08/blobs/sha256/{pack.evidence.sha256}"
    ]

    with pytest.raises(ExamplePackError, match="missing referenced blob"):
        repository.validate()
