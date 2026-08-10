"""Deterministic verifiers for reconstructed Example Pack regressions."""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from . import migrations
from .example_pack import (
    EvidenceReceiptV0,
    FrozenModel,
    VerifierReceiptV0,
    sha256_hex,
)


class ReconstructedVerifierError(ValueError):
    """A reconstructed regression claim or its deterministic proof drifted."""


class CallerReceiptV0(FrozenModel):
    path: str
    line: int
    call_form: str
    has_base_sha: bool


class ReconstructedDispositionV0(FrozenModel):
    rule: str
    disposition: Literal["disproved", "verified_accepted_nonactionable"]
    evidence: tuple[EvidenceReceiptV0, ...]
    verifier_receipts: tuple[VerifierReceiptV0, ...]


_EXCLUDED_PARTS = frozenset({"tests", "__pycache__", ".venv", "venv"})
_EXPECTED_RULES = (
    "reader:api-contract-change",
    "reader:migration-version-conflict",
    "reader:silent-work-drop",
    "reader:retry-exhaustion",
)


def _import_aliases(tree: ast.AST) -> tuple[set[str], set[str], set[str]]:
    module_aliases: set[str] = set()
    direct_aliases: set[str] = set()
    qualified_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports_package = node.module == "doug" or (node.module is None and node.level > 0)
            if imports_package:
                for imported in node.names:
                    if imported.name == "ingest":
                        module_aliases.add(imported.asname or imported.name)
            imports_ingest = node.module == "doug.ingest" or (
                node.module == "ingest" and node.level > 0
            )
            if imports_ingest:
                for imported in node.names:
                    if imported.name == "enqueue":
                        direct_aliases.add(imported.asname or imported.name)
        elif isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name != "doug.ingest":
                    continue
                if imported.asname:
                    module_aliases.add(imported.asname)
                else:
                    qualified_roots.add("doug")
    return module_aliases, direct_aliases, qualified_roots


def _call_form(
    function: ast.expr,
    module_aliases: set[str],
    direct_aliases: set[str],
    qualified_roots: set[str],
) -> str | None:
    if isinstance(function, ast.Name) and function.id in direct_aliases:
        return function.id
    if not isinstance(function, ast.Attribute) or function.attr != "enqueue":
        return None
    if isinstance(function.value, ast.Name) and function.value.id in module_aliases:
        return f"{function.value.id}.enqueue"
    value = function.value
    if (
        isinstance(value, ast.Attribute)
        and value.attr == "ingest"
        and isinstance(value.value, ast.Name)
        and value.value.id in qualified_roots
    ):
        return f"{value.value.id}.ingest.enqueue"
    return None


def production_ingest_enqueue_callers(repo_root: Path) -> list[CallerReceiptV0]:
    """Inventory production ``ingest.enqueue`` calls using Python syntax."""

    root = Path(repo_root).resolve()
    paths: list[Path] = []
    for relative in (Path("api/doug"), Path("api/scripts")):
        directory = root / relative
        if directory.is_dir():
            paths.extend(directory.rglob("*.py"))

    receipts: list[CallerReceiptV0] = []
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        module_aliases, direct_aliases, qualified_roots = _import_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_form = _call_form(node.func, module_aliases, direct_aliases, qualified_roots)
            if call_form is None:
                continue
            receipts.append(
                CallerReceiptV0(
                    path=relative.as_posix(),
                    line=node.lineno,
                    call_form=call_form,
                    has_base_sha=any(keyword.arg == "base_sha" for keyword in node.keywords),
                )
            )
    return sorted(receipts, key=lambda item: (item.path, item.line, item.call_form))


