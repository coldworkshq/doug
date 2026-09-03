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
# that may already carry up to 100k characters of diff.
MAX_DOCS = 6
DOC_BUDGET = 12_000  # chars across all selected records
BODY_BUDGET = 4_000  # chars of any single record, matching the probe's ticket budget

# "Scored above zero" is not the same as "bears on this change". Decision
# records from one team share vocabulary, so almost every record scores
# slightly against almost every PR. Sending that tail asks the model to find a
# deviation from a decision that has nothing to do with the diff, which is how
# invented findings happen — and it degrades the derangement check, because
# both arms end up full of the same noise.
#
# Whether a record bears on a change at all is decided by `_bears_on`, not by
# a score threshold. Two ratio floors used to carry that job and could not
# (#264): a ratio is normalised by the change's vocabulary, so a cosmetic PR
# with five words in its title and path clears any floor on two incidental
# body hits. Measured on 2026-09-02 against Doug's own 28 accepted records,
# 20 of 22 unrelated changes — typo fixes, dependency bumps, a favicon —
# selected at least one record, most of them six. The floors stay for what
# they still do: MIN_RELEVANCE is a sanity bound on the score, and
# RELATIVE_FLOOR keeps the set tight around the best match rather than
# padding to MAX_DOCS.
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


ALLOWLIST_ENV = "DOUG_INTENT_INSTALLATIONS"


def enabled_for(installation_id: int | None) -> bool:
    """Is the experimental intent tier on for THIS installation?

    design-lock.md:62 ("overclaim #4 = scope #1") scopes this tier to a
    per-installation flag, default OFF, on for the dogfood install only,
    and holds it there until the pre-registered positive control passes.
    The 2026-07-31 derangement check FAILED its bar, so that control is
    still unrun and every deviation finding is unbelieved — an unset
    allowlist therefore enables nobody rather than everybody.

    This replaced a process-wide DOUG_INTENT env var, which turned the tier
    on for every installation the service reviewed. Doug's own intent probe
    flagged exactly that deviation against ADR-0008.
    """
    if installation_id is None:
        return False
    allow = os.environ.get(ALLOWLIST_ENV, "")
    return str(installation_id) in {i.strip() for i in allow.split(",") if i.strip()}


def _normalise(word: str) -> str:
    """Fold the two inflections that split one term into two tokens.

    `comments` and `comment`, `posted` and `post`, `deploys` and `deploy`
    must meet, or a record titled for the thing being changed is missed on a
    plural. Applied to both sides, so a wrong stem is harmless as long as it
    is the same wrong stem: `status` becomes `statu` in the record and in the
    change alike. Deliberately not a stemmer — no `-ing`, no vowel rules — so
    that `mode` and `model` stay different words.
    """
    if len(word) >= 5 and word.endswith("ed"):
        return word[:-2]
    if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    # The stop list is checked on the folded form as well as the raw one, or
    # an inflection the list does not spell out (`recorded`, `adrs`) survives
    # as a stem the list does. Doug flagged the one-sided check
    # (`reader:stopword-ordering`); three such words exist in the record set.
    out: set[str] = set()
    for w in _WORD.findall(text.lower()):
        if len(w) <= 2 or w in _STOP:
            continue
        folded = _normalise(w)
        if folded not in _STOP:
            out.add(folded)
    return out


def _file_names(files: list[str]) -> set[str]:
    """The name of each changed file, without its directories or extension.

    `doug/reader.py` contributes `reader`; `web/app/about/page.tsx`
    contributes `page`. Directory segments are the repository's layout, not
    the change's subject — `api`, `web`, `app` and `components` appear in
    nearly every record and were the main carrier of the #264 leak. An
    extension says even less: `lock` matched six records for a `uv.lock` bump.
    """
    out: set[str] = set()
    for path in files:
        base = path.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0] if "." in base[1:] else base
        out |= _tokens(stem.replace(".", " ").replace("_", " ").replace("-", " "))
    return out


def _change_tokens(title: str, files: list[str]) -> set[str]:
    return _tokens(title) | _file_names(files)


def _bears_on(title_words: set[str], file_names: set[str], doc: IntentDoc) -> bool:
    """Does this record bear on the change at all? Pure, no I/O, no model.

    Two rules, both about naming rather than overlap:

    1. The change must name the record in its TITLE — a word of the PR title,
       or the name of a changed file, appears in the record's title. A record
       whose title shares nothing with the change is rarely binding on it,
       and the alternative is what #264 measured: any long record contains
       `web` and `fix` somewhere in its prose.
    2. One shared word is a coincidence; two are a subject. The exception is
       the file's own name: a record titled for `reader` binds a change to
       `reader.py` whatever the PR is called, which is the property
       test_file_paths_are_tokenised_for_matching has always pinned.

    Neither rule is a tunable. Retuning MIN_RELEVANCE by feel was the fix this
    repo refused, because a ratio floor cannot separate "two incidental words
    over a short title" from "two words that name the subject".
    """
    head = _tokens(doc.title)
    change = title_words | file_names
    named = change & head
    if not named:
        return False
    if file_names & head:
        return True
    return len(named | (change & _tokens(doc.body))) >= 2


def relevance(
    title: str, files: list[str], doc: IntentDoc, *, change: set[str] | None = None
) -> float:
    """How much a decision bears on a change. Pure, no I/O, no model.

    Jaccard-style overlap, with the record's own title weighted above its
    body: a decision named "Freeze the reader's prompt" should surface for
    a PR touching reader.py even if the body never says "reader" again.
    File names are tokenised, so `doug/reader.py` matches a record about
    the reader; directories and extensions are not (see `_file_names`).

    This is the RANKING. Whether a record is a candidate at all is
    `_bears_on`, which select() applies first; a score above zero here does
    not mean the record reaches the model.

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
    title_words, file_names = _tokens(title), _file_names(files)
    change = title_words | file_names
    scored = [
        (relevance(title, files, d, change=change), d)
        for d in docs
        if d.status.lower() == BINDING and _bears_on(title_words, file_names, d)
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
