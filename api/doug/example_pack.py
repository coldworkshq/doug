"""Immutable Example Pack v0 records and deterministic local storage.

This module owns evidence serialization only. It deliberately imports no
reader, worker, SDK, database, or deployment code, so storing an example
cannot become a second production-verdict path by accident.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExamplePackError(ValueError):
    """An Example Pack object or store failed its integrity contract."""


class SecretFieldError(ExamplePackError):
    """Structured capture data contains a credential-bearing field name."""


class ContentCollisionError(ExamplePackError):
    """A content address already exists with different bytes."""


_SECRET_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "authorization",
        "cookie",
        "cookies",
        "headers",
        "installation_token",
        "private_key",
        "client",
        "sdk_client",
        "sdk_client_state",
    }
)


def _normalise_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def reject_secret_fields(value: object, *, path: str = "$") -> None:
    """Reject credential-shaped *structure* without scanning evidence text.

    Exact source bytes may legitimately contain words such as
    ``authorization``. Scanning arbitrary strings would corrupt the captured
    evidence and pretend to prove secret absence. The safe enforceable
    boundary is the typed structure Doug itself controls.
    """

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        for key, nested in value.items():
            normalised = _normalise_key(key)
            if normalised in _SECRET_FIELDS:
                raise SecretFieldError(f"secret-bearing field {normalised!r} at {path}")
            reject_secret_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            reject_secret_fields(nested, path=f"{path}[{index}]")


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        rendered = value.isoformat()
        return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered
    if isinstance(value, dict):
        return {str(key): _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(nested) for nested in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    """The one canonical JSON encoding used by requests, hashes, and files."""

    serializable = _jsonable(value)
    reject_secret_fields(serializable)
    return json.dumps(
        serializable,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NameVersionV0(FrozenModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ContentRefV0(FrozenModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    media_type: str = Field(min_length=1)

    @classmethod
    def from_bytes(cls, data: bytes, *, media_type: str) -> Self:
        return cls(sha256=sha256_hex(data), size=len(data), media_type=media_type)


class PackScopeV0(FrozenModel):
    installation_id: int
    github_repository_id: int
    repository_full_name: str = Field(min_length=1)
    pull_number: int = Field(gt=0)
    admitted_base_sha: str = Field(min_length=1, max_length=64)
    admitted_head_sha: str = Field(min_length=1, max_length=64)


class CaptureScopeV0(FrozenModel):
    """Task-local worker facts needed to build packs and instruments."""

    run_id_prefix: str = Field(min_length=1)
    review_job_id: int | None = Field(default=None, gt=0)
    scope: PackScopeV0
    read_order: str = Field(min_length=1)
    input_policy_version: str = Field(min_length=1)
    coverage_policy_version: str = Field(min_length=1)
    verifier_versions: tuple[NameVersionV0, ...]
    tool_versions: tuple[NameVersionV0, ...]
    failure_policy_version: str = "reader-fallback-v0"
    publication_policy_version: str = "neutral-check-v0"
    application_revision: str | None = None
    runtime_revision: str | None = None


class CoverageV0(FrozenModel):
    diff_chars: int = Field(ge=0)
    sent_chars: int = Field(ge=0)
    files_sent: int = Field(ge=0)
    files_unseen: tuple[str, ...]
    file_cut: str | None = None
    changed_files: int | None = Field(default=None, ge=0)
    files_dropped: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.sent_chars >= self.diff_chars and not self.files_dropped


class UsageV0(FrozenModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class FailureV0(FrozenModel):
    phase: Literal["preflight", "transport", "stop_reason", "parse"]
    error_type: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=500)


class WholeInstrumentManifestV0(FrozenModel):
    schema_version: Literal["whole-instrument-v0"] = "whole-instrument-v0"
    provider: str = Field(min_length=1)
    pinned_model_id: str = Field(min_length=1)
    max_output_tokens: int = Field(gt=0)
    effort: str = Field(min_length=1)
    inference_parameters: tuple[NameVersionV0, ...]
    # ADR-0027 C3. The mechanical tier's identity — `verify_finding` and
    # `attribute_findings` — as `<pass>.<parameter>` entries. Without it two
    # reads that ran different mechanical models hash to the same
    # instrument_id, while ADR-0015 makes attribution's validated output part
    # of convergence identity and example_pack_eval.py partitions on that hash.
    # Required rather than defaulted: a default would let a manifest built by
    # an older call site silently claim a tier it never described.
    mechanical_parameters: tuple[NameVersionV0, ...]
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diff_budget: int = Field(gt=0)
    read_order: str = Field(min_length=1)
    input_policy_version: str = Field(min_length=1)
    coverage_policy_version: str = Field(min_length=1)
    verifier_versions: tuple[NameVersionV0, ...]
    tool_versions: tuple[NameVersionV0, ...]
    failure_policy_version: str = Field(min_length=1)
    publication_policy_version: str = Field(min_length=1)
    application_revision: str | None
    runtime_revision: str | None
    attempt_kind: Literal["risk", "intent"]

    def instrument_id(self) -> str:
        return sha256_hex(canonical_json_bytes(self.model_dump(mode="json")))


class CapturedFindingV0(FrozenModel):
    finding_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordinal: int = Field(ge=0)
    finding: dict[str, Any]

    @classmethod
    def build(
        cls,
        *,
        raw_output_sha256: str,
        attempt_kind: Literal["risk", "intent"],
        ordinal: int,
        finding: dict[str, Any],
    ) -> Self:
        identity = {
            "raw_output_sha256": raw_output_sha256,
            "attempt_kind": attempt_kind,
            "ordinal": ordinal,
            "finding": finding,
        }
        return cls(
            finding_id=sha256_hex(canonical_json_bytes(identity)),
            ordinal=ordinal,
            finding=finding,
        )


def parsed_finding_values(
    parsed_output: dict[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Return the exact ordered finding objects represented by parsed output."""

    if parsed_output is None:
        return ()
    values: list[dict[str, Any]] = []
    for field in ("findings", "deviation_findings"):
        findings = parsed_output.get(field, [])
        if not isinstance(findings, list):
            raise ValueError(f"parsed output {field} must be a list")
        for finding in findings:
            if not isinstance(finding, dict):
                raise ValueError(f"parsed output {field} entries must be objects")
            values.append(finding)
    return tuple(values)


