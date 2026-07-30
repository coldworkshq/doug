"""Selecting which recorded decisions a change gets judged against.

The failure modes here are quiet ones: a superseded record reaching the
model produces a confident finding against a rule the team already
dropped, and an irrelevant record invites an invented deviation. Both
look like working software.
"""

import pytest

from doug import intent, intent_providers
from doug.intent import IntentDoc


def _doc(id_, title, body="", status="accepted"):
    return IntentDoc(id=id_, title=title, body=body, status=status, ref=f"docs/{id_}.md")


def test_superseded_records_never_reach_the_model():
    """The whole reason this reads status. `d_81e789` records that
    LLM-assisted scoring was rejected; ADR-0004 overturned it. Feeding the
    dead record would flag Doug's own shipped reader as a deviation."""
    docs = [
        _doc("ADR-0001", "No model in the scoring path", status="superseded"),
        _doc("ADR-0004", "Put the model in the scoring path"),
    ]
    chosen = intent.select(docs, "Speed up the model scoring path", ["doug/reader.py"])
    assert [d.id for d in chosen] == ["ADR-0004"]


@pytest.mark.parametrize("status", ["proposed", "rejected", "deprecated", "superseded"])
def test_only_accepted_records_are_binding(status):
    docs = [_doc("ADR-0001", "Freeze the reader prompt", status=status)]
    assert intent.select(docs, "Freeze the reader prompt", ["reader.py"]) == []


def test_status_matching_is_case_insensitive():
    docs = [_doc("ADR-0001", "Freeze the reader prompt", status="Accepted")]
    assert len(intent.select(docs, "reader prompt change", ["doug/reader.py"])) == 1


def test_irrelevant_records_are_not_sent():
    """Most changes touch none of the recorded decisions. Sending records
    anyway asks the model to find a deviation where none is possible."""
    docs = [_doc("ADR-0001", "Keep the outcome ledger in Postgres", "database storage")]
    assert intent.select(docs, "Fix a typo in the footer", ["web/app/footer.tsx"]) == []


def test_file_paths_are_tokenised_for_matching():
    """A decision about the reader must surface for a PR touching
    doug/reader.py even when the title never says 'reader'."""
    doc = _doc("ADR-0002", "Freeze the reader prompt and schema")
    assert intent.relevance("Tidy up", ["doug/reader.py"], doc) > 0
    assert intent.relevance("Tidy up", ["web/app/page.tsx"], doc) == 0


def test_title_matches_outrank_body_matches():
    """A record named for the thing being changed bears on it more than one
    that merely mentions it in passing."""
    named = _doc("ADR-0002", "Freeze the reader prompt", "unrelated prose here")
    mentions = _doc("ADR-0009", "Unrelated subject", "we also touch the reader prompt")
    title, files = "Change the reader prompt", ["doug/reader.py"]
    assert intent.relevance(title, files, named) > intent.relevance(title, files, mentions)


def test_selection_is_deterministic_on_ties():
    """Two runs over the same PR must send the same records, or the
    derangement check compares different reads."""
    docs = [_doc(f"ADR-000{i}", "Freeze the reader prompt") for i in (3, 1, 2)]
    once = intent.select(docs, "reader prompt", ["doug/reader.py"])
    twice = intent.select(list(reversed(docs)), "reader prompt", ["doug/reader.py"])
    assert [d.id for d in once] == [d.id for d in twice]


def test_selection_respects_the_document_budget():
    docs = [_doc(f"ADR-{i:04d}", "reader prompt", "x" * 5000) for i in range(10)]
    chosen = intent.select(docs, "reader prompt", ["doug/reader.py"])
    assert len(chosen) <= intent.MAX_DOCS
    assert sum(len(d.title) + len(d.body) for d in chosen) <= intent.DOC_BUDGET


def test_truncate_marks_what_it_cut():
    doc = _doc("ADR-0001", "t", "y" * (intent.BODY_BUDGET + 500))
    out = intent.truncate(doc)
    assert len(out.body) < len(doc.body)
    assert out.body.endswith("[record truncated]")


ADR = """---
title: Freeze the reader's prompt
status: accepted
date: 2026-07-29
---

## Context
Body text.
"""


def test_parse_record_extracts_the_contract():
    doc = intent_providers.parse_record("docs/decisions/ADR-0002-freeze.md", ADR)
    assert doc.id == "ADR-0002"
    assert doc.title == "Freeze the reader's prompt"
    assert doc.status == "accepted" and doc.date == "2026-07-29"
    assert doc.body.startswith("## Context")
    assert doc.ref == "docs/decisions/ADR-0002-freeze.md"


@pytest.mark.parametrize(
    "text",
    [
        "# Decision records\n\nA README, not a record.",       # no frontmatter
        "---\ntitle: No status\n---\nbody",                     # missing status
        "---\nstatus: accepted\n---\nbody",                     # missing title
        "---\ntitle: unterminated\nstatus: accepted\nbody",     # no closing fence
    ],
)
def test_parse_record_skips_non_records(text):
    """These directories hold READMEs and templates. A mis-parsed file
    would be handed to the model as team policy."""
    assert intent_providers.parse_record("docs/decisions/x.md", text) is None


def test_parse_record_keeps_unconventional_filenames():
    doc = intent_providers.parse_record("docs/decisions/use-postgres.md", ADR)
    assert doc.id == "use-postgres"


def test_derangement_never_leaves_a_pr_with_its_own_records():
    """The integrity check is meaningless if any PR is compared against
    its own decisions in the 'deranged' arm."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from decision_intent_probe import _derange

    for n in range(2, 60):
        order = _derange(n)
        assert sorted(order) == list(range(n)), "not a permutation"
        assert all(i != j for i, j in enumerate(order)), f"fixed point at n={n}"


def _real_records():
    from pathlib import Path

    d = Path(__file__).resolve().parents[2] / "docs" / "decisions"
    out = []
    for f in sorted(d.glob("*.md")):
        doc = intent_providers.parse_record(f"docs/decisions/{f.name}", f.read_text())
        if doc:
            out.append(doc)
    return out


def test_selection_on_dougs_own_records():
    """Synthetic docs cannot show the real failure: records written by one
    team share vocabulary, so nearly every record scores slightly against
    nearly every PR. Without a floor this sent six records for a ruff bump.

    Pins both halves — the right record surfaces, and unrelated changes
    trigger no read at all.
    """
    docs = _real_records()
    assert len(docs) >= 8, "Doug's own decision records are the fixture here"

    def sent(title, files):
        return [d.id for d in intent.select(docs, title, files)]

    assert sent("Tighten the reader prompt wording", ["doug/reader.py"])[0] == "ADR-0002"
    assert sent("Post Doug verdicts as PR comments", [".github/workflows/x.yml"])[0] == "ADR-0003"
    lema = sent("Read decisions from lema's hosted API", ["doug/intent_providers.py"])
    assert lema == ["ADR-0006"]

    # Changes that bear on no recorded decision must be read against none.
    assert sent("Bump ruff 0.14.1 to 0.14.2", ["api/pyproject.toml"]) == []
    assert sent("Fix a typo in the footer", ["web/components/footer.tsx"]) == []

    # And the set stays tight rather than padding out to MAX_DOCS.
    for title, files in [
        ("Tighten the reader prompt wording", ["doug/reader.py"]),
        ("Add a deviations table to the ledger", ["doug/store.py"]),
    ]:
        assert len(sent(title, files)) <= 3
