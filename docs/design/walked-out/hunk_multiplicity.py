#!/usr/bin/env python3
"""Measure hunk multiplicity for option-B finding identity on the convergence eval sample.

Read-only on the repo. Writes hunk_multiplicity.csv next to this script.
"""
import csv
import hashlib
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict

REPO = "/Users/andrew/Projects/doughq/repo"
EVAL = "/Users/andrew/Projects/doughq/workspace/research/two-lane-2026-08-11/convergence-eval-run1.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hunk_multiplicity.csv")


def git(*args):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"git {' '.join(args)} -> {r.returncode}: {r.stderr[:300]}")
    return r


_cache = {}


def merge_base(a, b):
    k = ("mb", a, b)
    if k not in _cache:
        _cache[k] = git("merge-base", a, b).stdout.strip()
    return _cache[k]


def is_ancestor(a, b):
    return git("merge-base", "--is-ancestor", a, b).returncode == 0


def hunks(base, head, path, with_context=False):
    """Return list of hunk content hashes for `path` in diff base..head.

    Hunk content = '+'/'-' lines (file headers excluded); optionally context lines too.
    """
    k = ("hunks", base, head, path, with_context)
    if k in _cache:
        return _cache[k]
    r = git("diff", "--unified=3", "--no-color", "--no-ext-diff", base, head, "--", path)
    out = []
    cur = None
    in_file_hdr = True
    for line in r.stdout.splitlines():
        if line.startswith("diff --git"):
            in_file_hdr = True
            continue
        if in_file_hdr and (line.startswith("---") or line.startswith("+++") or line.startswith("index ")
                            or line.startswith("new file") or line.startswith("deleted file")
                            or line.startswith("similarity") or line.startswith("rename")
                            or line.startswith("old mode") or line.startswith("new mode")
                            or line.startswith("Binary files")):
            continue
        if line.startswith("@@"):
            in_file_hdr = False
            if cur is not None:
                out.append(cur)
            cur = []
            continue
        if cur is None:
            continue
        if line.startswith("+") or line.startswith("-"):
            cur.append(line)
        elif line.startswith(" ") or line == "":
            if with_context:
                cur.append(line)
        elif line.startswith("\\"):  # "\ No newline at end of file"
            if with_context:
                cur.append(line)
    if cur is not None:
        out.append(cur)
    hashes = [hashlib.sha1("\n".join(h).encode("utf-8", "surrogateescape")).hexdigest()[:12] for h in out]
    _cache[k] = hashes
    return hashes


def name_only(a, b):
    k = ("names", a, b)
    if k not in _cache:
        _cache[k] = set(git("diff", "--name-only", a, b).stdout.split("\n")) - {""}
    return _cache[k]


def classify_b(hf, ht):
    """Option B outcome given hunk-hash lists for from and to."""
    if not hf:
        return "file-not-in-from-diff"
    cf, ct = Counter(hf), Counter(ht)
    if cf == ct:
        return "by-construction"
    if not (set(cf) & set(ct)):
        return "resolved"
    # partial: distinguish "all from-hunks survive, to has extra/changed others" from "some survive"
    if all(ct[h] >= n for h, n in cf.items()):
        return "unknown(partial:all-survive+extra)"
    return "unknown(partial)"


def nbucket(n):
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 3:
        return "2-3"
    return "4+"


