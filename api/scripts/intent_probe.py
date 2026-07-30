"""Intent/deviation probe — does the reader actually read the ticket?

Experiment B, pre-registered in
workspace/research/phase1-entry-preregistration.md before any read. The
capability under test is the one no incumbent reviewer has: compare a PR
against the intent surface (its linked ticket) and report deviations.
Runs on grafana — the only harvested repo where issue linkage is dense
enough (2,054/12,000 strong links, 16/57 defects linked; sentry has zero
linked defects).

Three arms: `matched` (diff + its own ticket, n=100), `mismatched` (30 of
those with tickets swapped by derangement — the integrity check: if
deviation findings don't fire on a wrong ticket, the reader is not reading
intent), and `diffonly` (no-intent reads for sampled PRs Experiment 1b
didn't cover). The kill bar lives on the mismatched arm.

    uv run python scripts/intent_probe.py build       # links + issue fetch + requests
    uv run python scripts/intent_probe.py submit matched|mismatched|diffonly
    uv run python scripts/intent_probe.py fetch matched|mismatched|diffonly
    uv run python scripts/intent_probe.py analyze     # bars + audit file
"""

import copy
import functools
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from llm_probe import EFFORT as BASE_EFFORT
from llm_probe import MAX_TOKENS, MODEL, SCHEMA, SYSTEM, _client, _diff_text
from rf_kamei import REPOS, load

from doug.backtest.curve import capture_curve
from doug.backtest.harvest import resolve_token

print = functools.partial(print, flush=True)  # noqa: A001

DIR = Path(".backtest-cache/intent-probe-v2")  # v1 artifacts kept for the record
PROBE_1B = Path(".backtest-cache/llm-probe-grafana")
N_SAMPLE = 100
N_MISMATCH = 30
MIN_ISSUE_BODY = 100  # chars; a bare title is not intent (pre-registered)
# v1's matched arm was 39% contaminated by stale refs — `fix #1970`-style
# quotes resolving to 2014-era issues. Modern grafana issues are 6-digit;
# the floor kills the junk without reading any reader output (non-circular).
MIN_ISSUE_NUMBER = 50_000
TICKET_BUDGET = 4000
SEED = 0
LINK = re.compile(
    r"(?:fixes|closes|resolves|fix|close|resolve)\s+"
    r"(?:#|https://github\.com/[\w-]+/[\w-]+/issues/)(\d+)",
    re.I,
)

INTENT_SYSTEM = SYSTEM + (
    " You are ALSO given the issue/ticket this PR claims to resolve. Compare "
    "the ticket's intent with what the diff actually does and report "
    "deviations: things the ticket asks for that the PR does not do "
    "(missing-from-pr), material changes the ticket does not sanction "
    "(beyond-ticket), and places where the PR contradicts the ticket "
    "(contradicts-ticket). Routine implementation detail the ticket leaves "
    "open is NOT a deviation."
)

INTENT_SCHEMA = copy.deepcopy(SCHEMA)
INTENT_SCHEMA["properties"]["intent_alignment"] = {
    "type": "integer",
    "description": "0-100: how fully and faithfully the diff implements the ticket's intent.",
}
INTENT_SCHEMA["properties"]["deviation_findings"] = {
    "type": "array",
    "description": (
        "Gaps between ticket intent and diff behavior; empty if the PR "
        "does what the ticket asks."
    ),
    "items": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["missing-from-pr", "beyond-ticket", "contradicts-ticket"],
            },
            "description": {"type": "string"},
            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["type", "description", "severity"],
        "additionalProperties": False,
    },
}
INTENT_SCHEMA["required"] = [*SCHEMA["required"], "intent_alignment", "deviation_findings"]


def _linked_pairs():
    prs, defects = load(*REPOS["grafana"])
    pairs = []
    for p in prs:
        m = LINK.search(p.body or "")
        if (
            m
            and int(m.group(1)) >= MIN_ISSUE_NUMBER
            and p.file_details
            and any(f.patch for f in p.file_details)
        ):
            pairs.append((p, int(m.group(1))))
    return pairs, defects


