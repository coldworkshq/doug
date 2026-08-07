"""Inspect, apply, verify, or roll back the historical 60-day outcome-job repair.

Run this file directly from the API directory:

    uv run python scripts/backfill_outcome_jobs.py --dry-run
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from doug import outcome_backfill, store  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded backfill for missing 60-day outcome jobs."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify-manifest", action="store_true")
    modes.add_argument("--rollback", action="store_true")
    parser.add_argument("--expect-missing", type=int)
    parser.add_argument("--expect-count", type=int)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--from-gcp")
    return parser


def _validate_mode_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.manifest is not None and not args.manifest.is_absolute():
        parser.error("--manifest must be an absolute path")
    if args.dry_run:
        mode_arguments = (args.expect_missing, args.expect_count, args.manifest)
        if any(value is not None for value in mode_arguments):
            parser.error("--dry-run does not accept apply or rollback arguments")
        return
    if args.apply:
        if args.expect_missing is None or args.manifest is None:
            parser.error("--apply requires --expect-missing and --manifest")
        if args.expect_count is not None:
            parser.error("--apply does not accept --expect-count")
        return
    if args.expect_count is None or args.manifest is None:
        parser.error("--verify-manifest and --rollback require --expect-count and --manifest")
    if args.expect_missing is not None:
        parser.error("--verify-manifest and --rollback do not accept --expect-missing")


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
            report = outcome_backfill.inspect(conn)
        print(json.dumps(report.to_dict(), sort_keys=True))
        return 0
    if args.apply:
        result = outcome_backfill.apply(
            engine,
            expected_missing=args.expect_missing,
            manifest_path=args.manifest,
        )
        print(json.dumps(result.to_dict(), sort_keys=True))
        return 0
    if args.verify_manifest:
        verified = outcome_backfill.verify_manifest(
            engine,
            expected_count=args.expect_count,
            manifest_path=args.manifest,
        )
        print(
            json.dumps(
                {"manifest": str(args.manifest), "verified_untouched": verified}, sort_keys=True
            )
        )
        return 0
    rolled_back = outcome_backfill.rollback(
        engine,
        expected_count=args.expect_count,
        manifest_path=args.manifest,
    )
    print(json.dumps({"manifest": str(args.manifest), "rolled_back": rolled_back}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
