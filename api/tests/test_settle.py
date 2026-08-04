"""Post-read import settlements — REVIEWING.md resolution rule, no prompt edit."""

from doug import settle
from doug.reader import ReaderFinding, ReaderVerdict

FILE = """\
import threading
from pathlib import Path

def ready():
    threading.Thread(target=lambda: None).start()
    return Path('.')
"""

TYPE_CHECKING_ONLY = """\
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import threading

def ready():
    threading.Thread(target=lambda: None).start()
"""


def _f(slug="missing-import", desc="uses `threading` with no import", file="api.py"):
    return ReaderFinding(
        category_slug=slug, description=desc, file=file, severity="medium"
    )


def test_drops_missing_import_when_runtime_import_exists():
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[_f()])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: FILE)
    assert len(dropped) == 1
    assert out.findings == []


def test_keeps_type_checking_only_import():
    """REVIEWING.md residual-real: TYPE_CHECKING import + runtime use."""
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[_f()])
    out, dropped = settle.drop_disproved_import_findings(
        rv, lambda p: TYPE_CHECKING_ONLY
    )
    assert dropped == []
    assert len(out.findings) == 1


def test_does_not_settle_undefined_name_via_later_assign():
    """Use-before-assign must not be cleared by a later binding."""
    src = "x = 1\n"  # name bound, but slug is undefined-name — out of scope
    f = ReaderFinding(
        category_slug="undefined-name",
        description="`x` is used before it is defined",
        file="api.py",
        severity="medium",
    )
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: src)
    assert dropped == []
    assert out.findings == [f]


def test_keeps_finding_when_name_truly_absent():
    f = _f(desc="uses `asyncio` with no import")
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: FILE)
    assert dropped == []
    assert out.findings == [f]


def test_keeps_finding_when_file_unreadable():
    rv = ReaderVerdict(risk_score=40, rationale="x", findings=[_f()])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: None)
    assert dropped == []
    assert len(out.findings) == 1


def test_does_not_touch_non_resolution_findings():
    f = ReaderFinding(
        category_slug="race-condition",
        description="shared state without a lock",
        file="api.py",
        severity="high",
    )
    rv = ReaderVerdict(risk_score=70, rationale="x", findings=[f])
    out, dropped = settle.drop_disproved_import_findings(rv, lambda p: FILE)
    assert dropped == []
    assert out.findings == [f]


def test_settlement_notice_explains_empty_findings_list():
    notice = settle.settlement_notice([_f()])
    assert notice is not None
    assert notice.rule == "settled-missing-import"
    assert notice.weight == 0.0


def test_score_one_applies_settlement_and_keeps_score(monkeypatch):
    from doug import reader, review
    from doug.models import AuthorType, Band, PRMetadata

    monkeypatch.setenv("DOUG_READER", "1")
    monkeypatch.setattr(reader, "enabled", lambda: True)
    monkeypatch.setattr(
        reader,
        "read_diff",
        lambda meta, diff, *, scope, client=None: ReaderVerdict(
            risk_score=40,
            rationale="x",
            findings=[_f()],
        ),
    )
    meta = PRMetadata(
        number=1,
        title="t",
        author="a",
        author_type=AuthorType.HUMAN,
        additions=1,
        deletions=0,
        files=["api.py"],
        approvals=0,
        approval_latency_s=None,
        days_since_last_human_commit=None,
        files_added=0,
        files_modified=1,
        url="https://example.test/1",
        head_sha="abc",
        changed_files=1,
        files_dropped=[],
    )
    tier, verdict, rv, _cov = review.score_one(
        meta, "+ x", scope=reader.SENTINEL_SCOPE, resolve_file=lambda p: FILE
    )
    assert tier == "reader"
    assert rv is not None
    assert rv.findings == []
    # Score is the instrument's; we do not rewrite it after settlement.
    assert verdict.score == 0.4
    assert verdict.band is Band.FLAGGED
    assert any(r.rule == "settled-missing-import" for r in verdict.reasons)
    assert all(r.rule != "reader:missing-import" for r in verdict.reasons)
