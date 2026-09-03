import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from doug import example_pack_capture, reader, review, store
from doug.api import app
from doug.example_pack import (
    CaptureScopeV0,
    ExamplePackV0,
    FileExamplePackStore,
    NameVersionV0,
    PackScopeV0,
    canonical_json_bytes,
)
from doug.models import Band, PRMetadata

PAYLOAD = {
    "risk_score": 62,
    "rationale": "Concurrent writes to shared cache without a lock.",
    "findings": [
        {
            "category_slug": "race-condition",
            "description": "Cache write is not guarded",
            "file": "cache.py",
            "severity": "high",
        }
    ],
}


class _FakeMessages:
    """`calls` and `log` exist for the spend-cap tests below, which turn on
    whether the model was called at all — a cap asserted only through the
    verdict it produces has already paid for the read it was meant to stop.
    """

    def __init__(
        self,
        payload: dict | None,
        stop_reason: str = "end_turn",
        usage: tuple[int, int] | None = (1200, 340),
        log: list[str] | None = None,
    ):
        self._payload = payload
        self._stop_reason = stop_reason
        self._usage = usage
        self._log = log
        self.calls = 0
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.calls += 1
        if self._log is not None:
            self._log.append("create")
        self.last_kwargs = kwargs
        text = json.dumps(self._payload) if self._payload is not None else ""
        block = SimpleNamespace(type="text", text=text)
        usage = (
            None
            if self._usage is None
            else SimpleNamespace(input_tokens=self._usage[0], output_tokens=self._usage[1])
        )
        return SimpleNamespace(content=[block], stop_reason=self._stop_reason, usage=usage)


class FakeClient:
    def __init__(
        self,
        payload: dict | None = PAYLOAD,
        stop_reason: str = "end_turn",
        usage: tuple[int, int] | None = (1200, 340),
        log: list[str] | None = None,
    ):
        self.messages = _FakeMessages(payload, stop_reason, usage, log)


SCOPE = "installation:1"

INTENT_PAYLOAD = {**PAYLOAD, "intent_alignment": 90, "deviation_findings": []}

DOCS = [SimpleNamespace(id="ADR-1", title="t", body="b")]


def _capture_scope() -> CaptureScopeV0:
    return CaptureScopeV0(
        run_id_prefix="review-job:9:claim:1",
        scope=PackScopeV0(
            installation_id=10,
            github_repository_id=20,
            repository_full_name="owner/repo",
            pull_number=7,
            admitted_base_sha="base-sha",
            admitted_head_sha="head-sha",
        ),
        read_order="tiered",
        input_policy_version="reader-input-v0",
        coverage_policy_version="reader-coverage-v0",
        verifier_versions=(NameVersionV0(name="settle", version="v0"),),
        tool_versions=(NameVersionV0(name="anthropic-sdk", version="0.70.0"),),
    )


def _enable_capture(monkeypatch, root):
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_CAPTURE", "1")
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_DIR", str(root))


def _captured_packs(root) -> list[ExamplePackV0]:
    directory = root / "packs/sha256"
    return [
        ExamplePackV0.model_validate_json(path.read_bytes())
        for path in sorted(directory.iterdir())
    ]


def _blob(root, reference) -> bytes:
    return (root / "blobs/sha256" / reference.sha256).read_bytes()


def _pr(**kw) -> PRMetadata:
    base = dict(number=7, title="Add cache", author="dev", files=["cache.py"])
    base.update(kw)
    return PRMetadata.model_validate(base)


def _rv(risk_score: int, findings: list | None = None) -> reader.ReaderVerdict:
    return reader.ReaderVerdict(
        risk_score=risk_score, rationale="test", findings=findings or []
    )


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv("DOUG_READER", raising=False)
    assert not reader.enabled()
    monkeypatch.setenv("DOUG_READER", "1")
    assert reader.enabled()


def test_read_diff_parses_and_sends_schema():
    client = FakeClient()
    rv = reader.read_diff(_pr(), "+ cache[k] = v", scope=SCOPE, client=client)
    assert rv.risk_score == 62
    assert rv.findings[0].category_slug == "race-condition"
    kw = client.messages.last_kwargs
    assert kw["model"] == reader.MODEL
    assert kw["system"] == reader.SYSTEM
    assert kw["output_config"]["format"]["schema"] == reader.SCHEMA
    assert "Add cache" in kw["messages"][0]["content"]


def test_read_diff_truncates_at_budget():
    client = FakeClient()
    reader.read_diff(_pr(), "x" * (reader.DIFF_BUDGET + 500), scope=SCOPE, client=client)
    body = client.messages.last_kwargs["messages"][0]["content"]
    assert "[diff truncated at budget]" in body
    assert len(body) < reader.DIFF_BUDGET + 300


def test_read_diff_raises_on_refusal():
    with pytest.raises(reader.ReaderError):
        reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient(stop_reason="refusal"))


@pytest.mark.parametrize(
    "payload",
    [PAYLOAD, {**PAYLOAD, "risk_score": 5, "findings": []}],
    ids=["findings", "zero-findings"],
)
def test_read_diff_captures_exact_request_output_and_success(
    tmp_path, monkeypatch, payload
):
    _enable_capture(monkeypatch, tmp_path)
    client = FakeClient(payload=payload, usage=(321, 45))
    diff = "+ authorization is source text, not a request header"

    with example_pack_capture.capture_scope(_capture_scope()):
        returned = reader.read_diff(_pr(), diff, scope=SCOPE, client=client)

    (pack,) = _captured_packs(tmp_path)
    assert pack.capture_status == "captured"
    assert pack.failure is None
    assert pack.parsed_output == returned.model_dump(mode="json")
    assert pack.usage.model_dump() == {"input_tokens": 321, "output_tokens": 45}
    assert pack.latency_ms >= 0
    assert _blob(tmp_path, pack.request) == canonical_json_bytes(client.messages.last_kwargs)
    assert _blob(tmp_path, pack.evidence) == diff.encode()
    assert _blob(tmp_path, pack.raw_output) == json.dumps(payload).encode()
    assert len(pack.findings) == len(payload["findings"])
    assert b"sdk_client" not in pack.canonical_bytes()
    assert b'"headers"' not in _blob(tmp_path, pack.request)


def test_read_diff_captures_partial_status_and_exact_coverage(tmp_path, monkeypatch):
    _enable_capture(monkeypatch, tmp_path)
    diff = reader.diff_chunk(
        "large.py", "modified", 1, 0, "+" + "x" * reader.DIFF_BUDGET
    )
    pr = _pr(changed_files=2, files_dropped=["binary.dat"])

    with example_pack_capture.capture_scope(_capture_scope()):
        reader.read_diff(pr, diff, scope=SCOPE, client=FakeClient())

    (pack,) = _captured_packs(tmp_path)
    assert pack.capture_status == "partial"
    # The pack's coverage is the frozen V0 contract, projected field-by-field
    # from the live model — additive live fields (hunks, migration 12) must
    # not leak into it, so the comparison projects through the same function.
    assert pack.coverage == reader._capture_coverage(pr, diff)


def test_read_diff_captures_transport_stop_parse_and_spend_failures(
    tmp_path, monkeypatch
):
    terminals = tmp_path / "terminals"
    terminals.mkdir()

    transport_root = terminals / "transport"
    _enable_capture(monkeypatch, transport_root)
    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(reader.ReaderError, match="RuntimeError: transport down"):
            reader.read_diff(
                _pr(), "+ x", scope=SCOPE, client=RaisingClient(RuntimeError("transport down"))
            )
    (transport,) = _captured_packs(transport_root)
    assert transport.capture_status == "failed"
    assert transport.failure.phase == "transport"
    assert transport.model_call_made
    assert transport.request is not None
    assert transport.raw_output is None

    stop_root = terminals / "stop"
    _enable_capture(monkeypatch, stop_root)
    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(reader.ReaderError, match="read stopped with refusal"):
            reader.read_diff(
                _pr(), "+ x", scope=SCOPE, client=FakeClient(stop_reason="refusal")
            )
    (stopped,) = _captured_packs(stop_root)
    assert stopped.failure.phase == "stop_reason"
    assert stopped.raw_output is not None
    assert _blob(stop_root, stopped.raw_output) == json.dumps(PAYLOAD).encode()

    parse_root = terminals / "parse"
    _enable_capture(monkeypatch, parse_root)
    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(reader.ReaderError, match="unparseable reader output"):
            reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient(payload=None))
    (unparseable,) = _captured_packs(parse_root)
    assert unparseable.failure.phase == "parse"
    assert unparseable.raw_output is not None
    assert _blob(parse_root, unparseable.raw_output) == b""

    capped_root = terminals / "capped"
    _enable_capture(monkeypatch, capped_root)
    monkeypatch.setattr(store, "record_deep_read", lambda scope, cap: False)
    client = FakeClient()
    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(reader.SpendCapExceeded):
            reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)
    (capped,) = _captured_packs(capped_root)
    assert capped.failure.phase == "preflight"
    assert capped.fallback_state == "spend_capped"
    assert not capped.model_call_made
    assert capped.request is None
    assert client.messages.calls == 0


def test_client_construction_failures_are_captured_without_changing_exception(
    tmp_path, monkeypatch
):
    def fail_client():
        raise RuntimeError("client initialization failed")

    monkeypatch.setattr(reader, "_client", fail_client)

    risk_root = tmp_path / "risk"
    _enable_capture(monkeypatch, risk_root)
    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(RuntimeError, match="client initialization failed"):
            reader.read_diff(_pr(), "+ x", scope=SCOPE)
    (risk,) = _captured_packs(risk_root)
    assert risk.capture_status == "failed"
    assert risk.failure.phase == "preflight"
    assert not risk.model_call_made
    assert risk.request is None

    intent_root = tmp_path / "intent"
    _enable_capture(monkeypatch, intent_root)
    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(RuntimeError, match="client initialization failed"):
            reader.read_with_decisions(_pr(), "+ x", DOCS, scope=SCOPE)
    (intent,) = _captured_packs(intent_root)
    assert intent.capture_status == "failed"
    assert intent.failure.phase == "preflight"
    assert not intent.model_call_made
    assert intent.request is None


def test_transport_failure_capture_never_persists_exception_headers_or_secrets(
    tmp_path, monkeypatch
):
    _enable_capture(monkeypatch, tmp_path)
    unsafe = RuntimeError(
        "response headers={'authorization': 'Bearer secret-token', "
        "'cookie': 'session-secret'}"
    )

    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(reader.ReaderError) as raised:
            reader.read_diff(_pr(), "+ x", scope=SCOPE, client=RaisingClient(unsafe))

    assert "secret-token" in str(raised.value), "live error behavior is unchanged"
    (pack,) = _captured_packs(tmp_path)
    captured = pack.canonical_bytes().lower()
    assert b"secret-token" not in captured
    assert b"session-secret" not in captured
    assert b"authorization" not in captured
    assert pack.failure.error_type == "RuntimeError"


