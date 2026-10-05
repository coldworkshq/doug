"""The suite never traces, whatever is in the developer's shell.

Tracing reads its switch from the environment (ADR-0031), and a developer who
has switched it on for local dogfooding has `DOUG_TRACING=1` and a real key
pair exported — or in `api/.env`, which `make api-dev` loads. Without this
file, `pytest` in that same shell sends a span for every reader test: hundreds
of fixtures, fake diffs and synthetic PRs into the same Langfuse project
someone is using to look at real reviews.

It fails quietly, too. The reads still pass, the spans still export, and the
only evidence is a `Failed to export span batch` line when the host happens to
be unreachable. A suite whose behaviour depends on who is running it is not a
suite, so the switch is cleared here rather than trusted to be off.

Cleared per test, not once at import, so a test that sets the variable and
leaks it cannot change what the next test does. `test_tracing.py` sets it
inside each test body, which runs after this fixture and is unaffected.
"""

import os

import pytest

# Every variable tracing.enabled() consults, plus the host, so a leftover value
# cannot point a stray span at a real project either.
_TRACING_ENV = (
    "DOUG_TRACING",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
)


@pytest.fixture(autouse=True)
def _tracing_is_off_during_tests():
    for name in _TRACING_ENV:
        os.environ.pop(name, None)
    yield


# ADR-0038: the closing gate refuses a read to every installation outside the
# deploy's founder list. Every other test in this suite describes what an
# installation that IS read gets, under whatever id its fixture happens to
# use, so the suite's default is that the gate admits every installation. The
# gate's own tests opt back into the real decision with `closing_gate`, which
# reads DOUG_FOUNDER_INSTALLATIONS exactly as production does.
from doug import outside as _outside  # noqa: E402

_REAL_REFUSAL_FOR = _outside.refusal_for


@pytest.fixture(autouse=True)
def _every_test_installation_is_a_founder(monkeypatch):
    monkeypatch.setattr(_outside, "refusal_for", lambda installation_id: None)
    yield


@pytest.fixture
def closing_gate(monkeypatch):
    """The real gate, with coldworkshq as the only founder unless a test
    sets DOUG_FOUNDER_INSTALLATIONS itself."""
    monkeypatch.setattr(_outside, "refusal_for", _REAL_REFUSAL_FOR)
    monkeypatch.setenv(_outside.FOUNDER_ENV, "153075663")
    return _outside