def _fetch_issue(gh, number: int, cache: dict) -> dict | None:
    """Issue title/body, cached; None for PR-refs, gone issues, thin bodies."""
    key = str(number)
    if key in cache:
        return cache[key] or None
    from githubkit.utils import UNSET

    try:
        data = gh.rest.issues.get(owner="grafana", repo="grafana", issue_number=number).parsed_data
        # githubkit models absent fields as UNSET, not None — a real issue
        # has pull_request UNSET; a PR-ref has it populated.
        if data.pull_request is not UNSET and data.pull_request is not None:
            cache[key] = None
        elif len(data.body or "") < MIN_ISSUE_BODY:
            cache[key] = None
        else:
            cache[key] = {"title": data.title, "body": (data.body or "")[:TICKET_BUDGET]}
    except Exception:
        cache[key] = None
    return cache[key] or None


def _request(pr, ticket: dict | None, tag: str) -> dict:
    diff, truncated = _diff_text(pr)
    user = (
        f"Title: {pr.title}\n"
        f"Files changed: {', '.join(pr.files)}\n"
        + ("[diff truncated at budget]\n" if truncated else "")
        + f"\n{diff}"
    )
    if ticket is not None:
        user = (
            "Ticket (the issue this PR claims to resolve):\n"
            f"{ticket['title']}\n\n{ticket['body']}\n\n---\n" + user
        )
    return {
        "custom_id": f"{tag}-{pr.number}",
        "params": {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "output_config": {
                "effort": BASE_EFFORT,
                "format": {
                    "type": "json_schema",
                    "schema": INTENT_SCHEMA if ticket is not None else SCHEMA,
                },
            },
            "system": INTENT_SYSTEM if ticket is not None else SYSTEM,
            "messages": [{"role": "user", "content": user}],
        },
    }


def build() -> int:
    from githubkit import GitHub

    pairs, defects = _linked_pairs()
    print(f"linked PRs with patch text: {len(pairs)}")
    DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DIR / "issues.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    gh = GitHub(resolve_token(None))

    # All qualifying defects first, then a seed-0 shuffle of clean linked
    # PRs taken in order until the sample fills — a uniform draw from the
    # qualified pool, without fetching 2,000 issues.
    defect_pairs = [(p, n) for p, n in pairs if p.number in defects]
    clean_pairs = [(p, n) for p, n in pairs if p.number not in defects]
    rng = np.random.default_rng(SEED)
    order = rng.permutation(len(clean_pairs))

    sample = []  # (pr, ticket)
    for p, n in defect_pairs:
        t = _fetch_issue(gh, n, cache)
        if t:
            sample.append((p, t))
    n_defects = len(sample)
    for i in order:
        if len(sample) >= N_SAMPLE:
            break
        p, n = clean_pairs[i]
        t = _fetch_issue(gh, n, cache)
        if t:
            sample.append((p, t))
    cache_path.write_text(json.dumps(cache))
    print(f"sample: {n_defects} defects + {len(sample) - n_defects} clean = {len(sample)}")

    matched = [_request(p, t, "mt") for p, t in sample]

    mm_idx = sorted(rng.choice(len(sample), N_MISMATCH, replace=False))
    # Derangement by rotation over a fixed shuffle: nobody keeps their ticket.
    perm = rng.permutation(N_MISMATCH)
    mismatched = []
    for j, i in enumerate(mm_idx):
        donor = mm_idx[perm[(j + 1) % N_MISMATCH]] if mm_idx[perm[j]] == i else mm_idx[perm[j]]
        mismatched.append(_request(sample[i][0], sample[donor][1], "mm"))

    covered = set(json.loads((PROBE_1B / "findings-main.json").read_text()))
    diffonly = [_request(p, None, "do") for p, _ in sample if str(p.number) not in covered]

    (DIR / "sample.json").write_text(json.dumps({
        "prs": [p.number for p, _ in sample],
        "defects": [p.number for p, _ in sample[:n_defects]],
        "mismatched": [sample[i][0].number for i in mm_idx],
        "model": MODEL, "effort": BASE_EFFORT, "seed": SEED,
        "min_issue_body": MIN_ISSUE_BODY,
    }, indent=2))
    for name, reqs in [("matched", matched), ("mismatched", mismatched), ("diffonly", diffonly)]:
        (DIR / f"requests-{name}.json").write_text(json.dumps(reqs))
        print(f"{name}: {len(reqs)} requests")
    return 0


def submit(arm: str) -> int:
    client = _client()
    requests = json.loads((DIR / f"requests-{arm}.json").read_text())
    batch = client.messages.batches.create(requests=requests)
    (DIR / f"batch-{arm}.json").write_text(json.dumps({"id": batch.id}))
    print(f"submitted {len(requests)} requests: {batch.id}")
    return 0


