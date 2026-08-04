"""Denominator for REVIEWING.md — every finding disposition, not only lessons.

Prospective rows are the only ones that count toward rates. Backfill rows
seeded from prose demonstrate the schema; they are quarantined the same way
`verdicts.source` quarantines `replay` / `research`.

This module does not change the frozen reader (ADR-0002). It only makes the
meta-review denominator enforceable: schema check, append, and rates.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

Layer = Literal["doug", "agent-reviewer"]
Verdict = Literal["real", "disproved", "adjacent"]
Source = Literal["prospective", "backfill"]

REQUIRED = frozenset(
    {"date", "pr", "layer", "rule", "verdict", "changed", "settled_by", "source"}
)
LAYERS = frozenset({"doug", "agent-reviewer"})
VERDICTS = frozenset({"real", "disproved", "adjacent"})
SOURCES = frozenset({"prospective", "backfill"})


def default_log_path() -> Path:
    # api/doug/findings_log.py → repo/docs/findings-log.jsonl
    return Path(__file__).resolve().parents[2] / "docs" / "findings-log.jsonl"


@dataclass(frozen=True)
class FindingRow:
    date: str
    pr: int
    layer: Layer
    rule: str
    verdict: Verdict
    changed: bool
    settled_by: str
    source: Source
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "date": self.date,
            "pr": self.pr,
            "layer": self.layer,
            "rule": self.rule,
            "verdict": self.verdict,
            "changed": self.changed,
            "settled_by": self.settled_by,
            "source": self.source,
        }
        if self.note:
            out["note"] = self.note
        return out


class FindingsLogError(ValueError):
    """A row or file failed the REVIEWING.md schema."""


def parse_row(raw: Any, *, line_no: int | None = None) -> FindingRow:
    where = f"line {line_no}" if line_no is not None else "row"
    if not isinstance(raw, dict):
        raise FindingsLogError(f"{where}: expected a JSON object")
    missing = REQUIRED - raw.keys()
    if missing:
        raise FindingsLogError(f"{where}: missing keys {sorted(missing)}")
    extra = set(raw) - REQUIRED - {"note"}
    if extra:
        raise FindingsLogError(f"{where}: unknown keys {sorted(extra)}")

    layer = raw["layer"]
    verdict = raw["verdict"]
    source = raw["source"]
    if layer not in LAYERS:
        raise FindingsLogError(f"{where}: layer must be one of {sorted(LAYERS)}")
    if verdict not in VERDICTS:
        raise FindingsLogError(f"{where}: verdict must be one of {sorted(VERDICTS)}")
    if source not in SOURCES:
        raise FindingsLogError(f"{where}: source must be one of {sorted(SOURCES)}")
    if not isinstance(raw["pr"], int) or isinstance(raw["pr"], bool):
        raise FindingsLogError(f"{where}: pr must be an int")
    if not isinstance(raw["changed"], bool):
        raise FindingsLogError(f"{where}: changed must be a bool")
    for key in ("date", "rule", "settled_by"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise FindingsLogError(f"{where}: {key} must be a non-empty string")
    note = raw.get("note")
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise FindingsLogError(f"{where}: note must be a non-empty string when present")

    return FindingRow(
        date=raw["date"],
        pr=raw["pr"],
        layer=layer,
        rule=raw["rule"],
        verdict=verdict,
        changed=raw["changed"],
        settled_by=raw["settled_by"],
        source=source,
        note=note,
    )


def load_rows(path: Path | None = None) -> list[FindingRow]:
    path = path or default_log_path()
    if not path.is_file():
        raise FindingsLogError(f"missing findings log: {path}")
    rows: list[FindingRow] = []
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            raise FindingsLogError(f"line {i}: invalid JSON ({e})") from e
        rows.append(parse_row(raw, line_no=i))
    return rows


def check(path: Path | None = None) -> list[FindingRow]:
    """Validate every line; return rows. Raises FindingsLogError on the first fault."""
    return load_rows(path)


@dataclass(frozen=True)
class Rates:
    """Prospective-only rates. Backfill never enters the denominator."""

    n: int
    by_verdict: dict[str, int]
    by_layer: dict[str, int]
    changed_true: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "by_verdict": dict(self.by_verdict),
            "by_layer": dict(self.by_layer),
            "changed_true": self.changed_true,
            "share": {
                v: (self.by_verdict.get(v, 0) / self.n if self.n else None)
                for v in ("real", "disproved", "adjacent")
            },
        }


def rates(rows: Iterable[FindingRow]) -> Rates:
    prospective = [r for r in rows if r.source == "prospective"]
    by_verdict = Counter(r.verdict for r in prospective)
    by_layer = Counter(r.layer for r in prospective)
    return Rates(
        n=len(prospective),
        by_verdict=dict(by_verdict),
        by_layer=dict(by_layer),
        changed_true=sum(1 for r in prospective if r.changed),
    )


def append(
    *,
    pr: int,
    layer: Layer,
    rule: str,
    verdict: Verdict,
    changed: bool,
    settled_by: str,
    note: str | None = None,
    when: str | None = None,
    path: Path | None = None,
) -> FindingRow:
    """Append one prospective disposition line. Always source=prospective."""
    path = path or default_log_path()
    row = FindingRow(
        date=when or date.today().isoformat(),
        pr=pr,
        layer=layer,
        rule=rule,
        verdict=verdict,
        changed=changed,
        settled_by=settled_by,
        source="prospective",
        note=note,
    )
    # Re-parse through the same gate a CI check will use.
    parse_row(row.to_json())
    with path.open("a") as f:
        f.write(json.dumps(row.to_json(), separators=(",", ":")) + "\n")
    return row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="REVIEWING.md findings-log tools")
    p.add_argument(
        "--path",
        type=Path,
        default=None,
        help="override docs/findings-log.jsonl",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="validate every line (exit 1 on fault)")
    sub.add_parser("rate", help="print prospective-only rates as JSON")

    ap = sub.add_parser("append", help="append one prospective disposition")
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--layer", choices=sorted(LAYERS), required=True)
    ap.add_argument("--rule", required=True)
    ap.add_argument("--verdict", choices=sorted(VERDICTS), required=True)
    ap.add_argument("--changed", action=argparse.BooleanOptionalAction, required=True)
    ap.add_argument("--settled-by", required=True)
    ap.add_argument("--note", default=None)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")

    args = p.parse_args(argv)
    path = args.path
    try:
        if args.cmd == "check":
            rows = check(path)
            print(f"ok: {len(rows)} rows", file=sys.stderr)
            return 0
        if args.cmd == "rate":
            print(json.dumps(rates(check(path)).as_dict(), indent=2, sort_keys=True))
            return 0
        if args.cmd == "append":
            row = append(
                pr=args.pr,
                layer=args.layer,
                rule=args.rule,
                verdict=args.verdict,
                changed=args.changed,
                settled_by=args.settled_by,
                note=args.note,
                when=args.date,
                path=path,
            )
            print(json.dumps(row.to_json(), separators=(",", ":")))
            return 0
    except FindingsLogError as e:
        print(f"findings-log: {e}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
