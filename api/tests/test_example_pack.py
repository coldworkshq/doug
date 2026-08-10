import json
import math
from datetime import UTC, datetime

import pytest

from doug.example_pack import (
    CapturedFindingV0,
    CaptureScopeV0,
    ContentCollisionError,
    ContentRefV0,
    CoverageV0,
    ExampleAdjudicationV0,
    ExamplePackV0,
    FailureV0,
    FileExamplePackStore,
    NameVersionV0,
    PackScopeV0,
    SecretFieldError,
    UsageV0,
    WholeInstrumentManifestV0,
    canonical_json_bytes,
    main,
)

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _manifest(**changes) -> WholeInstrumentManifestV0:
    values = {
        "provider": "anthropic",
        "pinned_model_id": "claude-opus-5",
        "max_output_tokens": 6000,
        "effort": "medium",
        "inference_parameters": (NameVersionV0(name="temperature", version="provider-default"),),
        "system_prompt_sha256": "1" * 64,
        "output_schema_sha256": "2" * 64,
        "diff_budget": 100_000,
        "read_order": "tiered",
        "input_policy_version": "reader-input-v0",
        "coverage_policy_version": "reader-coverage-v0",
        "verifier_versions": (NameVersionV0(name="settle", version="v0"),),
        "tool_versions": (NameVersionV0(name="anthropic-sdk", version="0.120.2"),),
        "failure_policy_version": "reader-fallback-v0",
        "publication_policy_version": "neutral-check-v0",
        "application_revision": None,
        "runtime_revision": None,
        "attempt_kind": "risk",
    }
    values.update(changes)
    return WholeInstrumentManifestV0(**values)


def _scope() -> PackScopeV0:
    return PackScopeV0(
        installation_id=150424894,
        github_repository_id=987,
        repository_full_name="drewjst/doug",
        pull_number=78,
        admitted_base_sha="0" * 40,
        admitted_head_sha="a" * 40,
    )


def _pack(
    *,
    request: bytes = b'{"model":"a"}',
    evidence: bytes = b"+x",
    raw_output: bytes = b'{"findings":[]}',
    status: str = "captured",
    findings: tuple[CapturedFindingV0, ...] = (),
    manifest: WholeInstrumentManifestV0 | None = None,
) -> ExamplePackV0:
    manifest = manifest or _manifest()
    parsed_findings = [finding.finding for finding in findings]
    return ExamplePackV0.build(
        run_id="review-job:1:claim:1:risk",
        attempt_kind="risk",
        captured_at=NOW,
        scope=_scope(),
        request=ContentRefV0.from_bytes(request, media_type="application/json"),
        evidence=ContentRefV0.from_bytes(evidence, media_type="text/x-diff"),
        model_call_made=True,
        raw_output=ContentRefV0.from_bytes(raw_output, media_type="application/json"),
        parsed_output={
            "risk_score": 0,
            "rationale": "",
            "findings": parsed_findings,
        },
        coverage=CoverageV0(
            diff_chars=len(evidence),
            sent_chars=len(evidence),
            files_sent=1,
            files_unseen=(),
            changed_files=1,
            files_dropped=(),
        ),
        usage=UsageV0(input_tokens=100, output_tokens=10),
        latency_ms=4,
        capture_status=status,
        failure=None,
        fallback_state="none",
        instrument_manifest=manifest,
        instrument_id=manifest.instrument_id(),
        findings=findings,
    )


def test_canonical_json_is_stable_and_rejects_non_finite_numbers():
    assert canonical_json_bytes({"z": "é", "a": [2, 1]}) == (b'{"a":[2,1],"z":"\xc3\xa9"}')
    with pytest.raises(ValueError):
        canonical_json_bytes({"latency": math.nan})


def test_request_or_evidence_byte_changes_pack_hash():
    first = _pack(request=b'{"model":"a"}', evidence=b"+x")
    request_changed = _pack(request=b'{"model":"b"}', evidence=b"+x")
    evidence_changed = _pack(request=b'{"model":"a"}', evidence=b"+y")
    assert len({first.pack_hash, request_changed.pack_hash, evidence_changed.pack_hash}) == 3


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "other"},
        {"pinned_model_id": "claude-opus-5-1"},
        {"max_output_tokens": 5999},
        {"effort": "high"},
        {"inference_parameters": (NameVersionV0(name="temperature", version="0"),)},
        {"system_prompt_sha256": "3" * 64},
        {"output_schema_sha256": "4" * 64},
        {"diff_budget": 99_999},
        {"read_order": "linear"},
        {"input_policy_version": "reader-input-v1"},
        {"coverage_policy_version": "reader-coverage-v1"},
        {"verifier_versions": (NameVersionV0(name="settle", version="v1"),)},
        {"tool_versions": (NameVersionV0(name="anthropic-sdk", version="0.121.0"),)},
        {"failure_policy_version": "reader-fallback-v1"},
        {"publication_policy_version": "neutral-check-v1"},
        {"application_revision": "git:abc"},
        {"runtime_revision": "doug-api-00042"},
        {"attempt_kind": "intent"},
    ],
)
def test_every_whole_instrument_component_changes_instrument_id(change):
    assert _manifest(**change).instrument_id() != _manifest().instrument_id()


