import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from doug import reader
from doug.api import app
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
    def __init__(self, payload: dict | None, stop_reason: str = "end_turn"):
        self._payload = payload
        self._stop_reason = stop_reason
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        text = json.dumps(self._payload) if self._payload is not None else ""
        block = SimpleNamespace(type="text", text=text)
        return SimpleNamespace(content=[block], stop_reason=self._stop_reason)


class FakeClient:
    def __init__(self, payload: dict | None = PAYLOAD, stop_reason: str = "end_turn"):
        self.messages = _FakeMessages(payload, stop_reason)


def _pr(**kw) -> PRMetadata:
    base = dict(number=7, title="Add cache", author="dev", files=["cache.py"])
    base.update(kw)
    return PRMetadata.model_validate(base)


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv("DOUG_READER", raising=False)
    assert not reader.enabled()
    monkeypatch.setenv("DOUG_READER", "1")
    assert reader.enabled()


def test_read_diff_parses_and_sends_schema():
    client = FakeClient()
    rv = reader.read_diff(_pr(), "+ cache[k] = v", client=client)
    assert rv.risk_score == 62
    assert rv.findings[0].category_slug == "race-condition"
    kw = client.messages.last_kwargs
    assert kw["model"] == reader.MODEL
    assert kw["system"] == reader.SYSTEM
    assert kw["output_config"]["format"]["schema"] == reader.SCHEMA
    assert "Add cache" in kw["messages"][0]["content"]


def test_read_diff_truncates_at_budget():
    client = FakeClient()
    reader.read_diff(_pr(), "x" * (reader.DIFF_BUDGET + 500), client=client)
    body = client.messages.last_kwargs["messages"][0]["content"]
    assert "[diff truncated at budget]" in body
    assert len(body) < reader.DIFF_BUDGET + 300


def test_read_diff_raises_on_refusal():
    with pytest.raises(reader.ReaderError):
        reader.read_diff(_pr(), "+ x", client=FakeClient(stop_reason="refusal"))


def test_verdict_mapping_and_threshold():
    rv = reader.ReaderVerdict.model_validate(PAYLOAD)
    v = reader.verdict_from_reader(rv)
    assert v.band is Band.FLAGGED  # 62 >= default threshold 30
    assert v.score == 0.62
    assert v.reasons[0].rule == "reader:race-condition"

    low = reader.ReaderVerdict.model_validate({**PAYLOAD, "risk_score": 12, "findings": []})
    assert reader.verdict_from_reader(low).band is Band.CLEARED


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

    def spy(pr, diff, client=None):
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
    fake = lambda pr, diff, client=None: reader.ReaderVerdict.model_validate(PAYLOAD)  # noqa: E731
    monkeypatch.setattr(reader, "read_diff", fake)
    r = _authed_read()
    assert r.status_code == 200
    body = r.json()
    assert body["band"] == "flagged"
    assert body["reasons"][0]["rule"] == "reader:race-condition"


def test_endpoint_falls_back_loudly_on_reader_failure(monkeypatch):
    monkeypatch.setenv("DOUG_API_TOKEN", TOKEN)
    monkeypatch.setenv("DOUG_READER", "1")

    def boom(pr, diff, client=None):
        raise reader.ReaderError("api down")

    monkeypatch.setattr(reader, "read_diff", boom)
    r = _authed_read()
    assert r.status_code == 200
    assert "reader-unavailable" in {x["rule"] for x in r.json()["reasons"]}


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
        reader.read_diff(_pr(), "+ x", client=RaisingClient(billing))
    assert "credit balance" in str(e.value)


def test_score_one_degrades_to_deterministic_when_the_api_is_down(monkeypatch):
    """The end the caller actually sees: a verdict, not an exception, and it
    says why it is a lesser verdict."""
    from doug import review

    monkeypatch.setenv("DOUG_READER", "1")
    real = reader.read_diff  # bind before patching, or the lambda calls itself
    monkeypatch.setattr(
        reader, "read_diff",
        lambda pr, diff: real(pr, diff, client=RaisingClient(RuntimeError("boom"))),
    )
    tier, verdict, rv, _cov = review.score_one(_pr(), "+ x")
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
    payload = {**PAYLOAD, "intent_alignment": 90, "deviation_findings": []}

    class Capturing:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = _FakeMessages(payload, "end_turn")

    monkeypatch.setattr(anthropic, "Anthropic", Capturing)

    monkeypatch.delenv("DOUG_READ_TIMEOUT_S", raising=False)
    reader.read_diff(_pr(), "+ x")
    assert captured["timeout"] == reader.DEFAULT_READ_TIMEOUT_S

    captured.clear()
    monkeypatch.setenv("DOUG_READ_TIMEOUT_S", "45")
    reader.read_with_decisions(
        _pr(), "+ x", docs=[SimpleNamespace(id="ADR-1", title="t", body="b")],
    )
    assert captured["timeout"] == 45.0


# --- ADR-0002: the reader's frozen prompt is the probe's, verbatim -------

def test_reader_and_probe_share_the_validated_prompt_bytes():
    """ADR-0002 claims reader.py is byte-identical to scripts/llm_probe.py,
    the module the Phase-1 probes actually validated (AUC 0.687/0.668,
    pre-registered, replicated). Until now nothing checked that — the only
    existing assertion near this compared reader.py to itself (read_diff
    passes reader.SYSTEM to the API call; of course it equals reader.SYSTEM).
    llm_probe.py keeps its own independent copies of these constants
    (unlike SLUG_MERGES, which the probe imports from doug.patterns), so
    only a real cross-module comparison can catch the two drifting —
    at which point the live service would be running an unvalidated
    instrument under a validated instrument's claimed AUC."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import llm_probe

    assert reader.SYSTEM == llm_probe.SYSTEM
    assert reader.SCHEMA == llm_probe.SCHEMA
    assert reader.DIFF_BUDGET == llm_probe.DIFF_BUDGET
    assert reader.MODEL == llm_probe.MODEL


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
