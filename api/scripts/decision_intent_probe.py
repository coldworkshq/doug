"""Derangement check — is the reader reading the decisions, or the diff?

The one experiment that decides whether decision-record intent is real or
theater. Two arms over the same pull requests:

  matched  — each PR with the decisions that actually bear on it.
  deranged — each PR with another PR's decisions, by derangement so no PR
             keeps its own.

If deviation findings fire at the same rate on both arms, the reader is
pattern-matching the diff and the records are decoration. Experiment B v2
set the shape to beat on tickets: HIGH-severity deviations on 4% of
matched PRs against 100% of mismatched, alignment 80 versus 2.

This does NOT gate shipping (ADR-0007) — the feature is live either way,
because a job-summary note cannot hurt anyone. It gates *belief*.

Pre-register the bar in workspace/research/phase1-entry-preregistration.md
before running. Suggested, matching B v2's structure:

  PASS  deranged HIGH-severity rate >= 3x matched, and mean alignment on
        the matched arm exceeds the deranged arm by >= 30 points.
  FAIL  the arms are within noise of each other — the records are not
        being read, and the feature should be pulled rather than polished.

    ANTHROPIC_API_KEY=... GITHUB_TOKEN=... \\
      uv run python scripts/decision_intent_probe.py drewjst/doug --limit 40

Reads are sequential and small-n by construction; this is not a Batches
job. Cost is roughly 2 reads per PR.
"""

import argparse
import functools
import json
from pathlib import Path

from doug import intent, intent_providers, reader
from doug.backtest.harvest import resolve_token
from doug.review import fetch_pr

print = functools.partial(print, flush=True)  # noqa: A001

OUT = Path(".backtest-cache/decision-intent-probe")
SEED = 0


def _derange(n: int, seed: int = SEED) -> list[int]:
    """A permutation with no fixed point, so no PR keeps its own records.

    Sattolo's algorithm gives a single cycle, which is a derangement for
    n >= 2 and needs no rejection loop.
    """
    import random

    rng = random.Random(seed)
    idx = list(range(n))
    for i in range(n - 1, 0, -1):
        j = rng.randrange(i)  # strictly less than i — this is what forbids fixed points
        idx[i], idx[j] = idx[j], idx[i]
    return idx


def _high(findings) -> int:
    return sum(1 for f in findings if f.severity == "high")


def collect(gh, owner: str, repo: str, limit: int) -> list[dict]:
    """PRs that have relevant binding decisions. Others cannot be tested."""
    docs = intent_providers.fetch(gh, owner, repo)
    n_ok = sum(1 for d in docs if d.status == "accepted")
    print(f"{len(docs)} decision records, {n_ok} accepted")
    if not docs:
        print("no decision records in this repo — nothing to test")
        return []

    pulls = gh.rest.pulls.list(
        owner=owner, repo=repo, state="closed", sort="created",
        direction="desc", per_page=min(limit, 100),
    ).parsed_data[:limit]

    rows = []
    for p in pulls:
        if not p.merged_at:
            continue
        meta, diff = fetch_pr(gh, owner, repo, p.number)
        if not diff:
            continue
        chosen = [intent.truncate(d) for d in intent.select(docs, meta.title, meta.files)]
        if not chosen:
            continue  # no decision bears on this PR; the arms would be identical
        rows.append({"meta": meta, "diff": diff, "docs": chosen})
    print(f"{len(rows)} PRs carry at least one relevant decision")
    return rows


def run(rows: list[dict]) -> dict:
    if len(rows) < 2:
        print("need at least 2 testable PRs to derange")
        return {}
    order = _derange(len(rows))
    assert all(i != j for i, j in enumerate(order)), "derangement has a fixed point"

    out = {"matched": [], "deranged": []}
    for i, row in enumerate(rows):
        for arm, docs in (("matched", row["docs"]), ("deranged", rows[order[i]]["docs"])):
            try:
                # An offline research run holds no installation, so it
                # charges the sentinel scope like every other un-tenanted
                # caller. It normally runs against no ledger at all, in
                # which case nothing counts it — but a probe pointed at a
                # deployment that HAS one must not spend a customer's
                # budget on an experiment.
                rv = reader.read_with_decisions(
                    row["meta"], row["diff"], docs, scope=reader.SENTINEL_SCOPE
                )
            except reader.ReaderError as e:
                print(f"  #{row['meta'].number} {arm}: read failed ({e})")
                continue
            out[arm].append({
                "pr": row["meta"].number,
                "alignment": rv.intent_alignment,
                "high": _high(rv.deviation_findings),
                "deviations": [d.model_dump() for d in rv.deviation_findings],
                "refs": [d.id for d in docs],
            })
            print(
                f"  #{row['meta'].number} {arm}: alignment {rv.intent_alignment}"
                f" · {len(rv.deviation_findings)} deviations ({_high(rv.deviation_findings)} high)"
            )
    return out


def report(out: dict) -> int:
    if not out or not out["matched"]:
        print("no reads completed")
        return 1
    if not out.get("deranged"):
        # Matched-only quiet looks like PASS when ratio is inf against an
        # empty deranged arm — that is a false integrity pass.
        print("no deranged reads completed — cannot evaluate the bar")
        return 1
    stats = {}
    for arm, rows in out.items():
        n = len(rows)
        stats[arm] = {
            "n": n,
            "high_rate": sum(1 for r in rows if r["high"]) / n if n else 0.0,
            "alignment": sum(r["alignment"] for r in rows) / n if n else 0.0,
        }
        print(
            f"{arm:>9}: n={n} · HIGH-severity deviation on {stats[arm]['high_rate']:.0%}"
            f" of PRs · mean alignment {stats[arm]['alignment']:.0f}"
        )

    m, d = stats["matched"], stats["deranged"]
    ratio = (d["high_rate"] / m["high_rate"]) if m["high_rate"] else float("inf")
    gap = m["alignment"] - d["alignment"]
    print(
        f"\nderanged/matched HIGH ratio: {ratio:.1f}x (bar >=3)"
        f" · alignment gap: {gap:.0f} (bar >=30)"
    )
    ok = ratio >= 3 and gap >= 30
    print(
        "BAR: PASS — the reader is reading the records"
        if ok
        else "BAR: FAIL — arms are too close; the records are not being read"
    )
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    owner, name = args.repo.split("/", 1)

    if not reader.enabled():
        print("set DOUG_READER=1")
        return 1

    from githubkit import GitHub

    gh = GitHub(resolve_token(None))
    rows = collect(gh, owner, name, args.limit)
    out = run(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arms.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {OUT / 'arms.json'}")
    return report(out)


if __name__ == "__main__":
    raise SystemExit(main())
