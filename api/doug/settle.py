"""Post-read settlements that do not touch the frozen prompt (ADR-0002).

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
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable

from .reader import ReaderFinding, ReaderVerdict

_IMPORT_SLUGS = frozenset(
    {
        "missing-import",
        "missing-module-import",
    }
)

_NAME_IN_BACKTICKS = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_IMPORT_WORD = re.compile(r"\bimport\s+([A-Za-z_][A-Za-z0-9_]*)")


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
    """Names the finding asserts are absent. Empty ⇒ we cannot settle it."""
    found: list[str] = []
    for rx in (_NAME_IN_BACKTICKS, _IMPORT_WORD):
        found.extend(rx.findall(f.description))
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
        rule="settled-missing-import",
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
