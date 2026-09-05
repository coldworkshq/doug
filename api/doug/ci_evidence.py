"""Which of the repository's own gates ran green at the reviewed head (#307).

A finding that predicts a failure the repository's CI would have caught
cannot be true when that gate concluded `success` at the reviewed head, and
the reader cannot know that: a diff carries no evidence about which gates
run. #232 measured the class on PR #229; docs/findings-log.jsonl holds three
more (PRs 28, 75, 198) where the disposition names the tool that had
already answered. settle.py turns this module's evidence into a third
settlement, after the read and without touching ADR-0012's frozen
constants.

Two sources, both under permissions Doug already holds:

  * the workflow files at head (`.github/workflows/*.yml`, contents:read),
    which say what each job runs; and
  * the check runs at head (`checks.list_for_ref`, checks:read), which say
    how each job concluded.

The Actions jobs API would have been cleaner — its step names carry the
command — but it needs `actions: read`, an installation-permission change
(R11), so the workflow file is parsed instead. The parser below is a
stdlib-only subset of YAML: block mappings and sequences, plain and quoted
scalars, `|`/`>` block scalars, comments. Anything it cannot read yields
nothing, and nothing is the safe answer here: a job this module cannot name
contributes no evidence and every finding it might have settled stays
published.

A falsifier kind is green only when EVERY job that runs it concluded
success. One green `web` build says nothing about `console/`, and the
per-kind roots (working directories and `--workspace` flags) narrow it
further: a finding is covered only by a green job whose commands ran over
the finding's file.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The YAML subset. Line-oriented, indentation-driven, deliberately partial.


_KEY_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*:(?:\s+(.*)|$)")
_SEQ_RE = re.compile(r"^-(?:\s+(.*)|$)")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(line: str) -> str | None:
    """The line stripped, or None for a blank, a comment, or a document marker."""
    s = line.strip()
    if not s or s.startswith("#") or s == "---" or s == "...":
        return None
    return s


def _uncomment(value: str) -> str:
    """Drop a trailing ` # comment` outside quotes."""
    out: list[str] = []
    quote: str | None = None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).strip()


def _scalar(value: str) -> str:
    v = _uncomment(value)
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _next_content(lines: list[str], i: int) -> int:
    while i < len(lines) and _content(lines[i]) is None:
        i += 1
    return i


def _parse(lines: list[str], i: int, indent: int):
    if _SEQ_RE.match(lines[i].strip()):
        return _parse_seq(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_map(lines: list[str], i: int, indent: int) -> tuple[dict, int]:
    node: dict = {}
    while True:
        i = _next_content(lines, i)
        if i >= len(lines) or _indent(lines[i]) != indent:
            return node, i
        m = _KEY_RE.match(lines[i].strip())
        if not m:
            return node, i
        key, rest = m.group(1), m.group(2)
        i += 1
        if rest is None or _uncomment(rest) == "":
            j = _next_content(lines, i)
            if j < len(lines) and _indent(lines[j]) > indent:
                node[key], i = _parse(lines, j, _indent(lines[j]))
            elif (
                j < len(lines)
                and _indent(lines[j]) == indent
                and _SEQ_RE.match(lines[j].strip())
            ):
                # YAML lets a sequence sit at its key's own indent.
                node[key], i = _parse_seq(lines, j, indent)
            else:
                node[key] = ""
        elif rest.lstrip()[0] in "|>":
            node[key], i = _parse_block_scalar(lines, i, indent)
        else:
            node[key] = _scalar(rest)


def _parse_seq(lines: list[str], i: int, indent: int) -> tuple[list, int]:
    items: list = []
    while True:
        i = _next_content(lines, i)
        if i >= len(lines) or _indent(lines[i]) != indent:
            return items, i
        s = lines[i].strip()
        m = _SEQ_RE.match(s)
        if not m:
            return items, i
        rest = m.group(1)
        if rest is None or _uncomment(rest) == "":
            i += 1
            j = _next_content(lines, i)
            if j < len(lines) and _indent(lines[j]) > indent:
                item, i = _parse(lines, j, _indent(lines[j]))
            else:
                item = ""
            items.append(item)
        elif _KEY_RE.match(rest) and not rest.lstrip().startswith(("'", '"')):
            # `- key: value`: a mapping whose first key shares the dash's line.
            # Rewrite that line as if the key sat at its own indent, then
            # parse the mapping from there.
            inner = indent + len(s) - len(s[1:].lstrip())
            lines[i] = " " * inner + rest
            item, i = _parse_map(lines, i, inner)
            items.append(item)
        else:
            items.append(_scalar(rest))
            i += 1


def _parse_block_scalar(lines: list[str], i: int, indent: int) -> tuple[str, int]:
    out: list[str] = []
    block_indent: int | None = None
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            out.append("")
            i += 1
            continue
        ind = _indent(line)
        if ind <= indent:
            break
        if block_indent is None:
            block_indent = ind
        out.append(line[block_indent:] if ind >= block_indent else line.strip())
        i += 1
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out), i


def parse_yaml_subset(text: str):
    """The document as nested dicts, lists and strings. Partial by design."""
    lines = text.splitlines()
    i = _next_content(lines, 0)
    if i >= len(lines):
        return {}
    node, _ = _parse(lines, i, _indent(lines[i]))
    return node


# ---------------------------------------------------------------------------
# Workflows → jobs → steps.


@dataclass(frozen=True)
class Step:
    command: str
    # Repo-relative directory the command ran in; "" for the repository root.
    working_directory: str


@dataclass(frozen=True)
class Job:
    # The check run's name: the job's `name:` when set, else its key.
    check_name: str
    steps: tuple[Step, ...]
    # A matrix job's check runs are named `<name> (<values>)`.
    matrix: bool = False


def _norm_dir(d: str) -> str:
    d = posixpath.normpath(d.strip()) if d.strip() else "."
    return "" if d in (".", "/") else d.strip("/")


def _run_default(node) -> str | None:
    if not isinstance(node, dict):
        return None
    defaults = node.get("defaults")
    if not isinstance(defaults, dict):
        return None
    run = defaults.get("run")
    if not isinstance(run, dict):
        return None
    wd = run.get("working-directory")
    return wd if isinstance(wd, str) and wd else None


def parse_workflow(text: str) -> list[Job]:
    """Every job the parser can name, with its `run:` steps.

    A job with `uses:` (a reusable workflow) has no steps of its own and is
    skipped. A job whose name, or whose working directory, holds an
    expression (`${{ … }}`) cannot be matched to a check run or a path
    without evaluating it, so it is skipped too — skipped is the safe
    direction, because a skipped job settles nothing.
    """
    try:
        doc = parse_yaml_subset(text)
    except RecursionError:
        return []
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return []
    workflow_wd = _run_default(doc)
    out: list[Job] = []
    for key, job in jobs.items():
        if not isinstance(job, dict) or "uses" in job:
            continue
        name = job.get("name", key)
        if not isinstance(name, str) or not name or "${{" in name:
            continue
        job_wd = _run_default(job) or workflow_wd or ""
        steps: list[Step] = []
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if not isinstance(run, str) or not run.strip():
                continue
            step_wd = step.get("working-directory")
            wd = step_wd if isinstance(step_wd, str) and step_wd else job_wd
            if "${{" in wd:
                continue
            steps.append(Step(command=run, working_directory=_norm_dir(wd)))
        strategy = job.get("strategy")
        matrix = isinstance(strategy, dict) and "matrix" in strategy
        out.append(Job(check_name=name, steps=tuple(steps), matrix=matrix))
    return out


# ---------------------------------------------------------------------------
# Falsifier kinds: which commands answer which finding classes.

RUFF = "ruff"
JS_LINT = "js-lint"
JS_BUILD = "js-build"

_FALSIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (RUFF, re.compile(r"\bruff\s+check\b")),
    (
        JS_LINT,
        re.compile(r"\beslint\b|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?lint\b"),
    ),
    (
        JS_BUILD,
        re.compile(
            r"\btsc\b"
            r"|\b(?:next|vite|nuxt|astro|turbo)\s+build\b"
            r"|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?build\b"
        ),
    ),
)

# `npm run build --workspace=web` / `-w web` ran over one workspace, not
# the root. `pnpm --filter` names a package, not a directory, so a step
# carrying it has no root this module can state.
_WORKSPACE_RE = re.compile(r"(?:--workspace[= ]|(?<!\S)-w\s+)([^\s]+)")
_FILTER_RE = re.compile(r"(?<!\S)--filter(?:[= ]|\b)")


def kinds_of(command: str) -> frozenset[str]:
    return frozenset(kind for kind, rx in _FALSIFIERS if rx.search(command))


def _step_roots(step: Step) -> list[str] | None:
    """Directories the step's command ran over; None when that cannot be said."""
    if _FILTER_RE.search(step.command):
        return None
    workspaces = _WORKSPACE_RE.findall(step.command)
    if not workspaces:
        return [step.working_directory]
    return [
        _norm_dir(posixpath.join(step.working_directory, w) if step.working_directory else w)
        for w in workspaces
    ]


