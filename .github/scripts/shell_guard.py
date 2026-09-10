#!/usr/bin/env python3
"""The review lane is provably untouched by a shell pull request (ADR-0034).

Usage: shell_guard.py <base sha> <head sha>

Fails (exit 1) when the diff base...head names api/doug/review.py,
api/doug/worker.py, or api/doug/check_run.py, or when any hunk of
api/doug/api.py overlaps the GitHub webhook handler in either the base or
the head version. Passes (exit 0) otherwise, printing what it checked.

Stdlib only; run locally with two refs before pushing. The red probe is a
branch with one comment in review.py: this must fail on it.
"""
from __future__ import annotations

import re
import subprocess
import sys

FORBIDDEN = ("api/doug/review.py", "api/doug/worker.py", "api/doug/check_run.py")
API = "api/doug/api.py"
WEBHOOK = '@app.post("/webhooks/github"'


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def webhook_span(ref: str) -> tuple[int, int] | None:
    """1-based inclusive line span of the webhook handler at `ref`, or None."""
    try:
        text = git("show", f"{ref}:{API}")
    except subprocess.CalledProcessError:
        return None
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(WEBHOOK)), None)
    if start is None:
        return None
    # The decorator line, then the def, then the body. The handler ends
    # before the next top-level statement: a line that starts with an
    # identifier character or a decorator. A `)` at column 0 closing a
    # multi-line signature is part of the handler, not the end of it, and
    # so is a blank line or a comment; over-inclusion is the safe direction.
    end = start + 1
    while end < len(lines) and re.match(r"(?:async def |def )", lines[end]):
        end += 1
    while end < len(lines) and not re.match(r"[A-Za-z_@]", lines[end]):
        end += 1
    return (start + 1, end)  # 1-based, inclusive of the last handler line


def hunks(base: str, head: str) -> list[tuple[int, int, int, int]]:
    out = git("diff", "-U0", f"{base}...{head}", "--", API)
    found = []
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", out, re.M):
        a, b, c, d = int(m[1]), int(m[2] or 1), int(m[3]), int(m[4] or 1)
        found.append((a, b, c, d))
    return found


def overlaps(start: int, count: int, span: tuple[int, int]) -> bool:
    if count == 0:
        # A pure insertion at `start` sits between start-1 and start.
        return span[0] <= start <= span[1] + 1 and start > span[0]
    return start <= span[1] and start + count - 1 >= span[0]


def main() -> int:
    base, head = sys.argv[1], sys.argv[2]
    changed = git("diff", "--name-only", f"{base}...{head}").split()
    bad = [f for f in changed if f in FORBIDDEN]
    if bad:
        print(f"shell guard: the review lane is touched: {', '.join(bad)}")
        return 1
    if API in changed:
        base_span, head_span = webhook_span(base), webhook_span(head)
        for a, b, c, d in hunks(base, head):
            if base_span and overlaps(a, b, base_span):
                print(f"shell guard: hunk -{a},{b} overlaps the webhook handler at base lines {base_span}")
                return 1
            if head_span and overlaps(c, d, head_span):
                print(f"shell guard: hunk +{c},{d} overlaps the webhook handler at head lines {head_span}")
                return 1
        print(f"shell guard: {API} changed outside the webhook handler ({len(hunks(base, head))} hunks)")
    print(f"shell guard: {len(changed)} files changed, none in the review lane")
    return 0


if __name__ == "__main__":
    sys.exit(main())
