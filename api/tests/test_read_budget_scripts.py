"""Regression coverage for the executable read-budget evidence scripts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


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


def test_historical_probe_coverage_uses_the_probe_budget_and_restores_live_budget():
    """Backfilled reads must describe the 30k instrument that ran Phase 1.

    Using today's live 100k ceiling turns this partial historical read into a
    complete 68k read and fabricates evidence about what the probe observed.
    """
    import backfill_ledger
    import llm_probe

    diff = backfill_ledger.reader.diff_chunk(
        "historical.py", "modified", 1, 0, "x" * 68_000
    )
    live_budget = backfill_ledger.reader.DIFF_BUDGET
    cov = backfill_ledger._probe_coverage(diff)

    assert backfill_ledger.reader.DIFF_BUDGET == live_budget
    assert cov.sent_chars == llm_probe.DIFF_BUDGET == 30_000
    assert not cov.complete
    assert cov.file_cut == "historical.py"