def main():
    d = json.load(open(EVAL))
    pairs = [p for p in d["pairs"] if p["from_head_sha"] and p["to_head_sha"]]
    assert len(pairs) == 76, len(pairs)

    # sample re-derivation
    frame = [p for p in pairs if any(c["state"] == "resolved" for c in p["classifications"])]
    assert len(frame) == 75, len(frame)
    frame.sort(key=lambda p: (p["from_verdict_id"], p["to_verdict_id"]))
    random.Random(20260811).shuffle(frame)
    cum = 0
    sample_ids = set()
    for p in frame:
        n = sum(1 for c in p["classifications"] if c["state"] == "resolved")
        sample_ids.add((p["from_verdict_id"], p["to_verdict_id"]))
        cum += n
        if cum >= 40:
            break
    assert len(sample_ids) == 13 and cum == 43, (len(sample_ids), cum)

    rows = []
    for p in pairs:
        f, t = p["from_head_sha"], p["to_head_sha"]
        pid = (p["from_verdict_id"], p["to_verdict_id"])
        base = merge_base("origin/main", f)
        base_to = merge_base("origin/main", t)
        linear = is_ancestor(f, t)
        touched_set = name_only(f, t)
        for c in p["classifications"]:
            if c["state"] != "resolved":
                continue
            F = c["file"]
            hf = hunks(base, f, F)
            ht = hunks(base, t, F)
            hf_ctx = hunks(base, f, F, with_context=True)
            ht_ctx = hunks(base, t, F, with_context=True)
            # per-side base variant (three-dot compare semantics for each read)
            ht_b2 = hunks(base_to, t, F)
            rows.append({
                "from_verdict_id": pid[0],
                "to_verdict_id": pid[1],
                "pr": p["group"]["pr_number"],
                "in_sample": pid in sample_ids,
                "from_sha": f[:10],
                "to_sha": t[:10],
                "base": base[:10],
                "base_to": base_to[:10],
                "same_base": base == base_to,
                "linear": linear,
                "rule": c["rule"],
                "file": F,
                "n_hunks_from": len(hf),
                "n_hunks_to": len(ht),
                "n_bucket": nbucket(len(hf)),
                "n_common": sum((Counter(hf) & Counter(ht)).values()),
                "optB": classify_b(hf, ht),
                "optB_ctx": classify_b(hf_ctx, ht_ctx),
                "optB_base_to": classify_b(hf, ht_b2),
                "file_touched": F in touched_set,
                "label": c["label"][:100].replace("\n", " "),
            })

    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def report(rs, title):
        print(f"\n=== {title}: n={len(rs)} ===")
        print("n_hunks_from buckets:", dict(sorted(Counter(r["n_bucket"] for r in rs).items())))
        print("optB outcomes:", dict(Counter(r["optB"] for r in rs).most_common()))
        print("file-level touched:", Counter(r["file_touched"] for r in rs))
        xt = defaultdict(Counter)
        for r in rs:
            xt[("touched" if r["file_touched"] else "untouched")][r["optB"]] += 1
        for k in sorted(xt):
            print(f"  {k:9s}", dict(xt[k]))
        xb = defaultdict(Counter)
        for r in rs:
            xb[("touched" if r["file_touched"] else "untouched", r["n_bucket"])][r["optB"]] += 1
        for k in sorted(xb):
            print(f"  {k[0]:9s} n={k[1]:3s}", dict(xb[k]))
        touched = [r for r in rs if r["file_touched"]]
        print("touched on single-hunk files:", sum(1 for r in touched if r["n_hunks_from"] == 1), "of", len(touched))
        mt = [r for r in touched if r["n_hunks_from"] > 1]
        print("touched multi-hunk:", len(mt), dict(Counter(r["optB"] for r in mt)))
        print("ctx-variant changes:", sum(1 for r in rs if r["optB"] != r["optB_ctx"]),
              [(r["optB"], r["optB_ctx"]) for r in rs if r["optB"] != r["optB_ctx"]])
        print("per-side-base variant changes:", sum(1 for r in rs if r["optB"] != r["optB_base_to"]),
              "(pairs with differing base:", len({(r['from_verdict_id'], r['to_verdict_id']) for r in rs if not r['same_base']}), ")")
        print("nonlinear rows:", [(r["from_verdict_id"], r["to_verdict_id"], r["pr"], r["file"], r["n_hunks_from"], r["optB"], r["file_touched"]) for r in rs if not r["linear"]])

    report(rows, "POPULATION")
    srows = [r for r in rows if r["in_sample"]]
    report(srows, "SAMPLE")
    print("\nSample touched units:")
    for r in sorted(srows, key=lambda r: (r["from_verdict_id"], r["to_verdict_id"], r["file"])):
        if r["file_touched"]:
            print(f"  {r['from_verdict_id']}->{r['to_verdict_id']} PR#{r['pr']:<3} {r['file']:40s} n_from={r['n_hunks_from']} n_to={r['n_hunks_to']} common={r['n_common']} {r['optB']:32s} ctx={r['optB_ctx']} rule={r['rule']}")
    print("\nSample untouched units:")
    for r in sorted(srows, key=lambda r: (r["from_verdict_id"], r["to_verdict_id"], r["file"])):
        if not r["file_touched"]:
            print(f"  {r['from_verdict_id']}->{r['to_verdict_id']} PR#{r['pr']:<3} {r['file']:40s} n_from={r['n_hunks_from']} {r['optB']:32s} rule={r['rule']}")
    print("\nCSV:", OUT)


if __name__ == "__main__":
    main()
