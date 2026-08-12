"""Evaluate convergence against the ledger's multi-round PRs.

Task 3 of the Lane 2 plan, graded against the bars pre-registered in
`docs/design/outcome-loop/convergence-design.md`. This script does the
autonomous half: it finds every PR with two or more reader-tier verdicts, runs
the shipped classifier on each consecutive pair, and emits JSON complete enough
that a human can hand-label the sample without database access. It computes no
precision — the labels are the input to that, and they are a person's judgment
about what a PR actually fixed.

    DATABASE_URL=... uv run python scripts/convergence_eval.py \\
        --signed-off-floor 0.90 > /tmp/convergence-eval.json

Two guards, both deliberate:

**It cannot write.** No `.begin()`, no insert path, and no `create_all` — this
runs against production, and `store._get_existing_schema_engine()` is the
engine builder that does not migrate the schema out from under it. On Postgres
it also asks the server to enforce read-only, so a mistake fails loudly at the
database instead of quietly succeeding.

**It will not run before bar 1's floor is signed off.** The plan gates the
evaluation on the controller confirming the floor first, so the operator has to
type it and it has to match the note. Pre-registration you can forget to check
is not pre-registration.

Exit codes: 0 evaluated; 2 refused (no signed-off floor, or no DATABASE_URL);
3 evaluated but the sample is below the note's STOP threshold — the bars are
not gradeable without controller sign-off on the smaller n.
"""

import argparse
import json
import sys
from collections import defaultdict

from sqlalchemy import select, text

from doug import convergence, store
from doug.patterns import from_rule

# The floor pre-registered in the design note. The operator must repeat it back;
# a mismatch means they are working from a different version of the note.
PREREGISTERED_FLOOR = 0.90
# The note's STOP threshold for bar 1's sample size.
MIN_LABELABLE_PAIRS = 10

READER_TIER = "reader"

VERDICT_COLUMNS = (
    "id",
    "repo",
    "pr_number",
    "scored_at",
    "head_sha",
    "installation_id",
    "github_repo_id",
)
FINDING_COLUMNS = ("rule", "label", "file", "severity")
COVERAGE_COLUMNS = ("files_unseen", "file_cut", "files_dropped", "changed_files")


# --- analysis (pure: rows in, JSON out) ------------------------------------


def group_key(verdict: dict) -> tuple:
    """The PR a verdict belongs to.

    App identity when it is present; `repo` is a display string and two
    installations can carry the same one. Rows scored before migration 002 have
    NULL ids (store.py:82-88), and those fall back to the repo string rather
    than pooling every such row under `(None, None, pr_number)`, which would
    diff unrelated repositories that happen to share a PR number.
    """
    if verdict["installation_id"] is not None and verdict["github_repo_id"] is not None:
        return (verdict["installation_id"], verdict["github_repo_id"], verdict["pr_number"])
    return ("repo", verdict["repo"], verdict["pr_number"])


def consecutive_pairs(verdicts: list[dict]) -> list[tuple[dict, dict]]:
    """Adjacent (earlier, later) verdicts for one PR, ordered by `scored_at`.

    Not by id: a retry scored after a peer carries the higher id either way,
    and the direction of the diff is a fact about time, not about insert order.
    """
    ordered = sorted(verdicts, key=lambda v: (v["scored_at"], v["id"]))
    return list(zip(ordered, ordered[1:], strict=False))


def pair_payload(
    prior: dict,
    later: dict,
    findings_by_verdict: dict[int, list[dict]],
    reads_by_verdict: dict[int, dict],
) -> dict:
    """Everything about one pair a labeller needs, and nothing they would have
    to query for."""
    prior_findings = findings_by_verdict.get(prior["id"], [])
    later_findings = findings_by_verdict.get(later["id"], [])
    later_read = reads_by_verdict.get(later["id"])

    # Findings and reasons are one table (store.py:104-114) — the settlement
    # notices sit among the later verdict's own rows. Handing the same list in
    # as both is what lets rule 4 fire; `compare` separates them by vocabulary.
    entries = convergence.classify(prior_findings, later_findings, later_findings, later_read)
    report = convergence.compare(prior_findings, later_findings, later_findings, later_read)

    classifications = [
        {
            "side": entry.side,
            "state": entry.state,
            "unknown_reason": entry.unknown_reason,
            **{column: entry.finding[column] for column in FINDING_COLUMNS},
        }
        for entry in entries
    ]
    return {
        "group": _group_payload(prior),
        "from_verdict_id": prior["id"],
        "to_verdict_id": later["id"],
        "from_head_sha": prior["head_sha"],
        "to_head_sha": later["head_sha"],
        "from_scored_at": _iso(prior["scored_at"]),
        "to_scored_at": _iso(later["scored_at"]),
        "report": {
            "resolved": report.resolved,
            "persisted": report.persisted,
            "new": report.new,
            "unknown": report.unknown,
            "unknown_total": report.unknown_total,
            "ratio": report.ratio,
        },
        "classifications": classifications,
        "later_coverage": (
            {column: later_read[column] for column in COVERAGE_COLUMNS}
            if later_read is not None
            else None
        ),
        "labelable": _labelable(classifications),
        "path_form_suspects": path_form_suspects(prior_findings, later_read),
    }


