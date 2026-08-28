"""Inspect, apply, or roll back the repair for transfer-caused censorings.

A repository transfer used to look like an uninstall to the outcome
adjudicator, which settled every job that came due afterwards as
`censored` / `unreachable` — terminally. `doug/transfer_repair.py` explains
the predicate; this is its command line.

Run from the API directory, with the Cloud SQL proxy on :5433:

    uv run python scripts/repair_transfer_censored.py --dry-run --from-gcp doug-prod0
    uv run python scripts/repair_transfer_censored.py --apply \\
        --expect-outcomes 15 --manifest /absolute/path/manifest.json \\
        --from-gcp doug-prod0

Apply is safe to run before the fixed revision is deployed — the requeued
jobs simply censor again on the next drain, and the manifest still names
them. Deploy first anyway; there is no reason to spend the drain.
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from doug import store, transfer_repair  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded repair for outcomes censored by a repository transfer."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--rollback", action="store_true")
    parser.add_argument("--expect-outcomes", type=int)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--from-gcp")
    return parser


def _validate_mode_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.manifest is not None and not args.manifest.is_absolute():
        parser.error("--manifest must be an absolute path")
    if args.dry_run:
        if args.expect_outcomes is not None or args.manifest is not None:
            parser.error("--dry-run does not accept --expect-outcomes or --manifest")
        return
    if args.expect_outcomes is None or args.manifest is None:
        parser.error("--apply and --rollback require --expect-outcomes and --manifest")


def _database_url_from_gcp(project: str) -> str:
    url = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret=doug-database-url",
            f"--project={project}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return url.split("?host=")[0].replace("@/doug", "@127.0.0.1:5433/doug")


def _report_json(report: transfer_repair.RepairReport) -> str:
    return json.dumps(
        {
            "outcomes": report.outcomes,
            "jobs_requeued": report.jobs,
            "prs": report.prs,
            "rows": [asdict(row) for row in report.rows],
        },
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_mode_args(args, parser)

    if args.from_gcp:
        os.environ["DATABASE_URL"] = _database_url_from_gcp(args.from_gcp)
    engine = store._get_existing_schema_engine()
    if engine is None:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    if args.dry_run:
        with engine.connect() as conn:
            print(_report_json(transfer_repair.inspect(conn)))
        return 0
    if args.apply:
        report = transfer_repair.apply(
            engine,
            expect_outcomes=args.expect_outcomes,
            manifest_path=args.manifest,
        )
        print(_report_json(report))
        return 0
    restored = transfer_repair.rollback(
        engine,
        manifest_path=args.manifest,
        expect_outcomes=args.expect_outcomes,
    )
    print(json.dumps({"manifest": str(args.manifest), "restored": restored}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
