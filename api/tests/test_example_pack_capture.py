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
    capture_scope_if_enabled,
    configured_hosted_capture,
    configured_store,
    current_scope,
    prepare_request_bytes,
    record_attempt,
)
from doug.example_pack_hosted import HostedExamplePackRepository

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _scope(pull_number: int, *, application_revision: str | None = None) -> CaptureScopeV0:
    return CaptureScopeV0(
        run_id_prefix=f"review-job:{pull_number}:claim:1",
        review_job_id=pull_number,
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
        application_revision=application_revision,
    )


class _MemoryObjects:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def create(self, key: str, data: bytes, *, content_type: str) -> None:
        existing = self.objects.get(key)
        if existing is None:
            self.objects[key] = (data, content_type)
            return
        if existing != (data, content_type):
            from doug.example_pack import ContentCollisionError

            raise ContentCollisionError("different bytes")

    def read(self, key: str) -> bytes:
        try:
            return self.objects[key][0]
        except KeyError:
            raise FileNotFoundError(key) from None

    def list(self, prefix: str) -> tuple[str, ...]:
        return tuple(sorted(key for key in self.objects if key.startswith(prefix)))


def _hosted_env(monkeypatch) -> None:
    values = {
        "DOUG_EXAMPLE_PACK_CAPTURE": "1",
        "DOUG_EXAMPLE_PACK_BUCKET": "private-evidence",
        "DOUG_EXAMPLE_PACK_COHORT": "doug-dogfood-2026-08",
        "DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT": "2026-08-10T17:00:00Z",
        "DOUG_EXAMPLE_PACK_CAPTURE_UNTIL": "2026-08-11T18:00:00Z",
        "DOUG_EXAMPLE_PACK_INSTALLATION_IDS": "27",
        "DOUG_EXAMPLE_PACK_REPOSITORY_IDS": "20",
        "DOUG_APPLICATION_REVISION": "a" * 40,
        "DOUG_EXAMPLE_PACK_ADJUDICATOR": "andrew",
    }
    monkeypatch.delenv("DOUG_EXAMPLE_PACK_DIR", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


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


def test_local_and_hosted_targets_are_rejected_as_ambiguous(tmp_path):
    with pytest.raises(CaptureConfigurationError, match="mutually exclusive"):
        configured_store(
            {
                "DOUG_EXAMPLE_PACK_CAPTURE": "1",
                "DOUG_EXAMPLE_PACK_DIR": str(tmp_path),
                "DOUG_EXAMPLE_PACK_BUCKET": "private-evidence",
            }
        )


def test_non_allowlisted_hosted_job_does_not_build_a_scope(monkeypatch):
    _hosted_env(monkeypatch)

    with capture_scope_if_enabled(
        lambda: pytest.fail("foreign tenant built a capture scope"),
        run_id_prefix="review-job:41:claim:1",
        installation_id=18,
        github_repository_id=20,
        now=NOW,
    ):
        assert current_scope() is None


def test_hosted_scope_without_numeric_worker_identity_yields_disabled(monkeypatch):
    _hosted_env(monkeypatch)

    with capture_scope_if_enabled(
        lambda: pytest.fail("identity-free caller built a capture scope"),
        run_id_prefix="unscoped",
        now=NOW,
    ):
        assert current_scope() is None


def test_dirty_application_revision_is_a_named_configuration_error(monkeypatch):
    _hosted_env(monkeypatch)
    monkeypatch.setenv("DOUG_APPLICATION_REVISION", "dirty")

    with pytest.raises(CaptureConfigurationError, match="DOUG_APPLICATION_REVISION"):
        configured_hosted_capture()


def test_hosted_intent_request_is_not_canonicalized(monkeypatch):
    _hosted_env(monkeypatch)
    with capture_scope(_scope(17, application_revision="a" * 40)):
        assert prepare_request_bytes({"kind": "intent"}, attempt_kind="intent") == (
            None,
            None,
        )
        assert prepare_request_bytes({"kind": "risk"}, attempt_kind="risk")[0] == (
            b'{"kind":"risk"}'
        )


def test_hosted_risk_capture_writes_manifest_pack_and_membership(monkeypatch):
    _hosted_env(monkeypatch)
    objects = _MemoryObjects()
    repository = HostedExamplePackRepository(objects, "doug-dogfood-2026-08")
    request = canonical_json_bytes({"model": "m", "messages": []})
    raw = canonical_json_bytes({"risk_score": 0, "rationale": "", "findings": []})

    with capture_scope(_scope(17, application_revision="a" * 40)):
        result = record_attempt(
            attempt_kind="risk",
            request_bytes=request,
            evidence_bytes=b"diff",
            raw_output_bytes=raw,
            parsed_output={"risk_score": 0, "rationale": "", "findings": []},
            coverage=CoverageV0(
                diff_chars=4,
                sent_chars=4,
                files_sent=1,
                files_unseen=(),
            ),
            usage=UsageV0(input_tokens=1, output_tokens=1),
            latency_ms=1,
            model_call_made=True,
            failure=None,
            fallback_state="none",
            provider="anthropic",
            model="m",
            max_output_tokens=100,
            effort="medium",
            inference_parameters=(),
            mechanical_parameters= (
                NameVersionV0(name="verify_finding.model", version="claude-sonnet-5"),
            ),
            system_prompt_bytes=b"system",
            output_schema_bytes=b"schema",
            diff_budget=1000,
            store=repository,
            captured_at=NOW,
        )

    assert result.captured
    assert result.member is True
    assert result.path is None
    validated = repository.validate()
    assert validated.manifest.installation_ids == (27,)
    assert validated.memberships[0].review_job_id == 17
    assert validated.memberships[0].pack_hash == result.pack_hash


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
            mechanical_parameters= (
                NameVersionV0(name="verify_finding.model", version="claude-sonnet-5"),
            ),
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
            mechanical_parameters= (
                NameVersionV0(name="verify_finding.model", version="claude-sonnet-5"),
            ),
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
        mechanical_parameters= (
            NameVersionV0(name="verify_finding.model", version="claude-sonnet-5"),
        ),
        system_prompt_bytes=b"system",
        output_schema_bytes=b"schema",
        diff_budget=1,
        store=FileExamplePackStore(tmp_path),
        captured_at=NOW,
    )

    assert not result.captured
    assert "capture unavailable: no admitted worker scope" in capsys.readouterr().err
    assert not (tmp_path / "packs").exists()