def test_risk_and_intent_captures_have_distinct_instruments(tmp_path, monkeypatch):
    _enable_capture(monkeypatch, tmp_path)

    with example_pack_capture.capture_scope(_capture_scope()):
        reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient())
        reader.read_with_decisions(
            _pr(),
            "+ x",
            DOCS,
            scope=SCOPE,
            client=FakeClient(payload=INTENT_PAYLOAD),
        )

    packs = {pack.attempt_kind: pack for pack in _captured_packs(tmp_path)}
    assert set(packs) == {"risk", "intent"}
    assert packs["risk"].run_id == "review-job:9:claim:1:risk"
    assert packs["intent"].run_id == "review-job:9:claim:1:intent"
    assert packs["risk"].instrument_id != packs["intent"].instrument_id
    assert (
        packs["risk"].instrument_manifest.system_prompt_sha256
        != packs["intent"].instrument_manifest.system_prompt_sha256
    )
    assert (
        packs["risk"].instrument_manifest.output_schema_sha256
        != packs["intent"].instrument_manifest.output_schema_sha256
    )


def test_disabled_capture_writes_nothing_and_preserves_exact_sdk_kwargs(
    tmp_path, monkeypatch
):
    sentinel = tmp_path / "disabled"
    monkeypatch.delenv("DOUG_EXAMPLE_PACK_CAPTURE", raising=False)
    monkeypatch.setenv("DOUG_EXAMPLE_PACK_DIR", str(sentinel))
    client = FakeClient()
    pr = _pr()
    diff = "+ x"

    reader.read_diff(pr, diff, scope=SCOPE, client=client)

    assert client.messages.last_kwargs == {
        "model": reader.MODEL,
        "max_tokens": reader.MAX_TOKENS,
        "output_config": {
            "effort": reader.EFFORT,
            "format": {"type": "json_schema", "schema": reader.SCHEMA},
        },
        "system": reader.SYSTEM,
        "messages": [{"role": "user", "content": reader._user_text(pr, diff)}],
    }
    assert not sentinel.exists()


@pytest.mark.parametrize("attempt_kind", ["risk", "intent"])
def test_disabled_capture_never_canonicalizes_the_full_request(
    monkeypatch, attempt_kind
):
    """Default-off instrumentation must not inspect or serialize the prompt."""
    monkeypatch.delenv("DOUG_EXAMPLE_PACK_CAPTURE", raising=False)
    monkeypatch.delenv("DOUG_EXAMPLE_PACK_DIR", raising=False)
    canonicalized: list[object] = []
    real_canonical = example_pack_capture.canonical_json_bytes

    def observe_canonicalization(value):
        canonicalized.append(value)
        return real_canonical(value)

    monkeypatch.setattr(
        example_pack_capture, "canonical_json_bytes", observe_canonicalization
    )
    client = FakeClient(payload=PAYLOAD if attempt_kind == "risk" else INTENT_PAYLOAD)

    if attempt_kind == "risk":
        returned = reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)
    else:
        returned = reader.read_with_decisions(
            _pr(), "+ x", DOCS, scope=SCOPE, client=client
        )

    assert returned.risk_score == 62
    assert client.messages.calls == 1
    assert canonicalized == []


def test_non_allowlisted_hosted_reader_never_constructs_storage_client(monkeypatch):
    """Admission must reject a foreign tenant before any GCS client work.

    The worker still performs the live model read; capture is the optional lane.
    Exercising the reader call site prevents a scope-only test from missing a
    later ``record_attempt`` regression.
    """
    hosted = {
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
    for name, value in hosted.items():
        monkeypatch.setenv(name, value)

    def fail_storage(*_args, **_kwargs):
        pytest.fail("foreign tenant constructed an Example Pack GCS client")

    monkeypatch.setattr(example_pack_capture, "GcsObjectStore", fail_storage)
    client = FakeClient()

    with example_pack_capture.capture_scope_if_enabled(
        lambda: pytest.fail("foreign tenant built a capture scope"),
        run_id_prefix="review-job:41:claim:1",
        installation_id=18,
        github_repository_id=20,
        now=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
    ):
        returned = reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)

    assert returned.risk_score == 62
    assert client.messages.calls == 1


@pytest.mark.parametrize("attempt_kind", ["risk", "intent"])
def test_request_capture_serialization_failure_cannot_change_the_live_read(
    tmp_path, monkeypatch, capsys, attempt_kind
):
    """The SDK call remains authoritative when optional capture cannot serialize."""
    _enable_capture(monkeypatch, tmp_path)

    def fail_canonicalization(_value):
        raise RuntimeError("request capture unavailable")

    monkeypatch.setattr(
        example_pack_capture, "canonical_json_bytes", fail_canonicalization
    )
    client = FakeClient(payload=PAYLOAD if attempt_kind == "risk" else INTENT_PAYLOAD)

    with example_pack_capture.capture_scope(_capture_scope()):
        if attempt_kind == "risk":
            returned = reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)
        else:
            returned = reader.read_with_decisions(
                _pr(), "+ x", DOCS, scope=SCOPE, client=client
            )

    assert returned.risk_score == 62
    assert client.messages.calls == 1
    expected_schema = reader.SCHEMA if attempt_kind == "risk" else reader.INTENT_SCHEMA
    expected_system = (
        reader.SYSTEM if attempt_kind == "risk" else reader.DECISION_INTENT_SYSTEM
    )
    expected_content = (
        reader._user_text(_pr(), "+ x")
        if attempt_kind == "risk"
        else reader._intent_text(_pr(), "+ x", DOCS)
    )
    assert client.messages.last_kwargs == {
        "model": reader.MODEL,
        "max_tokens": reader.MAX_TOKENS,
        "output_config": {
            "effort": reader.EFFORT,
            "format": {"type": "json_schema", "schema": expected_schema},
        },
        "system": expected_system,
        "messages": [{"role": "user", "content": expected_content}],
    }
    assert not (tmp_path / "packs").exists()
    diagnostics = [
        line
        for line in capsys.readouterr().err.splitlines()
        if "example-pack" in line
    ]
    assert len(diagnostics) == 1
    assert "example-pack capture failed" in diagnostics[0]
    assert "RuntimeError" in diagnostics[0]


class _FailingPackStore(FileExamplePackStore):
    def put_pack(self, pack):
        raise RuntimeError("pack sink unavailable")


def test_capture_storage_failure_cannot_change_successful_reader_result(
    tmp_path, monkeypatch, capsys
):
    sink = _FailingPackStore(tmp_path)
    _enable_capture(monkeypatch, tmp_path)
    monkeypatch.setattr(example_pack_capture, "configured_store", lambda environ=None: sink)
    client = FakeClient()

    with example_pack_capture.capture_scope(_capture_scope()):
        returned = reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)

    assert returned == reader.ReaderVerdict.model_validate(PAYLOAD)
    assert client.messages.last_kwargs["system"] == reader.SYSTEM
    error = capsys.readouterr().err
    assert "example-pack capture failed" in error
    assert "RuntimeError" in error


def test_capture_storage_failure_cannot_replace_transport_reader_error(
    tmp_path, monkeypatch, capsys
):
    sink = _FailingPackStore(tmp_path)
    _enable_capture(monkeypatch, tmp_path)
    monkeypatch.setattr(example_pack_capture, "configured_store", lambda environ=None: sink)

    with example_pack_capture.capture_scope(_capture_scope()):
        with pytest.raises(reader.ReaderError) as raised:
            reader.read_diff(
                _pr(), "+ x", scope=SCOPE, client=RaisingClient(TimeoutError("original"))
            )

    assert str(raised.value) == "TimeoutError: original"
    error = capsys.readouterr().err
    assert "example-pack capture failed" in error
    assert "RuntimeError" in error


def test_verdict_mapping_and_threshold():
    rv = reader.ReaderVerdict.model_validate(PAYLOAD)
    v = reader.verdict_from_reader(rv)
    assert v.band is Band.FLAGGED  # 62 >= default threshold 30
    assert v.score == 0.62
    assert v.reasons[0].rule == "reader:race-condition"

    low = reader.ReaderVerdict.model_validate({**PAYLOAD, "risk_score": 12, "findings": []})
    assert reader.verdict_from_reader(low).band is Band.CLEARED


def test_verdict_from_reader_carries_each_findings_own_file():
    """`file` travels on the Reason for the same reason `severity` does.

    store.save_review used to recover it afterwards by matching each Reason's
    label against the model's own `description` text — a key the model
    chooses and can repeat. Two findings that word one defect the same way
    collapsed to a single dict entry there, so both rows took the last
    finding's file. Setting it at construction removes the key entirely.
    """
    rv = reader.ReaderVerdict.model_validate(
        {
            **PAYLOAD,
            "findings": [
                {
                    "category_slug": "missing-null-check",
                    "description": "Response is dereferenced without a guard",
                    "file": "a.py",
                    "severity": "high",
                },
                {
                    "category_slug": "missing-null-check",
                    "description": "Response is dereferenced without a guard",
                    "file": "b.py",
                    "severity": "low",
                },
            ],
        }
    )

    reasons = reader.verdict_from_reader(rv).reasons
    assert [r.file for r in reasons] == ["a.py", "b.py"]
    assert [r.severity for r in reasons] == ["high", "low"]


def test_verdict_from_reader_on_the_line_needs_you_at_every_two_decimal_stop():
    """0.55*100 == 55.00000000000001; with an integer risk_score and >=, a PR
    sitting exactly on the line would clear while the check run printed
    'Risk 0.55 against a flag line of 0.55'. The caller passes round(t*100);
    this pins the two sides agree at the stops that would otherwise fail."""
    for line in (0.07, 0.14, 0.28, 0.55, 0.56):
        points = round(line * 100)
        on = reader.verdict_from_reader(_rv(risk_score=points), threshold=points)
        under = reader.verdict_from_reader(_rv(risk_score=points - 1), threshold=points)
        assert on.band is Band.FLAGGED, line
        assert under.band is Band.CLEARED, line
        assert on.threshold == line, line


# --- The spend cap, at the one place money is actually spent -------------
#
# store.record_deep_read has been tested since #25 and called from nowhere,
# which left production spend unbounded — a tested cap nothing consults is
# worth less than it looks. These tests turn on whether the model was
# called AT ALL, never on what verdict came back: a cap asserted through
# the fallback verdict alone would still pass with the check moved below
# client.messages.create, by which point the read is bought and the ceiling
# is decoration.


