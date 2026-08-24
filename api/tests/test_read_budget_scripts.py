"""Regression coverage for the executable read-budget evidence scripts."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_the_preregistered_coverage_bar_still_holds_at_the_shipped_budget(capsys):
    """ADR-0012's bar, run in CI rather than by hand.

    The bar is "every code-tier file sent whole on >=95% of PRs" over the 30
    first-parent commits ending at END_SHA, with a fixed-sample requirement of
    30/30. It costs zero model calls, which ADR-0012 says is "the property that
    makes a coverage bar a safe replacement for a freeze" — and until now
    nothing ran it automatically, so the bar was only as live as someone's
    memory to invoke the script.

    That gap became load-bearing when `features._is_prose` changed: the bar is
    measured against the CODE TIER, and redefining which files are code
    redefines the bar's own subject. Doug flagged it on b767f2e — "no re-run of
    read_budget_gate.py under the new tiering is included, so the
    pre-registered sanity sample's 30/30 result is no longer known to hold for
    the definition that ships." It does hold, and now every commit proves it
    instead of one person having checked once.

    Deliberately asserts the 30/30 sanity sample and not only the 95% rate:
    ADR-0012 requires the exact pinned sample, so a range that silently shrank
    would otherwise pass on a smaller denominator.
    """
    import read_budget_gate

    assert read_budget_gate.main() == 0
    output = capsys.readouterr().out
    assert "all code sent whole on 30/30 (100%)" in output
    assert "PASS" in output


def test_gate_rejects_partially_sent_code_at_the_probe_budget(monkeypatch, capsys):
    """A code file cut mid-patch is not whole and cannot satisfy the gate.

    The fixed historical range has five such commits at the probe's 30k
    budget. Counting only files_unseen turns that strict 24/30 result into
    29/30 and lets an incomplete reader pass.
    """
    import read_budget_gate

    monkeypatch.setattr(read_budget_gate.reader, "DIFF_BUDGET", 30_000)

    assert read_budget_gate.main() == 1
    output = capsys.readouterr().out
    assert "all code sent whole on 24/30 (80%)" in output
    assert "FAIL" in output


def test_historical_probe_coverage_does_not_change_concurrent_live_coverage(monkeypatch):
    """Backfilled reads must describe the 30k instrument that ran Phase 1.

    Using today's live 100k ceiling turns this partial historical read into a
    complete 68k read and fabricates evidence about what the probe observed.
    Temporarily changing the live module global is also unsafe: a concurrent
    caller can observe the historical budget even though it asked for live
    coverage. The historical budget must travel as an explicit argument.
    """
    import backfill_ledger
    import llm_probe

    diff = backfill_ledger.reader.diff_chunk(
        "historical.py", "modified", 1, 0, "x" * 68_000
    )
    live_budget = backfill_ledger.reader.DIFF_BUDGET
    entered = Event()
    release = Event()
    real_coverage = backfill_ledger.reader.coverage

    def paused_coverage(diff, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return real_coverage(diff, **kwargs)

    monkeypatch.setattr(backfill_ledger.reader, "coverage", paused_coverage)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(backfill_ledger._probe_coverage, diff)
        assert entered.wait(timeout=5)
        budget_during_probe = backfill_ledger.reader.DIFF_BUDGET
        live_cov_during_probe = real_coverage(diff)
        release.set()
        cov = future.result(timeout=5)

    assert budget_during_probe == backfill_ledger.reader.DIFF_BUDGET == live_budget
    assert live_cov_during_probe.complete
    assert live_cov_during_probe.sent_chars == live_cov_during_probe.diff_chars
    assert cov.sent_chars == llm_probe.DIFF_BUDGET == 30_000
    assert not cov.complete
    assert cov.file_cut == "historical.py"
