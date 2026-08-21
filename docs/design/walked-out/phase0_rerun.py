#!/usr/bin/env python3
"""Phase 0(b): $0 offline re-run of the 43-unit sample under the locked rule-5 table,
pure and attribution-refined (frozen attributions from span-verification/).

Reports the split, the resolved units for Bar A(B) hand-check, the 26-unit
labeling sheet for Bar B (Andrew), abstention/silence numbers, and the
coverage covariate. Read-only; writes phase0_labeling_sheet.md next to itself.
"""
import json, os, sys, random
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hunk_multiplicity import hunks, merge_base, name_only

EVAL = "/Users/andrew/Projects/doughq/workspace/research/two-lane-2026-08-11/convergence-eval-run1.json"
HERE = os.path.dirname(os.path.abspath(__file__))

def locked_state(hf, ht, attributed=None):
    """The locked rule-5 table. hf/ht: hash lists (prior/later). attributed: hash list or None."""
    if not hf:
        return "unknown(file-uncovered)", None
    cf, ct = Counter(hf), Counter(ht)
    if cf == ct:
        return "persisted(by-construction)", None
    common = sum((cf & ct).values())
    if common == 0:
        return ("resolved(hunk-edited)", None) if ht else ("unknown(left-diff)", None)
    # partial survival -> not-reconfirmed, then attribution refinement
    if attributed:
        att = [h for h in attributed if h in cf]
        if len(att) != len(attributed) or not att:
            return "unknown(not-reconfirmed)", "attribution-invalid"
        avail = dict(ct); surv = []
        for h in att:
            if avail.get(h, 0) > 0:
                surv.append(True); avail[h] -= 1
            else:
                surv.append(False)
        if all(surv):
            return "persisted(attributed-surviving)", "refined"
        if not any(surv):
            return "resolved(attributed-edited)", "refined"
        return "unknown(not-reconfirmed)", "mixed"
    return "unknown(not-reconfirmed)", None

def main():
    d = json.load(open(EVAL))
    pairs = [p for p in d["pairs"] if p["from_head_sha"] and p["to_head_sha"]]
    # sample re-derivation (identical to hunk_multiplicity.py)
    frame = [p for p in pairs if any(c["state"] == "resolved" for c in p["classifications"])]
    frame.sort(key=lambda p: (p["from_verdict_id"], p["to_verdict_id"]))
    random.Random(20260811).shuffle(frame)
    cum, sample_ids = 0, set()
    for p in frame:
        n = sum(1 for c in p["classifications"] if c["state"] == "resolved")
        sample_ids.add((p["from_verdict_id"], p["to_verdict_id"])); cum += n
        if cum >= 40: break
    assert len(sample_ids) == 13 and cum == 43

    # frozen attributions: manifest fid -> record; join key (pair, file, rule, label)
    man = json.load(open(os.path.join(HERE, "span-verification/manifest.json")))
    calls = json.load(open(os.path.join(HERE, "span-verification/calls.json")))["calls"]
    att_by_fid = {}
    for c in calls:
        if c["run"] != "R1": continue      # runs agreed on all derived states; R1 is the instrument
        for a in c["result"]["attributions"]:
            att_by_fid[a["finding"]] = a["hunks"]
    att_key = {}
    for m in man:
        idx = att_by_fid.get(m["fid"]) or []
        hashes = [m["from_hashes"][i-1] for i in idx if 1 <= i <= len(m["from_hashes"])]
        att_key[(tuple(m["pair"]), m["file"], m["rule"], m["label"])] = hashes

    units, path_suspects = [], 0
    for p in pairs:
        pid = (p["from_verdict_id"], p["to_verdict_id"])
        if pid not in sample_ids: continue
        f, t = p["from_head_sha"], p["to_head_sha"]
        base = merge_base("origin/main", f)
        if p.get("path_form_suspects"): path_suspects += len(p["path_form_suspects"])
        for c in p["classifications"]:
            if c["state"] != "resolved": continue
            F = c["file"]
            hf, ht = hunks(base, f, F), hunks(base, t, F)
            attributed = att_key.get((pid, F, c["rule"], c["label"]))
            pure, _ = locked_state(hf, ht, None)
            refined, note = locked_state(hf, ht, attributed)
            units.append({"pair": pid, "pr": p["group"]["pr_number"], "file": F,
                          "rule": c["rule"], "label": c["label"], "from": f, "to": t,
                          "base": base, "n_hunks": len(hf),
                          "pure": pure, "refined": refined, "note": note})

    assert len(units) == 43, len(units)
    def bucket(k): return Counter(u[k].split("(")[0] + "(" + u[k].split("(")[1] for u in units)
    print("PURE split:", dict(Counter(u["pure"] for u in units).most_common()))
    print("REFINED split:", dict(Counter(u["refined"] for u in units).most_common()))
    print("path_form_suspects in sample pairs:", path_suspects)

    print("\n-- resolved units (Bar A(B) hand-check) --")
    for u in units:
        if u["refined"].startswith("resolved"):
            print(f"  PR#{u['pr']} {u['file']} [{u['rule']}] {u['refined']}")
            print(f"    {u['from'][:10]}..{u['to'][:10]} label: {u['label'][:110]}")

    bc = [u for u in units if u["pure"] == "persisted(by-construction)"]
    print(f"\n-- by-construction units for Andrew's Bar B labels: {len(bc)} --")
    with open(os.path.join(HERE, "phase0_labeling_sheet.md"), "w") as fh:
        fh.write("# Phase 0(b) — Bar B labeling sheet (Andrew)\n\n"
                 "For each unit the cited file's diff is byte-unchanged between the two reads,\n"
                 "so the locked rule carries the finding forward. Mark `addressed: yes` only if\n"
                 "the defect was in fact addressed anyway (fix landed elsewhere, defect gone at\n"
                 "the later head). Bar B passes at <= 1 of 26 addressed. `#75` deploy-ordering is\n"
                 "pre-declared as the expected member.\n\n")
        for i, u in enumerate(sorted(bc, key=lambda u: (u["pr"], u["file"])), 1):
            fh.write(f"## {i}. PR#{u['pr']} `{u['file']}` [{u['rule']}]\n"
                     f"- pair {u['pair'][0]}->{u['pair'][1]}, {u['from'][:10]}..{u['to'][:10]}\n"
                     f"- finding: {u['label']}\n- addressed: \n\n")
    print("labeling sheet written: phase0_labeling_sheet.md")
    json.dump(units, open(os.path.join(HERE, "phase0_units.json"), "w"), indent=1)
    print("units written: phase0_units.json")

if __name__ == "__main__":
    main()
