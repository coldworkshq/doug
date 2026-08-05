"""The intent tier must not be able to touch the risk verdict.

ADR-0007 makes deviation a separate stream. That decision is only worth
anything if it is enforced, so these tests treat "the score changed
because intent ran" as the defect it would be.
"""

import re

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
    # SCOPE is installation 1, so that is the installation these tests opt
    # in — the tier is per-installation now, not process-wide.
    monkeypatch.setenv("DOUG_INTENT_INSTALLATIONS", "1")
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


# --- The per-installation gate -------------------------------------------
#
# design-lock.md:62 (red-team mitigation "overclaim #4 = scope #1") commits
# the intent tier to a "per-installation flag, default OFF, ON for the
# dogfood install; labeled experimental; stays off until the pre-registered
# positive control passes." The 2026-07-31 derangement check FAILED its bar,
# so that positive control is still unrun and every deviation finding is
# UNBELIEVED. These tests treat "an installation nobody opted in paid for an
# experimental read" as the defect it would be — the intent read is the
# LARGER of the two paid reads (in=16601 vs in=14031 on #38), so this is the
# expensive direction to be wrong in.

DOGFOOD = 150424894


def _no_read_may_happen(monkeypatch):
    """Booby-trap the paid call site.

    Asserting `read_intent(...) is None` alone would still pass if the read
    were bought and its result discarded. This fails on the *purchase*.
    """

    def _explode(*a, **k):
        raise AssertionError("a disabled installation reached the paid intent read")

    monkeypatch.setattr(reader, "read_with_decisions", _explode)
    monkeypatch.setattr(intent_providers, "fetch", lambda *a, **k: [DOC])
    # DOUG_INTENT=1 deliberately. Without it these tests pass whether or not
    # an allowlist exists, because the old process-wide gate being off is
    # enough to return None on its own — they would be vacuous. Setting it
    # makes the allowlist the ONLY thing that can keep the read from firing.
    monkeypatch.setenv("DOUG_INTENT", "1")


def test_an_installation_off_the_allowlist_buys_no_intent_read(monkeypatch):
    """The whole point: one tenant opting in must not opt in the next one."""
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setenv("DOUG_INTENT_INSTALLATIONS", str(DOGFOOD))
    _no_read_may_happen(monkeypatch)

    stranger = reader.installation_scope(999)
    assert review.read_intent(None, "o", "r", _pr(), "+ x", scope=stranger) is None


def test_the_allowlisted_installation_still_gets_its_intent_read(monkeypatch):
    """The other half — a gate that blocks everything is not a gate.

    DOUG_INTENT is deliberately UNSET here: the allowlist alone must be able
    to turn the read on, or the old switch is still load-bearing."""
    _enable(monkeypatch)
    # After _enable, which sets its own allowlist — this test is about the
    # dogfood id specifically.
    monkeypatch.setenv("DOUG_INTENT_INSTALLATIONS", str(DOGFOOD))
    monkeypatch.delenv("DOUG_INTENT", raising=False)

    got = review.read_intent(None, "o", "r", _pr(), "+ x", scope=reader.installation_scope(DOGFOOD))
    assert isinstance(got, review.IntentRead)


def test_intent_is_off_when_no_allowlist_is_configured(monkeypatch):
    """Default OFF, per design-lock. An unset env var must not mean 'all'."""
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.delenv("DOUG_INTENT_INSTALLATIONS", raising=False)
    _no_read_may_happen(monkeypatch)

    assert review.read_intent(
        None, "o", "r", _pr(), "+ x", scope=reader.installation_scope(DOGFOOD)
    ) is None


def test_untenanted_callers_never_buy_an_intent_read(monkeypatch):
    """The CI path, the credential probe, the CLI and the intent probe all
    charge SENTINEL_SCOPE and hold no installation. There is no installation
    to have opted in, so the experimental read must not fire for them."""
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setenv("DOUG_INTENT_INSTALLATIONS", str(DOGFOOD))
    _no_read_may_happen(monkeypatch)

    assert review.read_intent(
        None, "o", "r", _pr(), "+ x", scope=reader.SENTINEL_SCOPE
    ) is None


