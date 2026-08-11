"""Deterministic scorecards over immutable Example Pack evidence.

Evaluation is deliberately offline-only: it consumes frozen packs and
append-only adjudications, and has no dependency on the live review path.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from pydantic import Field

from .example_pack import ExampleAdjudicationV0, ExamplePackV0, FrozenModel


class EvaluationContractError(ValueError):
    """Input evidence cannot be scored without silently choosing semantics."""


class ScorecardV0(FrozenModel):
    schema_version: str = "example-pack-scorecard-v0"
    eligible_prs: int = Field(ge=0)
    yield_denominator: int = Field(ge=0)
    burden_denominator: int = Field(ge=0)
    validated_actionable: int = Field(ge=0)
    verified_accepted_nonactionable: int = Field(ge=0)
    unsupported: int = Field(ge=0)

    @property
    def validated_actionable_yield(self) -> float:
        if self.yield_denominator == 0:
            return 0.0
        return self.validated_actionable / self.yield_denominator

    @property
    def unsupported_finding_burden(self) -> float:
        if self.burden_denominator == 0:
            return 0.0
        return self.unsupported / self.burden_denominator


class InstrumentScorecardV0(FrozenModel):
    instrument_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    scorecard: ScorecardV0


class ControlGateV0(FrozenModel):
    schema_version: str = "example-pack-control-gate-v0"
    null: ScorecardV0
    spam: ScorecardV0
    required_yield: float = Field(ge=0)
    reference_burden: float = Field(ge=0)
    burden_margin: float = Field(ge=0)
    null_passes_yield: bool
    spam_passes_burden: bool


AdjudicationTargetV0 = tuple[str, str, str]


def _target(overlay: ExampleAdjudicationV0) -> AdjudicationTargetV0:
    return (overlay.pack_hash, overlay.run_id, overlay.finding_id)


def resolve_adjudications(
    overlays: Iterable[ExampleAdjudicationV0],
) -> dict[AdjudicationTargetV0, ExampleAdjudicationV0]:
    """Resolve one live append-only adjudication head per finding.

    Time never breaks a tie. Every correction must name exactly the record it
    supersedes, and an ambiguous graph fails instead of inventing a winner.
    """

    records: dict[str, ExampleAdjudicationV0] = {}
    for overlay in overlays:
        if overlay.adjudication_id in records:
            raise EvaluationContractError(f"duplicate adjudication id {overlay.adjudication_id}")
        records[overlay.adjudication_id] = overlay

    for overlay in records.values():
        if overlay.supersedes is None:
            continue
        target = records.get(overlay.supersedes)
        if target is None:
            raise EvaluationContractError(f"missing supersession target {overlay.supersedes}")
        if _target(target) != _target(overlay):
            raise EvaluationContractError(
                f"cross-finding supersession from {overlay.adjudication_id}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(adjudication_id: str) -> None:
        if adjudication_id in visited:
            return
        if adjudication_id in visiting:
            raise EvaluationContractError("supersession cycle")
        visiting.add(adjudication_id)
        parent = records[adjudication_id].supersedes
        if parent is not None:
            visit(parent)
        visiting.remove(adjudication_id)
        visited.add(adjudication_id)

    for adjudication_id in records:
        visit(adjudication_id)

    superseded = {
        overlay.supersedes for overlay in records.values() if overlay.supersedes is not None
    }
    live_by_finding: dict[AdjudicationTargetV0, list[ExampleAdjudicationV0]] = defaultdict(list)
    for adjudication_id, overlay in records.items():
        if adjudication_id not in superseded:
            live_by_finding[_target(overlay)].append(overlay)

    resolved: dict[AdjudicationTargetV0, ExampleAdjudicationV0] = {}
    for target, live in live_by_finding.items():
        if len(live) != 1:
            raise EvaluationContractError(f"two live adjudication heads for finding {target}")
        resolved[target] = live[0]
    return resolved


def _validate_packs(
    packs: Sequence[ExamplePackV0], *, finding_cap: int
) -> tuple[ExamplePackV0, ...]:
    if isinstance(finding_cap, bool) or finding_cap <= 0:
        raise EvaluationContractError("finding_cap must be positive")

    identities: set[tuple[object, ...]] = set()
    checked: list[ExamplePackV0] = []
    for pack in packs:
        if pack.attempt_kind != "risk":
            raise EvaluationContractError("PR scorecards accept risk packs only")
        identity = (
            pack.instrument_id,
            pack.scope.installation_id,
            pack.scope.github_repository_id,
            pack.scope.pull_number,
            pack.scope.admitted_base_sha,
            pack.scope.admitted_head_sha,
        )
        if identity in identities:
            raise EvaluationContractError(f"duplicate eligible PR identity {identity}")
        identities.add(identity)
        checked.append(pack)
    return tuple(checked)


def _validate_overlay_references(
    packs: Sequence[ExamplePackV0], overlays: Sequence[ExampleAdjudicationV0]
) -> None:
    by_hash = {pack.pack_hash: pack for pack in packs}
    for overlay in overlays:
        pack = by_hash.get(overlay.pack_hash)
        if pack is None:
            raise EvaluationContractError(
                f"adjudication {overlay.adjudication_id} references missing pack"
            )
        if overlay.run_id != pack.run_id:
            raise EvaluationContractError(f"adjudication {overlay.adjudication_id} run_id mismatch")
        if overlay.finding_id not in {finding.finding_id for finding in pack.findings}:
            raise EvaluationContractError(
                f"adjudication {overlay.adjudication_id} references missing finding"
            )


def score_packs(
    packs: Sequence[ExamplePackV0],
    overlays: Sequence[ExampleAdjudicationV0],
    *,
    finding_cap: int,
) -> ScorecardV0:
    """Score every eligible pack, including empty, partial, and failed runs."""

    checked = _validate_packs(packs, finding_cap=finding_cap)
    _validate_overlay_references(checked, overlays)
    effective = resolve_adjudications(overlays)

    actionable = 0
    accepted = 0
    unsupported = 0
    for pack in checked:
        for finding in pack.findings[:finding_cap]:
            adjudication = effective.get((pack.pack_hash, pack.run_id, finding.finding_id))
            if adjudication is None:
                unsupported += 1
            elif adjudication.disposition == "verified_actionable":
                actionable += 1
            elif adjudication.disposition == "verified_accepted_nonactionable":
                accepted += 1
            else:
                unsupported += 1

    eligible = len(checked)
    return ScorecardV0(
        eligible_prs=eligible,
        yield_denominator=eligible,
        burden_denominator=eligible,
        validated_actionable=actionable,
        verified_accepted_nonactionable=accepted,
        unsupported=unsupported,
    )


def score_packs_by_instrument(
    packs: Sequence[ExamplePackV0],
    overlays: Sequence[ExampleAdjudicationV0],
    *,
    finding_cap: int,
) -> tuple[InstrumentScorecardV0, ...]:
    """Partition before scoring so whole-instrument revisions never mix."""

    partitions: dict[str, list[ExamplePackV0]] = defaultdict(list)
    for pack in packs:
        partitions[pack.instrument_id].append(pack)

    results: list[InstrumentScorecardV0] = []
    for instrument_id in sorted(partitions):
        selected = partitions[instrument_id]
        pack_hashes = {pack.pack_hash for pack in selected}
        selected_overlays = [
            overlay for overlay in overlays if overlay.pack_hash in pack_hashes
        ]
        results.append(
            InstrumentScorecardV0(
                instrument_id=instrument_id,
                scorecard=score_packs(
                    selected,
                    selected_overlays,
                    finding_cap=finding_cap,
                ),
            )
        )
    return tuple(results)


def null_control_scorecard(packs: Sequence[ExamplePackV0], *, finding_cap: int) -> ScorecardV0:
    checked = _validate_packs(packs, finding_cap=finding_cap)
    eligible = len(checked)
    return ScorecardV0(
        eligible_prs=eligible,
        yield_denominator=eligible,
        burden_denominator=eligible,
        validated_actionable=0,
        verified_accepted_nonactionable=0,
        unsupported=0,
    )


def spam_control_scorecard(packs: Sequence[ExamplePackV0], *, finding_cap: int) -> ScorecardV0:
    checked = _validate_packs(packs, finding_cap=finding_cap)
    eligible = len(checked)
    return ScorecardV0(
        eligible_prs=eligible,
        yield_denominator=eligible,
        burden_denominator=eligible,
        validated_actionable=0,
        verified_accepted_nonactionable=0,
        unsupported=eligible * finding_cap,
    )


def evaluate_control_gates(
    packs: Sequence[ExamplePackV0],
    *,
    finding_cap: int,
    required_yield: float,
    reference_burden: float,
    burden_margin: float,
) -> ControlGateV0:
    for name, value in (
        ("required_yield", required_yield),
        ("reference_burden", reference_burden),
        ("burden_margin", burden_margin),
    ):
        if value < 0:
            raise EvaluationContractError(f"{name} must be non-negative")

    null = null_control_scorecard(packs, finding_cap=finding_cap)
    spam = spam_control_scorecard(packs, finding_cap=finding_cap)
    return ControlGateV0(
        null=null,
        spam=spam,
        required_yield=required_yield,
        reference_burden=reference_burden,
        burden_margin=burden_margin,
        null_passes_yield=null.validated_actionable_yield >= required_yield,
        spam_passes_burden=(spam.unsupported_finding_burden <= reference_burden + burden_margin),
    )
