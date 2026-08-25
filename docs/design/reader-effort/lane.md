---
lane: reader-effort
vertical: Review pipe
status: parked
opened: 2026-08-23
closed:
next: run the 20-PR cost pilot ADR-0018 names (~$1) before anyone quotes a per-read cost, and watch `reader-unavailable` rates for the unmeasured latency. The comparison this pre-registration specifies has NOT been run; nothing may report a pass from it.
branches: []
prs: [187]
supersedes:
---

# Lane: reader effort — raising `reader.EFFORT`, and not measuring it

`reader.EFFORT` sat at `"medium"`, one step below the provider default, chosen
by the probe on 2026-07-29 and frozen there by ADR-0002. The question this lane
pre-registered: does raising it to `"high"` reduce the rate at which Doug
publishes findings a look at the repository disproves, without reducing the rate
at which it publishes real ones?

**Status: PARKED, and the shape of that matters.** The bars were locked before
any run — and then `EFFORT` was raised to `"high"` anyway, deliberately and
without the run, under **ADR-0018**. The pre-registration is therefore an open
instrument, not a finished experiment: it describes a comparison nobody has
made. Two consequences ADR-0018 records and this lane owes:

- **Cost per read is unmeasured.** `effort` raises thinking tokens, billed as
  output. The pre-registration's 3× estimate is flagged there as *assumed*.
- **Latency per read is unmeasured**, against a 120s per-attempt timeout.

`instrument_id` moved at the cutover (`EFFORT` is in the Example Pack manifest),
so reads either side are not the same instrument and must not be pooled;
`PROMPT_HASH` did not move, so verdict comparability on prompt identity
survives. Two of the probe's six constants have now left the freeze and four
remain — `SYSTEM`, `SCHEMA`, `MODEL`, `MAX_TOKENS`. If a third leaves, ADR-0018
says the freeze should be retired by name rather than eroded.

## Read in this order

1. [`preregistration.md`](preregistration.md) — the question, the bars, the kill conditions. Note its own header still names ADR-0016 as the companion record; the decision that actually governs is **ADR-0018**, which raised `EFFORT` without this run. ADR-0016 became the separate ruling that the mechanical passes run their own cheaper model.
2. `docs/decisions/ADR-0018-effort-leaves-the-freeze-unmeasured.md` — what was decided, and what it admits is unmeasured.
