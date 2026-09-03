from datetime import UTC, datetime, timedelta

import pytest

from doug.example_pack import (
    CapturedFindingV0,
    ContentRefV0,
    CoverageV0,
    ExampleAdjudicationV0,
    ExamplePackV0,
    FailureV0,
    NameVersionV0,
    PackScopeV0,
    UsageV0,
    WholeInstrumentManifestV0,
    canonical_json_bytes,
)
from doug.example_pack_eval import (
    EvaluationContractError,
    evaluate_control_gates,
    resolve_adjudications,
    score_packs,
    score_packs_by_instrument,
)

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _manifest(*, attempt_kind: str = "risk") -> WholeInstrumentManifestV0:
    return WholeInstrumentManifestV0(
        provider="anthropic",
        pinned_model_id="claude-opus-5",
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
        application_revision=None,
        runtime_revision=None,
        attempt_kind=attempt_kind,
    )


def _pack(
    finding_count: int = 0,
    *,
    status: str = "captured",
    pull_number: int = 1,
    attempt_kind: str = "risk",
    run_suffix: str = "0",
    raw_sha: str | None = None,
) -> ExamplePackV0:
    raw_sha = raw_sha or f"{pull_number:064x}"
    findings = tuple(
        CapturedFindingV0.build(
            raw_output_sha256=raw_sha,
            attempt_kind=attempt_kind,
            ordinal=index,
            finding={"rule": f"rule-{index}", "severity": "high"},
        )
        for index in range(finding_count)
    )
    complete = status != "partial"
    coverage = CoverageV0(
        diff_chars=10,
        sent_chars=10 if complete else 5,
        files_sent=1,
        files_unseen=() if complete else ("unseen.py",),
        files_dropped=() if complete else ("unseen.py",),
    )
    manifest = _manifest(attempt_kind=attempt_kind)
    is_failed = status == "failed"
    return ExamplePackV0.build(
        run_id=f"review-job:{pull_number}:claim:{run_suffix}:{attempt_kind}",
        attempt_kind=attempt_kind,
        captured_at=NOW + timedelta(seconds=pull_number),
        scope=PackScopeV0(
            installation_id=100,
            github_repository_id=200,
            repository_full_name="owner/repo",
            pull_number=pull_number,
            admitted_base_sha=f"base-{pull_number}",
            admitted_head_sha=f"head-{pull_number}",
        ),
        request=None
        if is_failed
        else ContentRefV0(sha256="3" * 64, size=3, media_type="application/json"),
        evidence=ContentRefV0(sha256="4" * 64, size=4, media_type="text/plain"),
        model_call_made=not is_failed,
        raw_output=(
            None
            if is_failed
            else ContentRefV0(sha256=raw_sha, size=5, media_type="application/json")
        ),
        parsed_output=None
        if is_failed
        else {"findings": [finding.finding for finding in findings]},
        coverage=coverage,
        usage=UsageV0(input_tokens=None, output_tokens=None),
        latency_ms=1,
        capture_status=status,
        failure=(
            FailureV0(phase="preflight", error_type="SpendCapExceeded", detail="capped")
            if is_failed
            else None
        ),
        fallback_state="spend_capped" if is_failed else "none",
        instrument_manifest=manifest,
        instrument_id=manifest.instrument_id(),
        findings=findings,
    )


def _adjudication(
    pack: ExamplePackV0,
    disposition: str,
    *,
    ordinal: int = 0,
    supersedes: str | None = None,
    second: int = 0,
) -> ExampleAdjudicationV0:
    return ExampleAdjudicationV0.build(
        pack_hash=pack.pack_hash,
        run_id=pack.run_id,
        finding_id=pack.findings[ordinal].finding_id,
        disposition=disposition,
        evidence=(),
        verifier_receipts=(),
        adjudicator="test",
        adjudicated_at=NOW + timedelta(seconds=second),
        supersedes=supersedes,
    )


