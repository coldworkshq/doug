"""The job-summary script must survive bash quoting.

It is embedded in `python3 -c "..."` inside a double-quoted shell string.
A double-quoted Python f-string terminates that string early and the whole
summary — risk verdict included — never writes.
"""

import json
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOWS = (
    Path(__file__).resolve().parents[1] / "deploy" / "doug-review.yml",
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "doug-review.yml",
)


def _python_c_block(path: Path) -> str:
    """The script as the *runner* sees it, not as the file stores it.

    The block lives inside a YAML `run: |` scalar, and YAML strips the
    block's common indentation before bash ever sees it. Reading the raw
    file keeps that indentation, so without dedenting, this test feeds
    python3 a payload no runner ever executes.

    That mattered: an indented `-c` argument is an IndentationError on every
    CPython through 3.13, and 3.14 — the version CI happens to put on PATH —
    dedents it silently. The test passed for a reason that had nothing to do
    with what it claims to check, and failed on any machine whose `python3`
    was older.
    """
    text = path.read_text()
    match = re.search(r'python3 -c "(.*?)" >> "\$GITHUB_STEP_SUMMARY"', text, re.S)
    assert match, f"could not find python3 -c block in {path}"
    return textwrap.dedent(match.group(1))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(p.parents[2])))
def test_summary_script_is_flush_with_the_line_that_opens_it(path: Path):
    """YAML strips the block's *common* indent, so anything indented deeper
    than the opening `echo ... python3 -c "` reaches the runner still
    indented — an IndentationError on every CPython before 3.14. Nothing
    else in this file can catch that, because dedent() would hide it."""
    text = path.read_text()
    match = re.search(r'( *)echo "\$verdict" \| python3 -c "(.*?)"\n', text, re.S)
    assert match, f"could not find the summary pipeline in {path}"
    opener, body = len(match.group(1)), match.group(2)
    deepest_shared = min(
        (len(ln) - len(ln.lstrip()) for ln in body.splitlines() if ln.strip()),
        default=opener,
    )
    assert deepest_shared == opener, (
        f"{path}: summary script is indented {deepest_shared} vs {opener} for the "
        "line opening it; YAML will hand the runner indented Python"
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(p.parents[2])))
def test_summary_script_embeds_no_raw_double_quotes(path: Path):
    """Any " inside the -c payload terminates the shell string early."""
    py = _python_c_block(path)
    assert '"' not in py, f"{path} python -c block still contains a raw double quote"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(p.parents[2])))
def test_summary_script_renders_under_bash(path: Path):
    py = _python_c_block(path)
    verdict = {
        "band": "cleared",
        "score": 0.12,
        "threshold": 0.5,
        "reasons": [],
        "deviations": [
            {
                "type": "contradicts-ticket",
                "severity": "high",
                "description": "Edits the frozen reader prompt",
            }
        ],
        "intent_alignment": 41,
        "intent_refs": ["ADR-0002"],
    }
    script = f"echo {json.dumps(json.dumps(verdict))} | python3 -c \"{py}\""
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Doug: cleared" in result.stdout
    assert "Against recorded decisions" in result.stdout
    assert "ADR-0002" in result.stdout
    assert "contradicts-ticket" in result.stdout
    assert "| decision |" in result.stdout