def path_form_suspects(prior_findings: list[dict], later_read: dict | None) -> list[list[str]]:
    """Files the identity key would treat as different that a human would not.

    Identity compares paths by exact string equality, but `findings.file` is
    model-emitted while the coverage paths come from the diff headers. Where
    those disagree on form, rule 3 stops abstaining and bar 2's failure mode is
    live. Same basename with a different path is the cheap signal; only the
    coverage lists are searched, because those are the paths rule 3 consults.
    """
    coverage: list[str] = []
    if later_read is not None:
        coverage = [
            path
            for path in [
                *(later_read.get("files_unseen") or []),
                *(later_read.get("files_dropped") or []),
                later_read.get("file_cut"),
            ]
            if path
        ]
    suspects = {
        (finding["file"], path)
        for finding in prior_findings
        if finding["file"]
        for path in coverage
        if path != finding["file"] and _basename(path) == _basename(finding["file"])
    }
    return sorted([list(pair) for pair in suspects])


def summarize(pairs: list[dict]) -> dict:
    """The covariates and exposure counts the results doc has to carry.

    `bars_without_exposure` is the honest-exposure note in machine-readable
    form: a bar the sample never tested is not a bar the sample passed.
    """
    raw_slugs: set[str] = set()
    patterns: set[str] = set()
    for pair in pairs:
        for row in pair["classifications"]:
            pattern = from_rule(row["rule"])
            if pattern is not None:
                raw_slugs.add(row["rule"].removeprefix("reader:"))
                patterns.add(pattern)

    exposures = {
        "findings_uncovered": _finding_count(pairs, convergence.FILE_UNCOVERED),
        "pairs_with_uncovered": _pair_count(pairs, convergence.FILE_UNCOVERED),
        "findings_settled": _finding_count(pairs, convergence.SETTLED),
        "pairs_with_settled": _pair_count(pairs, convergence.SETTLED),
        "findings_identity_incomplete": _finding_count(pairs, convergence.IDENTITY_INCOMPLETE),
    }
    without_exposure = []
    if not exposures["findings_uncovered"]:
        without_exposure.append("bar 2 (uncovered-file findings)")
    if not exposures["findings_settled"]:
        without_exposure.append("bar 3 (settled findings)")

    labelable = sum(1 for pair in pairs if pair["labelable"])
    suspects = sorted({tuple(pair) for p in pairs for pair in p["path_form_suspects"]})
    return {
        "pairs": len(pairs),
        "labelable_pairs": labelable,
        "prs_with_multiple_reader_verdicts": len({_pr(pair) for pair in pairs}),
        "resolved_total": sum(pair["report"]["resolved"] for pair in pairs),
        "persisted_total": sum(pair["report"]["persisted"] for pair in pairs),
        "new_total": sum(pair["report"]["new"] for pair in pairs),
        "exposures": exposures,
        "bars_without_exposure": without_exposure,
        "slug_drift": {"raw_slugs": len(raw_slugs), "patterns": len(patterns)},
        "path_form_suspects": [list(pair) for pair in suspects],
        "min_labelable_pairs": MIN_LABELABLE_PAIRS,
        "stop_required": labelable < MIN_LABELABLE_PAIRS,
    }


def _labelable(classifications: list[dict]) -> bool:
    """The note's definition: the EARLIER verdict carries at least one reader
    finding with a complete identity. Anything less has nothing to grade."""
    return any(
        row["side"] == "prior"
        and row["state"] != convergence.EXCLUDED
        and row["unknown_reason"] != convergence.IDENTITY_INCOMPLETE
        for row in classifications
    )


def _finding_count(pairs: list[dict], reason: str) -> int:
    return sum(
        1 for pair in pairs for row in pair["classifications"] if row["unknown_reason"] == reason
    )