def test_the_old_global_env_var_cannot_enable_intent_by_itself(monkeypatch):
    """DOUG_INTENT=1 was a process-wide switch: it turned the experimental
    read on for every installation the service reviewed. Doug's own intent
    probe flagged that deviation (.backtest-cache/decision-intent-probe/
    arms.json:187) and it was disbelieved along with the rest of the tier.
    Deleting the switch is the fix; this pins that it cannot creep back as a
    second, wider gate beside the allowlist."""
    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setenv("DOUG_INTENT", "1")
    monkeypatch.delenv("DOUG_INTENT_INSTALLATIONS", raising=False)
    _no_read_may_happen(monkeypatch)

    assert review.read_intent(
        None, "o", "r", _pr(), "+ x", scope=reader.installation_scope(DOGFOOD)
    ) is None


def test_installation_id_round_trips_through_the_scope_string(monkeypatch):
    """The flag reads the same string the spend cap charges, so the two can
    never disagree about whose read this is."""
    assert reader.installation_from_scope(reader.installation_scope(DOGFOOD)) == DOGFOOD
    assert reader.installation_from_scope(reader.SENTINEL_SCOPE) is None


def test_the_deployed_config_opts_the_dogfood_installation_in_and_nobody_else():
    """A per-installation flag whose deployment still sets the retired
    process-wide switch is a flag in the source and nothing in production.

    The gate defaults OFF, so a stale deploy config cannot over-enable — it
    silently turns the dogfood intent read OFF instead. Silent-off is the
    safe direction and therefore the easy one to ship by accident, which is
    exactly why it is pinned here rather than left to the deploy checklist.
    """
    from pathlib import Path

    from doug import intent

    gcp = (Path(__file__).resolve().parents[1] / "deploy" / "gcp.sh").read_text()
    # The DEPLOYED env vars, not the prose around them — the comment above
    # them names the retired switch in order to explain why it is gone, and
    # a test that cannot tell those apart would forbid documenting it.
    # Every deployed env block, joined — NOT "the one line containing
    # DOUG_READER". An earlier draft unpacked exactly one such line and
    # broke the moment it met the second service's block, which is a test
    # failing on the file's shape rather than on the config being wrong.
    # Adding a service, reflowing a continuation or changing the quoting
    # must not fail this; deploying the wrong thing must.
    deployed = "\n".join(
        ln for ln in gcp.splitlines()
        if "--set-env-vars" in ln and not ln.lstrip().startswith("#")
    )

    opted_in = re.findall(rf"{intent.ALLOWLIST_ENV}=([^,\"'\s]*)", deployed)
    assert opted_in, "the deploy configures no intent allowlist at all"
    # "and nobody else" is half the property and the half a substring check
    # would have missed: this reads the VALUE, so adding a second id fails.
    assert opted_in == [str(DOGFOOD)]
    assert "DOUG_INTENT=1" not in deployed, (
        "the retired process-wide switch is still deployed"
    )


def test_only_a_canonical_scope_string_names_an_installation():
    """installation_from_scope is the exact inverse of installation_scope,
    and nothing looser.

    'installation:007' and 'installation:-5' are not strings this codebase
    can produce — installation_scope builds them all — so accepting them
    would mean honouring an id that came from somewhere else. int() alone
    would take both, and '007' would then resolve to installation 7 while
    an allowlist entry of '007' matched nothing: two spellings of one id,
    disagreeing. Refusing is the safe direction — an unrecognised scope
    names nobody, and nobody is opted in.
    """
    assert reader.installation_from_scope("installation:007") is None
    assert reader.installation_from_scope("installation:-5") is None
    assert reader.installation_from_scope("installation: 7") is None
    assert reader.installation_from_scope("installation:") is None
    assert reader.installation_from_scope("installation:abc") is None
    # The canonical form still round-trips, including a plain zero.
    assert reader.installation_from_scope(reader.installation_scope(7)) == 7
