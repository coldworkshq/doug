"""Who gets a model read, decided by the deploy's founder list (ADR-0038).

Every unknown fails closed: the table names each way an installation can be
not-a-founder and expects a refusal for all of them, beside the one way it can
be a founder.
"""

import pytest

from doug import outside
from doug.outside import Founder, Reason, Refused

FOUNDERS = frozenset({153075663, 151500529})


@pytest.mark.parametrize(
    ("installation_id", "founders", "expected"),
    [
        (153075663, FOUNDERS, Founder()),
        (151500529, FOUNDERS, Founder()),
        (7, FOUNDERS, Refused(Reason.NOT_OPEN)),
        (153075663, frozenset(), Refused(Reason.NOT_OPEN)),
        (None, FOUNDERS, Refused(Reason.NOT_OPEN)),
    ],
    ids=["founder", "second-founder", "unknown", "empty-list", "no-id"],
)
def test_decide_admits_only_a_listed_installation(installation_id, founders, expected) -> None:
    assert outside.decide(installation_id, founders) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("153075663", {153075663}),
        ("153075663 151500529", {153075663, 151500529}),
        ("153075663,151500529", {153075663, 151500529}),
        (" 153075663 ,\n151500529 ", {153075663, 151500529}),
        ("", set()),
        ("   ", set()),
    ],
)
def test_the_list_parses_commas_and_whitespace(raw, expected) -> None:
    assert outside.parse_founders(raw) == frozenset(expected)


@pytest.mark.parametrize("raw", ["153075663 abc", "007", "-5", "153075663;151500529", "1.5"])
def test_a_malformed_entry_raises_rather_than_naming_nobody(raw) -> None:
    """A typo that silently dropped an entry would refuse that founder."""
    with pytest.raises(ValueError, match="not a canonical installation id"):
        outside.parse_founders(raw)


def test_the_boot_check_refuses_an_empty_or_malformed_list(monkeypatch) -> None:
    monkeypatch.delenv(outside.FOUNDER_ENV, raising=False)
    with pytest.raises(RuntimeError, match="unset"):
        outside.require_founders()
    monkeypatch.setenv(outside.FOUNDER_ENV, "153075663 x")
    with pytest.raises(RuntimeError, match="not a canonical installation id"):
        outside.require_founders()
    monkeypatch.setenv(outside.FOUNDER_ENV, "153075663 151500529")
    assert outside.require_founders() == FOUNDERS


def test_refusal_for_reads_the_deploys_list(monkeypatch) -> None:
    monkeypatch.setenv(outside.FOUNDER_ENV, "153075663")
    assert outside.refusal_for(153075663) is None
    assert outside.refusal_for(7) == Refused(Reason.NOT_OPEN)
    monkeypatch.delenv(outside.FOUNDER_ENV)
    assert outside.refusal_for(153075663) == Refused(Reason.NOT_OPEN)


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("installation:153075663", 153075663),
        ("verify:153075663", 153075663),
        ("attribution:153075663", 153075663),
        ("carry:153075663", 153075663),
        ("untenanted", None),
        ("verify:untenanted", None),
        ("attribution:untenanted", None),
        ("installation:007", None),
        ("installation:", None),
        ("other:153075663", None),
    ],
)
def test_installation_of_reads_every_tier_prefix_canonically(scope, expected) -> None:
    assert outside.installation_of(scope) == expected


def test_installation_of_agrees_with_the_reader_on_the_installation_prefix() -> None:
    """One parser for one string: the two must never disagree on a scope
    the reader itself charges."""
    from doug import reader

    for scope in ("installation:153075663", "installation:007", "untenanted", "installation:x"):
        assert outside.installation_of(scope) == reader.installation_from_scope(scope)


def test_every_scope_builder_the_reader_has_is_covered() -> None:
    """A fifth tier prefix added to the reader without one here would charge
    a refused installation's reads through a scope the gate cannot read."""
    from doug import reader

    built = [
        reader.installation_scope(42),
        reader.verify_scope(42),
        reader.attribution_scope(42),
        reader.carry_scope(42),
    ]
    assert [outside.installation_of(s) for s in built] == [42, 42, 42, 42]