def test_read_diff_charges_the_scope_before_it_calls_the_model(monkeypatch):
    """Order, not outcome. store.record_deep_read's own docstring: "a cap
    enforced after paying for the call is not spend control, just a
    receipt." Pinning the sequence is what makes this test fail if the
    check is ever moved below the call — the mutation that would otherwise
    leave every cap test passing over an uncapped service."""
    order: list[str] = []
    monkeypatch.setattr(
        store, "record_deep_read", lambda scope, cap: order.append(f"spend:{scope}") or True
    )
    client = FakeClient(log=order)

    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)

    assert order == [f"spend:{SCOPE}", "create"]


def test_read_diff_at_the_cap_makes_no_model_call_at_all(monkeypatch):
    """The property the whole task exists for: not spending. A refused read
    must leave client.messages.create untouched, not merely produce a
    different verdict afterwards."""
    monkeypatch.setattr(store, "record_deep_read", lambda scope, cap: False)
    client = FakeClient()

    with pytest.raises(reader.SpendCapExceeded):
        reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)

    assert client.messages.calls == 0


def test_read_with_decisions_at_the_cap_makes_no_model_call_at_all(monkeypatch):
    """Both reads charge the same scope, so both have to stop at it. The
    intent read is the half the roadmap flags as uncapped and unmetered,
    and it costs the same money as the risk read."""
    monkeypatch.setattr(store, "record_deep_read", lambda scope, cap: False)
    client = FakeClient(payload=INTENT_PAYLOAD)

    with pytest.raises(reader.SpendCapExceeded):
        reader.read_with_decisions(_pr(), "+ x", DOCS, scope=SCOPE, client=client)

    assert client.messages.calls == 0


def test_a_read_with_no_decisions_to_judge_against_charges_nothing(monkeypatch):
    """read_with_decisions refuses an empty docs list before it sends
    anything, so that refusal must not burn a unit of a tenant's monthly
    budget for a read nobody ever made."""
    charged: list[str] = []
    monkeypatch.setattr(
        store, "record_deep_read", lambda scope, cap: charged.append(scope) or True
    )

    with pytest.raises(reader.ReaderError):
        reader.read_with_decisions(_pr(), "+ x", [], scope=SCOPE, client=FakeClient())

    assert charged == []


def test_reads_proceed_when_the_deployment_has_no_ledger(monkeypatch):
    """The honest limit of this cap, asserted rather than assumed.

    store.record_deep_read returns True when DATABASE_URL is unset ("if
    engine is None: return True"), so the cap is a property of deployments
    that HAVE a ledger — production — and not a property of this code.
    Local dogfooding and the open-source path run uncapped, deliberately,
    and a cap that could not be satisfied without a ledger would break
    every one of those runs instead.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = FakeClient()

    rv = reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)

    assert rv.risk_score == 62
    assert client.messages.calls == 1


def test_the_sentinel_scope_spends_its_own_budget_not_a_tenants(tmp_path, monkeypatch):
    """Un-tenanted reads (the CI path, the credential probe) charge a
    sentinel scope, and it is a SEPARATE ceiling on purpose: the CI path is
    deliberately dual-running against the App path as the soak comparison,
    and it must not be able to eat the dogfood installation's budget on its
    way. Real ledger, so this exercises the counter rather than a stub.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doug.db")
    monkeypatch.setattr(reader, "SENTINEL_MONTHLY_READ_CAP", 1)
    monkeypatch.setattr(reader, "INSTALLATION_MONTHLY_READ_CAP", 3)
    client = FakeClient()

    reader.read_diff(_pr(), "+ x", scope=reader.SENTINEL_SCOPE, client=client)
    with pytest.raises(reader.SpendCapExceeded):
        reader.read_diff(_pr(), "+ x", scope=reader.SENTINEL_SCOPE, client=client)

    # The installation's budget is untouched by the sentinel's exhaustion.
    reader.read_diff(_pr(), "+ x", scope=reader.installation_scope(42), client=client)

    assert client.messages.calls == 2


def test_a_read_cannot_be_bought_without_naming_who_pays_for_it():
    """`scope` is required, never defaulted, and this is the test that says
    why: a default is how the next caller silently becomes un-metered,
    which is the exact bug this branch closes (record_deep_read shipped
    tested in #25 and was called from nowhere for three weeks). A missing
    scope must be a TypeError at the call site, not a read charged to
    whichever tenant the default happened to name."""
    import inspect

    for fn in (reader.read_diff, reader.read_with_decisions, review.score_one):
        scope = inspect.signature(fn).parameters["scope"]
        assert scope.default is inspect.Parameter.empty, fn.__name__


def test_score_one_falls_back_with_a_rule_of_its_own_at_the_cap(monkeypatch):
    """A capped verdict and a broken-reader verdict need different
    operator responses — top up / raise the ceiling vs page someone — so
    they cannot share `reader-unavailable`. The band still comes back
    deterministic rather than the job failing: a PR left silently
    unreviewed is the failure mode this codebase exists to avoid."""
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(store, "record_deep_read", lambda scope, cap: False)
    # Not stubbed: a client built here would prove the cap ran too late.
    monkeypatch.setattr(reader, "_client", lambda: pytest.fail("built a client at the cap"))

    tier, verdict, rv, cov = review.score_one(_pr(), "+ x", scope=SCOPE)

    assert (tier, rv, cov) == ("deterministic", None, None)
    assert any(r.rule == "reader-capped" for r in verdict.reasons)
    assert not any(r.rule == "reader-unavailable" for r in verdict.reasons)


def test_the_cap_is_a_runaway_guard_with_room_over_a_real_months_reads():
    """Both constants are ceilings on a redelivery loop or an abuser, not
    business limits (per-installation pricing is M4), so they have to sit
    far above anything a real month of PR activity reaches — two reads per
    PR, risk and intent. A cap tightened to a plan-shaped number would
    start silently downgrading honest tenants to the deterministic tier,
    and the reason line for that is indistinguishable from an abuse stop.
    """
    assert reader.INSTALLATION_MONTHLY_READ_CAP >= 2 * 500
    assert reader.SENTINEL_MONTHLY_READ_CAP < reader.INSTALLATION_MONTHLY_READ_CAP


# --- /v1/score/read is token-gated: every call here can buy a read -------
#
# doug-api is deployed --allow-unauthenticated with DOUG_READER=1
# (api/deploy/gcp.sh:212,216), so before this gate anyone holding the URL
# could bill the account once per request. DIFF_BUDGET bounds what a single
# call costs; only the token bounds how many calls there are.

TOKEN = "score-read-token"


def _authed_read(diff: str = "+ x"):
    """An authorised POST. The gate is exercised by the three tests that
    follow; the behaviour tests after those carry the token so they keep
    testing what they are named for rather than re-testing auth."""
    return TestClient(app).post(
        "/v1/score/read",
        json={"pr": _pr().model_dump(mode="json"), "diff": diff},
        headers={"x-doug-token": TOKEN},
    )


def test_score_read_rejects_anonymous_before_paying_for_a_read(monkeypatch):
    """The 401 is only half the property worth having. The gate has to run
    BEFORE reader.read_diff, or an anonymous caller still buys the model
    call and merely fails to read the answer back — the spend hole would be
    open with a 401 painted over it. So this asserts the read never
    happened, not just the status code."""
    monkeypatch.setenv("DOUG_API_TOKEN", TOKEN)
    monkeypatch.setenv("DOUG_READER", "1")
    reads: list[str] = []

    def spy(pr, diff, *, scope, client=None):
        reads.append(diff)
        return reader.ReaderVerdict.model_validate(PAYLOAD)

    monkeypatch.setattr(reader, "read_diff", spy)
    r = TestClient(app).post(
        "/v1/score/read", json={"pr": _pr().model_dump(mode="json"), "diff": "+ x"}
    )
    assert r.status_code == 401
    assert reads == []


