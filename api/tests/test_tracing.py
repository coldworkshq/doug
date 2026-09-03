"""Tracing may observe a read. It may not change one, and it may not break one.

Every test here encodes one of those two sentences. The freeze tests exist
because ADR-0002 and ADR-0012 make what reaches the wire evidence, and a
wrapper between the caller and the SDK is exactly the kind of code that comes
to disagree with the constants it was supposed to forward. The fail-soft tests
exist because the reader falls back silently on any exception: a tracing bug
would not show up as a tracing bug, it would show up as "the model is down"
on every PR, which is the misdiagnosis this repository has already paid for
once on the Vertex transport.
"""

import json
from types import SimpleNamespace

import pytest

from doug import reader, tracing


class _RecordingMessages:
    """Records the kwargs the SDK is handed, and nothing else."""

    def __init__(self, payload=None, stop_reason="end_turn", usage=(11, 7), raises=None):
        self._payload = payload
        self._stop_reason = stop_reason
        self._usage = usage
        self._raises = raises
        self.seen: list[dict] = []

    def create(self, **kwargs):
        self.seen.append(kwargs)
        if self._raises is not None:
            raise self._raises
        text = json.dumps(self._payload) if self._payload is not None else "{}"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason=self._stop_reason,
            usage=SimpleNamespace(
                input_tokens=self._usage[0], output_tokens=self._usage[1]
            ),
        )


class _RecordingClient:
    def __init__(self, **kwargs):
        self.messages = _RecordingMessages(**kwargs)


class _FakeGeneration:
    def __init__(self, log):
        self._log = log

    def update(self, **fields):
        self._log.append(("update", fields))


class _FakeSpan:
    """What start_as_current_observation returns: a context manager."""

    def __init__(self, log, generation):
        self._log = log
        self._generation = generation

    def __enter__(self):
        self._log.append(("enter", None))
        return self._generation

    def __exit__(self, *exc):
        self._log.append(("exit", exc[0].__name__ if exc[0] is not None else None))
        return False


class _FakeLangfuse:
    def __init__(self, log, start_raises=None, update_raises=None):
        self.log = log
        self._start_raises = start_raises
        self._update_raises = update_raises
        self.flushed = 0

    def start_as_current_observation(self, **fields):
        self.log.append(("start", fields))
        if self._start_raises is not None:
            raise self._start_raises
        generation = _FakeGeneration(self.log)
        if self._update_raises is not None:

            def _boom(**_fields):
                raise self._update_raises

            generation.update = _boom
        return _FakeSpan(self.log, generation)

    def flush(self):
        self.flushed += 1


@pytest.fixture(autouse=True)
def _clean_tracing_state(monkeypatch):
    """No test may inherit another's memoized client or environment."""
    monkeypatch.delenv(tracing.TRACING_ENV, raising=False)
    monkeypatch.delenv(tracing.PUBLIC_KEY_ENV, raising=False)
    monkeypatch.delenv(tracing.SECRET_KEY_ENV, raising=False)
    tracing._reset_for_tests()
    yield
    tracing._reset_for_tests()


def _switch_on(monkeypatch):
    monkeypatch.setenv(tracing.TRACING_ENV, "1")
    monkeypatch.setenv(tracing.PUBLIC_KEY_ENV, "pk-test")
    monkeypatch.setenv(tracing.SECRET_KEY_ENV, "sk-test")


def _install(monkeypatch, fake):
    monkeypatch.setattr(tracing, "_client", lambda: fake)


REQUEST = {
    "model": "claude-opus-5",
    "max_tokens": 6000,
    "output_config": {"effort": "high", "format": {"type": "json_schema", "schema": {}}},
    "system": "SYSTEM TEXT",
    "messages": [{"role": "user", "content": "DIFF TEXT"}],
}


# --- the freeze -----------------------------------------------------------


def test_the_request_reaches_the_sdk_unchanged_when_tracing_is_on(monkeypatch):
    """The kwargs the SDK receives are the caller's own dict, byte for byte.

    This is the whole reason `create` takes a request rather than building
    one. ADR-0002 and ADR-0012 make MODEL, SYSTEM, SCHEMA and MAX_TOKENS
    evidence, and a wrapper that assembled its own kwargs would be one
    refactor away from sending something the frozen constants do not describe
    — silently, because the read would still succeed and the pack would still
    hash. Comparing against a deep copy taken before the call is what makes
    an in-place mutation fail here rather than in production.
    """
    import copy

    _switch_on(monkeypatch)
    log: list = []
    _install(monkeypatch, _FakeLangfuse(log))
    client = _RecordingClient()
    before = copy.deepcopy(REQUEST)

    tracing.create(client, REQUEST, kind="risk", scope="installation:1")

    assert client.messages.seen == [before]
    assert REQUEST == before