def fetch(arm: str) -> int:
    client = _client()
    batch_id = json.loads((DIR / f"batch-{arm}.json").read_text())["id"]
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            break
        print(f"{batch.processing_status}: {batch.request_counts}")
        time.sleep(60)
    out, errors = {}, []
    for result in client.messages.batches.results(batch_id):
        n = result.custom_id.split("-", 1)[1]
        if result.result.type != "succeeded":
            errors.append((result.custom_id, result.result.type))
            continue
        msg = result.result.message
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            out[n] = json.loads(text)
        except json.JSONDecodeError:
            errors.append((result.custom_id, f"unparseable ({msg.stop_reason})"))
    (DIR / f"findings-{arm}.json").write_text(json.dumps(out, indent=2))
    print(f"stored {len(out)} results; {len(errors)} errors: {errors[:10]}")
    return 0


def analyze() -> int:
    meta = json.loads((DIR / "sample.json").read_text())
    matched = json.loads((DIR / "findings-matched.json").read_text())
    mismatched = json.loads((DIR / "findings-mismatched.json").read_text())
    defects = set(meta["defects"])

    # (c) integrity. v1's binary any-deviation metric saturated (the reader
    # legitimately notes partial-implementation gaps on real pairs), so the
    # v2 pre-registered criterion is HIGH-severity deviations + alignment.
    def _hi(r) -> bool:
        return any(d["severity"] == "high" for d in r.get("deviation_findings", []))

    m_hi = sum(1 for r in matched.values() if _hi(r)) / len(matched)
    x_hi = sum(1 for r in mismatched.values() if _hi(r)) / len(mismatched)
    m_align = float(np.mean([r["intent_alignment"] for r in matched.values()]))
    x_align = float(np.mean([r["intent_alignment"] for r in mismatched.values()]))
    print(f"(c) INTEGRITY — matched n={len(matched)}, mismatched n={len(mismatched)}")
    print(f"  HIGH-sev deviation: matched {m_hi:.0%} · mismatched {x_hi:.0%}")
    print(f"  mean intent_alignment: matched {m_align:.0f} · mismatched {x_align:.0f}")
    passed = x_hi >= 0.80 and m_hi <= 0.15
    verdict = "PASS" if passed else "FAIL"
    print(f"  BAR (v2): mismatched HIGH-sev >=80% AND matched HIGH-sev <=15% -> {verdict}")
    sec = m_align >= 60 and x_align <= 20
    print(f"  secondary: matched align >=60 AND mismatched <=20 -> {'PASS' if sec else 'FAIL'}")

    # (b) audit file — every matched-arm deviation, for hand review
    lines = ["# Matched-arm deviation findings — hand audit (Experiment B)\n"]
    for n, r in sorted(matched.items(), key=lambda kv: int(kv[0])):
        devs = r.get("deviation_findings", [])
        if devs:
            lines.append(f"\n## PR {n} · alignment {r['intent_alignment']} · risk {r['risk_score']}"
                         f"{' · DEFECT' if int(n) in defects else ''}")
            for d in devs:
                lines.append(f"- [{d['type']} · {d['severity']}] {d['description']}")
    (DIR / "audit-matched-deviations.md").write_text("\n".join(lines))
    n_dev = sum(len(r.get("deviation_findings", [])) for r in matched.values())
    print(f"(b) audit file written: {n_dev} matched-arm deviation findings -> "
          f"{DIR / 'audit-matched-deviations.md'}")

    # (a) informational ranking delta
    do_path = DIR / "findings-diffonly.json"
    diffonly = json.loads(do_path.read_text()) if do_path.exists() else {}
    covered = json.loads((PROBE_1B / "findings-main.json").read_text())
    y, with_intent, without = [], [], []
    for n in meta["prs"]:
        base = diffonly.get(str(n)) or covered.get(str(n))
        if base and str(n) in matched:
            y.append(n in defects)
            with_intent.append(float(matched[str(n)]["risk_score"]))
            without.append(float(base["risk_score"]))
    a1 = capture_curve(list(zip(with_intent, y, strict=True))).auc
    a0 = capture_curve(list(zip(without, y, strict=True))).auc
    print(f"(a) informational — {len(y)} rows, {sum(y)} defects: "
          f"AUC diff+intent {a1:.3f} vs diff-only {a0:.3f} (no bar; tiny n)")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        return build()
    if cmd == "submit":
        return submit(sys.argv[2])
    if cmd == "fetch":
        return fetch(sys.argv[2])
    if cmd == "analyze":
        return analyze()
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
