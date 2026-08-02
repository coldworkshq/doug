"""The intent tier must not be able to touch the risk verdict.

ADR-0007 makes deviation a separate stream. That decision is only worth
anything if it is enforced, so these tests treat "the score changed
because intent ran" as the defect it would be.
"""

from sqlalchemy import create_engine, select

from doug import intent_providers, reader, review, store
from doug.intent import IntentDoc
from doug.models import PRMetadata
from tests.test_reader import FakeClient

# Both reads charge one scope; nothing here is about spend, and these tests
# run against no ledger, so the cap never fires.
SCOPE = reader.installation_scope(1)

INTENT_PAYLOAD = {
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
    "intent_alignment": 41,
    "deviation_findings": [
        {
            "type": "contradicts-ticket",
            "description": "Edits the frozen reader prompt",
            "severity": "high",
        }
    ],
}

DOC = IntentDoc(
    id="ADR-0002",
    title="Freeze the reader prompt",
    body="The prompt is load-bearing evidence.",
    status="accepted",
    ref="docs/decisions/ADR-0002.md",
)


def _pr() -> PRMetadata:
    return PRMetadata.model_validate(
        dict(number=7, title="Change the reader prompt", author="dev", files=["doug/reader.py"])
    )


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/doug.db"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _enable(monkeypatch, docs=(DOC,)):
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setenv("DOUG_INTENT", "1")
    monkeypatch.setattr(intent_providers, "fetch", lambda *a, **k: list(docs))
    client = FakeClient(INTENT_PAYLOAD)
    monkeypatch.setattr(
        reader, "read_with_decisions",
        lambda pr, diff, chosen, *, scope: reader.IntentReaderVerdict.model_validate(
            {**INTENT_PAYLOAD}
        ),
    )
    return client


def test_intent_read_does_not_move_the_score(monkeypatch):
    """The load-bearing guarantee: the same PR must score identically with
    the intent tier on and off. If this fails, every score in the ledger
    means two different things depending on a flag."""
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(
        reader,
        "read_diff",
        lambda pr, diff, *, scope: reader.ReaderVerdict.model_validate(
            {k: INTENT_PAYLOAD[k] for k in ("risk_score", "rationale", "findings")}
        ),
    )

    monkeypatch.delenv("DOUG_INTENT", raising=False)
    _, without, _, _cov = review.score_one(_pr(), "+ x", scope=SCOPE)

    _enable(monkeypatch)
    _, with_intent, _, _cov = review.score_one(_pr(), "+ x", scope=SCOPE)

    assert with_intent.model_dump() == without.model_dump()


def test_read_intent_returns_none_when_disabled(monkeypatch):
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.delenv("DOUG_INTENT", raising=False)
    assert review.read_intent(None, "o", "r", _pr(), "+ x", scope=SCOPE) is None


def test_read_intent_returns_none_when_repo_keeps_no_records(monkeypatch):
    """The common case. It must be silent and inert, not an error."""
    _enable(monkeypatch, docs=())
    assert review.read_intent(None, "o", "r", _pr(), "+ x", scope=SCOPE) is None


def test_read_intent_returns_none_when_no_record_is_relevant(monkeypatch):
    unrelated = DOC.model_copy(update={"title": "Ship the marketing site", "body": ""})
    _enable(monkeypatch, docs=(unrelated,))
    assert review.read_intent(None, "o", "r", _pr(), "+ x", scope=SCOPE) is None


def test_read_intent_returns_failure_when_the_read_fails(monkeypatch):
    """A failed intent read must not look like 'feature off / no ADRs'
    (ADR-0007). IntentFailure is the distinct signal; the risk path surfaces
    it as a weight-0 reason without moving score or band."""
    _enable(monkeypatch)

    def _boom(pr, diff, chosen, *, scope):
        raise reader.ReaderError("truncated")

    monkeypatch.setattr(reader, "read_with_decisions", _boom)
    out = review.read_intent(None, "o", "r", _pr(), "+ x", scope=SCOPE)
    assert isinstance(out, review.IntentFailure)
    assert "truncated" in out.detail
    assert out.rule == "intent-unavailable"


def test_an_intent_read_at_the_cap_is_named_apart_from_a_broken_one(monkeypatch):
    """A tenant out of budget and a broken intent path are both
    IntentFailure — ADR-0007 keeps either one distinct from "this repo
    keeps no records" — but they must not arrive on the verdict under the
    same name. "Raise the ceiling" and "page someone, the reader is down"
    are different instructions to whoever reads it."""
    _enable(monkeypatch)

    def _capped(pr, diff, chosen, *, scope):
        raise reader.SpendCapExceeded("installation:1 has spent its cap")

    monkeypatch.setattr(reader, "read_with_decisions", _capped)
    out = review.read_intent(None, "o", "r", _pr(), "+ x", scope=SCOPE)
    assert isinstance(out, review.IntentFailure)
    assert out.rule == "intent-capped"