class ExamplePackV0(FrozenModel):
    schema_version: Literal["example-pack-v0"] = "example-pack-v0"
    pack_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    attempt_kind: Literal["risk", "intent"]
    captured_at: datetime
    scope: PackScopeV0
    request: ContentRefV0 | None
    evidence: ContentRefV0
    model_call_made: bool
    raw_output: ContentRefV0 | None
    parsed_output: dict[str, Any] | None
    coverage: CoverageV0
    usage: UsageV0
    latency_ms: int = Field(ge=0)
    capture_status: Literal["captured", "partial", "failed"]
    failure: FailureV0 | None
    fallback_state: Literal["none", "spend_capped", "deterministic_expected", "intent_unavailable"]
    instrument_manifest: WholeInstrumentManifestV0
    instrument_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: tuple[CapturedFindingV0, ...]

    @classmethod
    def build(cls, **values: object) -> Self:
        payload = {"schema_version": "example-pack-v0", **values}
        digest = sha256_hex(canonical_json_bytes(payload))
        return cls.model_validate({**payload, "pack_hash": digest})

    def payload_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"pack_hash"}))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        expected = sha256_hex(self.payload_bytes())
        if self.pack_hash != expected:
            raise ValueError(f"pack_hash mismatch: expected {expected}")
        if self.instrument_id != self.instrument_manifest.instrument_id():
            raise ValueError("instrument_id does not match instrument_manifest")
        if self.instrument_manifest.attempt_kind != self.attempt_kind:
            raise ValueError("attempt_kind does not match instrument manifest")
        if self.model_call_made and self.request is None:
            raise ValueError("request reference is required when model_call_made is true")
        if self.capture_status == "failed" and self.failure is None:
            raise ValueError("failed capture requires failure detail")
        if self.capture_status != "failed" and self.failure is not None:
            raise ValueError("successful capture cannot carry failure detail")
        if self.capture_status in ("captured", "partial") and self.parsed_output is None:
            raise ValueError("successful capture requires parsed output")
        if self.capture_status == "captured" and not self.coverage.complete:
            raise ValueError("incomplete coverage must be partial")
        if self.capture_status == "partial" and self.coverage.complete:
            raise ValueError("partial capture requires incomplete coverage")
        if self.findings and self.raw_output is None:
            raise ValueError("finding identities require raw output")
        parsed_findings = parsed_finding_values(self.parsed_output)
        if len(parsed_findings) != len(self.findings):
            raise ValueError("findings do not match parsed output finding count")
        for ordinal, (captured, parsed) in enumerate(
            zip(self.findings, parsed_findings, strict=True)
        ):
            if captured.finding != parsed:
                raise ValueError(f"finding ordinal {ordinal} does not match parsed output")
            if captured.ordinal != ordinal:
                raise ValueError(
                    f"finding ordinal {captured.ordinal} is not contiguous at {ordinal}"
                )
            expected = CapturedFindingV0.build(
                raw_output_sha256=self.raw_output.sha256,
                attempt_kind=self.attempt_kind,
                ordinal=ordinal,
                finding=parsed,
            )
            if captured.finding_id != expected.finding_id:
                raise ValueError(
                    f"finding_id mismatch at ordinal {ordinal}: expected {expected.finding_id}"
                )
        return self


