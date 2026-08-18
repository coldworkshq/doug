# Product spec — cited head reads

**Date:** 2026-08-18 · **Status:** locked alongside [`design-lock.md`](design-lock.md) · **Companion to:** `docs/design/outcome-loop/product-spec.md` (extends its honesty contract; reopens none of it)

---

## 1. What changes for the user

**Before.** Doug reads the patch and nothing else. When a finding's truth lives in a file the PR didn't touch, Doug either misses it or asserts it from the diff alone. On the one PR with an independent answer key, 7 of 8 real defects needed at least one byte Doug never received — including a meter rendering against a cap of 200 while spend is enforced at 4,000, a mismatch invisible unless you read a file that wasn't in the change.

**After.** When a finding turns on a value or a definition elsewhere in the repo, Doug goes and reads it, and the finding carries the exact bytes it rests on:

> `reader:cap-mismatch` — the footer meter renders against `PLAN_DEEP_READ_CAP = 200`, but spend is enforced at 4,000.
> Grounded in `api/doug/reader.py@a1b2c3d#L230` — `INSTALLATION_MONTHLY_READ_CAP = 4000` (sha256 `9f3c…`).

Anyone can re-derive that with `git show`. That is the whole of what the citation establishes, and the copy says so.

**What does not change.** The check run stays `neutral`. Doug does not open PRs, write code, or block. The routing band is unchanged. Findings are not deleted by a model.

## 2. The journey

1. Doug reads the diff, as today.
2. A finding whose truth depends on a value or definition outside the diff names the symbol and the predicate it needs.
3. Bounded reads at head resolve it. Each returns bytes, a SHA-anchored locator, and a hash.
4. The finding renders with its citation and an `evidence` class — `diff` or `head-cited`.
5. A finding that needed a read but could not get a clean one renders **unresolved**, not asserted.

## 3. v1 / vNext

**v1** — existence-and-value predicates only; `constant_value_is`, plus `symbol_referenced_at` if the find-references class earns it; the `evidence` discriminator; SHA-anchored receipts; a per-PR read cap; a dedicated spend scope. Plus, independently and **first**: publish the locked v9 pre-registration.

**vNext** — the agentic instrument as G1's compute-matched comparator (blocked on the `application_revision` ruling); the per-source grading table (blocked on a second reviewer existing on any installation); a zero-call gate over the read log.

**Never** — absence and universality claims certified by citation; a model deleting a finding; a per-finding confidence number.

## 4. Honesty contract

Sentences we will ship:

> This finding rests on code outside the diff. Doug chose which files to open, and it read 3 of them. There is no denominator here — a clear is not evidence about the files it didn't choose.

> `api/doug/reader.py@a1b2c3d#L230` hashes to `9f3c…`. That reproduces the quote. It does not establish the conclusion.

> Doug can show you the line a finding rests on. It cannot show you the lines it didn't read.

On the coverage line — this ships with the increment (design-lock L9):

> Coverage below describes the diff Doug was sent. Files Doug opened at head are not part of that percentage and have no denominator.

The vNext read-log gate — *every file cited in a finding appears in Doug's read log, checked at zero model calls* — is an additional integrity check, **not** a substitute for that sentence. It proves citations are honest; it cannot say what Doug should have opened.

**What we will not claim** — extending `docs/design/outcome-loop/product-spec.md`'s existing list:

- **"Verified" / "confirmed" / "validated"**, or a green check on any finding. A citation certifies a quote, never a conclusion.
- **"Doug checked the codebase."** It read files it selected. Those are different sentences and only the second is true.
- **Fewer false positives**, or any FP rate. ADR-0005 reserves *precision* for defect prediction and mandates two tables; `REVIEWING.md:286-289` forbids reporting a rate from the findings log as precision.
- **Any absence claim as settled** — "nothing else reads this", "no other caller", "this is the only cap." The citation shows one place out of a complement the model selected and never reported.
- **Any number from `findings-log.jsonl` as a rate.**
- **A comparison to another reviewer's false-positive rate.** We have no instrument for theirs.
- **That the PR #106 replay validated anything.** It is a smoke test against a spent, in-repo answer key that shaped this design.

**Precondition, not a deliverable.** `web/app/page.tsx:248-259` renders "0.69 / 0.67" under *"What's actually measured."* Before any new reading capability is announced, that panel gains: *"That's the 30,000-character probe reader, not the one running on your PRs — the shipped reader hasn't been measured by it."* If we won't ship that sentence, we don't get to talk about a new reader's quality.