@dataclass(frozen=True)
class CheckResult:
    name: str
    # GitHub's conclusion, or None while the run is queued or in progress.
    conclusion: str | None
    # The posting app's slug; only GitHub Actions' own check runs count.
    app: str | None


@dataclass(frozen=True)
class CiEvidence:
    # kind → job check names, for every kind whose jobs all concluded success
    settled_by: dict[str, tuple[str, ...]]
    # kind → repo-relative roots the green commands ran over ("" = root)
    roots: dict[str, tuple[str, ...]]

    def green(self, kind: str) -> bool:
        return kind in self.settled_by

    def covers(self, kind: str, path: str) -> bool:
        """A green job of `kind` ran its command over `path`."""
        if kind not in self.settled_by:
            return False
        return any(
            root == "" or path.startswith(root + "/") for root in self.roots.get(kind, ())
        )


def _concluded_success(job: Job, checks: list[CheckResult]) -> bool:
    matching = [
        c
        for c in checks
        if c.app == "github-actions"
        and (
            c.name == job.check_name
            or (job.matrix and c.name.startswith(job.check_name + " ("))
        )
    ]
    return bool(matching) and all(c.conclusion == "success" for c in matching)


def evidence(jobs: list[Job], checks: list[CheckResult]) -> CiEvidence:
    """Fold jobs and their check runs into per-kind green verdicts.

    Two workflows can both name a job `test`; their check runs then share a
    name and cannot be told apart. Requiring every same-named check to be
    green handles that without guessing: if all of them passed, whichever
    one ran the falsifier passed.
    """
    by_kind: dict[str, list[Job]] = {}
    for job in jobs:
        kinds: set[str] = set()
        for step in job.steps:
            kinds |= kinds_of(step.command)
        for kind in kinds:
            by_kind.setdefault(kind, []).append(job)
    settled_by: dict[str, tuple[str, ...]] = {}
    roots: dict[str, tuple[str, ...]] = {}
    for kind, kind_jobs in by_kind.items():
        if not all(_concluded_success(job, checks) for job in kind_jobs):
            continue
        settled_by[kind] = tuple(dict.fromkeys(j.check_name for j in kind_jobs))
        found: list[str] = []
        for job in kind_jobs:
            for step in job.steps:
                if kind not in kinds_of(step.command):
                    continue
                step_roots = _step_roots(step)
                if step_roots is not None:
                    found.extend(step_roots)
        roots[kind] = tuple(dict.fromkeys(found))
    return CiEvidence(settled_by=settled_by, roots=roots)


