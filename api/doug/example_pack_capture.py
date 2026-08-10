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


class CaptureConfigurationError(ValueError):
    """Opt-in capture settings are present but unsafe or incomplete."""


class CaptureResultV0(FrozenModel):
    enabled: bool
    captured: bool
    pack_hash: str | None = None
    path: str | None = None
    error_type: str | None = None


_CAPTURE_SCOPE: ContextVar[CaptureScopeV0 | None] = ContextVar(
    "doug_example_pack_capture_scope", default=None
)
_CAPTURE_SUPPRESSED: ContextVar[str | None] = ContextVar(
    "doug_example_pack_capture_suppressed", default=None
)


def capture_requested(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether both explicit opt-in settings are present."""

    values = os.environ if environ is None else environ
    return (
        values.get("DOUG_EXAMPLE_PACK_CAPTURE") == "1"
        and bool(values.get("DOUG_EXAMPLE_PACK_DIR"))
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
    scope_factory: Callable[[], CaptureScopeV0 | None], *, run_id_prefix: str
) -> Iterator[None]:
    """Build optional worker identity lazily without exposing capture failures."""

    if not capture_requested():
        yield
        return
    try:
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
    with capture_scope(scope):
        yield


def prepare_request_bytes(value: object) -> tuple[bytes | None, str | None]:
    """Canonicalize only capture-eligible requests and contain any failure."""

    if (
        not capture_requested()
        or current_scope() is None
        or capture_suppressed()
    ):
        return None, None
    try:
        return canonical_json_bytes(value), None
    except Exception as exc:  # noqa: BLE001 - capture cannot break a read
        return None, type(exc).__name__[:120]


def configured_store(
    environ: Mapping[str, str] | None = None,
) -> FileExamplePackStore | None:
    """Return the explicitly enabled local sink without creating it."""

    values = os.environ if environ is None else environ
    if not capture_requested(values):
        return None
    configured = values.get("DOUG_EXAMPLE_PACK_DIR")
    assert configured is not None  # capture_requested requires a non-empty value
    root = Path(configured)
    if not root.is_absolute():
        raise CaptureConfigurationError("DOUG_EXAMPLE_PACK_DIR must be absolute")
    return FileExamplePackStore(root)


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
        return CaptureResultV0(
            enabled=True,
            captured=True,
            pack_hash=pack.pack_hash,
            path=str(path),
        )
    except Exception as exc:  # noqa: BLE001 - capture cannot break a review
        _diagnostic(f"doug: example-pack capture failed run_id={run_id} error={type(exc).__name__}")
        return CaptureResultV0(enabled=True, captured=False, error_type=type(exc).__name__)