def test_adjudication_never_mutates_pack_and_supersession_is_explicit():
    pack = _pack(1)
    before = canonical_json_bytes(pack.model_dump(mode="json"))
    first = _adjudication(pack, "unknown")
    second = _adjudication(
        pack,
        "verified_actionable",
        supersedes=first.adjudication_id,
        second=1,
    )

    target = (pack.pack_hash, pack.run_id, pack.findings[0].finding_id)
    assert resolve_adjudications([first, second])[target] == second
    assert canonical_json_bytes(pack.model_dump(mode="json")) == before


def test_zero_partial_and_failed_runs_enter_both_denominators():
    score = score_packs(
        [
            _pack(status="captured", pull_number=1),
            _pack(status="partial", pull_number=2),
            _pack(status="failed", pull_number=3),
        ],
        [],
        finding_cap=3,
    )

    assert score.eligible_prs == 3
    assert score.yield_denominator == 3
    assert score.burden_denominator == 3
    assert score.validated_actionable_yield == 0
    assert score.unsupported_finding_burden == 0


@pytest.mark.parametrize(
    ("disposition", "actionable", "accepted", "unsupported"),
    [
        ("verified_actionable", 1, 0, 0),
        ("verified_accepted_nonactionable", 0, 1, 0),
        ("disproved", 0, 0, 1),
        ("unknown", 0, 0, 1),
        (None, 0, 0, 1),
    ],
)
def test_literal_disposition_table(
    disposition: str | None,
    actionable: int,
    accepted: int,
    unsupported: int,
):
    pack = _pack(1)
    overlays = [] if disposition is None else [_adjudication(pack, disposition)]

    score = score_packs([pack], overlays, finding_cap=3)

    assert score.validated_actionable == actionable
    assert score.verified_accepted_nonactionable == accepted
    assert score.unsupported == unsupported


def test_finding_cap_is_applied_per_pack_without_dropping_pack_denominators():
    first = _pack(3, pull_number=1)
    second = _pack(3, pull_number=2)

    score = score_packs([first, second], [], finding_cap=2)

    assert score.eligible_prs == 2
    assert score.unsupported == 4
    assert score.unsupported_finding_burden == 2


def test_identical_findings_on_independent_prs_have_independent_adjudications():
    shared_raw = "a" * 64
    first = _pack(1, pull_number=1, raw_sha=shared_raw)
    second = _pack(1, pull_number=2, raw_sha=shared_raw)
    assert first.findings[0].finding_id == second.findings[0].finding_id
    first_overlay = _adjudication(first, "verified_actionable")
    second_overlay = _adjudication(second, "disproved")

    resolved = resolve_adjudications([first_overlay, second_overlay])
    score = score_packs([first, second], [first_overlay, second_overlay], finding_cap=3)

    assert resolved[(first.pack_hash, first.run_id, first.findings[0].finding_id)] == first_overlay
    assert (
        resolved[(second.pack_hash, second.run_id, second.findings[0].finding_id)] == second_overlay
    )
    assert score.validated_actionable == 1
    assert score.unsupported == 1


def test_missing_supersession_target_is_rejected():
    pack = _pack(1)
    overlay = _adjudication(pack, "unknown").model_copy(update={"supersedes": "f" * 64})

    with pytest.raises(EvaluationContractError, match="missing supersession target"):
        resolve_adjudications([overlay])


def test_cross_finding_supersession_is_rejected():
    pack = _pack(2)
    first = _adjudication(pack, "unknown", ordinal=0)
    second = _adjudication(pack, "disproved", ordinal=1, supersedes=first.adjudication_id)

    with pytest.raises(EvaluationContractError, match="cross-finding"):
        resolve_adjudications([first, second])


def test_supersession_cycle_is_rejected():
    pack = _pack(1)
    first = _adjudication(pack, "unknown", second=1)
    second = _adjudication(pack, "disproved", second=2)
    cyclic_first = first.model_copy(update={"supersedes": second.adjudication_id})
    cyclic_second = second.model_copy(update={"supersedes": first.adjudication_id})

    with pytest.raises(EvaluationContractError, match="cycle"):
        resolve_adjudications([cyclic_first, cyclic_second])


