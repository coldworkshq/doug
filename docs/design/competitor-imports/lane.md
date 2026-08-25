---
lane: competitor-imports
vertical: Review pipe
status: shipped
opened: 2026-08-17
closed: 2026-08-23
next: none — the lane is closed. Phase 2 was deferred with named blockers and each piece has an issue: #136 (zero-call gate over the read log), #137 (application_revision in instrument_id), #133 (per-source grading trigger). Known drift inside this folder: #147 (stale "next free migration" pointers), #183 (design-lock L1's rationale predates hunk attribution).
branches: []
prs: [118]
supersedes:
---

# Lane: competitor-imports — cited head reads

**The folder name is the concept this lane started from, not the one it
shipped.** `ground-truth.md` was written against a competitor-imports brief and
records its own verdict — *"brief only — the concept it was written against did
not survive it"*. What survived the grounding phase and got built is **cited
head reads**: letting a finding cite bounded reads at the reviewed head to
*ground* an existence-or-value claim. Every other file here carries that title.
The folder keeps the original name because the convention's own rule is that a
reference which outlives its truth is the worst defect this repo has, and three
files outside this folder already point at this path.

Doug's reader receives `f.patch` and nothing else. It *had* an
outside-the-diff fetcher, wired exclusively into `settle.py` — so the system's
one outside-the-diff capability was licensed to subtract findings and forbidden
to raise them. On the only rater-independent evidence in the repo that
asymmetry produced 7 of 8 misses. The lock reverses the license, under a closed
vocabulary of existence-class predicates, with the evidence class machine-
separable from diff-proved findings. Absence and universality claims stay out of
scope for citation: the model picks which lines to look at, and a claim about an
absence cannot be settled by the same observation that produced it.

**Status: SHIPPED.** Phase 1 merged as PR #118 (2026-08-19), dark. Grounding
was then switched on for one named installation behind an allowlist rather than
for every tenant at once — ADR-0017, 2026-08-23. Phase 2 is deferred, not
forgotten; its three blockers are the issues named in `next` above.

## Read in this order

1. [`ground-truth.md`](ground-truth.md) — the four grounding briefs, and the verdict that killed the original concept
2. [`positions.md`](positions.md) — three cold opening positions
3. [`decisions.md`](decisions.md) — round-1 rulings (three later overturned by the red-team)
4. [`design-lock.md`](design-lock.md) — the locked design, L1–L9. **Start here if you only read one.**
5. [`product-spec.md`](product-spec.md) — the honesty contract this increment extends
6. [`build-plan.md`](build-plan.md) — Phase 0/1/2 and what each phase gated
