# Distillation shape — what “check against a deterministic model” looks like

**Status:** explanatory architecture note (2026-08-01). Not a new product commitment.
**Frame source:** `workspace/IDEAS.md` § “The distillation loop” (2026-07-29) ·
[`addendum-agentic-architecture.md`](addendum-agentic-architecture.md) **A1**.
**Product role:** margin engine (cheaper/faster/more accurate over time) — not the
landing pitch (hours + miss rate).
**Mirror:** `workspace/research/distillation-shape.md`
**See also:** [`health-connectors.md`](health-connectors.md)

---

## Check time (hot path — already shipping)

```
  PR → EXTRACT features (paths, size, migration?, tests?, deps?…)
     → MATCH ruleset@version  (if predicate → Reason + weight)
     → SCORE = base + Σ weights
     → cleared | flagged
          │           │
          │           └─ minority: LLM deep read
          └─ store verdict (cleared band = future training set)
```

Code: `api/doug/features.py`, `api/doug/scoring.py`. Pattern matching = boolean
predicates over a fixed feature schema — not a graph walk, not an embedding vote.

## Offline (A1 / IDEAS)

```
  LLM findings ⋈ outcomes → only outcome-predictive → refinery
  → deterministic GATE + replay → ruleset vN+1
```

Agents propose; evidence promotes. Graph DB optional — the join is the graph.

## Competitive honesty

Sonar owns expert deterministic rules; Greptile owns opinion-learning. Doug’s
wedge is **outcome joins + cleared-band miss rate**, not “we have rules too.”