class EvidenceReceiptV0(FrozenModel):
    kind: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    detail: str = Field(min_length=1, max_length=1000)


class VerifierReceiptV0(FrozenModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    result: str = Field(min_length=1)
    detail: str = Field(min_length=1, max_length=2000)


class ExampleAdjudicationV0(FrozenModel):
    schema_version: Literal["example-adjudication-v0"] = "example-adjudication-v0"
    adjudication_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    pack_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    finding_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: Literal[
        "disproved",
        "verified_actionable",
        "verified_accepted_nonactionable",
        "unknown",
    ]
    evidence: tuple[EvidenceReceiptV0, ...]
    verifier_receipts: tuple[VerifierReceiptV0, ...]
    adjudicator: str = Field(min_length=1)
    adjudicated_at: datetime
    supersedes: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, **values: object) -> Self:
        payload = {"schema_version": "example-adjudication-v0", **values}
        digest = sha256_hex(canonical_json_bytes(payload))
        return cls.model_validate({**payload, "adjudication_id": digest})

    def payload_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"adjudication_id"}))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def _validate_hash(self) -> Self:
        expected = sha256_hex(self.payload_bytes())
        if self.adjudication_id != expected:
            raise ValueError(f"adjudication_id mismatch: expected {expected}")
        if self.supersedes == self.adjudication_id:
            raise ValueError("adjudication cannot supersede itself")
        return self


class StoreValidationV0(FrozenModel):
    blobs: int
    packs: int
    adjudications: int


class ExamplePackStore(Protocol):
    def put_blob(self, data: bytes, *, media_type: str) -> ContentRefV0: ...

    def put_pack(self, pack: ExamplePackV0) -> Path | str: ...

    def put_adjudication(self, adjudication: ExampleAdjudicationV0) -> Path | str: ...

    def validate(self) -> StoreValidationV0: ...