def test_finding_identity_is_deterministic_and_ordinal_distinguishes_duplicates():
    exact = {
        "category_slug": "race-condition",
        "description": "unguarded write",
        "file": "cache.py",
        "severity": "high",
    }
    first = CapturedFindingV0.build(
        raw_output_sha256="a" * 64,
        attempt_kind="risk",
        ordinal=0,
        finding=exact,
    )
    repeated = CapturedFindingV0.build(
        raw_output_sha256="a" * 64,
        attempt_kind="risk",
        ordinal=0,
        finding=exact,
    )
    duplicate_position = CapturedFindingV0.build(
        raw_output_sha256="a" * 64,
        attempt_kind="risk",
        ordinal=1,
        finding=exact,
    )
    assert first == repeated
    assert first.finding_id != duplicate_position.finding_id


def test_pack_recomputes_finding_ids_ordinals_and_parsed_finding_values():
    raw = b'{"findings":[]}'
    exact = {
        "category_slug": "race-condition",
        "description": "unguarded write",
        "file": "cache.py",
        "severity": "high",
    }
    finding = CapturedFindingV0.build(
        raw_output_sha256=ContentRefV0.from_bytes(raw, media_type="application/json").sha256,
        attempt_kind="risk",
        ordinal=0,
        finding=exact,
    )

    with pytest.raises(ValueError, match="finding_id"):
        _pack(
            raw_output=raw,
            findings=(finding.model_copy(update={"finding_id": "f" * 64}),),
        )
    with pytest.raises(ValueError, match="ordinal"):
        _pack(
            raw_output=raw,
            findings=(finding.model_copy(update={"ordinal": 4}),),
        )

    valid = _pack(raw_output=raw, findings=(finding,))
    changed = valid.model_dump(mode="json", exclude={"pack_hash"})
    changed["parsed_output"]["findings"][0]["description"] = "different"
    with pytest.raises(ValueError, match="parsed output"):
        ExamplePackV0.build(**changed)


def test_model_call_requires_the_exact_request_reference():
    manifest = _manifest()
    with pytest.raises(ValueError, match="request"):
        ExamplePackV0.build(
            run_id="review-job:1:claim:1:risk",
            attempt_kind="risk",
            captured_at=NOW,
            scope=_scope(),
            request=None,
            evidence=ContentRefV0.from_bytes(b"+x", media_type="text/x-diff"),
            model_call_made=True,
            raw_output=None,
            parsed_output=None,
            coverage=CoverageV0(
                diff_chars=2,
                sent_chars=2,
                files_sent=1,
                files_unseen=(),
            ),
            usage=UsageV0(),
            latency_ms=0,
            capture_status="failed",
            failure=FailureV0(phase="transport", error_type="TimeoutError", detail="timeout"),
            fallback_state="deterministic_expected",
            instrument_manifest=manifest,
            instrument_id=manifest.instrument_id(),
            findings=(),
        )


def test_capture_context_keeps_pack_scope_separate_from_instrument_policy():
    context = CaptureScopeV0(
        run_id_prefix="review-job:1:claim:1",
        scope=_scope(),
        read_order="tiered",
        input_policy_version="reader-input-v0",
        coverage_policy_version="reader-coverage-v0",
        verifier_versions=(NameVersionV0(name="settle", version="v0"),),
        tool_versions=(NameVersionV0(name="anthropic-sdk", version="0.120.2"),),
    )
    assert context.scope == _scope()
    assert "read_order" not in context.scope.model_dump()


def test_secret_shaped_structural_fields_are_rejected():
    with pytest.raises(SecretFieldError, match="authorization"):
        canonical_json_bytes({"authorization": "Bearer secret"})
    with pytest.raises(SecretFieldError, match="sdk_client"):
        canonical_json_bytes({"nested": {"sdk_client": object()}})


def test_content_addressed_writes_are_idempotent_and_collision_loud(tmp_path):
    store = FileExamplePackStore(tmp_path)
    ref = store.put_blob(b"exact", media_type="application/octet-stream")
    target = tmp_path / "blobs" / "sha256" / ref.sha256
    before = target.stat().st_mtime_ns
    assert store.put_blob(b"exact", media_type="application/octet-stream") == ref
    assert target.stat().st_mtime_ns == before

    target.write_bytes(b"different")
    with pytest.raises(ContentCollisionError):
        store.put_blob(b"exact", media_type="application/octet-stream")