def test_score_read_rejects_a_wrong_token(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", TOKEN)
    r = TestClient(app).post(
        "/v1/score/read",
        json={"pr": _pr().model_dump(mode="json"), "diff": "+ x"},
        headers={"x-doug-token": "not-the-token"},
    )
    assert r.status_code == 401


def test_score_read_refuses_rather_than_running_open_when_unconfigured(monkeypatch):
    """An unset DOUG_API_TOKEN must fail closed. Comparing against an empty
    expected value would admit exactly the caller that sends no header —
    i.e. restore the anonymous hole on any deployment that forgot the
    secret, which is the deployment most likely to have forgotten it."""
    monkeypatch.delenv("DOUG_API_TOKEN", raising=False)
    r = TestClient(app).post(
        "/v1/score/read", json={"pr": _pr().model_dump(mode="json"), "diff": "+ x"}
    )
    assert r.status_code == 503


def test_endpoint_deterministic_when_reader_off(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", TOKEN)
    monkeypatch.delenv("DOUG_READER", raising=False)
    r = _authed_read()
    assert r.status_code == 200
    assert all(not x["rule"].startswith("reader:") for x in r.json()["reasons"])


def test_endpoint_uses_reader_when_enabled(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", TOKEN)
    monkeypatch.setenv("DOUG_READER", "1")
    fake = lambda pr, diff, *, scope, client=None: reader.ReaderVerdict.model_validate(  # noqa: E731
        PAYLOAD
    )
    monkeypatch.setattr(reader, "read_diff", fake)
    r = _authed_read()
    assert r.status_code == 200
    body = r.json()
    assert body["band"] == "flagged"
    assert body["reasons"][0]["rule"] == "reader:race-condition"


def test_endpoint_falls_back_loudly_on_reader_failure(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", TOKEN)
    monkeypatch.setenv("DOUG_READER", "1")

    def boom(pr, diff, *, scope, client=None):
        raise reader.ReaderError("api down")

    monkeypatch.setattr(reader, "read_diff", boom)
    r = _authed_read()
    assert r.status_code == 200
    assert "reader-unavailable" in {x["rule"] for x in r.json()["reasons"]}


def test_score_read_charges_the_sentinel_and_stops_at_it(monkeypatch):
    """The credential probe is never tenanted, so it spends against the
    sentinel — and at the sentinel's ceiling the endpoint still answers,
    with a deterministic verdict that names the cap. Holding a valid token
    stops being unlimited authority to bill the account; the token bounds
    who calls, the cap bounds how much they can spend.

    _client is booby-trapped rather than stubbed: at the cap this route
    must not so much as construct a client, let alone send a request.
    """
    monkeypatch.setenv("DOUG_API_TOKEN", TOKEN)
    monkeypatch.setenv("DOUG_READER", "1")
    charged: list[tuple[str, int]] = []

    def refuse(scope, cap):
        charged.append((scope, cap))
        return False

    monkeypatch.setattr(store, "record_deep_read", refuse)
    monkeypatch.setattr(reader, "_client", lambda: pytest.fail("built a client at the cap"))

    r = _authed_read()

    assert r.status_code == 200
    assert charged == [(reader.SENTINEL_SCOPE, reader.SENTINEL_MONTHLY_READ_CAP)]
    rules = {x["rule"] for x in r.json()["reasons"]}
    assert "reader-capped" in rules and "reader-unavailable" not in rules


class _RaisingMessages:
    def __init__(self, exc):
        self._exc = exc

    def create(self, **kwargs):
        raise self._exc


class RaisingClient:
    def __init__(self, exc):
        self.messages = _RaisingMessages(exc)


def test_transport_failures_become_reader_errors():
    """reader.py promises callers that a failed read falls back loudly. Only
    refusals and parse errors honoured that; everything the SDK raises —
    billing, rate limits, timeouts, 5xx — escaped and 500'd the caller.

    This is not hypothetical: an exhausted Anthropic balance took the CI
    path down for every repo, and continue-on-error reported it as success.
    """
    billing = RuntimeError(
        "Error code: 400 - Your credit balance is too low to access the Anthropic API."
    )
    with pytest.raises(reader.ReaderError) as e:
        reader.read_diff(_pr(), "+ x", scope=SCOPE, client=RaisingClient(billing))
    assert "credit balance" in str(e.value)


def test_score_one_degrades_to_deterministic_when_the_api_is_down(monkeypatch):
    """The end the caller actually sees: a verdict, not an exception, and it
    says why it is a lesser verdict."""
    monkeypatch.setenv("DOUG_READER", "1")
    real = reader.read_diff  # bind before patching, or the lambda calls itself
    monkeypatch.setattr(
        reader, "read_diff",
        lambda pr, diff, *, scope: real(
            pr, diff, scope=scope, client=RaisingClient(RuntimeError("boom"))
        ),
    )
    tier, verdict, rv, _cov = review.score_one(_pr(), "+ x", scope=SCOPE)
    assert tier == "deterministic" and rv is None
    assert any(r.rule == "reader-unavailable" for r in verdict.reasons)


def test_default_client_never_carries_the_sdk_default_timeout(monkeypatch):
    """The SDK defaults to 600s. Both read paths run on Starlette's shared
    sync thread pool, so at that bound one stalled Anthropic connection
    parks a request worker for ten minutes — enough of them and every
    route, /healthz included, queues behind dead reads. The default client
    must always carry our bounded timeout instead.
    """
    import anthropic

    captured = {}

    class Capturing:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = _FakeMessages(INTENT_PAYLOAD, "end_turn")

    monkeypatch.setattr(anthropic, "Anthropic", Capturing)
    # ADR-0029 made the transport a value, and the default is Vertex. Patching
    # anthropic.Anthropic while the reader builds an AnthropicVertex would
    # capture nothing and assert on an empty dict, so the transport this test
    # is about is named rather than inherited. The bound is pinned on BOTH
    # transports by test_both_clients_bound_the_whole_read_not_just_one_attempt.
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_ANTHROPIC)

    monkeypatch.delenv("DOUG_READ_TIMEOUT_S", raising=False)
    reader.read_diff(_pr(), "+ x", scope=SCOPE)
    assert captured["timeout"] == reader.DEFAULT_READ_TIMEOUT_S

    captured.clear()
    monkeypatch.setenv("DOUG_READ_TIMEOUT_S", "45")
    reader.read_with_decisions(_pr(), "+ x", docs=DOCS, scope=SCOPE)
    assert captured["timeout"] == 45.0


# --- What a read cost ----------------------------------------------------
#
# reader.py read response.stop_reason and response.content and threw
# response.usage away, discarding the cost of every read at the one moment
# it is knowable. The cap above is a guess until this data exists; these
# lines are what turns it into a number set from evidence.


def _read_lines(capsys) -> list[str]:
    return [x for x in capsys.readouterr().err.splitlines() if "(paid read)" in x]


def test_a_paid_read_reports_what_it_cost(capsys):
    client = FakeClient(usage=(8123, 612))

    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)

    (line,) = _read_lines(capsys)
    assert "kind=risk" in line
    assert f"scope={SCOPE}" in line
    assert f"model={reader.MODEL}" in line
    assert "in=8123" in line
    assert "out=612" in line


def test_the_two_reads_of_one_pr_report_their_costs_separately(capsys):
    """One PR buys two reads. The roadmap's open question is which half the
    money goes to — the intent read is the one flagged as both uncapped and
    unmetered, and it carries the decision records on top of the same diff,
    so it may well be the expensive one. A single summed line could not
    answer that; two lines, each naming its kind, can.
    """
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient(usage=(8000, 500)))
    reader.read_with_decisions(
        _pr(), "+ x", DOCS,
        scope=SCOPE,
        client=FakeClient(payload=INTENT_PAYLOAD, usage=(9500, 700)),
    )

    risk, intent = _read_lines(capsys)
    assert "kind=risk" in risk and "in=8000" in risk and "out=500" in risk
    assert "kind=intent" in intent and "in=9500" in intent and "out=700" in intent


def test_every_read_line_names_the_model_that_produced_it(capsys):
    """The split this test was written to survive has happened.

    _report_cost used to interpolate the module constant MODEL, which was
    correct only while one model served every call. The verify and
    attribution passes now run MECHANICAL_MODEL, so a line still quoting
    MODEL would name a real model that did not run this read — the exact
    silent meaning-change the original docstring warned about, and
    unfindable afterwards because the string still parses as a model.

    Asserting a literal here rather than reader.MODEL is deliberate: a
    formatting change that dropped `model=` entirely would satisfy an
    f-string-derived assertion against an empty capture.
    """
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient())
    reader.read_with_decisions(
        _pr(), "+ x", DOCS, scope=SCOPE, client=FakeClient(payload=INTENT_PAYLOAD)
    )

    assert all("model=claude-opus-5" in line for line in _read_lines(capsys))


def test_the_mechanical_passes_run_their_own_model_and_say_so(capsys):
    """ADR-0016. verify and attribution are the only paid calls whose output
    is fully validated in code before it can reach a stored row, so a weaker
    model can cost an abstention and nothing else. They run
    MECHANICAL_MODEL; their cost lines must name it.

    The cost line is asserted alongside the request because the two failure
    modes are independent and only one is visible in production: sending
    Sonnet while reporting Opus reads as a working substitution on every
    dashboard and log that exists.
    """
    finding = reader.ReaderFinding(
        category_slug="cap-mismatch",
        description="Meter renders against the wrong cap",
        file="api/doug/check_run.py",
        severity="high",
    )
    verify_client = FakeClient(payload={"checks": []})
    reader.verify_finding(finding, scope="verify:1", client=verify_client)

    diff, cov, reasons = _attr_fixture()
    attr_client = _AttrClient({"attributions": [{"finding": 0, "hunks": [1]}]})
    reader.attribute_findings(reasons, diff, cov, scope="attribution:1", client=attr_client)

    assert verify_client.messages.last_kwargs["model"] == reader.MECHANICAL_MODEL
    assert (
        verify_client.messages.last_kwargs["output_config"]["effort"]
        == reader.MECHANICAL_EFFORT
    )
    assert attr_client.requests[0]["model"] == reader.MECHANICAL_MODEL
    assert attr_client.requests[0]["output_config"]["effort"] == reader.MECHANICAL_EFFORT

    verify_line, attribution_line = _read_lines(capsys)
    assert "kind=verify" in verify_line
    assert "kind=attribution" in attribution_line
    assert all(
        "model=claude-sonnet-5" in line for line in (verify_line, attribution_line)
    )


# --- ADR-0029: the transport moved to Vertex, by direction, unmeasured ---
#
# test_the_risk_read_has_not_moved_to_vertex_before_its_bar_is_run lived here.
# Its docstring named one way to remove it: run ADR-0028's paired study,
# record the result against the four numbers in the bar table, and delete it in
# the PR that lands the Vertex client, citing that result.
#
# That is NOT what happened, and pretending otherwise is the failure the guard
# existed to prevent. The study was never run. Andrew directed the move on
# 2026-08-28 because the Anthropic balance funds the cutover or the study but
# not both, and ADR-0029 records the direction, the reason, and the fact that
# the new instrument era ships governed by nothing. ADR-0018 is the precedent
# for the shape.
#
# The tests below replace it. They pin what IS true — the destination, the
# rollback, the provider label, and the absence of a mapping layer — and none
# of them asserts that any bar was met, because none was.


def test_an_unconfigured_environment_does_not_silently_lose_its_reader(monkeypatch):
    """The deploy names the destination; the default is what everything ELSE
    gets, and those are different jobs.

    An earlier version of this change defaulted to Vertex, so production's
    value was also the fallback on every laptop, script and CI job. Doug
    flagged it (`reader:unsafe-default-flip`): none of those has a Vertex
    region or application default credentials, so the client raises at
    construction and the read falls soft into the deterministic score —
    silently, because that fallback is the contracted behaviour for a stalled
    upstream and says nothing about a misconfiguration.

    Asserted against the literal so DEFAULT_TRANSPORT = TRANSPORT_VERTEX cannot
    make this tautologically true. That production actually runs Vertex is
    pinned separately, on the deploy, by
    test_api_deploy_pins_the_chosen_transport_and_carries_a_region — which is
    where it belongs, because that is the environment configured for it.
    """
    assert reader.DEFAULT_TRANSPORT == "anthropic"

    monkeypatch.delenv("DOUG_READER_TRANSPORT", raising=False)
    assert reader.transport() == reader.TRANSPORT_ANTHROPIC

    for value, expected in (
        ("vertex", reader.TRANSPORT_VERTEX),
        ("anthropic", reader.TRANSPORT_ANTHROPIC),
        ("  Vertex  ", reader.TRANSPORT_VERTEX),
    ):
        monkeypatch.setenv("DOUG_READER_TRANSPORT", value)
        assert reader.transport() == expected, value


def test_an_unreadable_transport_value_falls_back_to_the_default(monkeypatch):
    """A typo must not construct an arbitrary client or crash every read.

    The reader fails soft everywhere else on purpose, and a misspelled env var
    is the one input an operator supplies under pressure — during the rollback
    this constant exists to make possible. Falling back to the default is what
    keeps a typo from becoming an outage.
    """
    for junk in ("", "   ", "bedrock", "vertexai", "anthropic-vertex"):
        monkeypatch.setenv("DOUG_READER_TRANSPORT", junk)
        assert reader.transport() == reader.DEFAULT_TRANSPORT, junk


def test_provider_names_the_api_surface_and_the_two_transports_do_not_pool(monkeypatch):
    """ADR-0028 item 1, which is the cost of the move rather than a detail.

    `provider` names the API surface actually called, not the vendor of the
    weights, so it moves instrument_id and partitions the labelled corpus at
    the cutover. example_pack_eval.py partitions by exactly that hash, so the
    partition is mechanical rather than a matter of discipline — but only while
    the two strings actually differ. Asserting inequality is the whole test:
    equal labels would silently pool two serving stacks, which is the
    inheritance A2 forbids and the cost ADR-0028 chose to pay.
    """
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_VERTEX)
    vertex = reader.provider_name()
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_ANTHROPIC)
    first_party = reader.provider_name()

    assert vertex == "anthropic-vertex"
    assert first_party == "anthropic"
    assert vertex != first_party


