from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from doug.example_pack import (
    CaptureScopeV0,
    CoverageV0,
    ExamplePackV0,
    FileExamplePackStore,
    NameVersionV0,
    PackScopeV0,
    UsageV0,
    canonical_json_bytes,
)
from doug.example_pack_capture import (
    CaptureConfigurationError,
    capture_scope,
    configured_store,
    current_scope,
    record_attempt,
)

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _scope(pull_number: int) -> CaptureScopeV0:
    return CaptureScopeV0(
        run_id_prefix=f"review-job:{pull_number}:claim:1",
        scope=PackScopeV0(
            installation_id=10 + pull_number,
            github_repository_id=20,
            repository_full_name="owner/repo",
            pull_number=pull_number,
            admitted_base_sha="base",
            admitted_head_sha="head",
        ),
        read_order="tiered",
        input_policy_version="reader-input-v0",
        coverage_policy_version="reader-coverage-v0",
        verifier_versions=(NameVersionV0(name="settle", version="v0"),),
        tool_versions=(NameVersionV0(name="anthropic-sdk", version="0.70.0"),),
    )


def test_capture_configuration_is_disabled_unless_both_settings_exist(tmp_path):
    sentinel = tmp_path / "must-not-exist"

    assert configured_store({}) is None
    assert configured_store({"DOUG_EXAMPLE_PACK_CAPTURE": "1"}) is None
    assert configured_store({"DOUG_EXAMPLE_PACK_DIR": str(sentinel)}) is None
    assert not sentinel.exists()


def test_capture_configuration_rejects_relative_directory():
    with pytest.raises(CaptureConfigurationError, match="must be absolute"):
        configured_store(
            {
                "DOUG_EXAMPLE_PACK_CAPTURE": "1",
                "DOUG_EXAMPLE_PACK_DIR": "relative/path",
            }
        )


def test_capture_configuration_returns_file_store_for_explicit_absolute_root(tmp_path):
    store = configured_store(
        {
            "DOUG_EXAMPLE_PACK_CAPTURE": "1",
            "DOUG_EXAMPLE_PACK_DIR": str(tmp_path),
        }
    )

    assert isinstance(store, FileExamplePackStore)
    assert store.root == tmp_path


def test_capture_scope_is_reset_and_isolated_between_threads():
    barrier = Barrier(2)

    def observe(scope):
        assert current_scope() is None
        with capture_scope(scope):
            barrier.wait()
            observed = current_scope()
            barrier.wait()
        assert current_scope() is None
        return observed

    first = _scope(1)
    second = _scope(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        observed = list(pool.map(observe, (first, second)))

    assert observed == [first, second]


def test_record_attempt_writes_exact_content_and_stable_findings(tmp_path):
    store = FileExamplePackStore(tmp_path)
    request = canonical_json_bytes({"model": "m", "messages": []})
    evidence = "diff café".encode()
    raw = canonical_json_bytes(
        {
            "risk_score": 70,
            "rationale": "risk",
            "findings": [
                {
                    "category_slug": "race",
                    "description": "unsafe",
                    "file": "x.py",
                    "severity": "high",
                }
            ],
        }
    )
    parsed = {
        "risk_score": 70,
        "rationale": "risk",
        "findings": [
            {
                "category_slug": "race",
                "description": "unsafe",
                "file": "x.py",
                "severity": "high",
            }
        ],
    }

    with capture_scope(_scope(7)):
        first = record_attempt(
            attempt_kind="risk",
            request_bytes=request,
            evidence_bytes=evidence,
            raw_output_bytes=raw,
            parsed_output=parsed,
            coverage=CoverageV0(
                diff_chars=len(evidence),
                sent_chars=len(evidence),
                files_sent=1,
                files_unseen=(),
            ),
            usage=UsageV0(input_tokens=100, output_tokens=20),
            latency_ms=12,
            model_call_made=True,
            failure=None,
            fallback_state="none",
            provider="anthropic",
            model="m",
            max_output_tokens=100,
            effort="medium",
            inference_parameters=(NameVersionV0(name="temperature", version="default"),),
            system_prompt_bytes=b"system",
            output_schema_bytes=b"schema",
            diff_budget=1000,
            store=store,
            captured_at=NOW,
        )
        second = record_attempt(
            attempt_kind="risk",
            request_bytes=request,
            evidence_bytes=evidence,
            raw_output_bytes=raw,
            parsed_output=parsed,
            coverage=CoverageV0(
                diff_chars=len(evidence),
                sent_chars=len(evidence),
                files_sent=1,
                files_unseen=(),
            ),
            usage=UsageV0(input_tokens=100, output_tokens=20),
            latency_ms=12,
            model_call_made=True,
            failure=None,
            fallback_state="none",
            provider="anthropic",
            model="m",
            max_output_tokens=100,
            effort="medium",
            inference_parameters=(NameVersionV0(name="temperature", version="default"),),
            system_prompt_bytes=b"system",
            output_schema_bytes=b"schema",
            diff_budget=1000,
            store=store,
            captured_at=NOW,
        )

    assert first.captured and second.captured
    assert first.pack_hash == second.pack_hash
    assert store.validate().packs == 1
    pack_path = next((tmp_path / "packs/sha256").iterdir())
    pack = ExamplePackV0.model_validate_json(pack_path.read_bytes())
    assert (tmp_path / "blobs/sha256" / pack.request.sha256).read_bytes() == request
    assert (tmp_path / "blobs/sha256" / pack.evidence.sha256).read_bytes() == evidence
    assert pack.run_id == "review-job:7:claim:1:risk"
    assert len(pack.findings) == 1


def test_enabled_capture_without_worker_scope_is_visible_and_writes_nothing(tmp_path, capsys):
    result = record_attempt(
        attempt_kind="risk",
        request_bytes=b"{}",
        evidence_bytes=b"diff",
        raw_output_bytes=None,
        parsed_output=None,
        coverage=CoverageV0(diff_chars=4, sent_chars=4, files_sent=0, files_unseen=()),
        usage=UsageV0(input_tokens=None, output_tokens=None),
        latency_ms=0,
        model_call_made=True,
        failure=None,
        fallback_state="none",
        provider="anthropic",
        model="m",
        max_output_tokens=1,
        effort="medium",
        inference_parameters=(),
        system_prompt_bytes=b"system",
        output_schema_bytes=b"schema",
        diff_budget=1,
        store=FileExamplePackStore(tmp_path),
        captured_at=NOW,
    )

    assert not result.captured
    assert "capture unavailable: no admitted worker scope" in capsys.readouterr().err
    assert not (tmp_path / "packs").exists()