def test_the_request_is_identical_whether_tracing_is_on_or_off(monkeypatch):
    """Turning tracing on must not be observable at the wire.

    The stronger statement of the test above: an operator flipping
    DOUG_TRACING changes what is recorded and nothing about what is read. If
    these two ever diverge, every measurement taken with tracing on belongs to
    a different instrument than every measurement taken with it off, and the
    example-pack corpus silently pools two populations — the exact defect
    ADR-0027 C3 was written to close.
    """
    off_client = _RecordingClient()
    tracing.create(off_client, REQUEST, kind="risk", scope="installation:1")

    _switch_on(monkeypatch)
    _install(monkeypatch, _FakeLangfuse([]))
    on_client = _RecordingClient()
    tracing.create(on_client, REQUEST, kind="risk", scope="installation:1")

    assert off_client.messages.seen == on_client.messages.seen


def test_tracing_is_off_unless_both_the_flag_and_both_keys_are_set(monkeypatch):
    """Any single missing piece means off, never partly on.

    A half-configured client constructs and then fails on every export, which
    costs a thread and a retry budget to produce nothing and reports it at a
    log level nobody reads. Same all-of rule, and the same reasoning, as
    reader.federation_configured.
    """
    assert not tracing.enabled()

    monkeypatch.setenv(tracing.TRACING_ENV, "1")
    assert not tracing.enabled()

    monkeypatch.setenv(tracing.PUBLIC_KEY_ENV, "pk-test")
    assert not tracing.enabled()

    monkeypatch.setenv(tracing.SECRET_KEY_ENV, "sk-test")
    assert tracing.enabled()

    monkeypatch.setenv(tracing.TRACING_ENV, "0")
    assert not tracing.enabled()


def test_no_langfuse_client_is_constructed_while_tracing_is_off(monkeypatch):
    """Off means nothing is imported, constructed, or started.

    Constructing the client installs a global OpenTelemetry tracer provider
    and starts an exporter thread. An image that never traces must not pay
    for either, and must not acquire a global side effect it did not ask for.
    """
    calls: list = []

    def _explode():
        calls.append("constructed")
        raise AssertionError("tracing constructed a client while switched off")

    monkeypatch.setattr(tracing, "_client", _explode)
    client = _RecordingClient()

    tracing.create(client, REQUEST, kind="risk", scope="installation:1")
    tracing.flush()
    with tracing.job(
        job_id=1,
        installation_id=2,
        repo_full_name="a/b",
        pr_number=3,
        head_sha="deadbeef",
    ):
        pass

    assert calls == []
    assert len(client.messages.seen) == 1


# --- fail-soft ------------------------------------------------------------


def test_a_read_survives_langfuse_failing_to_open_a_span(monkeypatch):
    """The call still goes out and the response still comes back.

    The reader turns any exception on this path into a ReaderError and falls
    back to the deterministic score. A tracing fault that took that path would
    be indistinguishable from a stalled upstream, so a vendor outage would
    read as "Doug's reader is broken" on every PR at once.
    """
    _switch_on(monkeypatch)
    _install(monkeypatch, _FakeLangfuse([], start_raises=RuntimeError("langfuse down")))
    client = _RecordingClient(payload={"ok": True})

    response = tracing.create(client, REQUEST, kind="risk", scope="installation:1")

    assert len(client.messages.seen) == 1
    assert response.stop_reason == "end_turn"


def test_a_read_survives_langfuse_failing_to_write_a_span(monkeypatch):
    """Same guarantee once the span is open. The update is best-effort."""
    _switch_on(monkeypatch)
    _install(monkeypatch, _FakeLangfuse([], update_raises=RuntimeError("export failed")))
    client = _RecordingClient(payload={"ok": True})

    response = tracing.create(client, REQUEST, kind="risk", scope="installation:1")

    assert response.stop_reason == "end_turn"


def test_a_drain_survives_langfuse_failing_to_flush(monkeypatch):
    """worker.drain ends with a flush, and a flush may not end a drain."""
    _switch_on(monkeypatch)

    class _Broken:
        def flush(self):
            raise RuntimeError("flush failed")

    _install(monkeypatch, _Broken())
    tracing.flush()  # must not raise


def test_the_job_scope_runs_its_body_even_when_langfuse_fails(monkeypatch):
    """A `with` that can decline to run its body is a `with` that skips reviews.

    tracing.job wraps process_job inside worker.drain. If a Langfuse fault let
    it swallow the body, a PR would be marked attempted, land 'done', and
    never be reviewed — and nothing would say so.
    """
    _switch_on(monkeypatch)
    _install(monkeypatch, _FakeLangfuse([], start_raises=RuntimeError("langfuse down")))
    ran = []

    with tracing.job(
        job_id=1,
        installation_id=2,
        repo_full_name="a/b",
        pr_number=3,
        head_sha="deadbeef",
    ):
        ran.append("body")

    assert ran == ["body"]