def test_the_capture_records_the_transport_that_actually_ran(monkeypatch):
    """The manifest must say which surface produced the row, not which one the
    module was written for.

    `provider` was a hardcoded "anthropic" literal at the risk-read call site
    until ADR-0029. A constant there survives the transport move, reads as
    correct, and quietly pools the two eras in the one corpus that partitions
    on it — the same defect ADR-0027 C3 describes for the mechanical tier.
    """
    recorded: list[str] = []

    monkeypatch.setattr(
        reader.example_pack_capture, "capture_requested", lambda *a, **k: True
    )
    monkeypatch.setattr(
        reader.example_pack_capture, "capture_suppressed", lambda *a, **k: False
    )
    monkeypatch.setattr(
        reader.example_pack_capture,
        "record_attempt",
        lambda **kw: recorded.append(kw["provider"]),
    )

    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_VERTEX)
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient())
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_ANTHROPIC)
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient())

    assert recorded == ["anthropic-vertex", "anthropic"]


def test_pyproject_declares_the_vertex_extra_adr_0028_item_4_requires():
    """ADR-0028 item 4: `anthropic[vertex]` is declared explicitly in
    api/pyproject.toml, so the Vertex client's own dependencies cannot be lost
    to an unrelated dependency change.

    Until #284 the only thing guarding that line was the intent tier: any
    change to pyproject.toml was read against ADR-0027/0028 by the model,
    which might notice the extra going missing. #284's naming rule stopped
    reading dependency bumps against records, and Doug raised it on every
    read of that PR (`deviation:contradicts-ticket`) — correctly: a binding
    requirement had gone from one soft guard to none. This is the hard one.
    A paid read that might notice is replaced by a test that must.

    Both the runtime dependency and the dev group are pinned, because the
    suite imports the SDK too and a dev-only drop would pass CI while the
    image lost the extra.
    """
    import re

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert "[dependency-groups]" in pyproject, (
        "pyproject.toml has no [dependency-groups] table; the dev group moved or was dropped"
    )
    runtime, dev = pyproject.split("[dependency-groups]", 1)
    pattern = re.compile(r'"anthropic\[vertex\]>=')
    assert pattern.search(runtime), (
        "api/pyproject.toml no longer declares anthropic[vertex] as a runtime "
        "dependency; ADR-0028 item 4 requires it"
    )
    assert pattern.search(dev), "the dev group lost anthropic[vertex]"


def test_the_transport_carries_MODEL_verbatim_with_no_mapping_layer():
    """ADR-0028 refuses a transport-specific model mapping by name.

    A mapping is how MODEL comes to say one thing while the wire says another,
    which is the state ADR-0012's freeze exists to make impossible. Vertex
    serves current-generation models under the bare first-party id, so the
    string is identical on both transports and nothing needs translating.

    Source inspection, and crude on purpose — the same treatment the guard this
    block replaced used, for the same reason. A mapping layer would have to
    name MODEL or a model id inside the constructor, so the construction site
    is asserted to name neither. If a dated snapshot is ever pinned the two
    transports stop sharing a string, and that reopens ADR-0028; it does not
    earn a mapping here.
    """
    import inspect

    source = inspect.getsource(reader._build_client)
    body = source.split('"""')[2] if source.count('"""') >= 2 else source
    code = "\n".join(
        line.split("#")[0] for line in body.splitlines() if not line.strip().startswith("#")
    )
    assert "AnthropicVertex(" in code, "the Vertex client is no longer built here"
    # "MODEL" and "claude-" are what a mapping layer must name. A bare "@" was
    # here too and is gone: Doug flagged the over-broad form
    # (`reader:brittle-source-inspection-test`) and a decorator on this function
    # would have tripped it for reasons unrelated to model mapping. A dated
    # snapshot id is caught by "claude-" anyway, since it has to name the model.
    for forbidden in ("MODEL", "claude-"):
        assert forbidden not in code, (
            f"_build_client names {forbidden!r}, which is a model-mapping layer. "
            "ADR-0028 refuses one: MODEL reaches the wire verbatim."
        )


def test_the_mechanical_tier_has_not_left_anthropic_while_the_manifest_cannot_say_so():
    """ADR-0027 C3, made to fail loudly instead of resting on prose.

    ADR-0027 is `accepted`, so the mechanical tier's vendor boundary is open in
    the directory the reader consumes. Three conditions bind before a foreign
    model may serve production traffic, and C3 is the one that is code rather
    than a measurement: WholeInstrumentManifestV0 carries one `provider` and one
    `pinned_model_id`, both describing the risk read, and MECHANICAL_MODEL
    reaches no durable surface but the cost log. So two reads that ran different
    mechanical models hash to the same instrument_id, while ADR-0015 makes
    findings.hunks — the attribution pass's output — part of convergence
    identity, and example_pack_eval.py partitions the corpus by exactly that
    hash.

    Doug flagged the gap as `beyond-ticket` on the signing PR: the record says
    the conditions bind, and nothing made the unenforceable-by-accident state
    fail. This is that guard. It is deliberately crude — a vendor check, not a
    model allowlist — because its whole job is to be impossible to trip over by
    accident and trivial to remove on purpose once #263 lands and the manifest
    can tell two mechanical models apart.

    **It is the only thing holding C1 and C2 as well, and that is deliberate.**
    Doug noted that C1 (re-run ADR-0015's span-verification) and C2 (a recorded
    grounding rate for verify_finding) are prose-only, enforceable in practice
    only by this guard — which the record says can be deleted once #263 lands.
    Correct, so the removal condition below is all three, not one.

    To remove this test: close #263, record C1's replication result against
    ADR-0015's frozen bars, record C2's before-and-after grounding rate, and
    then delete it in the same PR that changes MECHANICAL_MODEL, citing all
    three. Do not relax it to keep a swap green.
    """
    assert reader.MECHANICAL_MODEL.startswith("claude-"), (
        "MECHANICAL_MODEL left Anthropic while WholeInstrumentManifestV0 still "
        "cannot record which mechanical model produced a row (ADR-0027 C3, #263). "
        "Land the manifest change first."
    )


def test_the_two_paid_reads_did_not_follow_the_mechanical_tier_down():
    """The freeze binds the risk read, and ADR-0007 binds the intent read to
    the same instrument. Splitting the model per call makes "unify these two
    constants" look like a tidy-up; this test is what that tidy-up breaks.

    reader.MODEL is asserted against the literal so that setting
    MODEL = MECHANICAL_MODEL cannot make the assertion tautologically true.
    """
    risk = FakeClient()
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=risk)
    intent = FakeClient(payload=INTENT_PAYLOAD)
    reader.read_with_decisions(_pr(), "+ x", DOCS, scope=SCOPE, client=intent)

    assert reader.MODEL == "claude-opus-5" != reader.MECHANICAL_MODEL
    for client in (risk, intent):
        assert client.messages.last_kwargs["model"] == "claude-opus-5"
        assert client.messages.last_kwargs["output_config"]["effort"] == reader.EFFORT


def test_a_read_that_stopped_at_max_tokens_still_reports_its_cost(capsys):
    """The failure that costs the most reports like the ones that cost
    nothing unless this line is emitted before the stop_reason check: a
    max_tokens stop means the model produced every one of MAX_TOKENS output
    tokens and we are billed for all of them, then the read is thrown away.
    Reporting cost on the success path only would hide exactly the reads
    most worth finding."""
    client = FakeClient(stop_reason="max_tokens", usage=(4000, reader.MAX_TOKENS))

    with pytest.raises(reader.ReaderError):
        reader.read_diff(_pr(), "+ x", scope=SCOPE, client=client)

    (line,) = _read_lines(capsys)
    assert f"out={reader.MAX_TOKENS}" in line


def test_a_read_whose_usage_the_sdk_withheld_says_unknown_not_zero(capsys):
    """`in=0 out=0` would sum into a spend total as a free read. These
    lines exist to set the cap from evidence; a fabricated zero is worse
    evidence than an admitted gap."""
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient(usage=None))

    (line,) = _read_lines(capsys)
    assert "in=? out=?" in line
    assert "in=0" not in line


# --- ADR-0002: the reader's frozen prompt is the probe's, verbatim -------

def test_both_clients_bound_the_whole_read_not_just_one_attempt(monkeypatch):
    """Constructing the client is where the bound is applied, and it is the
    half a constants-only test cannot see.

    test_read_timeout_budget_fits_inside_the_cloud_run_timeout checks the
    arithmetic — DEFAULT_READ_TIMEOUT_S x (1 + MAX_READ_RETRIES) < the deployed
    --timeout. It stays green if someone deletes `max_retries=` from the
    constructor, because then the SDK default of 2 applies and the arithmetic
    the test checked describes nothing. Verified: that mutation survives with
    only the arithmetic test in place. This asserts the argument reaches the
    SDK, for both clients — grounding runs inside the same synchronous request
    the risk read does, so _verify_client needs the same bound.

    Both transports are checked. ADR-0029 made the transport a runtime value,
    so "the client" is now two classes, and AnthropicVertex carries the same
    SDK default of max_retries=2 that made this test necessary in the first
    place. Pinning only the live transport would leave the rollback path — the
    one taken while something is already wrong — unbounded.
    """
    import anthropic

    def _capturing(sink):
        def _capture(**kwargs):
            sink.append(kwargs)
            return object()

        return _capture

    for env, attr in (
        (reader.TRANSPORT_ANTHROPIC, "Anthropic"),
        (reader.TRANSPORT_VERTEX, "AnthropicVertex"),
    ):
        seen: list[dict] = []
        monkeypatch.setenv("DOUG_READER_TRANSPORT", env)
        monkeypatch.setattr(anthropic, attr, _capturing(seen))
        reader._client()
        reader._verify_client()

        assert len(seen) == 2, f"{env}: expected both clients to be constructed"
        for kwargs in seen:
            assert kwargs["max_retries"] == reader.MAX_READ_RETRIES, env
            assert kwargs["timeout"] > 0, env


