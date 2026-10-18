"""Ratchets that only tighten, checked against the merge base with origin/main.

- **ruff debt.** `[tool.ruff.lint.per-file-ignores]` in api/pyproject.toml
  holds violations that predate a rule, as (file, rule) pairs. An entry that
  no longer fires fails until `make ruff-debt` locks the improvement in, and a
  rule whose entry count exceeds the base's fails: fix the code, not the
  table. Counting per rule rather than per pair lets a module move without
  paying its debt in the same change. Deliberate exceptions, each with its
  reason, live in `extend-per-file-ignores` and are not debt: a `--config`
  override replaces `per-file-ignores` but only extends the other, and this
  script must see what fires without the debt.
- **Type-error baseline.** basedpyright shrinks api/.basedpyright/baseline.json
  on every run and only `--writebaseline` grows it, so a rule whose baseline
  entry count exceeds the base's fails. A baseline the run rewrote fails too:
  fixed errors are locked in by committing the smaller file.
- **Inline suppressions.** A `# noqa`, `# type: ignore`, or `# pyright:`
  comment silences a rule without entering the debt table or the baseline, so
  each is counted per rule and a rule whose count exceeds the base's fails.
  There is no allowance for a deliberate new one: pay one down or move the
  boundary into a helper that already holds its suppression. The noqa count
  is what ruff reports with `--ignore-noqa` and not without it, so a comment
  that silences nothing counts for nothing (RUF100 fails it outright). The
  type count reads comment tokens, so the same text inside a string is not a
  suppression. The base is counted by the same ruff over the merge base's
  api/ tree, not from a committed table, so there is nothing to regenerate.

Without origin/main in the clone the base comparisons are skipped and say so;
`--require-base` (CI) makes that a failure. Run from api/ under `uv run`.
"""

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import tokenize
import tomllib
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API = REPO / "api"
BASELINE = "api/.basedpyright/baseline.json"
BEGIN = "# BEGIN ruff-debt"
END = "# END ruff-debt"
CLEAR_DEBT = "lint.per-file-ignores = {}"
# What ruff needs to lint the base's api/ tree the way it lints this one.
LINTED = re.compile(r"^api/(.*/)?([^/]+\.pyi?|\.?(pyproject|ruff)\.toml)$")
TYPE_IGNORE = re.compile(r"#\s*(type|pyright):\s*ignore\b(?:\[([^\]]*)\])?")
# File-level pyright comments that loosen the checker. `strict` tightens it.
PYRIGHT_LOOSENING = re.compile(
    r"#\s*pyright:\s*(basic|standard|report\w+\s*=\s*(?:false|none|information|warning))\b"
)

Table = Mapping[str, Iterable[str]]
# (file, rule) -> how many times an inline comment silences it.
Suppressions = Counter[tuple[str, str]]