def test_an_sdk_exception_propagates_unchanged_through_the_span(monkeypatch):
    """The reader's ReaderError contract must not be softened by tracing.

    Every caller depends on `client.messages.create` raising so it can record
    the attempt and fall back loudly. A wrapper that caught the exception to
    close its span, and then returned None, would turn a failed read into an
    AttributeError three lines later — reported under a phase that never
    happened.
    """
    _switch_on(monkeypatch)
    log: list = []
    _install(monkeypatch, _FakeLangfuse(log))
    boom = ValueError("upstream refused")
    client = _RecordingClient(raises=boom)

    with pytest.raises(ValueError) as caught:
        tracing.create(client, REQUEST, kind="risk", scope="installation:1")

    assert caught.value is boom
    assert ("exit", "ValueError") in log


# --- what the span says ---------------------------------------------------


def test_the_span_carries_the_model_the_pass_actually_sent(monkeypatch):
    """Read from the request, never from a module constant.

    _report_cost carried this exact defect until the mechanical tier shipped:
    it quoted MODEL for all four passes, so half the spend was attributed to
    the wrong model — silently, because the string was still a real model
    name. The fix there was to make the model a parameter; the fix here is to
    take it from the dict that is about to be sent.
    """
    _switch_on(monkeypatch)
    log: list = []
    _install(monkeypatch, _FakeLangfuse(log))
    mechanical = {**REQUEST, "model": reader.MECHANICAL_MODEL}

    tracing.create(_RecordingClient(), mechanical, kind="verify", scope="installation:1")

    started = next(fields for kind, fields in log if kind == "start")
    assert started["model"] == reader.MECHANICAL_MODEL
    assert started["name"] == "reader.verify"


def test_a_stopped_generation_is_marked_rather_than_looking_clean(monkeypatch):
    """max_tokens is billed for every token and then thrown away.

    Reporting it as an ordinary success would hide the most expensive reads
    there are, which is the same reason _report_cost prints before the
    stop_reason check rather than after it.
    """
    _switch_on(monkeypatch)
    log: list = []
    _install(monkeypatch, _FakeLangfuse(log))
    client = _RecordingClient(stop_reason="max_tokens")

    tracing.create(client, REQUEST, kind="risk", scope="installation:1")

    fields = next(f for kind, f in log if kind == "update")
    assert fields["level"] == "WARNING"
    assert "max_tokens" in fields["status_message"]


def test_unknown_token_counts_are_absent_rather_than_zero(monkeypatch):
    """A read of unknown cost summed in as a free one understates the bill.

    Same rule _report_cost states for its `?`: this is the surface somebody
    sizes a budget from, and an admitted gap beats a confident zero.
    """
    _switch_on(monkeypatch)
    log: list = []
    _install(monkeypatch, _FakeLangfuse(log))

    class _NoUsage(_RecordingClient):
        def __init__(self):
            super().__init__()
            create = self.messages.create

            def _stripped(**kwargs):
                response = create(**kwargs)
                response.usage = None
                return response

            self.messages.create = _stripped

    tracing.create(_NoUsage(), REQUEST, kind="risk", scope="installation:1")

    fields = next(f for kind, f in log if kind == "update")
    assert "usage_details" not in fields


def test_the_span_records_the_text_the_caller_parses(monkeypatch):
    """The trace and the code must agree about what came back.

    All four callers select the response text the same way. If the trace
    assembled it differently — joining every block, say — a debugging session
    would be reading a string the parser never saw, which is worse than
    having no trace at all.
    """
    _switch_on(monkeypatch)
    log: list = []
    _install(monkeypatch, _FakeLangfuse(log))
    client = _RecordingClient(payload={"risk_score": 42})

    tracing.create(client, REQUEST, kind="risk", scope="installation:1")

    fields = next(f for kind, f in log if kind == "update")
    assert json.loads(fields["output"]) == {"risk_score": 42}


def test_every_paid_pass_names_itself_on_its_span(monkeypatch):
    """Four passes, four names, and no two the same.

    The risk and intent reads run the same model at the same effort, and the
    verify and attribution passes run the same model as each other. Without a
    per-pass name the four are indistinguishable in the trace, and "what did
    the intent tier cost" becomes unanswerable — which is most of the reason
    to have this at all.
    """
    _switch_on(monkeypatch)
    log: list = []
    _install(monkeypatch, _FakeLangfuse(log))

    for kind in ("risk", "intent", "verify", "attribution"):
        tracing.create(_RecordingClient(), REQUEST, kind=kind, scope="installation:1")

    names = [fields["name"] for phase, fields in log if phase == "start"]
    assert names == [
        "reader.risk",
        "reader.intent",
        "reader.verify",
        "reader.attribution",
    ]
    assert len(set(names)) == 4