def test_reader_and_probe_share_the_validated_prompt_bytes():
    """ADR-0002 froze six constants byte-identical to scripts/llm_probe.py,
    the module the Phase-1 probes actually validated (AUC 0.687/0.668,
    pre-registered, replicated). llm_probe.py keeps its own independent
    copies (unlike SLUG_MERGES, which it imports from doug.patterns), so
    only a real cross-module comparison can catch the two drifting — at
    which point the live service would be running an unvalidated
    instrument under a validated instrument's claimed AUC.

    ADR-0012 supersedes ADR-0002 and narrowed the freeze to five constants;
    ADR-0018 narrows it again to FOUR. DIFF_BUDGET is governed by a coverage
    bar and EFFORT by a pre-registration, and both are asserted separately
    below as deliberate divergences rather than dropped from the file.

    Dropping an assertion is how a freeze quietly becomes four constants that
    nobody decided on. Each removal here has an ADR and a replacement
    assertion; if you are removing a fifth, write the ADR first."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import llm_probe

    assert reader.SYSTEM == llm_probe.SYSTEM
    assert reader.SCHEMA == llm_probe.SCHEMA
    assert reader.MODEL == llm_probe.MODEL
    assert reader.MAX_TOKENS == llm_probe.MAX_TOKENS


def test_effort_diverges_from_the_probe_on_purpose():
    """ADR-0018, in the shape ADR-0012's divergence already uses.

    The probe stays at the "medium" it actually measured; the shipped reader
    runs "high", which is also the API default the probe's choice sat one step
    below. Asserting BOTH sides is what makes the divergence intentional and
    sized: syncing either constant to the other breaks this test and sends the
    author to ADR-0018 rather than silently re-anchoring the instrument.

    Literals, not a cross-module comparison, for the same reason: `reader.EFFORT
    != llm_probe.EFFORT` would stay green if someone raised the probe too, which
    is precisely the move that destroys the probe's ability to report what it
    measured.

    The consequence this encodes, which ADR-0018 states in full: EFFORT is
    UNMEASURED on this prompt. The pre-registration exists and has not been run,
    so no claim about accuracy attaches to this value.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import llm_probe

    assert reader.EFFORT == "high"
    assert llm_probe.EFFORT == "medium"
    assert reader.EFFORT != llm_probe.EFFORT
    # The mechanical tier did not follow. Its calls were never in the probe and
    # never in the freeze, so they have no divergence to record — but a blanket
    # "raise effort everywhere" edit would sweep them up, and this is where that
    # gets caught.
    assert reader.MECHANICAL_EFFORT == "medium"


def test_the_paths_that_inherit_the_raised_effort_are_enumerated():
    """EFFORT is shared, so raising it moves every consumer at once.

    Doug flagged that on b767f2e: read_with_decisions "and any other consumer of
    the shared EFFORT constant silently inherit the raise; only MECHANICAL_EFFORT
    is pinned." ADR-0018 names read_with_decisions. Nothing pinned the SET, so a
    future call site could join it and inherit an unmeasured value with no ADR
    and no test noticing.

    This enumerates the consumers by reading the module source, so adding a
    fourth `"effort": EFFORT` site fails here and sends the author to ADR-0018.
    Source inspection rather than call tracing because the point is coverage of
    every site, including ones no test exercises.
    """
    import inspect
    import re as _re

    source = inspect.getsource(reader)
    frozen_sites = _re.findall(r'"effort": (\w+)', source)

    # Three consumers of the raised constant: the risk read, the intent read,
    # and the Example Pack capture manifest that records what ran. Two of the
    # mechanical tier, unraised.
    assert frozen_sites.count("EFFORT") == 2, (
        f"expected 2 request sites on the raised EFFORT, found {frozen_sites}"
        " — a new consumer inherits an unmeasured value; see ADR-0018"
    )
    assert frozen_sites.count("MECHANICAL_EFFORT") == 2
    # The capture manifest passes it positionally, not as a dict key, so it is
    # asserted separately rather than being silently absent from the count.
    assert "effort=EFFORT" in source


def test_diff_budget_diverges_from_the_probe_on_purpose():
    """ADR-0012. The probe's DIFF_BUDGET stays at the 30,000 it actually
    measured; the shipped reader reads more. Asserting BOTH sides pins the
    divergence as intentional and sized: anyone who 'fixes the drift' by
    syncing either constant to the other breaks this test and gets sent to
    ADR-0012 rather than silently re-anchoring the instrument.

    The consequence this encodes, which ADR-0012 states in full: AUC
    0.687 sentry / 0.668 grafana describe the 30,000-char configuration,
    not what ships."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import llm_probe

    assert reader.DIFF_BUDGET == 100_000
    assert llm_probe.DIFF_BUDGET == 30_000
    assert reader.DIFF_BUDGET > llm_probe.DIFF_BUDGET


def test_prompt_hash_is_stable_and_changes_with_the_frozen_bytes(monkeypatch):
    """A verdict's prompt_hash is the "these numbers are about the same
    instrument" anchor for receipts and the pre-registration document —
    it has to actually move when SYSTEM/SCHEMA move, or a silent prompt
    edit would keep stamping old verdicts' hash on new-instrument reads."""
    import hashlib

    assert reader.PROMPT_HASH == hashlib.sha256(
        (reader.SYSTEM + repr(reader.SCHEMA)).encode()
    ).hexdigest()

    monkeypatch.setattr(reader, "SYSTEM", reader.SYSTEM + " ")
    assert reader._compute_prompt_hash() != reader.PROMPT_HASH


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_show(ref_path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "show", ref_path],
            cwd=_REPO_ROOT, capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.decode("utf-8")


def test_a_citation_is_re_derivable_by_a_third_party_with_git_and_sed():
    """The receipt has to survive leaving this process, or it establishes nothing.

    D6 says a citation is `path@sha#Lstart-Lend` + sha256 so someone else can get
    the same bytes. That claim is only worth anything if a DIFFERENT tool reaches
    the same hash — so this fetches the blob with git, cites a range from it, then
    re-derives the same range with sed and compares. If cite() ever drifts in how
    it slices (0-based, exclusive end, stripped newlines), the two disagree and
    this fails, which is the whole point.

    A locator without the ref is what makes this impossible, which is why
    Citation carries head_sha: `git show <path>` alone has nothing to resolve.
    """
    rel = "api/doug/models.py"
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, capture_output=True
    )
    if sha.returncode != 0:
        pytest.skip("not a git checkout")
    head_sha = sha.stdout.decode().strip()

    text = _git_show(f"{head_sha}:{rel}")
    if text is None:
        pytest.skip(f"{rel} is not committed at HEAD")

    c = reader.cite(path=rel, head_sha=head_sha, text=text, line_start=10, line_end=14)
    assert c is not None
    assert c.locator() == f"{rel}@{head_sha}#L10-L14"

    # The third party's route: same blob, different tool, no shared code.
    piped = subprocess.run(
        f"git show {head_sha}:{rel} | sed -n '10,14p'",
        cwd=_REPO_ROOT, shell=True, capture_output=True, check=True,
    ).stdout
    assert c.sha256 == hashlib.sha256(piped).hexdigest()


def test_an_off_by_one_range_does_not_hash_the_same():
    """A receipt that survives the wrong range is not a receipt.

    This is the property that makes a fabricated or mis-aimed citation a no-op
    instead of a false ground: the honor check compares hashes, so it can only
    pass for the exact bytes claimed.
    """
    text = "alpha\nbravo\ncharlie\ndelta\n"
    right = reader.cite(path="f.py", head_sha="a" * 40, text=text, line_start=2, line_end=3)
    wide = reader.cite(path="f.py", head_sha="a" * 40, text=text, line_start=2, line_end=4)
    shifted = reader.cite(path="f.py", head_sha="a" * 40, text=text, line_start=1, line_end=2)
    assert right is not None and wide is not None and shifted is not None
    assert right.sha256 != wide.sha256
    assert right.sha256 != shifted.sha256
    assert right.sha256 == hashlib.sha256(b"bravo\ncharlie\n").hexdigest()


def test_an_impossible_range_leaves_the_finding_ungrounded():
    """A bad line number must be a no-op, never an exception.

    design-lock L1: the model picks where to look and code checks the pick.
    Raising here would turn a hallucinated line number into a failed review
    instead of an ungrounded finding, which inverts the safety property — the
    finding still ships, it just carries no citation.
    """
    text = "alpha\nbravo\n"
    assert reader.cite(path="f.py", head_sha="a" * 40, text=text, line_start=0, line_end=1) is None
    assert reader.cite(path="f.py", head_sha="a" * 40, text=text, line_start=2, line_end=1) is None
    assert reader.cite(path="f.py", head_sha="a" * 40, text=text, line_start=1, line_end=99) is None
    assert reader.cite(path="f.py", head_sha="a" * 40, text="", line_start=1, line_end=1) is None


def test_the_verify_schema_cannot_express_a_conclusion():
    """The model must not be able to say a finding is wrong, at the type level.

    Not defensiveness about hallucination — a measured failure. On PR #107 a
    refutation of reader:serialization-contract quoted models.py's exclude=True
    line: byte-matching, grep-re-derivable, factually TRUE, and the refutation
    was still wrong, because exclude is honored by model_dump/FastAPI and by
    nothing else. A true quote carried a false conclusion.

    So the guarantee has to be structural, not a rule someone remembers. If a
    `refuted` field is ever added, or extra="forbid" is loosened, a conclusion
    becomes expressible and this fails.
    """
    assert "refuted" not in repr(reader.VERIFY_SCHEMA)
    assert reader.VERIFY_SCHEMA["additionalProperties"] is False
    item = reader.VERIFY_SCHEMA["properties"]["checks"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["properties"]) == {
        "file", "line_start", "line_end", "quoted_text", "predicate",
    }
    with pytest.raises(ValidationError):
        reader.VerifyResponse.model_validate(
            {"checks": [{
                "file": "f.py", "line_start": 1, "line_end": 1,
                "quoted_text": "X = 1", "predicate": "constant_value_is",
                "refuted": True,
            }]}
        )


def test_declining_to_name_a_location_is_the_natural_answer():
    """Returning nothing has to be cheap and valid, or the model will invent.

    An empty list means the finding rests on the diff, or names an absence, or
    could not be located. All three leave the finding published and ungrounded,
    which is the only safe default: nothing in this tier may remove a finding.
    """
    assert reader.VerifyResponse.model_validate({"checks": []}).checks == []
    assert reader.VerifyResponse().checks == []


def test_the_predicate_vocabulary_is_one_member_and_permanent():
    """A frozen prompt makes every predicate name permanent, so spending one is
    a decision with no take-backs.

    Four candidates were cut because each scored 0/8 against the only
    rater-independent evidence in the repo: name_is_runtime_imported,
    column_exists_in_live_schema, path_does_not_exist, symbol_defined_in_file.
    constant_value_is is the one that recovers a real finding. Adding another
    is a new frozen prompt and a new hash — not an edit to this one, which is
    what this pins.
    """
    enum = reader.VERIFY_SCHEMA["properties"]["checks"]["items"]["properties"]["predicate"]["enum"]
    assert enum == ["constant_value_is"]
    with pytest.raises(ValidationError):
        reader.VerifyCheck.model_validate({
            "file": "f.py", "line_start": 1, "line_end": 1,
            "quoted_text": "x", "predicate": "path_does_not_exist",
        })