def minimal_debt(violations: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    codes_by_path: dict[str, set[str]] = {}
    for path, code in violations:
        codes_by_path.setdefault(path, set()).add(code)
    return {path: sorted(codes) for path, codes in sorted(codes_by_path.items())}


def pairs(table: Table) -> set[tuple[str, str]]:
    return {(path, code) for path, codes in table.items() for code in codes}


def grown(before: Counter[str], after: Counter[str], what: str) -> list[str]:
    return [
        f"{what} for {rule} grew from {before[rule]} to {count}; "
        "fix the code instead of adding to the debt"
        for rule, count in sorted(after.items())
        if count > before[rule]
    ]


def debt_problems(committed: Table, actual: Table, base: Table | None) -> list[str]:
    have, fires = pairs(committed), pairs(actual)
    if have and not have & fires:
        # Every entry stale at once means the debt run never saw the debt.
        return [f"the debt run saw none of the table; `{CLEAR_DEBT}` did not clear it"]
    problems = [
        f"stale ruff debt: {code} no longer fires in {path}; run `make ruff-debt`"
        for path, code in sorted(have - fires)
    ]
    problems += [
        f"ruff violation outside the debt table: {code} in {path}; fix the code"
        for path, code in sorted(fires - have)
    ]
    if base is not None:
        problems += grown(
            Counter(code for _, code in pairs(base)),
            Counter(code for _, code in have),
            "ruff debt (files)",
        )
    return problems


def baseline_counts(baseline: Mapping[str, object]) -> Counter[str]:
    files = baseline.get("files", {})
    counts: Counter[str] = Counter()
    if isinstance(files, dict):
        for entries in files.values():
            counts.update(str(entry.get("code")) for entry in entries)
    return counts


def type_suppressions(source: str) -> Iterator[str]:
    """The rule each type-checker comment in `source` silences, one per code."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError) as error:
        raise SystemExit(f"cannot tokenize a linted file: {error}") from error
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        for match in TYPE_IGNORE.finditer(token.string):
            tool, codes = match[1], match[2] or ""
            named = [code.strip() for code in codes.split(",") if code.strip()]
            yield from (f"{tool}: ignore[{code}]" for code in named)
            if not named:
                yield f"{tool}: ignore"
        yield from (f"pyright: {match[1]}" for match in PYRIGHT_LOOSENING.finditer(token.string))


def inline_suppressions(root: Path) -> Suppressions:
    """Every inline suppression in the tree ruff lints under `root`."""
    hidden = Counter(ruff_violations(root, "--ignore-noqa"))
    hidden.subtract(ruff_violations(root))
    found: Suppressions = Counter(
        {(path, f"noqa: {code}"): n for (path, code), n in hidden.items() if n > 0}
    )
    for path in _ruff(root, "--show-files").splitlines():
        rules = type_suppressions(Path(path).read_text())
        found.update((_relative(path, root), rule) for rule in rules)
    return found


def suppression_problems(now: Suppressions, base: Suppressions) -> list[str]:
    before, after = _per_rule(base), _per_rule(now)
    problems = []
    for rule, count in sorted(after.items()):
        if count > before[rule]:
            grew = sorted({p for (p, r), n in now.items() if r == rule and n > base[p, r]})
            problems.append(
                f"inline `{rule}` grew from {before[rule]} to {count} in "
                f"{', '.join(grew)}; fix the code instead of silencing it"
            )
    return problems


def extract_tree(ref: str, dest: Path) -> None:
    """Writes the files ruff lints under api/ at `ref` to `dest`/api, and nothing else."""
    listed = _git("ls-tree", "-r", "-z", "--name-only", ref).stdout.split("\0")
    paths = [path for path in listed if LINTED.search(path)]
    if not paths:
        return
    archive = subprocess.run(
        ["git", "archive", ref, "--", *paths], cwd=REPO, capture_output=True, check=True
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(dest, filter="data")


def render_debt(table: Table) -> str:
    rows = [
        f"{json.dumps(path)} = [{', '.join(json.dumps(c) for c in codes)}]"
        for path, codes in table.items()
    ]
    header = f"{BEGIN} (generated by `make ruff-debt`; it only shrinks)"
    return "\n".join([header, *rows, END])


def replace_debt(text: str, rendered: str) -> str:
    block = re.compile(rf"^{re.escape(BEGIN)}.*?^{re.escape(END)}$", re.DOTALL | re.MULTILINE)
    replaced, count = block.subn(lambda _: rendered, text)
    if count != 1:
        raise SystemExit(f"api/pyproject.toml needs exactly one {BEGIN} block; found {count}")
    return replaced


def debt(config: Mapping[str, object]) -> dict[str, list[str]] | None:
    table = _lookup(config, "tool", "ruff", "lint", "per-file-ignores")
    return table if isinstance(table, dict) else None


def ruff_violations(root: Path = API, *flags: str) -> list[tuple[str, str]]:
    """Every (file, rule) under `root` that fires with the debt table cleared."""
    out = _ruff(root, "--output-format", "json", "--exit-zero", *flags)
    violations = []
    for v in json.loads(out):
        path = _relative(v["filename"], root)
        if v["code"] is None:
            raise SystemExit(f"ruff cannot parse {path}: {v['message']}")
        violations.append((path, v["code"]))
    return violations


def _ruff(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["ruff", "check", ".", "--config", CLEAR_DEBT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ruff failed under {root}: {proc.stderr.strip()}")
    return proc.stdout


def _relative(path: str, root: Path) -> str:
    return Path(path).resolve().relative_to(root.resolve()).as_posix()


def _per_rule(suppressions: Suppressions) -> Counter[str]:
    counts: Counter[str] = Counter()
    for (_, rule), n in suppressions.items():
        counts[rule] += n
    return counts


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)


def _lookup(config: Mapping[str, object], *keys: str) -> object:
    node: object = config
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _json_at(ref: str, path: str) -> dict[str, object] | None:
    shown = _git("show", f"{ref}:{path}")
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shrink-only ratchets.")
    parser.add_argument(
        "--write-ruff-debt",
        action="store_true",
        help="rewrite the ruff debt table to the violations that fire today",
    )
    parser.add_argument(
        "--require-base",
        action="store_true",
        help="fail when origin/main is not in this clone (CI)",
    )
    args = parser.parse_args(argv)

    pyproject = API / "pyproject.toml"
    actual = minimal_debt(ruff_violations())
    if args.write_ruff_debt:
        pyproject.write_text(replace_debt(pyproject.read_text(), render_debt(actual)))
        print(f"ruff debt: {len(pairs(actual))} pairs in {len(actual)} files")
        return 0

    committed = debt(tomllib.loads(pyproject.read_text())) or {}
    inline = inline_suppressions(API)
    merge_base = _git("merge-base", "HEAD", "origin/main")
    base = merge_base.stdout.strip() if merge_base.returncode == 0 else None

    problems: list[str] = []
    notes: list[str] = []
    rewritten = _git("diff", "--quiet", "HEAD", "--", BASELINE)
    if rewritten.returncode != 0 and _git("cat-file", "-e", f"HEAD:{BASELINE}").returncode == 0:
        problems.append(
            f"{BASELINE} differs from HEAD: basedpyright shrank it, so commit the smaller file"
        )
    if base is None:
        notes.append("no origin/main in this clone: base comparisons skipped")
        if args.require_base:
            problems.append("--require-base: fetch full history so the base exists")
        problems += debt_problems(committed, actual, None)
    else:
        shown = _git("show", f"{base}:api/pyproject.toml")
        base_debt = debt(tomllib.loads(shown.stdout)) if BEGIN in shown.stdout else None
        if base_debt is None:
            notes.append(f"no ruff debt table at {base[:7]}: growth not compared")
        problems += debt_problems(committed, actual, base_debt)
        base_baseline = _json_at(base, BASELINE)
        current = json.loads((REPO / BASELINE).read_text()) if (REPO / BASELINE).exists() else {}
        if base_baseline is None:
            notes.append(f"no type baseline at {base[:7]}: growth not compared")
        else:
            problems += grown(
                baseline_counts(base_baseline), baseline_counts(current), "type baseline"
            )
        with tempfile.TemporaryDirectory() as tree:
            extract_tree(base, Path(tree))
            base_inline = inline_suppressions(Path(tree) / "api")
        problems += suppression_problems(inline, base_inline)

    for note in notes:
        print(f"ratchets: {note}", file=sys.stderr)
    for problem in problems:
        print(f"ratchets: {problem}", file=sys.stderr)
    if problems:
        return 1
    where = f"against {base[:7]}" if base else "without a base"
    print(
        f"ratchets: ok {where} ({len(pairs(actual))} ruff debt pairs, "
        f"{inline.total()} inline suppressions)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
