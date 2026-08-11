"""Best-effort capture orchestration for admitted worker reader attempts."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from .example_pack import (
    CapturedFindingV0,
    CaptureScopeV0,
    CoverageV0,
    ExamplePackStore,
    ExamplePackV0,
    FailureV0,
    FileExamplePackStore,
    FrozenModel,
    NameVersionV0,
    UsageV0,
    WholeInstrumentManifestV0,
    canonical_json_bytes,
    parsed_finding_values,
    sha256_hex,
)
from .example_pack_gcs import GcsObjectStore, StorageBudget
from .example_pack_hosted import (
    CohortManifestV0,
    HostedExamplePackRepository,
)


class CaptureConfigurationError(ValueError):
    """Opt-in capture settings are present but unsafe or incomplete."""


class CaptureResultV0(FrozenModel):
    enabled: bool
    captured: bool
    pack_hash: str | None = None
    path: str | None = None
    member: bool | None = None
    error_type: str | None = None


class HostedCaptureConfigV0(FrozenModel):
    bucket: str = Field(min_length=1)
    manifest: CohortManifestV0
    adjudicator: str = Field(min_length=1)

    def eligible(
        self,
        *,
        installation_id: int,
        github_repository_id: int,
        now: datetime,
    ) -> bool:
        return (
            installation_id in self.manifest.installation_ids
            and github_repository_id in self.manifest.github_repository_ids
            and self.manifest.capture_started_at <= now < self.manifest.capture_until
        )


_CAPTURE_SCOPE: ContextVar[CaptureScopeV0 | None] = ContextVar(
    "doug_example_pack_capture_scope", default=None
)
_CAPTURE_SUPPRESSED: ContextVar[str | None] = ContextVar(
    "doug_example_pack_capture_suppressed", default=None
)
_HOSTED_CONFIG: ContextVar[HostedCaptureConfigV0 | None] = ContextVar(
    "doug_example_pack_hosted_config", default=None
)


def capture_requested(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether opt-in and one storage target are present."""

    values = os.environ if environ is None else environ
    return (
        values.get("DOUG_EXAMPLE_PACK_CAPTURE") == "1"
        and bool(
            values.get("DOUG_EXAMPLE_PACK_DIR")
            or values.get("DOUG_EXAMPLE_PACK_BUCKET")
        )
    )


