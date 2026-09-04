"""Denominator for REVIEWING.md — every finding disposition, not only lessons.

Prospective rows are the only ones that count toward rates. Backfill rows
seeded from prose demonstrate the schema; they are quarantined the same way
`verdicts.source` quarantines `replay` / `research`.

This module does not change ADR-0012's frozen five reader constants. It only makes the
meta-review denominator enforceable: schema check, append, and rates.

Two axes split the file, and both exist for the same reason. `repo` splits it
because a `pr` is only unique inside one repository. The `rule` prefix splits it
because more than one instrument writes here — the reader, the plan lane's
deviation findings — and they speak different vocabularies. `patterns.from_rule`
already refuses to pool them; so does `rates`.
"""

from __future__ import annotations

import argparse
import json
import re
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

REQUIRED = frozenset({"date", "pr", "layer", "rule", "verdict", "changed", "settled_by", "source"})
# `repo` is optional in the file and defaulted, so the rows written before Doug
# reviewed anything but itself stay valid: absence means "doug". It is REQUIRED
# on the CLI, because a `pr` is only unique within a repository and a rate that
# mixes two of them is not a rate of anything.
DEFAULT_REPO = "doug"
_REPO_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# `rule` is `<prefix>:<slug>`, both halves kebab-case. The prefix names the
# instrument that raised the finding and is the unit `rates` slices on. The slug
# is pinned too, and that is not symmetry for its own sake: on the reader tier
# the slug is `category_slug`, a free-form schema string with no enum and no
# pattern (reader.py:130-137), so `reader:Foo Bar` and `reader:foo-bar` are both
# reachable model output. `patterns.normalize` folds the spelling downstream
# (#244), but the log is the hand-transcribed record and a dirty slug here is a
# transcription error, not model output; transcription is the one place that
# can still be refused, so it is.
_RULE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*:[a-z0-9]+(-[a-z0-9]+)*$")
NO_PREFIX = "(none)"
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
    repo: str = DEFAULT_REPO
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
            "repo": self.repo,
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
    extra = set(raw) - REQUIRED - {"note", "repo"}
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
    if not _RULE_RE.match(raw["rule"]):
        raise FindingsLogError(
            f"{where}: rule must be <prefix>:<slug>, both kebab-case, e.g. "
            f"reader:missing-import (got {raw['rule']!r}). The prefix names the "
            f"instrument that raised the finding, and an untagged rule lands in a "
            f"share it does not belong to. If the reader emitted a slug in some "
            f"other shape, kebab-case it here and put the original in `note` — the "
            f"log is transcription, and two spellings of one defect are two patterns"
        )
    repo = raw.get("repo", DEFAULT_REPO)
    if not isinstance(repo, str) or not _REPO_RE.match(repo):
        raise FindingsLogError(
            f"{where}: repo must be a lowercase slug (got {repo!r}) — a typo here "
            f"silently splits the denominator into two repositories"
        )
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
        repo=repo,
        note=note,
    )


def prefix_of(rule: str) -> str:
    """The instrument a rule belongs to — its prefix, colon included.

    `NO_PREFIX` for an untagged rule. `parse_row` refuses those, so this only
    reports on rows built in memory; it never silently files one under a real
    instrument. Agrees with `patterns.RULE_PREFIX` by construction, pinned in
    tests/test_findings_log.py.
    """
    head, sep, _ = rule.partition(":")
    return head + sep if sep else NO_PREFIX


def normalize_prefix(prefix: str) -> str:
    """Accept `reader` for `reader:`.

    A caller who drops the colon would otherwise scope to a prefix no row can
    match and read the empty result as a measurement.
    """
    if prefix == NO_PREFIX or prefix.endswith(":"):
        return prefix
    return prefix + ":"


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
    by_repo: dict[str, int]
    by_rule_prefix: dict[str, int]
    changed_true: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "by_verdict": dict(self.by_verdict),
            "by_layer": dict(self.by_layer),
            "by_repo": dict(self.by_repo),
            "by_rule_prefix": dict(self.by_rule_prefix),
            "changed_true": self.changed_true,
            "share": {
                v: (self.by_verdict.get(v, 0) / self.n if self.n else None)
                for v in ("real", "disproved", "adjacent")
            },
        }


def rates(
    rows: Iterable[FindingRow],
    *,
    repo: str | None = None,
    rule_prefix: str | None = None,
) -> Rates:
    """Prospective-only, and scoped on two axes for the same reason.

    A share computed across two repositories describes neither, and neither does
    one computed across two instruments: the reader's findings and the plan
    lane's deviation findings are different vocabularies that happen to share a
    file, exactly as `patterns.from_rule` says. So `by_repo` and
    `by_rule_prefix` are always reported, and a published number should come
    from a call scoped on both.
    """
    prospective = [r for r in rows if r.source == "prospective"]
    if repo is not None:
        prospective = [r for r in prospective if r.repo == repo]
    if rule_prefix is not None:
        wanted = normalize_prefix(rule_prefix)
        prospective = [r for r in prospective if prefix_of(r.rule) == wanted]
    by_verdict = Counter(r.verdict for r in prospective)
    by_layer = Counter(r.layer for r in prospective)
    by_repo = Counter(r.repo for r in prospective)
    by_rule_prefix = Counter(prefix_of(r.rule) for r in prospective)
    return Rates(
        n=len(prospective),
        by_verdict=dict(by_verdict),
        by_layer=dict(by_layer),
        by_repo=dict(by_repo),
        by_rule_prefix=dict(by_rule_prefix),
        changed_true=sum(1 for r in prospective if r.changed),
    )


def append(
    *,
    pr: int,
    layer: Layer,
    repo: str = DEFAULT_REPO,
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
        repo=repo,
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
    rp = sub.add_parser("rate", help="print prospective-only rates as JSON")
    rp.add_argument(
        "--repo",
        default=None,
        help="scope the rate to one repository (default: all, with by_repo shown)",
    )
    rp.add_argument(
        "--rule-prefix",
        default=None,
        help=(
            "scope the rate to one instrument's vocabulary, e.g. reader: "
            "(default: all, with by_rule_prefix shown)"
        ),
    )

    ap = sub.add_parser("append", help="append one prospective disposition")
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--layer", choices=sorted(LAYERS), required=True)
    ap.add_argument(
        "--repo",
        required=True,
        help="repository the PR belongs to, e.g. doug, coldworks",
    )
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
            scoped = rates(check(path), repo=args.repo, rule_prefix=args.rule_prefix)
            print(json.dumps(scoped.as_dict(), indent=2, sort_keys=True))
            return 0
        if args.cmd == "append":
            row = append(
                pr=args.pr,
                layer=args.layer,
                repo=args.repo,
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
