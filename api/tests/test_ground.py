"""Grounding is additive, total, and fails soft.

Everything here defends one property: a finding that goes into ground_findings
comes out. It may gain an evidence class and a citation; it may never be
removed, and no failure mode may break the review.
"""

import json
from types import SimpleNamespace

import pytest

from doug import reader, review
from doug.models import AuthorType, PRMetadata

HEAD = "a" * 40
FILE = "import os\n\nCAP = 4000\nLIMIT = CAP\n"


class _Msgs:
    def __init__(self, payloads, raise_with=None):
        self._payloads = list(payloads)
        self._raise = raise_with
        self.calls = 0
        self.scopes: list[dict] = []

    def create(self, **kwargs):
        self.calls += 1
        self.scopes.append(kwargs)
        if self._raise is not None:
            raise self._raise
        payload = self._payloads.pop(0) if self._payloads else {"checks": []}
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


class Fake:
    def __init__(self, payloads=(), raise_with=None):
        self.messages = _Msgs(payloads, raise_with)


def _rv(n=1):
    return reader.ReaderVerdict(
        risk_score=50,
        rationale="r",
        findings=[
            reader.ReaderFinding(
                category_slug=f"cap-mismatch-{i}",
                description="Meter renders against the wrong cap",
                file="api/doug/check_run.py",
                severity="high",
            )
            for i in range(n)
        ],
    )


def _check(**kw):
    return {
        "file": "api/doug/reader.py",
        "line_start": 3,
        "line_end": 3,
        "quoted_text": "CAP = 4000",
        "predicate": "constant_value_is",
        **kw,
    }


def _ground(rv, client, **kw):
    return reader.ground_findings(
        rv,
        head_sha=kw.pop("head_sha", HEAD),
        resolve_file=kw.pop("resolve_file", lambda p: FILE),
        scope="verify:1",
        client=client,
    )


def test_a_grounded_finding_gains_a_citation_and_the_head_cited_class():
    out, n = _ground(_rv(), Fake([{"checks": [_check()]}]))
    assert n == 1
    f = out.findings[0]
    assert f.evidence == "head-cited"
    assert f.citations[0].locator() == f"api/doug/reader.py@{HEAD}#L3-L3"


def test_evidence_classes_never_mix():
    """A citation implies head-cited; its absence implies diff. No third state.

    If these ever come apart, the check-run copy that says a finding rests on
    code outside the diff is attached to the wrong findings — which is worse
    than not saying it at all, because it is then a false claim rather than a
    missing one.
    """
    out, _ = _ground(_rv(2), Fake([{"checks": [_check()]}, {"checks": []}]))
    for f in out.findings:
        assert (f.evidence == "head-cited") == bool(f.citations)


def test_an_abstained_check_leaves_the_finding_published_and_diff_classed():
    """The runner abstains on LIMIT = CAP (binds a name, not a literal).
    The finding must survive that untouched — abstention is not a verdict."""
    binds_a_name = _check(line_start=4, line_end=4, quoted_text="LIMIT = CAP")
    out, n = _ground(_rv(), Fake([{"checks": [binds_a_name]}]))
    assert n == 0
    assert len(out.findings) == 1
    assert out.findings[0].evidence == "diff"
    assert out.findings[0].citations == []


@pytest.mark.parametrize(
    "client",
    [
        Fake(raise_with=RuntimeError("transport exploded")),
        Fake([{"not_the_schema": True}]),
        Fake([]),
    ],
    ids=["transport-error", "unparseable", "empty-checks"],
)
def test_a_verify_failure_leaves_every_finding_intact(client):
    """Timeout, cap, garbage, or nothing — the review is unchanged.

    The model picks where to look. A bad pick has to cost nothing, or a
    hallucinated line number becomes an outage on a path whose entire job is
    to not leave a PR unreviewed.
    """
    rv = _rv(2)
    out, n = _ground(rv, client)
    assert n == 0
    assert len(out.findings) == 2
    assert [f.category_slug for f in out.findings] == [f.category_slug for f in rv.findings]
    assert all(f.evidence == "diff" for f in out.findings)