def _utc_timestamp(value: str, *, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CaptureConfigurationError(f"{name} must be a UTC RFC3339 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise CaptureConfigurationError(f"{name} must be UTC")
    return parsed


def _numeric_ids(value: str, *, name: str) -> tuple[int, ...]:
    try:
        parts = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError:
        raise CaptureConfigurationError(f"{name} must contain numeric IDs") from None
    if not parts or any(isinstance(part, bool) or part <= 0 for part in parts):
        raise CaptureConfigurationError(f"{name} must contain positive numeric IDs")
    if len(parts) != len(set(parts)):
        raise CaptureConfigurationError(f"{name} must contain unique IDs")
    return tuple(sorted(parts))


def configured_hosted_capture(
    environ: Mapping[str, str] | None = None,
) -> HostedCaptureConfigV0 | None:
    values = os.environ if environ is None else environ
    if values.get("DOUG_EXAMPLE_PACK_CAPTURE") != "1":
        return None
    local = values.get("DOUG_EXAMPLE_PACK_DIR")
    bucket = values.get("DOUG_EXAMPLE_PACK_BUCKET")
    if local and bucket:
        raise CaptureConfigurationError(
            "DOUG_EXAMPLE_PACK_DIR and DOUG_EXAMPLE_PACK_BUCKET are mutually exclusive"
        )
    if not bucket:
        return None

    required = (
        "DOUG_EXAMPLE_PACK_COHORT",
        "DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT",
        "DOUG_EXAMPLE_PACK_CAPTURE_UNTIL",
        "DOUG_EXAMPLE_PACK_INSTALLATION_IDS",
        "DOUG_EXAMPLE_PACK_REPOSITORY_IDS",
        "DOUG_APPLICATION_REVISION",
        "DOUG_EXAMPLE_PACK_ADJUDICATOR",
    )
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise CaptureConfigurationError(f"missing hosted capture setting {missing[0]}")

    try:
        manifest = CohortManifestV0(
            cohort_id=values["DOUG_EXAMPLE_PACK_COHORT"],
            capture_started_at=_utc_timestamp(
                values["DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT"],
                name="DOUG_EXAMPLE_PACK_CAPTURE_STARTED_AT",
            ),
            capture_until=_utc_timestamp(
                values["DOUG_EXAMPLE_PACK_CAPTURE_UNTIL"],
                name="DOUG_EXAMPLE_PACK_CAPTURE_UNTIL",
            ),
            installation_ids=_numeric_ids(
                values["DOUG_EXAMPLE_PACK_INSTALLATION_IDS"],
                name="DOUG_EXAMPLE_PACK_INSTALLATION_IDS",
            ),
            github_repository_ids=_numeric_ids(
                values["DOUG_EXAMPLE_PACK_REPOSITORY_IDS"],
                name="DOUG_EXAMPLE_PACK_REPOSITORY_IDS",
            ),
            application_revision=values["DOUG_APPLICATION_REVISION"],
        )
    except ValidationError as exc:
        field = str(exc.errors()[0]["loc"][0])
        setting = {
            "cohort_id": "DOUG_EXAMPLE_PACK_COHORT",
            "application_revision": "DOUG_APPLICATION_REVISION",
        }.get(field, field)
        raise CaptureConfigurationError(
            f"invalid hosted capture setting {setting}"
        ) from None
    return HostedCaptureConfigV0(
        bucket=bucket,
        manifest=manifest,
        adjudicator=values["DOUG_EXAMPLE_PACK_ADJUDICATOR"],
    )


def capture_suppressed() -> bool:
    """Return whether this context already reported a scope-construction failure."""

    return _CAPTURE_SUPPRESSED.get() is not None


def current_scope() -> CaptureScopeV0 | None:
    return _CAPTURE_SCOPE.get()


@contextmanager
def capture_scope(scope: CaptureScopeV0) -> Iterator[None]:
    token = _CAPTURE_SCOPE.set(scope)
    try:
        yield
    finally:
        _CAPTURE_SCOPE.reset(token)


@contextmanager
def capture_scope_if_enabled(
    scope_factory: Callable[[], CaptureScopeV0 | None],
    *,
    run_id_prefix: str,
    installation_id: int | None = None,
    github_repository_id: int | None = None,
    now: datetime | None = None,
) -> Iterator[None]:
    """Build optional worker identity lazily without exposing capture failures."""

    if not capture_requested():
        yield
        return
    try:
        hosted = configured_hosted_capture()
        if hosted is not None:
            if installation_id is None or github_repository_id is None:
                yield
                return
            observed_at = now or datetime.now(UTC)
            if not hosted.eligible(
                installation_id=installation_id,
                github_repository_id=github_repository_id,
                now=observed_at,
            ):
                yield
                return
        scope = scope_factory()
    except Exception as exc:  # noqa: BLE001 - capture cannot break a job
        error_type = type(exc).__name__[:120]
        _diagnostic(
            f"doug: example-pack capture failed run_id={run_id_prefix} "
            f"error={error_type}"
        )
        token = _CAPTURE_SUPPRESSED.set(error_type)
        try:
            yield
        finally:
            _CAPTURE_SUPPRESSED.reset(token)
        return
    if scope is None:
        yield
        return
    scope_token = _CAPTURE_SCOPE.set(scope)
    hosted_token = _HOSTED_CONFIG.set(hosted)
    try:
        yield
    finally:
        _HOSTED_CONFIG.reset(hosted_token)
        _CAPTURE_SCOPE.reset(scope_token)


def prepare_request_bytes(
    value: object, *, attempt_kind: Literal["risk", "intent"] = "risk"
) -> tuple[bytes | None, str | None]:
    """Canonicalize only capture-eligible requests and contain any failure."""

    if (
        not capture_requested()
        or current_scope() is None
        or capture_suppressed()
    ):
        return None, None
    if attempt_kind == "intent" and (
        _HOSTED_CONFIG.get() is not None
        or bool(os.environ.get("DOUG_EXAMPLE_PACK_BUCKET"))
    ):
        return None, None
    try:
        return canonical_json_bytes(value), None
    except Exception as exc:  # noqa: BLE001 - capture cannot break a read
        return None, type(exc).__name__[:120]


def configured_store(
    environ: Mapping[str, str] | None = None,
) -> FileExamplePackStore | HostedExamplePackRepository | None:
    """Return the explicit local or hosted sink, constructing it only now."""

    values = os.environ if environ is None else environ
    if not capture_requested(values):
        return None
    hosted = configured_hosted_capture(values)
    configured = values.get("DOUG_EXAMPLE_PACK_DIR")
    if hosted is not None:
        objects = GcsObjectStore(hosted.bucket, budget=StorageBudget(seconds=5.0))
        return HostedExamplePackRepository(objects, hosted.manifest.cohort_id)
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            raise CaptureConfigurationError("DOUG_EXAMPLE_PACK_DIR must be absolute")
        return FileExamplePackStore(root)
    return None


def _diagnostic(message: str) -> None:
    print(message[:500], file=sys.stderr)


def record_attempt(
    *,
    attempt_kind: Literal["risk", "intent"],
    request_bytes: bytes | None,
    evidence_bytes: bytes,
    raw_output_bytes: bytes | None,
    parsed_output: dict[str, object] | None,
    coverage: CoverageV0,
    usage: UsageV0,
    latency_ms: int,
    model_call_made: bool,
    failure: FailureV0 | None,
    fallback_state: Literal["none", "spend_capped", "deterministic_expected", "intent_unavailable"],
    provider: str,
    model: str,
    max_output_tokens: int,
    effort: str,
    inference_parameters: tuple[NameVersionV0, ...],
    system_prompt_bytes: bytes,
    output_schema_bytes: bytes,
    diff_budget: int,
    store: ExamplePackStore | None = None,
    captured_at: datetime | None = None,
    request_error_type: str | None = None,
) -> CaptureResultV0:
    """Append one terminal attempt, never changing the reader's outcome."""

    suppressed_error = _CAPTURE_SUPPRESSED.get()
    if suppressed_error is not None:
        return CaptureResultV0(
            enabled=True, captured=False, error_type=suppressed_error
        )
    scope = current_scope()
    hosted = _HOSTED_CONFIG.get()
    if hosted is None and os.environ.get("DOUG_EXAMPLE_PACK_BUCKET"):
        try:
            hosted = configured_hosted_capture()
        except Exception as exc:  # noqa: BLE001 - capture cannot break a review
            return CaptureResultV0(
                enabled=True, captured=False, error_type=type(exc).__name__
            )
    if hosted is not None and attempt_kind != "risk":
        return CaptureResultV0(enabled=True, captured=False)
    try:
        sink = configured_store() if store is None else store
    except Exception as exc:  # noqa: BLE001 - capture cannot break a review
        run_id = f"{scope.run_id_prefix}:{attempt_kind}" if scope else "unscoped"
        _diagnostic(f"doug: example-pack capture failed run_id={run_id} error={type(exc).__name__}")
        return CaptureResultV0(enabled=True, captured=False, error_type=type(exc).__name__)
    if sink is None:
        return CaptureResultV0(enabled=False, captured=False)
    if scope is None:
        _diagnostic(
            f"doug: example-pack capture unavailable: no admitted worker scope kind={attempt_kind}"
        )
        return CaptureResultV0(enabled=True, captured=False, error_type="MissingCaptureScope")

    if hosted is not None:
        if scope.review_job_id is None:
            return CaptureResultV0(
                enabled=True, captured=False, error_type="MissingReviewJobId"
            )
        if scope.application_revision != hosted.manifest.application_revision:
            return CaptureResultV0(
                enabled=True, captured=False, error_type="ApplicationRevisionMismatch"
            )
        if (
            scope.scope.installation_id not in hosted.manifest.installation_ids
            or scope.scope.github_repository_id
            not in hosted.manifest.github_repository_ids
        ):
            return CaptureResultV0(
                enabled=True, captured=False, error_type="CaptureIdentityNotAllowed"
            )

    run_id = f"{scope.run_id_prefix}:{attempt_kind}"
    if request_error_type is not None:
        _diagnostic(
            f"doug: example-pack capture failed run_id={run_id} "
            f"error={request_error_type[:120]}"
        )
        return CaptureResultV0(
            enabled=True, captured=False, error_type=request_error_type[:120]
        )
    try:
        if hosted is not None:
            if not isinstance(sink, HostedExamplePackRepository):
                raise CaptureConfigurationError("hosted capture requires hosted repository")
            sink.ensure_manifest(hosted.manifest)
        request_ref = (
            sink.put_blob(request_bytes, media_type="application/json")
            if request_bytes is not None
            else None
        )
        evidence_ref = sink.put_blob(evidence_bytes, media_type="text/plain; charset=utf-8")
        raw_ref = (
            sink.put_blob(raw_output_bytes, media_type="text/plain; charset=utf-8")
            if raw_output_bytes is not None
            else None
        )
        finding_values = parsed_finding_values(parsed_output)
        findings = (
            tuple(
                CapturedFindingV0.build(
                    raw_output_sha256=raw_ref.sha256,
                    attempt_kind=attempt_kind,
                    ordinal=ordinal,
                    finding=finding,
                )
                for ordinal, finding in enumerate(finding_values)
            )
            if raw_ref is not None
            else ()
        )
        if finding_values and raw_ref is None:
            raise ValueError("parsed findings require raw output bytes")

        manifest = WholeInstrumentManifestV0(
            provider=provider,
            pinned_model_id=model,
            max_output_tokens=max_output_tokens,
            effort=effort,
            inference_parameters=inference_parameters,
            system_prompt_sha256=sha256_hex(system_prompt_bytes),
            output_schema_sha256=sha256_hex(output_schema_bytes),
            diff_budget=diff_budget,
            read_order=scope.read_order,
            input_policy_version=scope.input_policy_version,
            coverage_policy_version=scope.coverage_policy_version,
            verifier_versions=scope.verifier_versions,
            tool_versions=scope.tool_versions,
            failure_policy_version=scope.failure_policy_version,
            publication_policy_version=scope.publication_policy_version,
            application_revision=scope.application_revision,
            runtime_revision=scope.runtime_revision,
            attempt_kind=attempt_kind,
        )
        status: Literal["captured", "partial", "failed"]
        if failure is not None:
            status = "failed"
        elif coverage.complete:
            status = "captured"
        else:
            status = "partial"
        pack = ExamplePackV0.build(
            run_id=run_id,
            attempt_kind=attempt_kind,
            captured_at=captured_at or datetime.now(UTC),
            scope=scope.scope,
            request=request_ref,
            evidence=evidence_ref,
            model_call_made=model_call_made,
            raw_output=raw_ref,
            parsed_output=parsed_output,
            coverage=coverage,
            usage=usage,
            latency_ms=latency_ms,
            capture_status=status,
            failure=failure,
            fallback_state=fallback_state,
            instrument_manifest=manifest,
            instrument_id=manifest.instrument_id(),
            findings=findings,
        )
        path = sink.put_pack(pack)
        member: bool | None = None
        rendered_path: str | None = str(path)
        if hosted is not None:
            assert scope.review_job_id is not None
            member = sink.put_membership(
                pack, review_job_id=scope.review_job_id
            ).member
            rendered_path = None
        return CaptureResultV0(
            enabled=True,
            captured=True,
            pack_hash=pack.pack_hash,
            path=rendered_path,
            member=member,
        )
    except Exception as exc:  # noqa: BLE001 - capture cannot break a review
        _diagnostic(f"doug: example-pack capture failed run_id={run_id} error={type(exc).__name__}")
        return CaptureResultV0(enabled=True, captured=False, error_type=type(exc).__name__)
