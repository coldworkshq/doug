import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from doug import reader, review, store
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


def test_verdict_mapping_and_threshold():
    rv = reader.ReaderVerdict.model_validate(PAYLOAD)
    v = reader.verdict_from_reader(rv)
    assert v.band is Band.FLAGGED  # 62 >= default threshold 30
    assert v.score == 0.62
    assert v.reasons[0].rule == "reader:race-condition"

    low = reader.ReaderVerdict.model_validate({**PAYLOAD, "risk_score": 12, "findings": []})
    assert reader.verdict_from_reader(low).band is Band.CLEARED


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
    """reader.MODEL is one constant today and both lines quote it, which
    looks redundant until someone splits the model per read — at which
    point a line that silently changed meaning is this repo's recurring
    defect. The name travels with the number instead."""
    reader.read_diff(_pr(), "+ x", scope=SCOPE, client=FakeClient())
    reader.read_with_decisions(
        _pr(), "+ x", DOCS, scope=SCOPE, client=FakeClient(payload=INTENT_PAYLOAD)
    )

    assert all(f"model={reader.MODEL}" in line for line in _read_lines(capsys))


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
