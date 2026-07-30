"""The job-summary script must survive bash quoting.

It is embedded in `python3 -c "..."` inside a double-quoted shell string.
A double-quoted Python f-string terminates that string early and the whole
summary — risk verdict included — never writes.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

WORKFLOWS = (
    Path(__file__).resolve().parents[1] / "deploy" / "doug-review.yml",
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "doug-review.yml",
)


def _python_c_block(path: Path) -> str:
    text = path.read_text()
    match = re.search(r'python3 -c "(.*?)" >> "\$GITHUB_STEP_SUMMARY"', text, re.S)
    assert match, f"could not find python3 -c block in {path}"
    return match.group(1)


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
