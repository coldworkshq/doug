"""Immutable hosted cohort contracts over a minimal object-store boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from .example_pack import (
    ContentCollisionError,
    ContentRefV0,
    ExampleAdjudicationV0,
    ExamplePackError,
    ExamplePackV0,
    FrozenModel,
    canonical_json_bytes,
    sha256_hex,
)
from .example_pack_eval import EvaluationContractError, resolve_adjudications


class CohortTooLarge(ExamplePackError):
    """A cohort exceeds the bounded all-or-nothing read contract."""


class HostedObjectStore(Protocol):
    def create(self, key: str, data: bytes, *, content_type: str) -> None: ...

    def read(self, key: str) -> bytes: ...

    def list(self, prefix: str) -> tuple[str, ...]: ...


class CohortManifestV0(FrozenModel):
    schema_version: Literal["example-pack-cohort-v0"] = "example-pack-cohort-v0"
    cohort_id: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    capture_started_at: datetime
    capture_until: datetime
    installation_ids: tuple[int, ...]
    github_repository_ids: tuple[int, ...]
    attempt_kinds: tuple[Literal["risk"], ...] = ("risk",)
    finding_cap: Literal[3] = 3
    raw_retention_days: Literal[90] = 90
    application_revision: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        for name, values in (
            ("installation_ids", self.installation_ids),
            ("github_repository_ids", self.github_repository_ids),
        ):
            if not values or any(isinstance(value, bool) or value <= 0 for value in values):
                raise ValueError(f"{name} must contain positive numeric IDs")
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{name} must be sorted and unique")
        if self.attempt_kinds != ("risk",):
            raise ValueError("hosted cohort attempt_kinds must be exactly risk")
        for name, value in (
            ("capture_started_at", self.capture_started_at),
            ("capture_until", self.capture_until),
        ):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError(f"{name} must be UTC")
        if self.capture_started_at >= self.capture_until:
            raise ValueError("capture_started_at must precede capture_until")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))


class EvaluationIdentityV0(FrozenModel):
    instrument_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    installation_id: int = Field(gt=0)
    github_repository_id: int = Field(gt=0)
    pull_number: int = Field(gt=0)
    admitted_base_sha: str = Field(min_length=1, max_length=64)
    admitted_head_sha: str = Field(min_length=1, max_length=64)

    @classmethod
    def from_pack(cls, pack: ExamplePackV0) -> Self:
        return cls(
            instrument_id=pack.instrument_id,
            installation_id=pack.scope.installation_id,
            github_repository_id=pack.scope.github_repository_id,
            pull_number=pack.scope.pull_number,
            admitted_base_sha=pack.scope.admitted_base_sha,
            admitted_head_sha=pack.scope.admitted_head_sha,
        )

    def eligibility_hash(self) -> str:
        return sha256_hex(canonical_json_bytes(self.model_dump(mode="json")))


class CohortMembershipV0(FrozenModel):
    schema_version: Literal["example-pack-membership-v0"] = "example-pack-membership-v0"
    cohort_id: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    eligibility_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: EvaluationIdentityV0
    review_job_id: int = Field(gt=0)
    pack_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    captured_at: datetime

    @classmethod
    def build(
        cls, *, cohort_id: str, pack: ExamplePackV0, review_job_id: int
    ) -> Self:
        identity = EvaluationIdentityV0.from_pack(pack)
        return cls(
            cohort_id=cohort_id,
            eligibility_hash=identity.eligibility_hash(),
            identity=identity,
            review_job_id=review_job_id,
            pack_hash=pack.pack_hash,
            run_id=pack.run_id,
            captured_at=pack.captured_at,
        )

    @model_validator(mode="after")
    def _validate_hash(self) -> Self:
        expected = self.identity.eligibility_hash()
        if self.eligibility_hash != expected:
            raise ValueError(f"eligibility_hash mismatch: expected {expected}")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))


class MembershipClaimV0(FrozenModel):
    member: bool
    membership: CohortMembershipV0


class ValidatedCohortV0(FrozenModel):
    manifest: CohortManifestV0
    blobs: int = Field(ge=0)
    packs: tuple[ExamplePackV0, ...]
    memberships: tuple[CohortMembershipV0, ...]
    adjudications: tuple[ExampleAdjudicationV0, ...]


class HostedExamplePackRepository:
    """Canonical cohort reads/writes independent of a particular cloud SDK."""

    PACK_LIMIT = 500

    def __init__(self, objects: HostedObjectStore, cohort_id: str):
        # Reuse the manifest validator for the slug without inventing a
        # second, subtly different path-safety contract.
        if not isinstance(cohort_id, str) or not cohort_id:
            raise ValueError("cohort_id is required")
        self.objects = objects
        self.cohort_id = cohort_id
        self.prefix = f"cohorts/{cohort_id}"

    def _key(self, group: str, name: str) -> str:
        return f"{self.prefix}/{group}/sha256/{name}"

    def ensure_manifest(self, manifest: CohortManifestV0) -> None:
        if manifest.cohort_id != self.cohort_id:
            raise ExamplePackError("manifest cohort_id does not match repository")
        self.objects.create(
            f"{self.prefix}/cohort.json",
            manifest.canonical_bytes(),
            content_type="application/json",
        )

    def put_blob(self, data: bytes, *, media_type: str) -> ContentRefV0:
        ref = ContentRefV0.from_bytes(data, media_type=media_type)
        self.objects.create(self._key("blobs", ref.sha256), data, content_type=media_type)
        return ref

    def put_pack(self, pack: ExamplePackV0) -> str:
        checked = ExamplePackV0.model_validate(pack.model_dump(mode="json"))
        key = self._key("packs", f"{checked.pack_hash}.json")
        self.objects.create(key, checked.canonical_bytes(), content_type="application/json")
        return key

    def read_blob(self, ref: ContentRefV0) -> bytes:
        """Read one validated content address without exposing its location."""

        self._validate_ref(ref)
        return self.objects.read(self._key("blobs", ref.sha256))

    def put_membership(
        self, pack: ExamplePackV0, *, review_job_id: int
    ) -> MembershipClaimV0:
        desired = CohortMembershipV0.build(
            cohort_id=self.cohort_id, pack=pack, review_job_id=review_job_id
        )
        key = self._key("members", f"{desired.eligibility_hash}.json")
        try:
            self.objects.create(key, desired.canonical_bytes(), content_type="application/json")
        except ContentCollisionError:
            existing = self._load_model(key, CohortMembershipV0)
            if existing.cohort_id != self.cohort_id or existing.identity != desired.identity:
                raise ExamplePackError("membership content-address collision") from None
            return MembershipClaimV0(member=False, membership=existing)
        return MembershipClaimV0(member=True, membership=desired)

    def put_adjudication(self, adjudication: ExampleAdjudicationV0) -> str:
        checked = ExampleAdjudicationV0.model_validate(adjudication.model_dump(mode="json"))
        key = self._key("adjudications", f"{checked.adjudication_id}.json")
        self.objects.create(key, checked.canonical_bytes(), content_type="application/json")
        return key

    def _load_model(self, key: str, model_type):
        try:
            data = self.objects.read(key)
        except FileNotFoundError:
            raise
        try:
            raw = json.loads(data)
            if canonical_json_bytes(raw) != data:
                raise ExamplePackError(f"non-canonical JSON object {key}")
            return model_type.model_validate(raw)
        except ExamplePackError:
            raise
        except Exception as exc:
            raise ExamplePackError(f"invalid JSON object {key}") from exc

    def _listed(self, group: str) -> tuple[str, ...]:
        prefix = f"{self.prefix}/{group}/sha256/"
        keys = self.objects.list(prefix)
        if any(not key.startswith(prefix) for key in keys):
            raise ExamplePackError("object list escaped cohort prefix")
        return tuple(sorted(keys))

    def _validate_ref(self, ref: ContentRefV0) -> None:
        key = self._key("blobs", ref.sha256)
        try:
            data = self.objects.read(key)
        except FileNotFoundError:
            raise ExamplePackError(f"missing referenced blob {ref.sha256}") from None
        if sha256_hex(data) != ref.sha256 or len(data) != ref.size:
            raise ExamplePackError(f"blob integrity mismatch for {ref.sha256}")

    def validate(self) -> ValidatedCohortV0:
        manifest_key = f"{self.prefix}/cohort.json"
        try:
            manifest = self._load_model(manifest_key, CohortManifestV0)
        except FileNotFoundError:
            raise ExamplePackError("missing cohort manifest") from None
        if manifest.cohort_id != self.cohort_id:
            raise ExamplePackError("manifest cohort_id does not match repository")

        pack_keys = self._listed("packs")
        if len(pack_keys) > self.PACK_LIMIT:
            raise CohortTooLarge(f"cohort exceeds {self.PACK_LIMIT} packs")
        packs: dict[str, ExamplePackV0] = {}
        for key in pack_keys:
            pack = self._load_model(key, ExamplePackV0)
            if key != self._key("packs", f"{pack.pack_hash}.json"):
                raise ExamplePackError("pack object name does not match hash")
            for ref in (pack.request, pack.evidence, pack.raw_output):
                if ref is not None:
                    self._validate_ref(ref)
            if pack.pack_hash in packs:
                raise ExamplePackError(f"duplicate pack {pack.pack_hash}")
            packs[pack.pack_hash] = pack

        memberships: list[CohortMembershipV0] = []
        seen_identities: set[str] = set()
        for key in self._listed("members"):
            membership = self._load_model(key, CohortMembershipV0)
            if key != self._key("members", f"{membership.eligibility_hash}.json"):
                raise ExamplePackError("membership object name does not match hash")
            if membership.cohort_id != self.cohort_id:
                raise ExamplePackError("membership references another cohort")
            if membership.eligibility_hash in seen_identities:
                raise ExamplePackError("duplicate membership identity")
            seen_identities.add(membership.eligibility_hash)
            pack = packs.get(membership.pack_hash)
            if pack is None:
                raise ExamplePackError("membership references missing pack")
            if membership.identity != EvaluationIdentityV0.from_pack(pack):
                raise ExamplePackError("membership identity does not match pack")
            if membership.run_id != pack.run_id or membership.captured_at != pack.captured_at:
                raise ExamplePackError("membership receipt does not match pack")
            memberships.append(membership)

        adjudications: list[ExampleAdjudicationV0] = []
        for key in self._listed("adjudications"):
            adjudication = self._load_model(key, ExampleAdjudicationV0)
            if key != self._key(
                "adjudications", f"{adjudication.adjudication_id}.json"
            ):
                raise ExamplePackError("adjudication object name does not match hash")
            pack = packs.get(adjudication.pack_hash)
            if pack is None:
                raise ExamplePackError("adjudication references missing pack")
            if adjudication.run_id != pack.run_id:
                raise ExamplePackError("adjudication run_id mismatch")
            if adjudication.finding_id not in {finding.finding_id for finding in pack.findings}:
                raise ExamplePackError("adjudication references missing finding")
            adjudications.append(adjudication)
        try:
            resolve_adjudications(adjudications)
        except EvaluationContractError as exc:
            raise ExamplePackError(str(exc)) from exc

        return ValidatedCohortV0(
            manifest=manifest,
            blobs=len(self._listed("blobs")),
            packs=tuple(
                sorted(
                    packs.values(), key=lambda pack: (pack.captured_at, pack.pack_hash)
                )
            ),
            memberships=tuple(
                sorted(memberships, key=lambda membership: membership.eligibility_hash)
            ),
            adjudications=tuple(
                sorted(adjudications, key=lambda item: item.adjudication_id)
            ),
        )