def test_the_verify_tier_does_not_move_the_shipped_prompt_hash():
    """ADR-0012's five constants stay byte-identical to the probe, and
    PROMPT_HASH is sha256(SYSTEM + repr(SCHEMA)).

    A second frozen prompt is exactly what ADR-0002 said to do instead of
    editing the first ("anything that adds input to the model must occupy a
    separate frozen prompt"). This pins that the separation actually held:
    verdicts written before and after this tier landed stay comparable on
    prompt identity.
    """
    assert reader.PROMPT_HASH == hashlib.sha256(
        (reader.SYSTEM + repr(reader.SCHEMA)).encode()
    ).hexdigest()
    assert reader.VERIFY_SYSTEM not in reader.SYSTEM
    assert "checks" not in repr(reader.SCHEMA)


def test_the_verify_prompt_hash_changes_with_its_own_frozen_bytes(monkeypatch):
    """The intent tier is frozen by prose with no test behind it; this one is not.

    A hash only anchors "these results came from this instrument" if editing the
    instrument moves it. Without this, VERIFY_SYSTEM could be reworded in a diff
    that reads as a copy change while every receipt kept claiming the old
    identity — the failure ADR-0012 wrote its freeze to prevent.
    """
    before = hashlib.sha256(
        (reader.VERIFY_SYSTEM + repr(reader.VERIFY_SCHEMA)).encode()
    ).hexdigest()
    assert before == reader.VERIFY_PROMPT_HASH

    after = hashlib.sha256(
        (reader.VERIFY_SYSTEM + " Also consider style." + repr(reader.VERIFY_SCHEMA)).encode()
    ).hexdigest()
    assert after != reader.VERIFY_PROMPT_HASH


# --- attribution tier (ADR-0015; Walked Out commit 7) -----------------------


class _AttrResponse:
    def __init__(self, payload, stop_reason="end_turn"):
        import json as _json

        class _Block:
            type = "text"

            def __init__(self, text):
                self.text = text

        self.content = [_Block(_json.dumps(payload))]
        self.stop_reason = stop_reason
        self.usage = None


class _AttrClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self._payload = payload
        self._stop = stop_reason
        self.requests = []

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **request):
            self._outer.requests.append(request)
            return _AttrResponse(self._outer._payload, self._outer._stop)

    @property
    def messages(self):
        return self._Messages(self)


def _attr_fixture():
    from doug.models import Reason

    patch_a = "@@ -1,2 +1,2 @@\n-x\n+y\n"
    patch_b = "@@ -9,2 +9,2 @@\n-p\n+q\n@@ -20,2 +20,2 @@\n-r\n+s\n"
    diff = reader.CHUNK_SEPARATOR.join([
        reader.diff_chunk("a.py", "modified", 1, 1, patch_a),
        reader.diff_chunk("b.py", "modified", 2, 2, patch_b),
    ])
    cov = reader.coverage(diff)
    reasons = [
        Reason(rule="reader:race-condition", label="finding on a", weight=0.0,
               severity="high", file="a.py"),
        Reason(rule="reader:logic-error", label="finding on b", weight=0.0,
               severity="low", file="b.py"),
        Reason(rule="size-large", label="not a reader finding", weight=0.4),
    ]
    return diff, cov, reasons


def test_attribute_findings_converts_valid_picks_to_stored_hashes():
    """The model picks numbers from an enumerated list; code owns the
    conversion to content hashes — the exact task shape the pre-registered
    span-verification pass validated."""
    diff, cov, reasons = _attr_fixture()
    client = _AttrClient({"attributions": [
        {"finding": 0, "hunks": [1]},
        {"finding": 1, "hunks": [2]},
    ]})
    n = reader.attribute_findings(reasons, diff, cov, scope="attribution:1", client=client)
    assert n == 2
    assert reasons[0].hunks == [cov.hunks["a.py"][0]]
    assert reasons[1].hunks == [cov.hunks["b.py"][1]]
    assert reasons[2].hunks is None
    (request,) = client.requests
    assert request["system"] == reader.ATTRIBUTION_SYSTEM
    assert "FINDING id=0" in request["messages"][0]["content"]


def test_attribute_findings_abstention_and_bad_picks_store_nothing():
    """An empty list is the model saying cannot-tell; an out-of-range number
    is a failed validation contract. Both leave hunks=None — the classifier
    reads that as an abstention, never a guess."""
    diff, cov, reasons = _attr_fixture()
    client = _AttrClient({"attributions": [
        {"finding": 0, "hunks": []},
        {"finding": 1, "hunks": [9]},
    ]})
    n = reader.attribute_findings(reasons, diff, cov, scope="attribution:1", client=client)
    assert n == 0
    assert reasons[0].hunks is None
    assert reasons[1].hunks is None


def test_attribute_findings_fails_soft_on_transport_and_stop():
    diff, cov, reasons = _attr_fixture()

    class _Boom:
        class messages:
            @staticmethod
            def create(**_):
                raise RuntimeError("transport down")

    assert reader.attribute_findings(reasons, diff, cov, scope="attribution:1", client=_Boom()) == 0
    stopped = _AttrClient({"attributions": []}, stop_reason="max_tokens")
    assert reader.attribute_findings(reasons, diff, cov, scope="attribution:1", client=stopped) == 0
    assert all(r.hunks is None for r in reasons)


def test_attribute_findings_no_call_without_candidates():
    """Deterministic-only verdicts and uncovered files buy no model call."""
    from doug.models import Reason

    diff, cov, _ = _attr_fixture()
    client = _AttrClient({"attributions": []})
    n = reader.attribute_findings(
        [Reason(rule="size-large", label="x", weight=0.4)], diff, cov,
        scope="attribution:1", client=client,
    )
    assert n == 0
    assert client.requests == []


def test_attribution_prompt_pair_is_frozen_separately():
    """Its own instrument: the risk read's PROMPT_HASH must not move when the
    attribution pair changes, and vice versa."""
    assert reader.ATTRIBUTION_PROMPT_HASH != reader.PROMPT_HASH
    import hashlib as _h

    assert reader.ATTRIBUTION_PROMPT_HASH == _h.sha256(
        (reader.ATTRIBUTION_SYSTEM + repr(reader.ATTRIBUTION_SCHEMA)).encode()
    ).hexdigest()


# --- Workload Identity Federation ------------------------------------------


def _clear_federation(monkeypatch):
    for name in (
        reader.FEDERATION_RULE_ENV,
        reader.FEDERATION_ORG_ENV,
        reader.FEDERATION_SERVICE_ACCOUNT_ENV,
        reader.FEDERATION_WORKSPACE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _set_federation(monkeypatch, *, workspace=True):
    # A mounted key makes federation_configured() False by design (ADR-0030's
    # rollback), so a developer machine or runner with ANTHROPIC_API_KEY
    # exported would fail every federation test spuriously. Doug caught it
    # (`reader:test-env-leakage`); cleared here so no caller has to remember.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv(reader.FEDERATION_RULE_ENV, "fdrl_test")
    monkeypatch.setenv(reader.FEDERATION_ORG_ENV, "org-test")
    monkeypatch.setenv(reader.FEDERATION_SERVICE_ACCOUNT_ENV, "svac_test")
    if workspace:
        monkeypatch.setenv(reader.FEDERATION_WORKSPACE_ENV, "wrkspc_test")
    else:
        monkeypatch.delenv(reader.FEDERATION_WORKSPACE_ENV, raising=False)


def test_federation_needs_every_id_not_any_of(monkeypatch):
    """A half-configured federation must read as NOT configured.

    Any-of would build a client that raises at the exchange, and every read
    would fail soft into the deterministic score — the silent death this
    module's alerting exists to catch, caused by a dropped env var rather than
    an outage. Absent an id, the honest answer is that this environment was
    not configured for federation.
    """
    _clear_federation(monkeypatch)
    assert reader.federation_configured() is False

    required = (
        reader.FEDERATION_RULE_ENV,
        reader.FEDERATION_ORG_ENV,
        reader.FEDERATION_SERVICE_ACCOUNT_ENV,
    )
    for omitted in required:
        _set_federation(monkeypatch)
        monkeypatch.delenv(omitted, raising=False)
        assert reader.federation_configured() is False, omitted

    # The workspace id is NOT one of them: the rule is scoped to a single
    # workspace, so the exchange does not need it.
    _set_federation(monkeypatch, workspace=False)
    assert reader.federation_configured() is True

    _set_federation(monkeypatch)
    assert reader.federation_configured() is True


def test_the_first_party_client_federates_when_configured(monkeypatch):
    """The credential fork, asserted on what actually reaches the SDK."""
    import anthropic

    captured: dict = {}

    class Capturing:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", Capturing)
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_ANTHROPIC)
    _set_federation(monkeypatch)

    reader._build_client(90.0)

    credentials = captured.get("credentials")
    assert isinstance(credentials, anthropic.WorkloadIdentityCredentials)
    assert captured["timeout"] == 90.0
    assert captured["max_retries"] == reader.MAX_READ_RETRIES
    # No api_key is passed even as None: the key path and the federation path
    # are alternatives, and the SDK would prefer a key over these credentials.
    assert "api_key" not in captured


def test_the_first_party_client_uses_a_key_when_federation_is_absent(monkeypatch):
    """Unconfigured environments — a laptop, a script, CI — keep the old path.

    Same posture as DEFAULT_TRANSPORT staying `anthropic`: the deploy is
    configured for federation and nothing else is, so nothing else may quietly
    depend on it.
    """
    import anthropic

    captured: dict = {}

    class Capturing:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", Capturing)
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_ANTHROPIC)
    _clear_federation(monkeypatch)

    reader._build_client(90.0)

    assert "credentials" not in captured
    assert captured["timeout"] == 90.0


@pytest.mark.parametrize(
    ("location", "host"),
    [
        ("us", "aiplatform.us.rep.googleapis.com"),
        ("eu", "aiplatform.eu.rep.googleapis.com"),
        ("global", "aiplatform.googleapis.com"),
        ("us-east5", "us-east5-aiplatform.googleapis.com"),
    ],
)
def test_the_installed_sdk_addresses_the_multi_region_hosts_the_preflight_probes(
    location, host
):
    """CLOUD_ML_REGION=us has to mean the same thing to the SDK and to the
    deploy gate, or the gate proves a route the service never calls.

    Claude 5 lineage quota is served on the `us`/`eu` multi-region and
    `global` endpoints only (#274), and those are not `<name>-aiplatform`
    hosts. `vertex_host` in deploy/gcp.sh carries the same table as the SDK;
    this pins the SDK half against the INSTALLED version, so an SDK downgrade
    that predates multi-region support fails here rather than as every read
    falling soft on a DNS miss. The other half is
    test_the_preflight_probes_the_host_the_sdk_will_call.
    """
    import anthropic

    client = anthropic.AnthropicVertex(region=location, project_id="p", access_token="t")
    assert str(client.base_url).startswith(f"https://{host}/v1")


