#!/usr/bin/env python3
"""Grade the span-verification runs against the frozen bars (span-verification.md).

Usage: span_verification_grade.py <calls.json>
  calls.json = the workflow's return value: {"calls": [{"run": "R1"|"R2", "path": ..., "result": {"attributions": [...]}}]}
Pure offline; reads manifest.json from the run dir.
"""
import json, sys, os
from collections import Counter

RUN = "/private/tmp/claude-501/-Users-andrew-Projects-doughq/f806f2a4-4c58-4850-b004-7fffa418cbec/scratchpad/span-verification"

def derived_state(m, hunks):
    """Frozen derivation. hunks: 1-based attributed hunk numbers (possibly empty)."""
    if not hunks:
        return "abstain"
    valid = [h for h in hunks if 1 <= h <= m["n_hunks"]]
    if len(valid) != len(hunks):
        return "invalid"
    surv = [m["survives"][h - 1] for h in hunks]
    if all(surv):
        return "persisted"
    if not any(surv):
        if m["state"] == "resolved":       # later read covered the file and was silent
            return "resolved-candidate"
        return "unknown"                   # re-reported or coverage failed: prereg letter
    return "unknown"                       # mixed survival

def main(path):
    calls = json.load(open(path))["calls"]
    manifest = {m["fid"]: m for m in json.load(open(os.path.join(RUN, "manifest.json")))}
    att = {"R1": {}, "R2": {}}
    for c in calls:
        for a in c["result"]["attributions"]:
            att[c["run"]][a["finding"]] = sorted(a["hunks"])

    missing = [(r, fid) for r in ("R1", "R2") for fid in manifest if fid not in att[r]]
    dupes_note = f"answers R1={len(att['R1'])} R2={len(att['R2'])} of {len(manifest)}; missing={len(missing)}"
    print(dupes_note)
    if missing:
        print("  missing fids:", missing[:20])

    test = [m for m in manifest.values() if m["cohort"] == "test"]
    control = [m for m in manifest.values() if m["cohort"] == "control"]
    marginal = [m for m in test if m["marginal"]]
    mech = [m for m in test if m["mech_hunk"]]

    # Bar S: derived-state disagreement on test set
    flips, raw_disagree = [], []
    states = {}
    for m in test:
        s1 = derived_state(m, att["R1"].get(m["fid"], None) or [])
        s2 = derived_state(m, att["R2"].get(m["fid"], None) or [])
        states[m["fid"]] = (s1, s2)
        if att["R1"].get(m["fid"]) != att["R2"].get(m["fid"]):
            raw_disagree.append(m["fid"])
        if s1 != s2:
            flips.append((m["fid"], m["file"], s1, s2, att["R1"].get(m["fid"]), att["R2"].get(m["fid"])))
    print(f"\nBar S: state flips {len(flips)}/{len(test)} (bar: <=2)  raw hunk-set disagreement {len(raw_disagree)}/{len(test)}")
    for f in flips:
        print("   FLIP", f)
    bar_s = len(flips) <= 2

    # Bar C(a): mechanical GT misses per run
    miss = {"R1": [], "R2": []}
    for m in mech:
        for r in ("R1", "R2"):
            a = att[r].get(m["fid"]) or []
            if a and m["mech_hunk"] not in a:
                miss[r].append((m["fid"], m["file"], m["mech_hunk"], a))
    print(f"\nBar C(a): GT misses R1={len(miss['R1'])}/{len(mech)} R2={len(miss['R2'])}/{len(mech)} (bar: <=1 per run)")
    for r in ("R1", "R2"):
        for x in miss[r]:
            print(f"   MISS {r}", x)
    # Bar C(b): control attribution rate
    ctl = {"R1": 0, "R2": 0}
    for m in control:
        for r in ("R1", "R2"):
            if (att[r].get(m["fid"]) or []) == [1]:
                ctl[r] += 1
    print(f"Bar C(b): control attributed-to-the-hunk R1={ctl['R1']}/{len(control)} R2={ctl['R2']}/{len(control)} (bar: >=90%)")
    bar_c = (len(miss["R1"]) <= 1 and len(miss["R2"]) <= 1
             and ctl["R1"] / len(control) >= 0.9 and ctl["R2"] / len(control) >= 0.9)

    # Bar P: marginal-set both-runs-agreed determinate
    det = [m["fid"] for m in marginal
           if states[m["fid"]][0] == states[m["fid"]][1]
           and states[m["fid"]][0] in ("persisted", "resolved-candidate")]
    print(f"\nBar P: marginal determinate+agreed {len(det)}/{len(marginal)} (bar: >=50% = >={ -(-len(marginal)//2) })")
    dist = Counter(states[m["fid"]] for m in marginal)
    print("  marginal (R1,R2) state pairs:", dict(dist.most_common()))
    abs_det = [m["fid"] for m in test
               if states[m["fid"]][0] == states[m["fid"]][1]
               and states[m["fid"]][0] in ("persisted", "resolved-candidate")]
    print(f"  absolute (all test): {len(abs_det)}/{len(test)}")
    bar_p = len(det) >= -(-len(marginal) // 2)

    print(f"\nVERDICT inputs: Bar S {'PASS' if bar_s else 'FAIL'} | Bar C {'PASS' if bar_c else 'FAIL'} | Bar P {'PASS' if bar_p else 'FAIL'}")
    print("ALL PASS -> A-prime enters v1 (ADR-0014)." if bar_s and bar_c and bar_p
          else "AT LEAST ONE FAIL -> option B stands as locked; A stays vNext.")
    json.dump({"states": {str(k): v for k, v in states.items()},
               "att": att, "flips": flips, "miss": miss, "control": ctl,
               "marginal_det": det},
              open(os.path.join(RUN, "grades.json"), "w"), indent=1)

if __name__ == "__main__":
    main(sys.argv[1])
