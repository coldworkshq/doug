"""Evidence-complete cohort reads joined to the durable review-job ledger."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal, Self

from pydantic import Field

from . import store
from .example_pack import (
    ExampleAdjudicationV0,
    ExamplePackError,
    ExamplePackV0,
    FrozenModel,
    WholeInstrumentManifestV0,
)
from .example_pack_eval import (
    ScorecardV0,
    null_control_scorecard,
    resolve_adjudications,
    score_packs_by_instrument,
    spam_control_scorecard,
)
from .example_pack_hosted import (
    CohortManifestV0,
    CohortMembershipV0,
    CohortTooLarge,
    HostedExamplePackRepository,
    HostedObjectStore,
    ValidatedCohortV0,
)


class UnknownCohortError(LookupError):
    """The requested cohort is not in the configured hosted set."""


class UnknownPackError(LookupError):
    """The requested pack is not present in the validated cohort."""


class CompletedJobIdentityV0(FrozenModel):
    installation_id: int = Field(gt=0)
    github_repository_id: int = Field(gt=0)
    repository_full_name: str = Field(min_length=1)
    pull_number: int = Field(gt=0)
    admitted_base_sha: str = Field(min_length=1, max_length=64)
    admitted_head_sha: str = Field(min_length=1, max_length=64)

    @classmethod
    def from_job(cls, job: dict[str, object]) -> Self:
        return cls.model_validate(
            {
                name: job[name]
                for name in (
                    "installation_id",
                    "github_repository_id",
                    "repository_full_name",
                    "pull_number",
                    "admitted_base_sha",
                    "admitted_head_sha",
                )
            }
        )

    @classmethod
    def from_membership(
        cls,
        membership: CohortMembershipV0,
        *,
        repository_full_name: str,
    ) -> Self:
        identity = membership.identity
        return cls(
            installation_id=identity.installation_id,
            github_repository_id=identity.github_repository_id,
            repository_full_name=repository_full_name,
            pull_number=identity.pull_number,
            admitted_base_sha=identity.admitted_base_sha,
            admitted_head_sha=identity.admitted_head_sha,
        )

    def match_key(self) -> tuple[object, ...]:
        return (
            self.installation_id,
            self.github_repository_id,
            self.pull_number,
            self.admitted_base_sha,
            self.admitted_head_sha,
        )


class CaptureCompletenessV0(FrozenModel):
    completed_jobs: int = Field(ge=0)
    members: int = Field(ge=0)
    missing: tuple[CompletedJobIdentityV0, ...]
    extra: tuple[CompletedJobIdentityV0, ...]
    boundary: str = "terminal-start-or-membership-linked-v0"


class CohortAvailabilityV0(FrozenModel):
    status: Literal["complete", "incomplete", "empty", "invalid", "too_large"]
    reason: str | None = None


class AttemptSummaryV0(FrozenModel):
    pack_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    member: bool
    review_job_id: int | None = Field(default=None, gt=0)
    instrument_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_full_name: str = Field(min_length=1)
    pull_number: int = Field(gt=0)
    admitted_base_sha: str = Field(min_length=1)
    admitted_head_sha: str = Field(min_length=1)
    captured_at: datetime
    capture_status: Literal["captured", "partial", "failed"]
    findings: int = Field(ge=0)


class InstrumentResultV0(FrozenModel):
    instrument_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: WholeInstrumentManifestV0
    scorecard: ScorecardV0
    null_control: ScorecardV0
    spam_control: ScorecardV0


class CohortDetailV0(FrozenModel):
    manifest: CohortManifestV0
    availability: CohortAvailabilityV0
    completeness: CaptureCompletenessV0
    adjudicated_findings: int = Field(ge=0)
    total_findings: int = Field(ge=0)
    members: tuple[AttemptSummaryV0, ...]
    non_member_attempts: tuple[AttemptSummaryV0, ...]
    instruments: tuple[InstrumentResultV0, ...]


class CohortSummaryV0(FrozenModel):
    cohort_id: str = Field(min_length=1)
    manifest: CohortManifestV0 | None
    availability: CohortAvailabilityV0
    completeness: CaptureCompletenessV0 | None


class CohortResultsV0(FrozenModel):
    manifest: CohortManifestV0
    availability: CohortAvailabilityV0
    completeness: CaptureCompletenessV0
    instruments: tuple[InstrumentResultV0, ...]
    members: tuple[AttemptSummaryV0, ...]


class PackDetailV0(FrozenModel):
    pack: ExamplePackV0
    request: dict[str, object] | None
    evidence_text: str
    raw_output_text: str | None
    effective_adjudications: tuple[ExampleAdjudicationV0, ...]


CompletedJobs = Callable[..., Sequence[dict[str, object]]]


class ExamplePackService:
    def __init__(
        self,
        objects: HostedObjectStore,
        *,
        cohort_ids: tuple[str, ...],
        completed_jobs: CompletedJobs = store.completed_example_pack_jobs,
    ):
        self._objects = objects
        self._cohort_ids = tuple(sorted(set(cohort_ids)))
        self._completed_jobs = completed_jobs

    def _repository(self, cohort_id: str) -> HostedExamplePackRepository:
        if cohort_id not in self._cohort_ids:
            raise UnknownCohortError("unknown cohort")
        return HostedExamplePackRepository(self._objects, cohort_id)

    @staticmethod
    def _summary(
        pack: ExamplePackV0,
        *,
        member: bool,
        review_job_id: int | None = None,
    ) -> AttemptSummaryV0:
        return AttemptSummaryV0(
            pack_hash=pack.pack_hash,
            run_id=pack.run_id,
            member=member,
            review_job_id=review_job_id,
            instrument_id=pack.instrument_id,
            repository_full_name=pack.scope.repository_full_name,
            pull_number=pack.scope.pull_number,
            admitted_base_sha=pack.scope.admitted_base_sha,
            admitted_head_sha=pack.scope.admitted_head_sha,
            captured_at=pack.captured_at,
            capture_status=pack.capture_status,
            findings=len(pack.findings),
        )

    def _jobs(self, cohort: ValidatedCohortV0) -> tuple[dict[str, object], ...]:
        manifest = cohort.manifest
        rows = self._completed_jobs(
            installation_ids=manifest.installation_ids,
            github_repository_ids=manifest.github_repository_ids,
            capture_started_at=manifest.capture_started_at,
            capture_until=manifest.capture_until,
            membership_job_ids=tuple(
                sorted({membership.review_job_id for membership in cohort.memberships})
            ),
        )
        return tuple(rows)

    def cohort_detail(self, cohort_id: str) -> CohortDetailV0:
        cohort = self._repository(cohort_id).validate()
        jobs = self._jobs(cohort)
        packs_by_hash = {pack.pack_hash: pack for pack in cohort.packs}
        job_identities = tuple(CompletedJobIdentityV0.from_job(job) for job in jobs)
        jobs_by_key = {identity.match_key(): identity for identity in job_identities}
        member_identities = tuple(
            CompletedJobIdentityV0.from_membership(
                membership,
                repository_full_name=packs_by_hash[
                    membership.pack_hash
                ].scope.repository_full_name,
            )
            for membership in cohort.memberships
        )
        members_by_key = {
            identity.match_key(): identity for identity in member_identities
        }
        missing = tuple(
            sorted(
                (
                    identity
                    for key, identity in jobs_by_key.items()
                    if key not in members_by_key
                ),
                key=lambda identity: identity.match_key(),
            )
        )
        extra = tuple(
            sorted(
                (
                    identity
                    for identity in member_identities
                    if identity.match_key() not in jobs_by_key
                ),
                key=lambda identity: identity.match_key(),
            )
        )
        completeness = CaptureCompletenessV0(
            completed_jobs=len(job_identities),
            members=len(cohort.memberships),
            missing=missing,
            extra=extra,
        )

        membership_by_hash = {
            membership.pack_hash: membership for membership in cohort.memberships
        }
        matched_memberships = tuple(
            membership
            for membership in cohort.memberships
            if CompletedJobIdentityV0.from_membership(
                membership,
                repository_full_name=packs_by_hash[
                    membership.pack_hash
                ].scope.repository_full_name,
            ).match_key()
            in jobs_by_key
        )
        matched_packs = tuple(
            packs_by_hash[membership.pack_hash] for membership in matched_memberships
        )
        member_summaries = tuple(
            self._summary(
                packs_by_hash[membership.pack_hash],
                member=True,
                review_job_id=membership.review_job_id,
            )
            for membership in cohort.memberships
        )
        nonmembers = tuple(
            self._summary(pack, member=False)
            for pack in cohort.packs
            if pack.pack_hash not in membership_by_hash
        )

        instruments: tuple[InstrumentResultV0, ...] = ()
        if not missing:
            matched_hashes = {pack.pack_hash for pack in matched_packs}
            overlays = tuple(
                overlay
                for overlay in cohort.adjudications
                if overlay.pack_hash in matched_hashes
            )
            partitions = score_packs_by_instrument(
                matched_packs,
                overlays,
                finding_cap=cohort.manifest.finding_cap,
            )
            packs_by_instrument = {
                pack.instrument_id: pack for pack in matched_packs
            }
            instruments = tuple(
                InstrumentResultV0(
                    instrument_id=partition.instrument_id,
                    manifest=packs_by_instrument[
                        partition.instrument_id
                    ].instrument_manifest,
                    scorecard=partition.scorecard,
                    null_control=null_control_scorecard(
                        tuple(
                            pack
                            for pack in matched_packs
                            if pack.instrument_id == partition.instrument_id
                        ),
                        finding_cap=cohort.manifest.finding_cap,
                    ),
                    spam_control=spam_control_scorecard(
                        tuple(
                            pack
                            for pack in matched_packs
                            if pack.instrument_id == partition.instrument_id
                        ),
                        finding_cap=cohort.manifest.finding_cap,
                    ),
                )
                for partition in partitions
            )

        matched_hashes = {pack.pack_hash for pack in matched_packs}
        matched_overlays = tuple(
            overlay
            for overlay in cohort.adjudications
            if overlay.pack_hash in matched_hashes
        )
        effective = resolve_adjudications(matched_overlays)
        total_findings = sum(len(pack.findings) for pack in matched_packs)
        if missing:
            availability = CohortAvailabilityV0(
                status="incomplete",
                reason="completed jobs are missing member packs",
            )
        elif not jobs and not cohort.packs and not cohort.memberships:
            availability = CohortAvailabilityV0(
                status="empty",
                reason="no captured attempts or completed eligible jobs",
            )
        else:
            availability = CohortAvailabilityV0(status="complete")
        return CohortDetailV0(
            manifest=cohort.manifest,
            availability=availability,
            completeness=completeness,
            adjudicated_findings=len(effective),
            total_findings=total_findings,
            members=member_summaries,
            non_member_attempts=nonmembers,
            instruments=instruments,
        )

    def list_cohorts(self) -> tuple[CohortSummaryV0, ...]:
        summaries: list[CohortSummaryV0] = []
        for cohort_id in self._cohort_ids:
            try:
                detail = self.cohort_detail(cohort_id)
            except CohortTooLarge:
                summaries.append(
                    CohortSummaryV0(
                        cohort_id=cohort_id,
                        manifest=None,
                        availability=CohortAvailabilityV0(
                            status="too_large",
                            reason="cohort exceeds the bounded pack limit",
                        ),
                        completeness=None,
                    )
                )
            except ExamplePackError:
                summaries.append(
                    CohortSummaryV0(
                        cohort_id=cohort_id,
                        manifest=None,
                        availability=CohortAvailabilityV0(
                            status="invalid",
                            reason="cohort evidence is invalid or unavailable",
                        ),
                        completeness=None,
                    )
                )
            else:
                summaries.append(
                    CohortSummaryV0(
                        cohort_id=cohort_id,
                        manifest=detail.manifest,
                        availability=detail.availability,
                        completeness=detail.completeness,
                    )
                )
        return tuple(summaries)

    def results(self, cohort_id: str) -> CohortResultsV0:
        detail = self.cohort_detail(cohort_id)
        return CohortResultsV0(
            manifest=detail.manifest,
            availability=detail.availability,
            completeness=detail.completeness,
            instruments=detail.instruments,
            members=detail.members,
        )

    def pack_detail(self, cohort_id: str, pack_hash: str) -> PackDetailV0:
        repository = self._repository(cohort_id)
        cohort = repository.validate()
        pack = next((item for item in cohort.packs if item.pack_hash == pack_hash), None)
        if pack is None:
            raise UnknownPackError("unknown pack")

        request: dict[str, object] | None = None
        if pack.request is not None:
            try:
                parsed_request = json.loads(repository.read_blob(pack.request))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExamplePackError("captured request is not valid JSON") from exc
            if not isinstance(parsed_request, dict):
                raise ExamplePackError("captured request is not a JSON object")
            request = parsed_request

        effective = resolve_adjudications(cohort.adjudications)
        finding_ids = {finding.finding_id for finding in pack.findings}
        adjudications = tuple(
            sorted(
                (
                    adjudication
                    for (target_pack, target_run, target_finding), adjudication in effective.items()
                    if target_pack == pack.pack_hash
                    and target_run == pack.run_id
                    and target_finding in finding_ids
                ),
                key=lambda adjudication: adjudication.finding_id,
            )
        )
        return PackDetailV0(
            pack=pack,
            request=request,
            evidence_text=repository.read_blob(pack.evidence).decode("utf-8"),
            raw_output_text=(
                repository.read_blob(pack.raw_output).decode("utf-8")
                if pack.raw_output is not None
                else None
            ),
            effective_adjudications=adjudications,
        )
