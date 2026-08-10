import json
from collections import Counter
from pathlib import Path

import pytest

from doug.example_pack_verifiers import (
    ReconstructedVerifierError,
    production_ingest_enqueue_callers,
    verify_pr78_fixture,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures/example_pack_v0/pr78-reconstructed.json"


def test_real_production_enqueue_inventory_is_exact_and_supplies_base_sha():
    callers = production_ingest_enqueue_callers(REPO_ROOT)

    assert Counter(receipt.path for receipt in callers) == {
        "api/doug/api.py": 1,
        "api/doug/worker.py": 2,
    }
    assert len(callers) == 3
    assert all(receipt.has_base_sha for receipt in callers)


def test_inventory_detects_supported_import_forms_and_excludes_tests(tmp_path):
    package = tmp_path / "api/doug"
    package.mkdir(parents=True)
    (tmp_path / "api/scripts").mkdir(parents=True)
    (tmp_path / "api/tests").mkdir(parents=True)
    (package / "calls.py").write_text(
        """from doug import ingest
from . import ingest as local_queue
import doug.ingest as aliased_queue
from doug.ingest import enqueue as direct_enqueue

ingest.enqueue(1, 2, 'o/r', 3, 'h', base_sha='b')
local_queue.enqueue(1, 2, 'o/r', 3, 'h')
aliased_queue.enqueue(1, 2, 'o/r', 3, 'h', base_sha='b')
direct_enqueue(1, 2, 'o/r', 3, 'h', base_sha='b')
"""
    )
    (tmp_path / "api/tests/test_calls.py").write_text(
        "from doug import ingest\ningest.enqueue(1, 2, 'o/r', 3, 'h')\n"
    )

    callers = production_ingest_enqueue_callers(tmp_path)

    assert len(callers) == 4
    assert [receipt.call_form for receipt in callers] == [
        "ingest.enqueue",
        "local_queue.enqueue",
        "aliased_queue.enqueue",
        "direct_enqueue",
    ]
    assert [receipt.has_base_sha for receipt in callers] == [True, False, True, True]
    assert {receipt.path for receipt in callers} == {"api/doug/calls.py"}


def test_pr78_reconstruction_has_literal_dispositions_and_full_receipts():
    dispositions = verify_pr78_fixture(REPO_ROOT, FIXTURE)

    assert {item.rule: item.disposition for item in dispositions} == {
        "reader:api-contract-change": "disproved",
        "reader:migration-version-conflict": "disproved",
        "reader:silent-work-drop": "verified_accepted_nonactionable",
        "reader:retry-exhaustion": "verified_accepted_nonactionable",
    }
    assert Counter(item.disposition for item in dispositions) == {
        "disproved": 2,
        "verified_accepted_nonactionable": 2,
    }
    assert all(item.evidence for item in dispositions)
    assert all(item.verifier_receipts for item in dispositions)
    api_result = dispositions[0]
    assert len(api_result.evidence) == 3
    assert all("base_sha=true" in receipt.detail for receipt in api_result.evidence)
    migration_result = dispositions[1]
    assert migration_result.verifier_receipts[0].result == "unapplied=[9]"
    for accepted in dispositions[2:]:
        assert accepted.evidence[0].kind == "accepted-contract"
        assert accepted.evidence[0].sha256 is not None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"exact_replay": True}, "exact_replay must be false"),
        ({"findings": [{"rule": "reader:api-contract-change"}]}, "rule set"),
    ],
)
def test_pr78_reconstruction_rejects_replay_claims_and_rule_drift(tmp_path, mutation, message):
    raw = json.loads(FIXTURE.read_text())
    raw.update(mutation)
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(ReconstructedVerifierError, match=message):
        verify_pr78_fixture(REPO_ROOT, changed)
