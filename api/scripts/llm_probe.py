"""The LLM probe — does reading the diff beat the metadata ceiling?

Pre-registered in workspace/research/phase1-entry-preregistration.md
(2026-07-29): sample, bars, and kill conditions were fixed before any LLM
call. Every deterministic route (rules, single features, RandomForest) hits
the same ~0.54-0.61 AUC ceiling on sentry and nothing transfers to grafana —
diff *content* is the last untested information source. Three questions:

  (i)   does an LLM risk score out-rank the best deterministic baseline on
        rows the baseline never trained on;
  (ii)  do findings recur (distillable) or is every one bespoke (loop dead);
  (iii) do findings survive polarity inversion (ReDef counterfactual) — if
        they don't change, the reader is surface-matching and we stop.

Reads run on claude-opus-5 via the Batches API (50% rates), structured
output enforced by schema. Input per PR is title + file list + truncated
diff — no author, dates, or outcome. Findings are stored against PR number,
durable and joinable, which is the distillation loop's step 2.

    uv run python scripts/llm_probe.py build           # sample + requests + cost
    uv run python scripts/llm_probe.py submit main     # needs ANTHROPIC_API_KEY
    uv run python scripts/llm_probe.py fetch main      # poll + store findings
    uv run python scripts/llm_probe.py counterfactual  # build inverted requests
    uv run python scripts/llm_probe.py submit cf
    uv run python scripts/llm_probe.py fetch cf
    uv run python scripts/llm_probe.py analyze         # (i)/(ii)/(iii) vs bars

Add --grafana to any command for the portability run (Experiment 1b) —
same protocol on grafana-12k, artifacts in their own directory.
"""

import functools
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from rf_kamei import REPOS, fit_rf, load, matrix
from screen_features import history_index

from doug.backtest.curve import capture_curve
from doug.backtest.hotspots import learn_hotspot_segments
from doug.backtest.replay import replay

print = functools.partial(print, flush=True)  # noqa: A001

REPO = "sentry"  # --grafana switches both; sentry keeps its original paths
DIR = Path(".backtest-cache/llm-probe")
MODEL = "claude-opus-5"
MAX_TOKENS = 6000
EFFORT = "medium"
DIFF_BUDGET = 30_000  # chars; truncation is logged per PR
N_CLEAN = 230
N_COUNTERFACTUAL = 30
SEED = 0

# Pre-registration (ii) allows "manual merge of obvious synonyms, logged".
# This map IS the log. Conservative: lexical variants and strict synonyms
# only — no thematic stretches (e.g. race-condition and import-cycle stay
# separate from anything they merely resemble).
SLUG_MERGES = {
    "missing-error-handling": "error-handling-gap",
    "unhandled-exception": "error-handling-gap",
    "unhandled-io-error": "error-handling-gap",
    "behavior-regression": "behavior-change",
    "circular-import": "import-cycle",
    "import-cycle-risk": "import-cycle",
    "metric-cardinality": "metrics-cardinality",
    "unchecked-type-conversion": "type-coercion",
    "unsafe-type-coercion": "type-coercion",
    "dead-reference-after-module-removal": "dead-reference",
}