def test_failed_intent_read_surfaces_intent_unavailable_without_moving_score(
    tmp_path, monkeypatch
):
    """Operators and precision must see a broken intent path on the verdict,
    not a quietly empty deviations list that looks like 'no ADRs'."""
    from fastapi.testclient import TestClient

    from doug.api import app
    from doug.models import Band, Reason, Verdict

    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DOUG_API_TOKEN", "secret")
    _enable(monkeypatch)

    def _boom(pr, diff, chosen, *, scope):
        raise reader.ReaderError("timeout")

    monkeypatch.setattr(reader, "read_with_decisions", _boom)
    monkeypatch.setattr(
        review,
        "fetch_pr",
        lambda gh, o, r, n: (_pr().model_copy(update={"head_sha": "a" * 40}), "+ x"),
    )
    fixed = Verdict(
        score=0.4,
        band=Band.CLEARED,
        threshold=0.62,
        reasons=[Reason(rule="size", label="small", weight=0.0)],
    )
    monkeypatch.setattr(
        review,
        "score_one",
        lambda meta, diff, *, scope: ("deterministic", fixed, None, None),
    )

    body = TestClient(app).post(
        "/v1/review",
        json={"repo": "o/r", "pr_number": 7},
        headers={"x-doug-token": "secret"},
    ).json()
    assert body["score"] == 0.4 and body["band"] == "cleared"
    assert body["deviations"] == []
    assert any(r["rule"] == "intent-unavailable" for r in body["reasons"])


def test_read_intent_carries_provenance(monkeypatch):
    _enable(monkeypatch)
    out = review.read_intent(None, "o", "r", _pr(), "+ x", scope=SCOPE)
    assert out.refs == ["ADR-0002"]
    assert out.alignment == 41
    assert out.findings[0].type == "contradicts-ticket"


def test_reader_refuses_to_read_against_no_decisions():
    """Asking the model to compare a diff against nothing is how invented
    deviations happen."""
    try:
        reader.read_with_decisions(_pr(), "+ x", [], scope=SCOPE)
    except reader.ReaderError as e:
        assert "no decision records" in str(e)
    else:
        raise AssertionError("expected ReaderError")


def test_save_deviations_leaves_the_verdict_untouched(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    rv = reader.ReaderVerdict.model_validate(
        {k: INTENT_PAYLOAD[k] for k in ("risk_score", "rationale", "findings")}
    )
    verdict = reader.verdict_from_reader(rv, threshold=30)
    vid = store.save_review("o/r", 7, "reader", verdict, rv)

    engine = create_engine(url)
    with engine.connect() as conn:
        before = dict(conn.execute(select(store.verdicts)).mappings().one())

    findings = [reader.DeviationFinding(**INTENT_PAYLOAD["deviation_findings"][0])]
    store.save_deviations(vid, findings, ["ADR-0002"], 41)

    with engine.connect() as conn:
        after = dict(conn.execute(select(store.verdicts)).mappings().one())
        dev = conn.execute(select(store.deviations)).mappings().one()
    assert after == before
    assert dev["verdict_id"] == vid and dev["kind"] == "contradicts-ticket"
    assert dev["intent_refs"] == ["ADR-0002"] and dev["intent_alignment"] == 41


def test_a_clean_intent_read_is_recorded_distinctly_from_no_read(tmp_path, monkeypatch):
    """"Read happened, nothing found" and "no read happened" must not look
    the same, or deviation precision will be computed over the wrong
    denominator."""
    url = _db(tmp_path, monkeypatch)
    rv = reader.ReaderVerdict.model_validate(
        {k: INTENT_PAYLOAD[k] for k in ("risk_score", "rationale", "findings")}
    )
    vid = store.save_review("o/r", 7, "reader", reader.verdict_from_reader(rv, 30), rv)

    store.save_deviations(vid, [], ["ADR-0003"], 92)

    with create_engine(url).connect() as conn:
        row = conn.execute(select(store.deviations)).mappings().one()
    assert row["kind"] == "none" and row["intent_alignment"] == 92


def test_save_deviations_is_a_no_op_without_storage(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert store.save_deviations(None, [], [], 0) == 0


def test_intent_schema_matches_the_probe_shape():
    """The schema is the one Experiment B v2 passed on. Storage, analysis
    and the derangement check all assume these exact fields."""
    props = reader.INTENT_SCHEMA["properties"]
    assert props["intent_alignment"]["type"] == "integer"
    item = props["deviation_findings"]["items"]
    assert item["properties"]["type"]["enum"] == [
        "missing-from-pr", "beyond-ticket", "contradicts-ticket",
    ]
    assert set(reader.INTENT_SCHEMA["required"]) == {
        "risk_score", "rationale", "findings", "intent_alignment", "deviation_findings",
    }
    # The diff-reader's own schema must be untouched by the intent tier.
    assert "intent_alignment" not in reader.SCHEMA["properties"]


def test_decision_prompt_is_not_the_ticket_prompt():
    """A decision record asks nothing of a PR, so the ticket wording would
    be false. This is a sibling prompt, frozen on its own terms."""
    assert "decisions this team has" in reader.DECISION_INTENT_SYSTEM
    assert "claims to resolve" not in reader.DECISION_INTENT_SYSTEM
    assert reader.DECISION_INTENT_SYSTEM.startswith(reader.SYSTEM[:60])