def test_store_round_trips_and_validates_pack_and_adjudication(tmp_path):
    store = FileExamplePackStore(tmp_path)
    request = b'{"model":"a"}'
    evidence = b"+x"
    raw = b'{"findings":[]}'
    for data, media_type in (
        (request, "application/json"),
        (evidence, "text/x-diff"),
        (raw, "application/json"),
    ):
        store.put_blob(data, media_type=media_type)
    pack = _pack(request=request, evidence=evidence, raw_output=raw)
    pack_path = store.put_pack(pack)
    assert pack_path.name == f"{pack.pack_hash}.json"

    finding = CapturedFindingV0.build(
        raw_output_sha256=pack.raw_output.sha256,
        attempt_kind="risk",
        ordinal=0,
        finding={
            "category_slug": "race-condition",
            "description": "unguarded write",
            "file": "cache.py",
            "severity": "high",
        },
    )
    pack_with_finding = _pack(
        request=request,
        evidence=evidence,
        raw_output=raw,
        findings=(finding,),
    )
    store.put_pack(pack_with_finding)
    adjudication = ExampleAdjudicationV0.build(
        pack_hash=pack_with_finding.pack_hash,
        run_id=pack_with_finding.run_id,
        finding_id=finding.finding_id,
        disposition="unknown",
        evidence=(),
        verifier_receipts=(),
        adjudicator="human:andrew",
        adjudicated_at=NOW,
        supersedes=None,
    )
    adjudication_path = store.put_adjudication(adjudication)
    assert adjudication_path.name == f"{adjudication.adjudication_id}.json"
    assert store.validate().model_dump() == {"blobs": 3, "packs": 2, "adjudications": 1}

    assert json.loads(pack_path.read_text())["pack_hash"] == pack.pack_hash


def test_store_validation_fails_on_a_missing_or_mismatched_reference(tmp_path):
    store = FileExamplePackStore(tmp_path)
    pack = _pack()
    store.put_pack(pack)
    with pytest.raises(FileNotFoundError, match=pack.request.sha256):
        store.validate()


def test_pack_hash_and_adjudication_hash_are_verified_on_load():
    pack = _pack()
    bad = pack.model_dump(mode="json")
    bad["pack_hash"] = "0" * 64
    with pytest.raises(ValueError, match="pack_hash"):
        ExamplePackV0.model_validate(bad)

    finding = CapturedFindingV0.build(
        raw_output_sha256="a" * 64,
        attempt_kind="risk",
        ordinal=0,
        finding={"category_slug": "x", "description": "x", "file": "x", "severity": "low"},
    )
    adjudication = ExampleAdjudicationV0.build(
        pack_hash=pack.pack_hash,
        run_id=pack.run_id,
        finding_id=finding.finding_id,
        disposition="unknown",
        evidence=(),
        verifier_receipts=(),
        adjudicator="human:andrew",
        adjudicated_at=NOW,
        supersedes=None,
    )
    bad_adjudication = adjudication.model_dump(mode="json")
    bad_adjudication["adjudication_id"] = "0" * 64
    with pytest.raises(ValueError, match="adjudication_id"):
        ExampleAdjudicationV0.model_validate(bad_adjudication)


def _valid_cli_store(root):
    store = FileExamplePackStore(root)
    request = b'{"model":"a"}'
    evidence = b"+x"
    raw = b'{"findings":[]}'
    for data, media_type in (
        (request, "application/json"),
        (evidence, "text/x-diff"),
        (raw, "application/json"),
    ):
        store.put_blob(data, media_type=media_type)
    finding = CapturedFindingV0.build(
        raw_output_sha256=ContentRefV0.from_bytes(raw, media_type="application/json").sha256,
        attempt_kind="risk",
        ordinal=0,
        finding={
            "category_slug": "race-condition",
            "description": "unguarded write",
            "file": "cache.py",
            "severity": "high",
        },
    )
    pack = _pack(
        request=request,
        evidence=evidence,
        raw_output=raw,
        findings=(finding,),
    )
    store.put_pack(pack)
    adjudication = ExampleAdjudicationV0.build(
        pack_hash=pack.pack_hash,
        run_id=pack.run_id,
        finding_id=finding.finding_id,
        disposition="unknown",
        evidence=(),
        verifier_receipts=(),
        adjudicator="test",
        adjudicated_at=NOW,
        supersedes=None,
    )
    store.put_adjudication(adjudication)
    return store, pack


def test_validate_cli_reports_deterministic_counts(tmp_path, capsys):
    _valid_cli_store(tmp_path)

    assert main(["validate", str(tmp_path)]) == 0

    output = capsys.readouterr()
    assert output.out == "blobs=3 packs=1 adjudications=1\n"
    assert output.err == ""


def test_validate_cli_fails_loudly_on_corrupt_referenced_blob(tmp_path, capsys):
    _store, pack = _valid_cli_store(tmp_path)
    request = tmp_path / "blobs/sha256" / pack.request.sha256
    request.write_bytes(b"corrupt")

    assert main(["validate", str(tmp_path)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "example-pack validation failed" in output.err
    assert len(output.err) <= 500


def test_validate_cli_refuses_relative_root(capsys):
    assert main(["validate", "relative/path"]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "must be absolute" in output.err