def _pair_count(pairs: list[dict], reason: str) -> int:
    return sum(
        1
        for pair in pairs
        if any(row["unknown_reason"] == reason for row in pair["classifications"])
    )


def _pr(pair: dict) -> tuple:
    group = pair["group"]
    return (group["installation_id"], group["github_repo_id"], group["repo"], group["pr_number"])


def _group_payload(verdict: dict) -> dict:
    key = group_key(verdict)
    return {
        "installation_id": verdict["installation_id"],
        "github_repo_id": verdict["github_repo_id"],
        "repo": verdict["repo"],
        "pr_number": verdict["pr_number"],
        "key_kind": "repo-fallback" if key[0] == "repo" else "app-identity",
    }


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


# --- the ledger half -------------------------------------------------------


def fetch(conn) -> tuple[list[dict], dict[int, list[dict]], dict[int, dict]]:
    """Reader-tier verdicts, their findings, and their read rows. Three plain
    selects: the ledger's multi-round PRs are a handful, and a clever query
    would be harder to audit than the thing it saves."""
    verdicts = [
        {column: row[column] for column in VERDICT_COLUMNS}
        for row in conn.execute(
            select(store.verdicts)
            .where(store.verdicts.c.tier == READER_TIER)
            .order_by(store.verdicts.c.scored_at, store.verdicts.c.id)
        )
        .mappings()
        .all()
    ]
    ids = [verdict["id"] for verdict in verdicts]

    findings_by_verdict: dict[int, list[dict]] = defaultdict(list)
    for row in (
        conn.execute(
            select(store.findings)
            .where(store.findings.c.verdict_id.in_(ids))
            .order_by(store.findings.c.id)
        )
        .mappings()
        .all()
    ):
        findings_by_verdict[row["verdict_id"]].append(
            {column: row[column] for column in FINDING_COLUMNS}
        )

    reads_by_verdict = {
        row["verdict_id"]: {column: row[column] for column in COVERAGE_COLUMNS}
        for row in conn.execute(select(store.reads).where(store.reads.c.verdict_id.in_(ids)))
        .mappings()
        .all()
    }
    return verdicts, dict(findings_by_verdict), reads_by_verdict


def evaluate(
    verdicts: list[dict],
    findings_by_verdict: dict[int, list[dict]],
    reads_by_verdict: dict[int, dict],
) -> dict:
    by_pr: dict[tuple, list[dict]] = defaultdict(list)
    for verdict in verdicts:
        by_pr[group_key(verdict)].append(verdict)

    pairs = [
        pair_payload(prior, later, findings_by_verdict, reads_by_verdict)
        for group in by_pr.values()
        for prior, later in consecutive_pairs(group)
    ]
    return {
        "preregistered_floor": PREREGISTERED_FLOOR,
        "summary": summarize(pairs),
        "pairs": pairs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--signed-off-floor",
        type=float,
        help="bar 1's pre-registered resolved-precision floor, as recorded in the design note",
    )
    args = parser.parse_args(argv)

    if args.signed_off_floor != PREREGISTERED_FLOOR:
        print(
            "refusing to evaluate: bar 1's floor must be signed off by the controller "
            f"before this runs. Re-run with --signed-off-floor {PREREGISTERED_FLOOR:.2f} "
            "once that confirmation is recorded in LANE2-REPORT.md.",
            file=sys.stderr,
        )
        return 2

    engine = store._get_existing_schema_engine()
    if engine is None:
        print("refusing to evaluate: DATABASE_URL is not set.", file=sys.stderr)
        return 2

    with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            # Belt and braces: the code below only reads, and now the server
            # will refuse anything else.
            conn.execute(text("SET TRANSACTION READ ONLY"))
        result = evaluate(*fetch(conn))

    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")

    summary = result["summary"]
    print(
        f"pairs={summary['pairs']} labelable={summary['labelable_pairs']} "
        f"resolved={summary['resolved_total']} persisted={summary['persisted_total']} "
        f"unknown-exposures={summary['exposures']}",
        file=sys.stderr,
    )
    if summary["bars_without_exposure"]:
        print(
            "no exposure for: "
            + ", ".join(summary["bars_without_exposure"])
            + " — a bar the sample never tested is not a bar the sample passed.",
            file=sys.stderr,
        )
    if summary["stop_required"]:
        print(
            f"STOP: {summary['labelable_pairs']} labelable pairs is below the "
            f"pre-registered minimum of {MIN_LABELABLE_PAIRS}. Report the count and get "
            "controller sign-off before grading bar 1 on a smaller n.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
