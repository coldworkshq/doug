"""SMOKE TEST — replay PR #106 with cited head reads. NOT a pre-registered bar.

Read this before quoting any number it prints.

The answer key is committed in this repo at
`docs/reviews/2026-08-12-pr-106-external-review.md`, its "deltas worth
encoding" section named the cross-file gap that this capability was then built
to close, and all eight findings were classified against Doug's byte window
while the design was being written. A target set after the answers are known,
on a corpus of one PR, is not a pre-registration. It is a wiring check: does a
citation get produced end to end, against a real diff, from a real head read.

The ceiling is low by construction, and a low number is not a failure. Of the
eight findings, four live in files absent from the PR entirely (`api.py`,
`worker.py`, `test_deploy_gcp.py`, `web/lib/api.ts`), so no reader that is
handed a diff can reach them. Of the four in files Doug saw, only finding #2 —
the footer meter rendering against `PLAN_DEEP_READ_CAP = 200` while spend is
enforced at `INSTALLATION_MONTHLY_READ_CAP = 4000` — is an existence-and-value
claim, which is the only shape `constant_value_is` can ground. So the realistic
ceiling for the shipped predicate is 1 of 8, and recovering that one means the
mechanism works.

No matching is automated. Deciding whether a Doug finding "is" an external
finding takes judgement, and a script that guessed would be inventing a metric.
This prints both lists and leaves the comparison to a person.

Runs the read more than once on purpose. design-lock open risk #2: Convergence
Bar 1 already failed with reader nondeterminism named as root cause, and this
capability adds a nondeterministic call that ADDS published findings. The
spread across runs is the observation; a single run would hide it.

    ANTHROPIC_API_KEY=... DOUG_READER=1 DOUG_VERIFY=1 \\
        uv run python scripts/smoke_cited_reads.py --runs 3

Costs real money: one risk read plus up to MAX_VERIFY_READS_PER_REVIEW verify
reads, per run.
"""

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doug import reader, review  # noqa: E402
from doug.models import AuthorType, PRMetadata  # noqa: E402

REF = "616ff99"
REPO_ROOT = Path(__file__).resolve().parents[2]

# Straight from docs/reviews/2026-08-12-pr-106-external-review.md. Kept here so
# the script is self-describing, and marked with whether the file was even in
# the diff — that column is what makes a low score legible.
ANSWER_KEY = [
    ("1", "api/doug/check_run.py:176", "footer joined with one newline; GFM lazy continuation"),
    ("2", "api/doug/check_run.py:86", "meter renders vs cap 200, spend enforced at 4000"),
    ("3", "api/doug/store.py:1361", "review_jobs fallback: unordered LIMIT 1"),
    ("4", "api/doug/worker.py:473", "_instrument unguarded at render time"),
    ("5", "api/tests/test_deploy_gcp.py:158", "promote-gate test weakened; count >= 1 vacuous"),
    ("6", "api/doug/api.py:2278", "bot-author predicate hand-copied at four sites"),
    ("7", "web/lib/api.ts:112", "scoreboard fetch-cache is a token-level copy"),
    ("8", "api/doug/store.py:1288", "snapshot ran 3 sequential SELECTs"),
]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")


def _files_at(ref: str) -> list:
    """The PR's files, shaped like the githubkit objects review.py consumes."""
    out = []
    for line in _git("diff", "--numstat", f"{ref}^", ref).splitlines():
        added, deleted, name = line.split("\t")
        raw = _git("diff", "--unified=3", f"{ref}^", ref, "--", name)
        at = raw.find("@@")
        out.append(
            SimpleNamespace(
                filename=name,
                status="modified",
                additions=int(added) if added != "-" else 0,
                deletions=int(deleted) if deleted != "-" else 0,
                patch=raw[at:] if at != -1 else None,
            )
        )
    return out


def _resolve_file(ref: str):
    def resolve(path: str) -> str | None:
        try:
            return _git("show", f"{ref}:{path}")
        except subprocess.CalledProcessError:
            return None

    return resolve