# ---------------------------------------------------------------------------
# Does ruff, as configured at head, report F821 for this file?

ResolveFile = Callable[[str], "str | None"]

# ruff's own precedence within one directory.
_RUFF_CONFIG_FILES = (".ruff.toml", "ruff.toml", "pyproject.toml")
# ruff's default `select`.
_RUFF_DEFAULT_SELECT = frozenset({"E4", "E7", "E9", "F"})
# ruff's default `exclude`, matched on any path component.
_RUFF_DEFAULT_EXCLUDE = frozenset(
    {
        ".bzr", ".direnv", ".eggs", ".git", ".git-rewrite", ".hg",
        ".ipynb_checkpoints", ".mypy_cache", ".nox", ".pants.d", ".pyenv",
        ".pytest_cache", ".pytype", ".ruff_cache", ".svn", ".tox", ".venv",
        ".vscode", "__pypackages__", "_build", "buck-out", "build", "dist",
        "node_modules", "site-packages", "venv",
    }
)  # fmt: skip


def _covers(code: str, rule: str) -> bool:
    return code == "ALL" or rule.startswith(code)


def _glob_matches(pattern: str, rel: str, path: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    stem = pattern.rstrip("/")
    for candidate in (rel, path, posixpath.basename(path)):
        if fnmatch.fnmatchcase(candidate, pattern) or fnmatch.fnmatchcase(candidate, stem):
            return True
        if candidate.startswith(stem + "/"):
            return True
    return False


def _codes(value) -> list[str]:
    return [c for c in value if isinstance(c, str)] if isinstance(value, list) else []


def _config_reports_f821(cfg: dict, path: str, cfg_dir: str) -> bool | None:
    if "extend" in cfg:
        return None  # inherits from another file; not followed
    lint = cfg.get("lint") if isinstance(cfg.get("lint"), dict) else {}

    def get(key: str):
        return lint.get(key, cfg.get(key))

    select = get("select")
    selected = set(_codes(select)) if select is not None else set(_RUFF_DEFAULT_SELECT)
    selected |= set(_codes(get("extend-select")))
    if not any(_covers(c, "F821") for c in selected):
        return False
    if any(_covers(c, "F821") for c in _codes(get("ignore")) + _codes(get("extend-ignore"))):
        return False
    rel = path[len(cfg_dir) + 1 :] if cfg_dir and path.startswith(cfg_dir + "/") else path
    for pattern in _codes(get("exclude")) + _codes(get("extend-exclude")):
        if _glob_matches(pattern, rel, path):
            return False
    per_file = get("per-file-ignores")
    if isinstance(per_file, dict):
        for pattern, codes in per_file.items():
            if _glob_matches(str(pattern), rel, path) and any(
                _covers(c, "F821") for c in _codes(codes)
            ):
                return False
    return True


def f821_selected(path: str, resolve_file: ResolveFile) -> bool | None:
    """True when ruff at head reports F821 in `path`; None when that cannot be told.

    Walks up from the file's directory the way ruff discovers configuration:
    the nearest `.ruff.toml`, `ruff.toml`, or `pyproject.toml` carrying
    `[tool.ruff]` governs. No configuration anywhere means ruff's defaults,
    which select `F`. A config that `extend`s another, or does not parse, is
    "cannot tell".
    """
    if any(part in _RUFF_DEFAULT_EXCLUDE for part in path.split("/")[:-1]):
        return False
    directory = posixpath.dirname(path)
    while True:
        for name in _RUFF_CONFIG_FILES:
            cfg_path = posixpath.join(directory, name) if directory else name
            text = resolve_file(cfg_path)
            if text is None:
                continue
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                return None
            if name == "pyproject.toml":
                tool = data.get("tool")
                data = tool.get("ruff") if isinstance(tool, dict) else None
                if not isinstance(data, dict):
                    continue
            return _config_reports_f821(data, path, directory)
        if not directory:
            return True
        directory = posixpath.dirname(directory)