class FileExamplePackStore:
    """Deterministic content-addressed storage for tests and local dogfood."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _target(self, group: str, name: str) -> Path:
        return self.root / group / "sha256" / name

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _put_bytes(self, target: Path, data: bytes) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() == data:
                return target
            raise ContentCollisionError(f"content address collision at {target}")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".tmp-example-pack-", dir=target.parent, delete=False
            ) as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            try:
                os.link(temporary_path, target)
                self._fsync_directory(target.parent)
            except FileExistsError:
                if target.read_bytes() != data:
                    raise ContentCollisionError(f"content address collision at {target}") from None
            return target
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def put_blob(self, data: bytes, *, media_type: str) -> ContentRefV0:
        ref = ContentRefV0.from_bytes(data, media_type=media_type)
        self._put_bytes(self._target("blobs", ref.sha256), data)
        return ref

    def put_pack(self, pack: ExamplePackV0) -> Path:
        # model_validate rechecks self-hash even when a model was constructed
        # through a non-validating Pydantic API.
        checked = ExamplePackV0.model_validate(pack.model_dump(mode="json"))
        return self._put_bytes(
            self._target("packs", f"{checked.pack_hash}.json"),
            checked.canonical_bytes(),
        )

    def put_adjudication(self, adjudication: ExampleAdjudicationV0) -> Path:
        checked = ExampleAdjudicationV0.model_validate(adjudication.model_dump(mode="json"))
        return self._put_bytes(
            self._target("adjudications", f"{checked.adjudication_id}.json"),
            checked.canonical_bytes(),
        )

    @staticmethod
    def _files(path: Path) -> list[Path]:
        return sorted(p for p in path.glob("*") if p.is_file() and not p.name.startswith(".tmp"))

    def _validate_ref(self, ref: ContentRefV0) -> None:
        path = self._target("blobs", ref.sha256)
        if not path.is_file():
            raise FileNotFoundError(f"missing referenced blob {ref.sha256}")
        data = path.read_bytes()
        if sha256_hex(data) != ref.sha256 or len(data) != ref.size:
            raise ExamplePackError(f"blob integrity mismatch for {ref.sha256}")

    def validate(self) -> StoreValidationV0:
        blob_paths = self._files(self.root / "blobs" / "sha256")
        for path in blob_paths:
            if sha256_hex(path.read_bytes()) != path.name:
                raise ExamplePackError(f"blob filename hash mismatch at {path}")

        packs: dict[str, ExamplePackV0] = {}
        pack_paths = self._files(self.root / "packs" / "sha256")
        for path in pack_paths:
            data = path.read_bytes()
            raw = json.loads(data)
            if canonical_json_bytes(raw) != data:
                raise ExamplePackError(f"non-canonical pack bytes at {path}")
            pack = ExamplePackV0.model_validate(raw)
            if path.name != f"{pack.pack_hash}.json":
                raise ExamplePackError(f"pack filename hash mismatch at {path}")
            for ref in (pack.request, pack.evidence, pack.raw_output):
                if ref is not None:
                    self._validate_ref(ref)
            packs[pack.pack_hash] = pack

        adjudication_paths = self._files(self.root / "adjudications" / "sha256")
        for path in adjudication_paths:
            data = path.read_bytes()
            raw = json.loads(data)
            if canonical_json_bytes(raw) != data:
                raise ExamplePackError(f"non-canonical adjudication bytes at {path}")
            adjudication = ExampleAdjudicationV0.model_validate(raw)
            if path.name != f"{adjudication.adjudication_id}.json":
                raise ExamplePackError(f"adjudication filename hash mismatch at {path}")
            pack = packs.get(adjudication.pack_hash)
            if pack is None:
                raise ExamplePackError(
                    f"adjudication {adjudication.adjudication_id} references missing pack"
                )
            if adjudication.run_id != pack.run_id:
                raise ExamplePackError(
                    f"adjudication {adjudication.adjudication_id} run_id mismatch"
                )
            if adjudication.finding_id not in {f.finding_id for f in pack.findings}:
                raise ExamplePackError(
                    f"adjudication {adjudication.adjudication_id} references missing finding"
                )

        return StoreValidationV0(
            blobs=len(blob_paths),
            packs=len(pack_paths),
            adjudications=len(adjudication_paths),
        )


def main(argv: list[str] | None = None) -> int:
    """Validate one explicitly named local store; never mutate or repair it."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2 or arguments[0] != "validate":
        print(
            "usage: python -m doug.example_pack validate <absolute-root>",
            file=sys.stderr,
        )
        return 2
    root = Path(arguments[1])
    if not root.is_absolute():
        print("doug: example-pack root must be absolute", file=sys.stderr)
        return 2
    try:
        result = FileExamplePackStore(root).validate()
    except Exception as exc:  # noqa: BLE001 - CLI converts integrity errors to status
        detail = f"{type(exc).__name__}: {exc}"
        print(f"doug: example-pack validation failed: {detail}"[:499], file=sys.stderr)
        return 1
    print(f"blobs={result.blobs} packs={result.packs} adjudications={result.adjudications}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
