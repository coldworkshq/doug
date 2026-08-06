"""ADR-0012's pre-registered coverage bar, checked against real history.

    uv run python scripts/read_budget_gate.py

The bar: 100% of code-tier characters sent on >=95% of PRs, over the 30
first-parent commits ending at END_SHA.

Costs ZERO model calls — reader.coverage is pure over the assembled diff
string, so the metric governing DIFF_BUDGET is verifiable by anyone at any
time without spending a cent. That property is why a coverage bar is a
safe replacement for ADR-0002's freeze.

END_SHA is pinned rather than "the last 30 commits" on purpose: a moving
window would drift under the gate and let a later commit re-open it
silently.

Honest limit, stated rather than discovered later: this reconstructs each
PR's diff from `git diff`, whose per-file output carries `diff --git` and
index headers that GitHub's `f.patch` does not. Sizes here therefore run
slightly LARGER than what the service actually assembles, which makes the
gate conservative — it can report a miss the live path would not have, but
it cannot report a pass the live path would have missed.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doug import features, reader, review  # noqa: E402

END_SHA = "135c8e5"
N_COMMITS = 30
BAR = 0.95
REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
    ).stdout


class _File:
    """The subset of a GitHub file object that read_order and diff_chunk read."""

    def __init__(self, filename: str, patch: str):
        self.filename = filename
        self.patch = patch
        self.status = "modified"
        self.additions = 1
        self.deletions = 0


def _files_for(sha: str) -> list[_File]:
    names = [n for n in _git("diff", "--name-only", f"{sha}^", sha).splitlines() if n]
    out = []
    for name in names:
        patch = _git("diff", f"{sha}^", sha, "--", name)
        if patch:
            out.append(_File(name, patch))
    return out


def _is_code(filename: str) -> bool:
    return not features._is_prose(filename) and not features._is_test(filename)


def main() -> int:
    shas = _git("log", "--first-parent", f"-{N_COMMITS}", "--format=%h", END_SHA).split()
    rows, met = [], 0

    for sha in shas:
        files = _files_for(sha)
        if not files:
            continue
        diff = reader.CHUNK_SEPARATOR.join(
            reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
            for f in review.read_order(files)
        )
        cov = reader.coverage(diff)
        code = [f.filename for f in files if _is_code(f.filename)]
        missed = [f for f in code if f in cov.files_unseen]
        ok = not missed
        met += ok
        rows.append((sha, len(files), cov.diff_chars, ok, missed))

    total = len(rows)
    rate = met / total if total else 0.0

    print(f"ADR-0012 coverage bar — DIFF_BUDGET = {reader.DIFF_BUDGET:,}")
    print(f"range: {N_COMMITS} first-parent commits ending {END_SHA}\n")
    print(f"{'sha':>9}  {'files':>5}  {'chars':>9}  all-code-sent")
    print("-" * 46)
    for sha, nfiles, chars, ok, missed in rows:
        mark = "yes" if ok else f"NO  {', '.join(missed[:2])}"
        print(f"{sha:>9}  {nfiles:>5}  {chars:>9,}  {mark}")

    print(f"\nall code sent on {met}/{total} ({rate:.0%}); bar is {BAR:.0%}")
    if rate >= BAR:
        print("PASS")
        return 0
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