def _dry_run(ref: str) -> int:
    """Prove the harness reaches the right bytes without spending anything.

    The single most useful check here is the last one: finding #2 needs
    `INSTALLATION_MONTHLY_READ_CAP` from `api/doug/reader.py`, a file that is
    not in this PR at all. If the resolver returns that line, the capability has
    a path to the answer; whether the model asks for it is the paid question.
    """
    files = _files_at(ref)
    with_patch = [f for f in files if f.patch]
    diff = reader.CHUNK_SEPARATOR.join(
        reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
        for f in review.read_order(with_patch)
    )
    resolve = _resolve_file(ref)
    target = resolve("api/doug/reader.py")
    line_no = next(
        (
            i + 1
            for i, line in enumerate((target or "").splitlines())
            if line.startswith("INSTALLATION_MONTHLY_READ_CAP =")
        ),
        None,
    )
    print(f"SMOKE TEST dry run at {ref} — no model calls, no spend.")
    print(f"  files with patches : {len(with_patch)}/{len(files)}")
    print(f"  assembled diff     : {len(diff)} chars")
    print(f"  resolver on a file NOT in the diff (api/doug/reader.py): "
          f"{'ok' if target else 'FAILED'}")
    print(f"  finding #2's constant is at reader.py:{line_no}")
    print(f"  resolver on a missing file returns None: {resolve('api/doug/nope.py') is None}")
    return 0 if (target and line_no) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="SMOKE TEST — not a bar.")
    ap.add_argument("--ref", default=REF)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Assemble the diff and check the resolver. No model calls, no spend.",
    )
    args = ap.parse_args()

    if args.dry_run:
        return _dry_run(args.ref)

    if not reader.enabled():
        print("SMOKE TEST: DOUG_READER is not 1; nothing to run.", file=sys.stderr)
        return 2
    if not reader.verify_enabled():
        print("SMOKE TEST: DOUG_VERIFY is not 1; grounding is off.", file=sys.stderr)
        return 2

    files = _files_at(args.ref)
    diff = reader.CHUNK_SEPARATOR.join(
        reader.diff_chunk(f.filename, f.status, f.additions, f.deletions, f.patch)
        for f in review.read_order(files)
        if f.patch
    )
    seen = {f.filename for f in files if f.patch}
    meta = PRMetadata(
        number=106,
        title="fix: keep the instrument footer, pick the live clock, split the hero",
        author="drewjst",
        author_type=AuthorType.HUMAN,
        additions=sum(f.additions for f in files),
        deletions=sum(f.deletions for f in files),
        files=[f.filename for f in files],
        head_sha=_git("rev-parse", args.ref).strip(),
    )

    print("=" * 72)
    print("SMOKE TEST — cited head reads on PR #106. NOT a pre-registered bar.")
    print("The answer key is committed in-repo and shaped this design.")
    print(f"ref={args.ref}  runs={args.runs}  diff={len(diff)} chars")
    print("=" * 72)
    print("\nAnswer key, with whether the file was in the diff at all:")
    for num, loc, desc in ANSWER_KEY:
        path = loc.rsplit(":", 1)[0]
        mark = "in diff " if path in seen else "NOT SENT"
        print(f"  [{mark}] #{num} {loc} — {desc}")
    print(
        f"\n{sum(1 for _, loc, _ in ANSWER_KEY if loc.rsplit(':', 1)[0] not in seen)}"
        " of 8 are in files no reader handed this diff could reach."
    )

    slug_runs, grounded_runs = [], []
    for run in range(1, args.runs + 1):
        print(f"\n--- run {run}/{args.runs} " + "-" * 50)
        try:
            rv = reader.read_diff(meta, diff, scope=reader.SENTINEL_SCOPE)
            rv, grounded = reader.ground_findings(
                rv,
                head_sha=meta.head_sha,
                resolve_file=_resolve_file(args.ref),
                scope=reader.verify_scope(None),
            )
        except Exception as exc:  # noqa: BLE001 — a smoke test reports, never raises
            print(f"  run failed: {type(exc).__name__}: {exc}")
            continue
        slug_runs.append(sorted(f.category_slug for f in rv.findings))
        grounded_runs.append(grounded)
        print(f"  risk_score={rv.risk_score}  findings={len(rv.findings)}  grounded={grounded}")
        for f in rv.findings:
            print(f"  [{f.evidence:>10}] reader:{f.category_slug} — {f.file}")
            for c in f.citations:
                print(f"               cited {c.locator()}  sha256={c.sha256[:12]}")

    print("\n" + "=" * 72)
    print("SPREAD ACROSS RUNS (design-lock open risk #2 — nondeterminism)")
    if not slug_runs:
        print("  no successful runs")
        return 1
    counts = Counter(len(s) for s in slug_runs)
    print(f"  finding counts: {dict(counts)}")
    print(f"  grounded counts: {grounded_runs}")
    stable = all(s == slug_runs[0] for s in slug_runs)
    print(f"  identical finding sets across runs: {stable}")
    if not stable:
        every = set.intersection(*(set(s) for s in slug_runs))
        union = set.union(*(set(s) for s in slug_runs))
        print(f"  in every run: {sorted(every)}")
        print(f"  in some runs only: {sorted(union - every)}")
    print("\nMatch these against the answer key yourself. This script does not.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
