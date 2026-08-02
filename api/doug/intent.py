"""Intent surface — the decisions a change should be judged against.

The capability this feeds is the one no incumbent reviewer has: not "is
this code buggy" but "is this code doing what we already decided". The
agent-PR failure mode is competent code implementing the wrong thing,
and that is invisible to a reviewer reading the diff in a vacuum.

This module owns two things and nothing else: the contract a decision
record must satisfy, and the deterministic choice of which records go in
front of the model. Fetching lives in intent_providers; the read lives
in reader.

Selection is deliberately model-free. Routing is not a judgement call,
and a model-selected record set would make the derangement check
uninterpretable — a null result could mean "the reader ignores intent"
or "selection handed it the wrong records", with no way to tell which.
"""

import os
import re

from pydantic import BaseModel

# Enough decisions to cover a change, few enough to stay inside a read
# that is already carrying 30k characters of diff.
MAX_DOCS = 6
DOC_BUDGET = 12_000  # chars across all selected records
BODY_BUDGET = 4_000  # chars of any single record, matching the probe's ticket budget

# Two floors, because "scored above zero" is not the same as "bears on this
# change". Decision records from one team share vocabulary, so almost every
# record scores slightly against almost every PR. Sending that tail asks the
# model to find a deviation from a decision that has nothing to do with the
# diff, which is how invented findings happen — and it degrades the
# derangement check, because both arms end up full of the same noise.
#
# MIN_RELEVANCE drops changes that match nothing in particular (a dependency
# bump matches no decision, and should be read against none). RELATIVE_FLOOR
# keeps the set tight around the best match rather than padding to MAX_DOCS,
# and adapts to repos whose records are more or less verbose than these.
MIN_RELEVANCE = 0.25
RELATIVE_FLOOR = 0.5  # fraction of the top-scoring record

# Records in any other state are history, not policy. Feeding a superseded
# decision to the reader produces a confident finding that current code
# deviates from a rule the team already dropped — the exact failure this
# whole design is arranged to avoid (ADR-0006).
BINDING = "accepted"

_WORD = re.compile(r"[a-z0-9]+")
# Words that appear in every decision record and every PR title, so they
# carry no signal about which record bears on which change.
_STOP = frozenset(
    "the a an and or of to in for on with is are be by it this that we our "
    "use uses used using add adds added new not no from at as if then than "
    "when what which why how doug decision decisions adr record records "
    "status accepted context rejected consequences".split()
)


class IntentDoc(BaseModel):
    """One recorded decision, normalised across providers."""

    id: str  # "ADR-0004"
    title: str
    body: str
    status: str
    date: str | None = None
    ref: str  # provenance, carried into every deviation finding


def enabled() -> bool:
    return os.environ.get("DOUG_INTENT") == "1"


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def _change_tokens(title: str, files: list[str]) -> set[str]:
    return _tokens(title) | _tokens(" ".join(files).replace("/", " ").replace(".", " "))


def relevance(
    title: str, files: list[str], doc: IntentDoc, *, change: set[str] | None = None
) -> float:
    """How much a decision bears on a change. Pure, no I/O, no model.

    Jaccard-style overlap, with the record's own title weighted above its
    body: a decision named "Freeze the reader's prompt" should surface for
    a PR touching reader.py even if the body never says "reader" again.
    Path segments are tokenised, so `doug/reader.py` matches a record
    about the reader.

    `change` lets select() tokenise the PR once and reuse it across docs.
    """
    if change is None:
        change = _change_tokens(title, files)
    if not change:
        return 0.0
    head = _tokens(doc.title)
    body = _tokens(doc.body)
    if not head and not body:
        return 0.0
    hits_head = len(change & head)
    hits_body = len(change & body)
    # Normalised by the change's vocabulary, not the record's, so a long
    # record does not out-rank a short one purely by surface area.
    return (3 * hits_head + hits_body) / len(change)


def select(docs: list[IntentDoc], title: str, files: list[str]) -> list[IntentDoc]:
    """Binding records that bear on this change, best first, within budget.

    Returns [] when nothing is relevant. That is the common case and it is
    correct: most changes touch none of the recorded decisions, and a read
    against irrelevant records invites invented findings.
    """
    change = _change_tokens(title, files)
    scored = [
        (relevance(title, files, d, change=change), d)
        for d in docs
        if d.status.lower() == BINDING
    ]
    ranked = sorted(
        (sd for sd in scored if sd[0] >= MIN_RELEVANCE),
        key=lambda sd: (-sd[0], sd[1].id),  # id breaks ties, so runs reproduce
    )
    if not ranked:
        return []
    cutoff = max(MIN_RELEVANCE, ranked[0][0] * RELATIVE_FLOOR)
    ranked = [sd for sd in ranked if sd[0] >= cutoff]

    out: list[IntentDoc] = []
    used = 0
    for _score, doc in ranked[:MAX_DOCS]:
        # Charge what the model will actually see: truncate() runs after
        # select, so budgeting the raw body lets one oversized record
        # veto every later fit (and itself — BODY_BUDGET always fits).
        cost = len(doc.title) + min(len(doc.body), BODY_BUDGET)
        if used + cost > DOC_BUDGET:
            continue
        out.append(doc)
        used += cost
    return out


def truncate(doc: IntentDoc) -> IntentDoc:
    if len(doc.body) <= BODY_BUDGET:
        return doc
    return doc.model_copy(update={"body": doc.body[:BODY_BUDGET] + "\n[record truncated]"})