def test_two_live_adjudication_heads_are_rejected():
    pack = _pack(1)
    first = _adjudication(pack, "unknown", second=1)
    second = _adjudication(pack, "disproved", second=2)

    with pytest.raises(EvaluationContractError, match="two live"):
        resolve_adjudications([first, second])


def test_duplicate_eligible_pr_identity_is_rejected():
    first = _pack(pull_number=1, run_suffix="1")
    second = _pack(pull_number=1, run_suffix="2")

    with pytest.raises(EvaluationContractError, match="duplicate eligible PR"):
        score_packs([first, second], [], finding_cap=3)


def test_non_risk_pack_is_rejected_from_pr_scorecard():
    with pytest.raises(EvaluationContractError, match="risk packs"):
        score_packs([_pack(attempt_kind="intent")], [], finding_cap=3)


def test_scorecards_partition_whole_instruments_before_aggregation():
    first = _pack(1, pull_number=1)
    second_manifest = _manifest().model_copy(update={"pinned_model_id": "claude-opus-5-1"})
    second_payload = _pack(1, pull_number=2).model_dump(
        mode="python", exclude={"pack_hash", "instrument_manifest", "instrument_id"}
    )
    second = ExamplePackV0.build(
        **second_payload,
        instrument_manifest=second_manifest,
        instrument_id=second_manifest.instrument_id(),
    )

    partitions = score_packs_by_instrument(
        [second, first],
        [_adjudication(first, "verified_actionable")],
        finding_cap=3,
    )

    assert [partition.instrument_id for partition in partitions] == sorted(
        [first.instrument_id, second.instrument_id]
    )
    assert [partition.scorecard.eligible_prs for partition in partitions] == [1, 1]
    assert sum(partition.scorecard.validated_actionable for partition in partitions) == 1


@pytest.mark.parametrize("finding_cap", [0, -1])
def test_non_positive_finding_cap_is_rejected(finding_cap: int):
    with pytest.raises(EvaluationContractError, match="positive"):
        score_packs([_pack()], [], finding_cap=finding_cap)


def test_overlay_must_reference_an_input_pack_and_its_exact_run_and_finding():
    pack = _pack(1)
    missing_pack = _adjudication(pack, "unknown").model_copy(update={"pack_hash": "f" * 64})
    wrong_run = _adjudication(pack, "unknown").model_copy(update={"run_id": "wrong"})
    wrong_finding = _adjudication(pack, "unknown").model_copy(update={"finding_id": "e" * 64})

    for overlay, message in (
        (missing_pack, "missing pack"),
        (wrong_run, "run_id mismatch"),
        (wrong_finding, "missing finding"),
    ):
        with pytest.raises(EvaluationContractError, match=message):
            score_packs([pack], [overlay], finding_cap=3)


def test_null_and_spam_controls_cannot_pass():
    packs = [
        _pack(status="captured", pull_number=1),
        _pack(status="partial", pull_number=2),
        _pack(status="failed", pull_number=3),
    ]

    gates = evaluate_control_gates(
        packs,
        finding_cap=4,
        required_yield=0.01,
        reference_burden=0.0,
        burden_margin=0.0,
    )

    assert gates.null.validated_actionable_yield == 0
    assert not gates.null_passes_yield
    assert gates.spam.unsupported_finding_burden == 4
    assert not gates.spam_passes_burden


def test_control_thresholds_are_literal_and_validated():
    packs = [_pack(pull_number=1), _pack(pull_number=2)]
    gates = evaluate_control_gates(
        packs,
        finding_cap=2,
        required_yield=0.0,
        reference_burden=2.0,
        burden_margin=0.0,
    )

    assert gates.null_passes_yield
    assert gates.spam_passes_burden

    for arguments, message in (
        ({"required_yield": -0.1}, "required_yield"),
        ({"reference_burden": -0.1}, "reference_burden"),
        ({"burden_margin": -0.1}, "burden_margin"),
    ):
        kwargs = {
            "finding_cap": 2,
            "required_yield": 0.0,
            "reference_burden": 0.0,
            "burden_margin": 0.0,
            **arguments,
        }
        with pytest.raises(EvaluationContractError, match=message):
            evaluate_control_gates(packs, **kwargs)
