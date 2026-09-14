"""The agent hooks in `.claude/hooks/` refuse what they claim to refuse.

A hook that silently allows reads as protection. Each refusal is driven with
the payload Claude Code sends and sits beside an allowed neighbour, so a hook
that refuses everything fails here too.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"


def _run(
    hook: str, payload: dict[str, object], root: Path = REPO
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOKS / hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        check=False,
    )


def _decision(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return "allow"
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("api/uv.lock", "deny"),
        ("package-lock.json", "deny"),
        ("api/.basedpyright/baseline.json", "deny"),
        ("api/pyproject.toml", "allow"),
        ("api/doug/api.py", "allow"),
        ("web/package.json", "allow"),
    ],
)
@pytest.mark.parametrize("tool", ["Edit", "Write"])
def test_protect_paths(tool: str, path: str, expected: str) -> None:
    payload = {"tool_name": tool, "tool_input": {"file_path": str(REPO / path)}}
    assert _decision(_run("protect-paths.sh", payload)) == expected


def test_protect_paths_ignores_files_outside_the_project(tmp_path: Path) -> None:
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "uv.lock")}}
    assert _decision(_run("protect-paths.sh", payload)) == "allow"


def test_the_stop_check_never_blocks_a_stop_that_follows_a_block() -> None:
    """Blocking again would loop an agent that cannot turn the tree green."""
    proc = _run("stop-check.sh", {"stop_hook_active": True})
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_the_ruff_hook_reports_but_never_deletes_a_noqa_or_an_import(tmp_path: Path) -> None:
    """An import added one edit before its first use survives the hook, and so
    does a noqa that reads as unused only because a per-file ignore covers the
    same rule. The same hook in coldworks deleted three such comments before
    RUF100 joined F401 and F841 as unfixable."""
    api = tmp_path / "api"
    bin_dir = api / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ruff").symlink_to(REPO / "api" / ".venv" / "bin" / "ruff")
    (api / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["F401", "RUF100", "S608"]\n'
        '[tool.ruff.lint.per-file-ignores]\n"x.py" = ["S608"]\n'
    )
    source = 'import os\n\nQUERY = f"SELECT {1} FROM t"  # noqa: S608\n'
    target = api / "x.py"
    target.write_text(source)

    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
    proc = _run("ruff-on-edit.sh", payload, root=tmp_path)

    assert proc.returncode == 2, proc.stderr
    assert "F401" in proc.stderr and "RUF100" in proc.stderr
    assert target.read_text() == source
