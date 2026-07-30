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


def test_endpoint_deterministic_when_reader_off(monkeypatch):
    monkeypatch.delenv("DOUG_READER", raising=False)
    r = TestClient(app).post(
        "/v1/score/read", json={"pr": _pr().model_dump(mode="json"), "diff": "+ x"}
    )
    assert r.status_code == 200
    assert all(not x["rule"].startswith("reader:") for x in r.json()["reasons"])


def test_endpoint_uses_reader_when_enabled(monkeypatch):
    monkeypatch.setenv("DOUG_READER", "1")
    fake = lambda pr, diff, client=None: reader.ReaderVerdict.model_validate(PAYLOAD)  # noqa: E731
    monkeypatch.setattr(reader, "read_diff", fake)
    r = TestClient(app).post(
        "/v1/score/read", json={"pr": _pr().model_dump(mode="json"), "diff": "+ x"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["band"] == "flagged"
    assert body["reasons"][0]["rule"] == "reader:race-condition"


def test_endpoint_falls_back_loudly_on_reader_failure(monkeypatch):
    monkeypatch.setenv("DOUG_READER", "1")

    def boom(pr, diff, client=None):
        raise reader.ReaderError("api down")

    monkeypatch.setattr(reader, "read_diff", boom)
    r = TestClient(app).post(
        "/v1/score/read", json={"pr": _pr().model_dump(mode="json"), "diff": "+ x"}
    )
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
    tier, verdict, rv = review.score_one(_pr(), "+ x")
    assert tier == "deterministic" and rv is None
    assert any(r.rule == "reader-unavailable" for r in verdict.reasons)