SYSTEM = (
    "You are reviewing a single pull request diff from a large production "
    "codebase. Judge the risk that this specific change introduces a defect "
    "that will later be reverted or hot-fixed. Flag concrete defect risks in "
    "the change itself — logic errors, unsafe migrations, concurrency "
    "hazards, error-handling gaps, contract mismatches — not style, tests, "
    "or hypothetical improvements. Most changes in a healthy repo are safe; "
    "score accordingly."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "risk_score": {
            "type": "integer",
            "description": (
                "0-100 risk that this change causes a revert or hotfix. "
                "Most PRs deserve <30; reserve >70 for changes you would block."
            ),
        },
        "rationale": {"type": "string", "description": "One or two sentences."},
        "findings": {
            "type": "array",
            "description": "Concrete defect risks in this change; empty if none.",
            "items": {
                "type": "object",
                "properties": {
                    "category_slug": {
                        "type": "string",
                        "description": (
                            "Short kebab-case defect pattern, reusable across "
                            "PRs — e.g. unsafe-migration, race-condition, "
                            "missing-null-check, api-contract-change."
                        ),
                    },
                    "description": {"type": "string"},
                    "file": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["category_slug", "description", "file", "severity"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["risk_score", "rationale", "findings"],
    "additionalProperties": False,
}


def _split():
    prs, defects = load(*REPOS[REPO])
    ordered = sorted(prs, key=lambda p: p.created_at)
    mid = len(ordered) // 2
    return prs, defects, ordered[:mid], ordered[mid:]


def _has_patch(pr) -> bool:
    return bool(pr.file_details) and any(f.patch for f in pr.file_details)


def _diff_text(pr, invert: bool = False) -> tuple[str, bool]:
    parts = []
    for f in pr.file_details or []:
        if not f.patch:
            continue
        patch = _invert_patch(f.patch) if invert else f.patch
        parts.append(f"### {f.filename} ({f.status}, +{f.additions}/-{f.deletions})\n{patch}")
    text = "\n\n".join(parts)
    return text[:DIFF_BUDGET], len(text) > DIFF_BUDGET


def _invert_patch(patch: str) -> str:
    """ReDef's counterfactual: flip diff polarity, added <-> deleted."""
    out = []
    for line in patch.splitlines():
        if line.startswith(("+++", "---")):
            out.append(line)
        elif line.startswith("+"):
            out.append("-" + line[1:])
        elif line.startswith("-"):
            out.append("+" + line[1:])
        else:
            out.append(line)
    return "\n".join(out)


def _request(pr, tag: str, invert: bool = False) -> dict:
    diff, truncated = _diff_text(pr, invert=invert)
    user = (
        f"Title: {pr.title}\n"
        f"Files changed: {', '.join(pr.files)}\n"
        + ("[diff truncated at budget]\n" if truncated else "")
        + f"\n{diff}"
    )
    return {
        "custom_id": f"{tag}-{pr.number}",
        "params": {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "output_config": {
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            "system": SYSTEM,
            "messages": [{"role": "user", "content": user}],
        },
    }


def build() -> int:
    prs, defects, older, newer = _split()
    defect_prs = sorted(
        (p for p in prs if p.number in defects and _has_patch(p)),
        key=lambda p: p.number,
    )
    newer_nums = {p.number for p in newer}
    clean_pool = sorted(
        (p for p in newer if p.number not in defects and _has_patch(p)),
        key=lambda p: p.number,
    )
    rng = np.random.default_rng(SEED)
    clean = [clean_pool[i] for i in sorted(rng.choice(len(clean_pool), N_CLEAN, replace=False))]

    sample = defect_prs + clean
    requests = [_request(p, "pr") for p in sample]
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "sample.json").write_text(json.dumps({
        "defects": [p.number for p in defect_prs],
        "clean": [p.number for p in clean],
        "newer_half": sorted(newer_nums & {p.number for p in sample}),
        "model": MODEL, "effort": EFFORT, "max_tokens": MAX_TOKENS,
        "diff_budget": DIFF_BUDGET, "seed": SEED,
    }, indent=2))
    (DIR / "requests-main.json").write_text(json.dumps(requests))

    bodies = [r["params"]["messages"][0]["content"] for r in requests]
    n_trunc = sum(1 for b in bodies if "[diff truncated" in b)
    in_chars = sum(len(b) for b in bodies) + len(SYSTEM) * len(requests)
    in_tok = in_chars / 3.6
    out_tok = 1200 * len(requests)  # thinking (medium) + JSON, rough
    cost = in_tok / 1e6 * 2.50 + out_tok / 1e6 * 12.50  # opus-5 batch rates
    print(
        f"sample: {len(defect_prs)} defects ({sum(1 for p in defect_prs if p.number in newer_nums)}"
        f" in newer half) + {len(clean)} clean (newer half) = {len(sample)} PRs"
    )
    print(f"truncated diffs: {n_trunc}/{len(requests)} at {DIFF_BUDGET} chars")
    print(
        f"estimated cost: ~{in_tok / 1e6:.1f}M in + ~{out_tok / 1e6:.1f}M out"
        f" ≈ ${cost:.2f} at batch rates"
    )
    return 0


def counterfactual() -> int:
    prs, defects, _, _ = _split()
    by = {p.number: p for p in prs}
    findings = json.loads((DIR / "findings-main.json").read_text())
    with_findings = sorted(
        int(n) for n, r in findings.items()
        if int(n) in defects and r.get("findings")
    )
    rng = np.random.default_rng(SEED)
    take = min(N_COUNTERFACTUAL, len(with_findings))
    picks = rng.choice(len(with_findings), take, replace=False)
    chosen = sorted(int(with_findings[i]) for i in picks)
    requests = [_request(by[n], "cf", invert=True) for n in chosen]
    (DIR / "requests-cf.json").write_text(json.dumps(requests))
    print(f"counterfactual: {take} defect PRs with findings, polarity-inverted")
    return 0


def _client():
    import anthropic

    # Gitignored; fallback when no env credential. One canonical location
    # regardless of which repo's probe is running.
    key_file = Path(".backtest-cache/llm-probe/api-key")
    if key_file.exists():
        return anthropic.Anthropic(api_key=key_file.read_text().strip())
    return anthropic.Anthropic()


def submit(which: str) -> int:
    client = _client()
    requests = json.loads((DIR / f"requests-{which}.json").read_text())
    batch = client.messages.batches.create(requests=requests)
    (DIR / f"batch-{which}.json").write_text(json.dumps({"id": batch.id}))
    print(f"submitted {len(requests)} requests: {batch.id}")
    return 0


def fetch(which: str) -> int:
    client = _client()
    batch_id = json.loads((DIR / f"batch-{which}.json").read_text())["id"]
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
            parsed = json.loads(text)
        except json.JSONDecodeError:
            errors.append((result.custom_id, f"unparseable ({msg.stop_reason})"))
            continue
        parsed["stop_reason"] = msg.stop_reason
        out[n] = parsed
    (DIR / f"findings-{which}.json").write_text(json.dumps(out, indent=2))
    print(f"stored {len(out)} results; {len(errors)} errors: {errors[:10]}")
    return 0


def analyze() -> int:
    meta = json.loads((DIR / "sample.json").read_text())
    findings = json.loads((DIR / "findings-main.json").read_text())
    prs, defects, older, newer = _split()
    hist = history_index(prs)
    by = {p.number: p for p in prs}
    train_defs = {p.number for p in older} & defects

    # (i) ranking, newer-half probe rows only (RF never trained on them)
    eval_nums = [n for n in meta["newer_half"] if str(n) in findings]
    eval_prs = [by[n] for n in eval_nums]
    y = [n in defects for n in eval_nums]
    llm = [float(findings[str(n)]["risk_score"]) for n in eval_nums]

    rf = fit_rf(matrix(older, hist), np.array([p.number in train_defs for p in older]))
    rf_s = rf.predict_proba(matrix(eval_prs, hist))[:, 1].tolist()
    learned = learn_hotspot_segments(older, train_defs)
    v3_s = {pr.number: s for pr, s, _ in replay(eval_prs, extra_hotspots=learned)}
    v3 = [v3_s[n] for n in eval_nums]
    size = [float(p.additions + p.deletions) for p in eval_prs]

    # Cross-repo RF (Tabassum OP): trained on the *other* repo's full
    # sample — on grafana this is the best deterministic point estimate
    # to date and belongs in the "best of" the LLM must beat.
    other = "grafana" if REPO == "sentry" else "sentry"
    o_prs, o_defs = load(*REPOS[other])
    rfx = fit_rf(
        matrix(o_prs, history_index(o_prs)),
        np.array([p.number in o_defs for p in o_prs]),
    )
    rfx_s = rfx.predict_proba(matrix(eval_prs, hist))[:, 1].tolist()

    scored = {"LLM": llm, "RF": rf_s, "RF-x": rfx_s, "v3": v3, "size": size}
    print(f"\n(i) RANKING — {len(eval_nums)} newer-half probe rows, {sum(y)} defects")
    aucs = {}
    for name, s in scored.items():
        curve = capture_curve(list(zip(s, y, strict=True)))
        aucs[name] = curve.auc
        print(
            f"  {name:<5} AUC {curve.auc:.3f}  "
            f"@20% {curve.capture_at(0.20):.0%}  @30% {curve.capture_at(0.30):.0%}"
        )
    best = max((n for n in aucs if n != "LLM"), key=lambda n: aucs[n])
    rng = np.random.default_rng(SEED)
    wins = 0
    for _ in range(1000):
        idx = rng.integers(0, len(y), len(y))
        if not any(y[i] for i in idx) or all(y[i] for i in idx):
            continue
        a = capture_curve([(llm[i], y[i]) for i in idx]).auc
        b = capture_curve([(scored[best][i], y[i]) for i in idx]).auc
        wins += a > b
    passed = aucs["LLM"] > aucs[best] and wins >= 900
    print(
        f"  best deterministic: {best} ({aucs[best]:.3f}); "
        f"paired bootstrap P(LLM>{best}) = {wins / 1000:.0%}"
    )
    print(f"  BAR: point estimate higher AND >=90% -> {'PASS' if passed else 'FAIL'}")

    # (ii) distillability — findings on defect PRs, synonym-merged (logged above)
    older_nums = {p.number for p in older}
    slug_findings = []  # (slug, pr_number)
    for n_str, r in findings.items():
        n = int(n_str)
        if n in defects:
            for f in r.get("findings", []):
                slug_findings.append((SLUG_MERGES.get(f["category_slug"], f["category_slug"]), n))
    slug_prs = defaultdict(set)
    for slug, n in slug_findings:
        slug_prs[slug].add(n)
    counts = Counter(s for s, _ in slug_findings)
    raw = Counter()
    for n_str, r in findings.items():
        if int(n_str) in defects:
            raw.update(f["category_slug"] for f in r.get("findings", []))
    raw_cov = sum(c for _, c in raw.most_common(10)) / len(slug_findings) if slug_findings else 0.0
    top10 = counts.most_common(10)
    coverage = sum(c for _, c in top10) / len(slug_findings) if slug_findings else 0.0
    big = [s for s, ps in slug_prs.items() if len(ps) >= 5]
    both_halves = [
        s for s, ps in slug_prs.items()
        if any(n in older_nums for n in ps) and any(n not in older_nums for n in ps)
    ]
    # Precision context on the newer-half probe rows: of rows carrying the
    # pattern, how many are defects, vs the probe-row base rate. Enriched
    # sample — lift is comparable within the probe, not to the population.
    base = sum(y) / len(y)
    slug_rows = defaultdict(set)
    for n in eval_nums:
        for f in findings[str(n)].get("findings", []):
            slug_rows[SLUG_MERGES.get(f["category_slug"], f["category_slug"])].add(n)
    print(
        f"\n(ii) DISTILLABILITY — {len(slug_findings)} findings on defect PRs, "
        f"{len(counts)} merged slugs ({len(raw)} raw; merge map in SLUG_MERGES); "
        f"raw top-10 coverage {raw_cov:.0%}"
    )
    for slug, c in top10:
        rows = slug_rows.get(slug, set())
        hit = sum(1 for n in rows if n in defects)
        prec = f"precision {hit}/{len(rows)} vs base {base:.0%}" if rows else "not on eval rows"
        print(f"  {slug:<28} {c:>3} findings on {len(slug_prs[slug]):>2} defect PRs · {prec}")
    print(
        f"  top-10 coverage {coverage:.0%} (bar >=30%) · "
        f"slugs on >=5 defect PRs: {len(big)} (bar >=3) · "
        f"slugs in both halves: {len(both_halves)} (bar >=1)"
    )
    ok = coverage >= 0.30 and len(big) >= 3 and len(both_halves) >= 1
    print(f"  BAR: {'PASS' if ok else 'FAIL — findings are bespoke, loop is dead at distillation'}")

    # (iii) counterfactual
    cf_path = DIR / "findings-cf.json"
    if cf_path.exists():
        cf = json.loads(cf_path.read_text())
        overlaps = []
        for n, r in cf.items():
            orig = {(f["category_slug"], f["file"]) for f in findings[n].get("findings", [])}
            new = {(f["category_slug"], f["file"]) for f in r.get("findings", [])}
            if orig:
                overlaps.append(len(orig & new) / len(orig))
        mean = float(np.mean(overlaps)) if overlaps else 0.0
        print(f"\n(iii) COUNTERFACTUAL — {len(overlaps)} PRs, mean finding overlap {mean:.0%}")
        verdict = "FAIL (ReDef reproduced — STOP)" if mean >= 0.50 else (
            "PASS" if mean <= 0.30 else "AMBIGUOUS — extend to 60 PRs")
        print(f"  BAR: >=50% fail / <=30% pass -> {verdict}")
    else:
        print("\n(iii) counterfactual not run yet")
    return 0


def main() -> int:
    global REPO, DIR
    args = [a for a in sys.argv[1:] if a != "--grafana"]
    if len(args) != len(sys.argv) - 1:
        REPO = "grafana"
        DIR = Path(".backtest-cache/llm-probe-grafana")
    cmd = args[0] if args else ""
    if cmd == "build":
        return build()
    if cmd == "submit":
        return submit(args[1])
    if cmd == "fetch":
        return fetch(args[1])
    if cmd == "counterfactual":
        return counterfactual()
    if cmd == "analyze":
        return analyze()
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