def _accepted_contract_receipt(
    repo_root: Path, contracts: object, reference: object
) -> tuple[EvidenceReceiptV0, VerifierReceiptV0]:
    if not isinstance(contracts, dict) or not isinstance(reference, str):
        raise ReconstructedVerifierError("accepted contract reference is missing")
    contract = contracts.get(reference)
    if not isinstance(contract, dict):
        raise ReconstructedVerifierError(f"accepted contract {reference!r} is missing")
    try:
        relative = Path(contract["path"])
        line_start = int(contract["line_start"])
        line_end = int(contract["line_end"])
        reason = str(contract["reason"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReconstructedVerifierError(f"accepted contract {reference!r} is malformed") from exc
    root = repo_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ReconstructedVerifierError(
            f"accepted contract path {relative.as_posix()!r} is invalid"
        )
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        raise ReconstructedVerifierError(f"accepted contract {reference!r} line range is invalid")
    exact = "".join(lines[line_start - 1 : line_end]).encode("utf-8")
    locator = f"{relative.as_posix()}#L{line_start}-L{line_end}"
    return (
        EvidenceReceiptV0(
            kind="accepted-contract",
            locator=locator,
            sha256=sha256_hex(exact),
            detail=reason,
        ),
        VerifierReceiptV0(
            name="accepted-contract-reference",
            version="v0",
            result="verified",
            detail=f"{locator} exists and hashes to {sha256_hex(exact)}",
        ),
    )


def verify_pr78_fixture(
    repo_root: Path, fixture_path: Path
) -> tuple[ReconstructedDispositionV0, ...]:
    """Verify the explicit non-replay PR #78 reconstruction without an LLM."""

    raw = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "reconstructed-verifier-regression-v0":
        raise ReconstructedVerifierError("unexpected fixture schema")
    if raw.get("source_pr") != 78:
        raise ReconstructedVerifierError("source_pr must be 78")
    if raw.get("exact_replay") is not False:
        raise ReconstructedVerifierError("exact_replay must be false")
    findings = raw.get("findings")
    if not isinstance(findings, list):
        raise ReconstructedVerifierError("fixture findings must be a list")
    rules = tuple(item.get("rule") for item in findings if isinstance(item, dict))
    if rules != _EXPECTED_RULES or len(findings) != len(_EXPECTED_RULES):
        raise ReconstructedVerifierError("fixture rule set or order drifted")

    callers = production_ingest_enqueue_callers(repo_root)
    caller_counts = Counter(receipt.path for receipt in callers)
    expected_counts = Counter({"api/doug/api.py": 1, "api/doug/worker.py": 2})
    if caller_counts != expected_counts or not all(receipt.has_base_sha for receipt in callers):
        raise ReconstructedVerifierError(
            "production enqueue caller contract no longer disproves the finding"
        )
    api_evidence = tuple(
        EvidenceReceiptV0(
            kind="production-caller",
            locator=f"{receipt.path}#L{receipt.line}",
            detail=(f"call={receipt.call_form}; base_sha={str(receipt.has_base_sha).lower()}"),
        )
        for receipt in callers
    )
    api_verifier = VerifierReceiptV0(
        name="production-ingest-enqueue-callers",
        version="ast-v0",
        result="3 callers; all base_sha=true",
        detail="api.py has one production call and worker.py has two; tests excluded",
    )

    probe = raw.get("migration_probe")
    if not isinstance(probe, dict):
        raise ReconstructedVerifierError("migration_probe is missing")
    try:
        available = [int(version) for version in probe["available_versions"]]
        applied = {int(version) for version in probe["applied_versions"]}
        expected = [int(version) for version in probe["expected_unapplied_versions"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ReconstructedVerifierError("migration_probe is malformed") from exc
    plan = [(version, (f"fixture-version-{version}",)) for version in available]
    unapplied = migrations.unapplied_migrations(plan, applied)
    actual = [version for version, _ in unapplied]
    if actual != expected:
        raise ReconstructedVerifierError(
            f"migration membership result {actual} does not match {expected}"
        )
    migration_evidence = EvidenceReceiptV0(
        kind="migration-membership-probe",
        locator="fixture:migration_probe",
        detail=f"available={available}; applied={sorted(applied)}; unapplied={actual}",
    )
    migration_verifier = VerifierReceiptV0(
        name="unapplied-migrations",
        version="exact-membership-v0",
        result=f"unapplied={actual}",
        detail="Migration eligibility uses exact ledger membership, not contiguity.",
    )

    results: list[ReconstructedDispositionV0] = [
        ReconstructedDispositionV0(
            rule=_EXPECTED_RULES[0],
            disposition="disproved",
            evidence=api_evidence,
            verifier_receipts=(api_verifier,),
        ),
        ReconstructedDispositionV0(
            rule=_EXPECTED_RULES[1],
            disposition="disproved",
            evidence=(migration_evidence,),
            verifier_receipts=(migration_verifier,),
        ),
    ]
    contracts = raw.get("accepted_contracts")
    for finding in findings[2:]:
        evidence, verifier = _accepted_contract_receipt(
            Path(repo_root), contracts, finding.get("accepted_contract_ref")
        )
        results.append(
            ReconstructedDispositionV0(
                rule=finding["rule"],
                disposition="verified_accepted_nonactionable",
                evidence=(evidence,),
                verifier_receipts=(verifier,),
            )
        )
    return tuple(results)