def test_a_spend_cap_stops_verifying_without_losing_the_tail():
    """Breaking out of the loop must not drop the findings not yet visited.

    This is the one place an additive step could silently become subtractive —
    an early exit that forgets to re-attach the remainder. The assertion inside
    ground_findings catches it; this proves the assertion is reachable.
    """
    class Capped:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise reader.SpendCapExceeded("verify:1 out of budget")

    rv = _rv(3)
    out, n = _ground(rv, Capped())
    assert n == 0
    assert len(out.findings) == 3


def test_grounding_never_spends_more_than_the_per_review_ceiling():
    """MAX_VERIFY_READS_PER_REVIEW bounds latency inside worker.drain's
    20-jobs-sequential loop, not just spend. A finding count above it must not
    turn one review into an unbounded number of model calls."""
    client = Fake([{"checks": []}] * 10)
    _ground(_rv(6), client)
    assert client.messages.calls == reader.MAX_VERIFY_READS_PER_REVIEW


def test_grounding_is_skipped_when_there_is_nothing_to_resolve_against():
    for kw in ({"head_sha": None}, {"resolve_file": None}):
        client = Fake([{"checks": [_check()]}])
        out, n = _ground(_rv(), client, **kw)
        assert n == 0 and client.messages.calls == 0
        assert out.findings[0].evidence == "diff"


def test_the_live_path_is_dark_until_the_flag_is_set(monkeypatch):
    """DOUG_VERIFY is separate from DOUG_READER so this can land without
    changing what Doug does to anyone. Merging the code must not switch it on."""
    monkeypatch.delenv("DOUG_VERIFY", raising=False)
    assert reader.verify_enabled() is False
    monkeypatch.setenv("DOUG_VERIFY", "1")
    assert reader.verify_enabled() is True
    monkeypatch.setenv("DOUG_VERIFY", "true")
    assert reader.verify_enabled() is False


def test_score_one_charges_verify_to_a_scope_the_customer_meter_cannot_see(monkeypatch):
    """The wiring's load-bearing assertion.

    score_one derives the verify scope from the SAME string the risk read
    charged, through installation_from_scope's inverse, so the two can never
    disagree about whose review this is. The prefix differs, which is what
    keeps the spend off store.instrument_snapshot's meter and therefore off the
    customer's `deep reads N/200` footer.
    """
    charged: list[str] = []
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setenv("DOUG_VERIFY", "1")
    monkeypatch.setattr(reader, "_charge", lambda scope: charged.append(scope))
    monkeypatch.setattr(
        reader, "read_diff", lambda *a, **k: _rv()
    )
    monkeypatch.setattr(reader, "_verify_client", lambda: Fake([{"checks": [_check()]}]))

    meta = PRMetadata(
        number=1, title="t", author="a", author_type=AuthorType.HUMAN,
        additions=1, deletions=0, files=["api/doug/check_run.py"], head_sha=HEAD,
    )
    review.score_one(
        meta, "+ x", scope=reader.installation_scope(99), resolve_file=lambda p: FILE
    )
    assert charged == ["verify:99"]
    assert reader.installation_scope(99) not in charged


def test_findings_come_out_in_order_and_none_is_duplicated():
    """The bug an earlier draft actually had, pinned.

    That draft repaired a short output list by re-slicing the original from
    len(out). With three findings where the middle one went missing, the repair
    restored the LENGTH — by dropping finding[1] and appending finding[2] twice.
    A count-based assertion passed and the corruption was silent; a mutation
    test surviving is what surfaced it.

    So this asserts identity and order, not length: ground exactly the middle
    finding and check all three come back, once each, in position.
    """
    rv = _rv(3)
    client = Fake([{"checks": []}, {"checks": [_check()]}, {"checks": []}])
    out, n = _ground(rv, client)

    assert n == 1
    slugs = [f.category_slug for f in out.findings]
    assert slugs == [f.category_slug for f in rv.findings]
    assert len(set(slugs)) == 3
    assert [f.evidence for f in out.findings] == ["diff", "head-cited", "diff"]
