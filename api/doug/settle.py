"""Post-read settlements that do not touch ADR-0012's frozen five constants.

REVIEWING.md: a claim about an absence cannot be settled by re-reading the
diff — the check and the error are the same observation. When the full file
at head is available, drop *missing-import* findings the file already
disproves via a runtime import. The model still saw only the diff; we just
stop publishing what the repo (or ruff F821) would have cleared.

Deliberately narrow. REVIEWING.md lists residual-real cases ruff misses —
TYPE_CHECKING-only imports used at runtime, imports of modules that do not
exist, `from x import Y` when Y is absent, getattr. Those must not be
settled by a coarse "name appears in the AST" check. So this module only
counts Import / ImportFrom outside `if TYPE_CHECKING:` blocks, and only for
the missing-import finding class — not undefined-name / use-before-assign.

Second class, same rule, different ground truth: REVIEWING.md ("No migration
for this column…", "Your disposition is invisible…") logs the
unmigrated-column / schema-dependency finding class at 5/5 disproved across
PRs 25, 30 (twice) and 48 (twice) — a claim that a column has no migration,
settled by re-reading the diff's own touched migration versions rather than
the two things that actually decide it: the full `MIGRATIONS` history, and
the live schema. `docs/findings-log.jsonl` calls this the same shape as
missing-import: an absence provable only from data the model was never
given. `drop_disproved_schema_findings` asks the live database instead of
migrations.py, because that is the check REVIEWING.md says "should have come
first" (`installations.token_hash` shipped with its table via `create_all()`
and never appears in any migration) — it does not need to know *why* a
column exists, only whether it does. Out of scope, same discipline as
TYPE_CHECKING above: a claim that a whole *table* is unmigrated. A brand-new
table introduced by the very diff under review is correctly absent from the
live schema — the disproof there is migrations.py's own convention (new
tables arrive via `create_all()`, never a migration), not the live schema,
and settling that would need a different check than this one.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable

from .reader import ReaderFinding, ReaderVerdict

# Weight-0 notices appended when a finding is disproved rather than the
# author fixing it. The only two producers are settlement_notice and
# schema_settlement_notice below. check_run.py and convergence.py import
# this set rather than prefix-matching "settled-".
SETTLED_MISSING_IMPORT = "settled-missing-import"
SETTLED_SCHEMA_DEPENDENCY = "settled-schema-dependency"
SETTLED_REASON_CODES = frozenset(
    {SETTLED_MISSING_IMPORT, SETTLED_SCHEMA_DEPENDENCY}
)

_IMPORT_SLUGS = frozenset(
    {
        "missing-import",
        "missing-module-import",
    }
)

_NAME_IN_BACKTICKS = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
# The root of a dotted expression inside backticks: `sys.stderr` and
# `file=sys.stderr` both name `sys`, and neither is a bare identifier.
_BACKTICK_SPAN = re.compile(r"`([^`]+)`")
_DOTTED_ROOT = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_]")
_IMPORT_WORD = re.compile(r"\bimport\s+([A-Za-z_][A-Za-z0-9_]*)")

_SCHEMA_SLUGS = frozenset(
    {
        "unmigrated-column",
        "missing-migration",
        "missing-migration-dependency",
        "schema-dependency",
    }
)

# `table.column`, backticked or bare — how every disproved instance in
# findings-log.jsonl actually phrased the claim (`installations.token_hash`,
# `verdicts.head_sha`, `verdicts.prompt_hash`). A bare table name with no
# dot (the whole-new-table shape) deliberately does not match — see the
# module docstring.
_TABLE_DOT_COLUMN = re.compile(r"`?([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)`?")


def looks_like_missing_import_finding(f: ReaderFinding) -> bool:
    slug = f.category_slug.lower().removeprefix("reader:")
    if slug in _IMPORT_SLUGS:
        return True
    desc = f.description.lower()
    # Require an import-shaped claim, not every "undefined" NameError.
    return "import" in desc and any(
        w in desc for w in ("missing", "without", "no import", "not imported")
    )


def claimed_names(f: ReaderFinding) -> list[str]:
    """Names the finding asserts are absent. Empty ⇒ we cannot settle it.

    Two ways a name is claimed, and the asymmetry between them is the point:

    - A bare identifier in backticks (`sys`) is a claim on its own.
    - The prose form "import X" is a claim only when X is also written as
      code in the description — bare, or as the root of a dotted expression
      such as `os.path.join`. The word after "import" in prose is usually
      prose: PR #278's third read said "the diff does not show a `sys`
      import being added", the old extractor claimed `being`, and because
      every claimed name must be imported for a finding to settle, one prose
      word republished a finding the first two reads had already dropped.

    A dotted root is never a claim on its own. Doug's review of this change
    (`reader:over-broad-regex`) was right that `self.client.post` or
    `config.value` in backticks would otherwise become permanent vetoes —
    `self` is never imported — so a finding that used to settle on `requests`
    alone would be published. The root only corroborates a prose claim.

    Errors here run in the safe direction: a name not claimed is a finding
    kept, never a finding hidden.
    """
    bare: list[str] = _NAME_IN_BACKTICKS.findall(f.description)
    roots: set[str] = set(bare)
    for span in _BACKTICK_SPAN.findall(f.description):
        roots.update(_DOTTED_ROOT.findall(span))
    found = list(bare)
    for word in _IMPORT_WORD.findall(f.description):
        if word in roots:
            found.append(word)
    return list(dict.fromkeys(found))


def _is_type_checking_test(test: ast.AST) -> bool:
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def runtime_imported_names(source: str) -> set[str] | None:
    """Names bound by runtime imports. None if the file will not parse.

    Skips bodies of `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` — those
    are the residual-real NameError class REVIEWING.md keeps open.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    imported: set[str] = set()

    def take_import(node: ast.Import | ast.ImportFrom) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".", 1)[0])
                imported.add(alias.name.split(".", 1)[0])
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            imported.add(alias.asname or alias.name)

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if _is_type_checking_test(node.test):
                # Still walk the else branch; skip the TYPE_CHECKING body.
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            take_import(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            take_import(node)

    Visitor().visit(tree)
    return imported


def is_disproved_by_file(f: ReaderFinding, source: str) -> bool:
    """True when every claimed name has a runtime import in the full file."""
    names = claimed_names(f)
    if not names:
        return False
    imported = runtime_imported_names(source)
    if imported is None:
        return False
    return all(n in imported for n in names)


ResolveFile = Callable[[str], str | None]


def drop_disproved_import_findings(
    rv: ReaderVerdict,
    resolve_file: ResolveFile,
) -> tuple[ReaderVerdict, list[ReaderFinding]]:
    """Return (possibly filtered verdict, dropped findings).

    `resolve_file(path)` returns the file bytes at the reviewed head, or
    None when the file cannot be fetched — those findings are kept.
    Non-Python paths are never settled here.

    risk_score is left alone: the frozen instrument's score is not ours to
    rewrite. Callers that render reasons from findings will see the drop;
    settle_reader_verdict records a weight-0 notice when anything was dropped
    so a FLAGGED empty-reason check run is not silent about why.
    """
    kept: list[ReaderFinding] = []
    dropped: list[ReaderFinding] = []
    for f in rv.findings:
        if not looks_like_missing_import_finding(f) or not f.file.endswith(".py"):
            kept.append(f)
            continue
        source = resolve_file(f.file)
        if source is not None and is_disproved_by_file(f, source):
            dropped.append(f)
            continue
        kept.append(f)
    if not dropped:
        return rv, []
    return rv.model_copy(update={"findings": kept}), dropped


def settlement_notice(dropped: list[ReaderFinding]):
    """Weight-0 reason so a score-flagged, findings-empty verdict stays honest."""
    from .models import Reason

    if not dropped:
        return None
    labels = "; ".join(
        f"{d.file}: {d.category_slug} ({claimed_names(d) or ['?']})" for d in dropped
    )
    return Reason(
        rule=SETTLED_MISSING_IMPORT,
        label=f"Dropped {len(dropped)} finding(s) disproved by runtime import at head — {labels}",
        weight=0.0,
    )


def settle_many(
    findings: Iterable[ReaderFinding], resolve_file: ResolveFile
) -> list[ReaderFinding]:
    """Test helper — filter a bare finding list the same way."""
    rv = ReaderVerdict(risk_score=0, rationale="", findings=list(findings))
    kept, _ = drop_disproved_import_findings(rv, resolve_file)
    return list(kept.findings)


def looks_like_schema_dependency_finding(f: ReaderFinding) -> bool:
    slug = f.category_slug.lower().removeprefix("reader:")
    if slug in _SCHEMA_SLUGS:
        return True
    desc = f.description.lower()
    return "migrat" in desc and any(
        w in desc for w in ("missing", "no migration", "not migrated", "unmigrated")
    )


def claimed_columns(f: ReaderFinding) -> list[tuple[str, str]]:
    """(table, column) pairs the finding asserts are not in the schema.

    A bare table name with no `.column` (the whole-new-table shape) yields
    nothing on its own — see the module docstring for why that claim needs a
    different check. Its mere PRESENCE anywhere in the description empties
    this out entirely, even alongside a resolvable pair: Doug's own review
    of this file (PR #49, reader:overly-broad-regex-match) found that a
    whole-table claim mixed with an unrelated real `table.column` mention
    (e.g. "`deep_read_counters` … extends verdicts.id via a foreign key")
    let the incidental pair settle a finding whose actual disputed claim was
    never checked. We cannot tell which mention is the real claim, so we
    settle neither rather than guess. Empty ⇒ we cannot settle it.
    """
    if _NAME_IN_BACKTICKS.search(f.description):
        return []
    return list(dict.fromkeys(_TABLE_DOT_COLUMN.findall(f.description)))


ResolveSchema = Callable[[str], "frozenset[str] | None"]


def is_disproved_by_schema(f: ReaderFinding, resolve_schema: ResolveSchema) -> bool:
    """True when every claimed (table, column) already exists in the live schema.

    `resolve_schema(table)` returns None for "cannot tell" — table not
    found, or no database configured — and None must never read as "absent";
    the finding stays live until something can actually confirm the column
    is not there.
    """
    pairs = claimed_columns(f)
    if not pairs:
        return False
    for table, column in pairs:
        columns = resolve_schema(table)
        if columns is None or column not in columns:
            return False
    return True


def drop_disproved_schema_findings(
    rv: ReaderVerdict,
    resolve_schema: ResolveSchema,
) -> tuple[ReaderVerdict, list[ReaderFinding]]:
    """Same contract as drop_disproved_import_findings, for the schema class.

    risk_score is left alone for the same reason: the frozen instrument's
    score is not ours to rewrite.
    """
    kept: list[ReaderFinding] = []
    dropped: list[ReaderFinding] = []
    for f in rv.findings:
        if not looks_like_schema_dependency_finding(f):
            kept.append(f)
            continue
        if is_disproved_by_schema(f, resolve_schema):
            dropped.append(f)
            continue
        kept.append(f)
    if not dropped:
        return rv, []
    return rv.model_copy(update={"findings": kept}), dropped


def schema_settlement_notice(dropped: list[ReaderFinding]):
    """Weight-0 reason so a score-flagged, findings-empty verdict stays honest."""
    from .models import Reason

    if not dropped:
        return None
    labels = "; ".join(
        f"{d.file}: {d.category_slug} ({claimed_columns(d) or ['?']})" for d in dropped
    )
    return Reason(
        rule=SETTLED_SCHEMA_DEPENDENCY,
        label=f"Dropped {len(dropped)} finding(s) disproved by the live schema — {labels}",
        weight=0.0,
    )