def test_federation_does_not_reach_the_vertex_transport(monkeypatch):
    """Two orthogonal facts, and the surface wins.

    Vertex authenticates with application default credentials; a federation
    rule says nothing about it. If both are configured — which production is,
    for the duration of the transport migration — the transport choice decides,
    and federation is simply not consulted.
    """
    import anthropic

    built: dict = {}

    class CapturingVertex:
        def __init__(self, **kwargs):
            built.update(kwargs)

    def _fail(**kwargs):  # pragma: no cover - asserted by not being called
        raise AssertionError("the first-party client was built on the Vertex transport")

    monkeypatch.setattr(anthropic, "AnthropicVertex", CapturingVertex)
    monkeypatch.setattr(anthropic, "Anthropic", _fail)
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_VERTEX)
    _set_federation(monkeypatch)

    reader._build_client(90.0)

    assert built["max_retries"] == reader.MAX_READ_RETRIES


def test_the_identity_token_is_fetched_fresh_for_every_exchange(monkeypatch):
    """A callable, never a cached string or a file.

    Google's tokens last about an hour, and nothing on Cloud Run rewrites a
    token file, so the provider has to be re-invocable rather than read once.
    Pinned by calling it twice and requiring two fetches.

    This docstring used to say Google's tokens carry a single-use `jti` and
    that a replayed token is rejected. That is wrong — the Google identity
    token documented for this path has no `jti` — and it was corrected in
    reader.py while this copy stood, which is the one-sided-amendment defect
    this repository keeps re-learning (Doug: `reader:stale-documentation`).
    """
    import google.oauth2.id_token

    calls: list = []

    def _fetch(request, audience):
        calls.append(audience)
        return f"jwt-{len(calls)}"

    monkeypatch.setattr(google.oauth2.id_token, "fetch_id_token", _fetch)

    assert reader._google_identity_token() == "jwt-1"
    assert reader._google_identity_token() == "jwt-2"
    assert calls == [reader.FEDERATION_AUDIENCE] * 2
    # The audience is matched exactly by the federation rule; a drift here is
    # a jwt_audience_mismatch on every read.
    assert reader.FEDERATION_AUDIENCE == "https://api.anthropic.com"


def test_a_mounted_key_wins_so_the_rollback_actually_rolls_back(monkeypatch):
    """ADR-0030 decision 4, pinned on the behaviour rather than the prose.

    The SDK ranks an explicit `credentials=` constructor argument ABOVE
    ANTHROPIC_API_KEY. A client built with federation credentials therefore
    ignores a mounted key completely — which would make the documented
    emergency rollback (`--update-secrets ANTHROPIC_API_KEY=...` on the running
    service) a no-op, reached for during an incident, appearing to work and
    changing nothing. Doug caught the gap between the record and the code
    (`beyond-ticket` on 250c10e).

    So the federation branch defers to a mounted key, and this is the test that
    says the runbook is true.
    """
    import anthropic

    captured: dict = {}

    class Capturing:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", Capturing)
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_ANTHROPIC)
    _set_federation(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-rollback")

    assert reader.federation_configured() is False
    reader._build_client(90.0)
    assert "credentials" not in captured, (
        "a mounted key was ignored, so ADR-0030's rollback does nothing"
    )

    # And removing it again returns the service to federation with no deploy,
    # which is the other half of the same one-command story.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured.clear()
    reader._build_client(90.0)
    assert isinstance(
        captured.get("credentials"), anthropic.WorkloadIdentityCredentials
    )


def test_the_federation_call_matches_the_installed_sdk(monkeypatch):
    """The contract with the SDK, checked against the SDK and not a stub.

    Every other federation test monkeypatches `anthropic.Anthropic` with a
    **kwargs stub, so none of them would notice if `credentials` stopped being
    a constructor parameter or a WorkloadIdentityCredentials field were
    renamed — the client would raise at construction in production and every
    read would fail soft, which is the unverified-external-contract shape that
    earned #275 (Doug: `reader:untested-external-api-contract` on 250c10e).

    Constructing the credentials object is offline: nothing is exchanged until
    a request is made, so this costs no call and needs no network.
    """
    import inspect

    import anthropic

    assert "credentials" in inspect.signature(anthropic.Anthropic.__init__).parameters

    credentials = anthropic.WorkloadIdentityCredentials(
        identity_token_provider=lambda: "jwt",
        federation_rule_id="fdrl_test",
        organization_id="org-test",
        service_account_id="svac_test",
        workspace_id="wrkspc_test",
    )
    assert credentials is not None

    # The real client, built by the real code path, with only the token
    # provider stubbed out. Reaching construction at all proves the kwargs
    # this module sends are the kwargs the SDK accepts.
    monkeypatch.setenv("DOUG_READER_TRANSPORT", reader.TRANSPORT_ANTHROPIC)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _set_federation(monkeypatch)
    monkeypatch.setattr(reader, "_google_identity_token", lambda: "jwt")

    client = reader._build_client(90.0)
    assert isinstance(client, anthropic.Anthropic)


# --- ADR-0027 C3: the manifest names the mechanical tier -------------------


def _captured_manifest_kwargs(monkeypatch) -> dict:
    """Run one risk read with capture on and return record_attempt's kwargs."""
    seen: dict = {}
    monkeypatch.setattr(
        reader.example_pack_capture, "capture_requested", lambda *a, **k: True
    )
    monkeypatch.setattr(
        reader.example_pack_capture, "capture_suppressed", lambda *a, **k: False
    )
    monkeypatch.setattr(
        reader.example_pack_capture, "record_attempt", lambda **kw: seen.update(kw)
    )
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient())
    return seen


def test_a_mechanical_model_change_moves_instrument_id(monkeypatch):
    """ADR-0027 C3, end to end and the reason the condition exists.

    Before this, two reads that ran different mechanical models produced the
    same instrument_id. That would be harmless if the mechanical passes were
    decorative. ADR-0015 makes attribute_findings' validated output part of
    convergence identity — code turns the model's picks into content hashes on
    findings.hunks — and example_pack_eval.py partitions the corpus by exactly
    that hash. So a swap changed what landed in the data while leaving the hash
    that separates instrument eras unmoved, and the two populations pooled with
    nothing in the data saying they should not.

    Asserted through a real read rather than by constructing two manifests,
    because the defect was never in the model — it was that the reader never
    told the manifest. A manifest-only test passes while reader.py keeps the
    tier to itself, which is precisely the state this replaces.
    """
    from doug.example_pack import WholeInstrumentManifestV0, sha256_hex

    def manifest_for(kwargs) -> WholeInstrumentManifestV0:
        return WholeInstrumentManifestV0(
            provider=kwargs["provider"],
            pinned_model_id=kwargs["model"],
            max_output_tokens=kwargs["max_output_tokens"],
            effort=kwargs["effort"],
            inference_parameters=kwargs["inference_parameters"],
            mechanical_parameters=kwargs["mechanical_parameters"],
            system_prompt_sha256=sha256_hex(kwargs["system_prompt_bytes"]),
            output_schema_sha256=sha256_hex(kwargs["output_schema_bytes"]),
            diff_budget=kwargs["diff_budget"],
            read_order="tier",
            input_policy_version=reader.INPUT_POLICY_VERSION,
            coverage_policy_version=reader.COVERAGE_POLICY_VERSION,
            verifier_versions=(),
            tool_versions=(),
            failure_policy_version="reader-fallback-v0",
            publication_policy_version="neutral-check-v0",
            application_revision=None,
            runtime_revision=None,
            attempt_kind="risk",
        )

    before = manifest_for(_captured_manifest_kwargs(monkeypatch))
    monkeypatch.setattr(reader, "MECHANICAL_MODEL", "some-other-model")
    after = manifest_for(_captured_manifest_kwargs(monkeypatch))

    assert before.instrument_id() != after.instrument_id(), (
        "the mechanical model changed and instrument_id did not move — "
        "two mechanical eras would pool in a corpus partitioned by that hash"
    )


def test_a_mechanical_effort_change_moves_instrument_id_too(monkeypatch):
    """ADR-0027 item 3 lets a vendor fork own its own parameter names, so the
    model is not the only thing that can change. Pinning only the model would
    let a request-shape change ride along invisibly."""
    before = _captured_manifest_kwargs(monkeypatch)["mechanical_parameters"]
    monkeypatch.setattr(reader, "MECHANICAL_EFFORT", "high")
    after = _captured_manifest_kwargs(monkeypatch)["mechanical_parameters"]

    assert before != after


def test_the_manifest_matches_what_the_mechanical_requests_actually_send():
    """The manifest describes configuration, not a captured request, because
    attribution runs after the read whose manifest it lands in. This is what
    keeps that honest.

    Without it the manifest could name claude-sonnet-5 while the request dicts
    sent something else, and the resulting instrument_id would be a confident
    description of a tier that never ran — worse than the missing field it
    replaces, because it looks answered.
    """
    finding = reader.ReaderFinding(
        category_slug="cap-mismatch",
        description="Meter renders against the wrong cap",
        file="api/doug/check_run.py",
        severity="high",
    )
    verify_client = FakeClient(payload={"checks": []})
    reader.verify_finding(finding, scope="verify:1", client=verify_client)

    diff, cov, reasons = _attr_fixture()
    attr_client = _AttrClient({"attributions": [{"finding": 0, "hunks": [1]}]})
    reader.attribute_findings(reasons, diff, cov, scope="attribution:1", client=attr_client)

    declared = {p.name: p.version for p in reader.mechanical_parameters()}
    sent = {
        "verify_finding.model": verify_client.messages.last_kwargs["model"],
        "verify_finding.effort": verify_client.messages.last_kwargs["output_config"]["effort"],
        "attribute_findings.model": attr_client.requests[0]["model"],
        "attribute_findings.effort": attr_client.requests[0]["output_config"]["effort"],
    }

    assert declared == sent, (
        "the manifest's mechanical entries disagree with the requests actually "
        "built; instrument_id would describe a tier that never ran"
    )


def test_the_two_mechanical_passes_are_named_separately():
    """ADR-0027 permits verify and attribution to run different models, and a
    single combined entry would hide that the day they do. #263 left the choice
    open; naming them separately is the answer, and this is what makes a later
    collapse into one entry a deliberate edit rather than a tidy-up."""
    names = {p.name for p in reader.mechanical_parameters()}
    assert names == {
        "verify_finding.model",
        "verify_finding.effort",
        "attribute_findings.model",
        "attribute_findings.effort",
    }
