#!/usr/bin/env python3
"""Build the frozen inputs for the span-verification pass (span-verification.md).

Writes, under the scratchpad run dir:
  manifest.json   - per-finding record: ids, hashes, B outcome, marginal-set flag, mech GT
  batch_NN.md     - agent payload files (numbered hunks + findings), <=35KB of hunk text
Pure read-only on the repo. No model calls here.
"""
import json, os, re, subprocess, hashlib
from collections import Counter, defaultdict

REPO = "/Users/andrew/Projects/doughq/repo"
SCRATCH = "/private/tmp/claude-501/-Users-andrew-Projects-doughq/f806f2a4-4c58-4850-b004-7fffa418cbec/scratchpad"
RUN = os.path.join(SCRATCH, "span-verification")
os.makedirs(RUN, exist_ok=True)

def git(*a):
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True).stdout

def parse_hunks(base, head, path):
    """Ordered hunk texts (header+body) and content hashes (+/- lines only)."""
    texts, cur = [], None
    for line in git("diff", "--unified=3", "--no-color", "--no-ext-diff", base, head, "--", path).splitlines():
        if line.startswith("@@"):
            if cur is not None:
                texts.append(cur)
            cur = [line]
        elif cur is not None and not line.startswith(("+++", "---", "diff --git", "index ")):
            cur.append(line)
    if cur is not None:
        texts.append(cur)
    hashes = []
    for t in texts:
        body = "\n".join(l for l in t if l.startswith(("+", "-")))
        hashes.append(hashlib.sha1(body.encode("utf-8", "surrogateescape")).hexdigest()[:12])
    return ["\n".join(t) for t in texts], hashes

def tokens(label):
    t = set()
    t.update(re.findall(r"`([^`]+)`", label))
    t.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\(\)?", label))
    t.update(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", label))
    t.update(re.findall(r"'([^']{3,40})'", label))
    t.update(re.findall(r'"([^"]{3,40})"', label))
    return {x.strip() for x in t if len(x.strip()) >= 4}

def main():
    pop = json.load(open(os.path.join(SCRATCH, "span_population.json")))
    touched = [r for r in pop if r["touched"]]

    groups = defaultdict(list)
    for r in touched:
        groups[(tuple(r["pair"]), r["file"], r["from"], r["to"], r["base"])].append(r)

    manifest, payload_groups = [], []
    fid = 0
    for (pair, F, f, t, base), members in sorted(groups.items()):
        from_texts, from_hashes = parse_hunks(base, f, F)
        _, to_hashes = parse_hunks(base, t, F)
        changed_only = ["\n".join(l for l in h.splitlines() if l.startswith(("+", "-"))) for h in from_texts]
        gfindings = []
        for r in members:
            mech = None
            if len(from_hashes) > 1:
                hits = set()
                for tk in tokens(r["label"]):
                    inh = [j for j, h in enumerate(changed_only) if tk in h]
                    if len(inh) == 1:
                        hits.add(inh[0])
                if len(hits) == 1:
                    mech = hits.pop() + 1  # 1-based
            cf, ct = Counter(from_hashes), Counter(to_hashes)
            n_common = sum((cf & ct).values())
            survives = {i + 1: (ct[h] >= from_hashes[:i + 1].count(h) if False else None) for i, h in enumerate(from_hashes)}
            # per-hunk survival: hash present in to multiset (multiplicity-aware, greedy by order)
            avail = dict(ct)
            surv = []
            for h in from_hashes:
                if avail.get(h, 0) > 0:
                    surv.append(True); avail[h] -= 1
                else:
                    surv.append(False)
            partial = 0 < n_common < len(from_hashes)
            marginal = (len(from_hashes) > 1 and r["state"] == "resolved" and partial)
            manifest.append({
                "fid": fid, "pair": pair, "pr": r["pr"], "file": F,
                "from": f, "to": t, "base": base,
                "state": r["state"], "rule": r["rule"], "label": r["label"],
                "n_hunks": len(from_hashes), "from_hashes": from_hashes,
                "to_hashes": to_hashes, "survives": surv,
                "cohort": "test" if len(from_hashes) > 1 else "control",
                "mech_hunk": mech, "marginal": marginal,
            })
            gfindings.append(fid)
            fid += 1
        payload_groups.append({
            "pair": pair, "file": F, "pr": members[0]["pr"],
            "hunk_texts": from_texts, "fids": gfindings,
            "size": sum(len(h) for h in from_texts),
        })

    # greedy batch packing <=35KB hunk text
    payload_groups.sort(key=lambda g: -g["size"])
    batches = []
    for g in payload_groups:
        placed = False
        for b in batches:
            if b["size"] + g["size"] <= 35000:
                b["groups"].append(g); b["size"] += g["size"]; placed = True; break
        if not placed:
            batches.append({"groups": [g], "size": g["size"]})

    bfiles = []
    for bi, b in enumerate(batches):
        lines = []
        for g in b["groups"]:
            lines.append(f"## GROUP file={g['file']} (PR #{g['pr']}, pair {g['pair'][0]}->{g['pair'][1]})")
            lines.append(f"### Hunks of this file's diff, numbered, exactly as sent to the reviewer")
            for i, h in enumerate(g["hunk_texts"], 1):
                lines.append(f"#### Hunk {i}")
                lines.append("```diff"); lines.append(h); lines.append("```")
            lines.append("### Findings previously reported on this file")
            for fd in g["fids"]:
                m = manifest[fd]
                lines.append(f"- FINDING id={fd} [{m['rule']}]: {m['label']}")
            lines.append("")
        path = os.path.join(RUN, f"batch_{bi:02d}.md")
        open(path, "w").write("\n".join(lines))
        bfiles.append({"path": path, "fids": [fd for g in b["groups"] for fd in g["fids"]]})

    json.dump(manifest, open(os.path.join(RUN, "manifest.json"), "w"), indent=1)
    json.dump(bfiles, open(os.path.join(RUN, "batches.json"), "w"), indent=1)
    n_test = sum(1 for m in manifest if m["cohort"] == "test")
    n_marg = sum(1 for m in manifest if m["marginal"])
    n_mech = sum(1 for m in manifest if m["mech_hunk"])
    print(f"findings={len(manifest)} test={n_test} control={len(manifest)-n_test} "
          f"marginal={n_marg} mech_gt={n_mech} batches={len(bfiles)}")

if __name__ == "__main__":
    main()
