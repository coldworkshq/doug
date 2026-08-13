# Unbeatable Doug — research synthesis and recommended increment

Date: 2026-08-13 · Status: **PROPOSED** (awaiting Andrew) · Baseline: `origin/main` @ `37942c3`

Method: five parallel research agents (landscape, outcome-loop gaps, scoring/reader quality, agent-door, belief/distribution), then a controller synthesis against this checkout. This document is the design brief. No production code ships from this branch until a shape is approved.

Evidence base lives in this file. Claims about the market cite public URLs; claims about Doug cite `file:line` in this repo.

---

## 0. What “unbeatable” means (operational)

Not “catch more bugs.” Not “higher F1.” Those are the incumbents’ treadmill, and they structurally cannot publish a miss rate while selling them.

Doug is unbeatable when **all four** are true:

1. **The instrument is visible.** Every PR check run shows `adjudicated N · pending M · as of <date>` and `deep reads x/200`. A public Doug-on-Doug page shows the same counters. A stranger can visit without signing in.
2. **The instrument is falsifiable.** A publication query (same SQL path as `store.governing_verdict()`) emits the pre-registered table on schedule — including `not yet decidable — a count, not a rate`. The prereg hash is on every receipt.
3. **Doug is the scoreboard, not a player.** Native reviews and (this increment or next) Copilot/Bugbot comments land as `verdicts.source` and get the same 14/60-day clock. Sales sentence: *Keep Bugbot. Doug grades it.*
4. **Agents consult Doug before they type — without Doug writing code.** Verdict MCP (Reading A) serves receipts that exist today. Garden waits for min-n adjudications. Session-lane boot brief is the later wedge no diff-only reviewer can copy.

Kill criterion unchanged: 2 of 3 prospects say “that’s not right” → halt productization. That interview cannot run honestly until (1) exists.

---

## 1. What 2026 did to the category

**Headline:** no incumbent grades review verdicts against production. Everyone still optimizes pre-merge author-response proxies (resolution, acceptance, Martian F1, chat learnings). The named Cursor risk — “graded against reverts” — has **not shipped**. What *has* shipped is a category-wide lunge into **writing code, opening PRs, blocking merges, and calling author-response “outcomes.”**

That makes Doug’s three rules *more* differentiated, not less — **if Doug actually publishes first.**

### Cost wedge is stale

Bugbot repriced to **$1.00–$1.50/run** (June 2026). Macroscope ~$0.95. Copilot Lite is cents-to-$1. The $15–25/PR figure now describes **Claude Code Review**, not the AI-review category. “We’re 10× cheaper than Bugbot” is false. The $99/installation **ledger** frame is still the right one; the comment-price slide is not.

Primary: [cursor.com/blog/may-2026-bugbot-changes](https://cursor.com/blog/may-2026-bugbot-changes).

### Structural gaps they cannot close without abandoning marketing

| Incumbent | What they sell | Why they cannot copy Doug |
|---|---|---|
| Cursor Bugbot | ~78–80% **resolution** (comment addressed by merge) | Resolution is precision-of-comments-left. A miss is a PR they *didn’t flag* that later reverted. Autofix (>35% of Autofix changes merge) contaminates the label — Bugbot agreeing with itself. |
| Copilot Review | 60M reviews, 1 in 5 GitHub reviews, default-on | Platform-wide cleared-band miss rate would be a Microsoft-shaped PR disaster. Customization is still static files + MCP *into* the review (4k-char cap **removed 2026-06-12** — `product-spec.md` is stale on this). |
| CodeRabbit | Martian F1 51.2%; chat learnings | “Precision” = developer changed code after a comment. Pre-merge checks that **block** select the merge population — they cannot honestly report a cleared-band miss rate on the process as a whole. |
| Greptile | Self-run 82% catch rate on 50 planted-bug PRs | Recall-only, FPs ignored, PRs with no planted bug ignored. Opposite of a miss rate on a population you declined to inspect. |
| Qodo | Agent-facing MCP over a **code index** | Closest garden cousin. Payload is indexed source, not “7 of 9 NOT NULL-without-backfill PRs reverted in 14d, n=9, detector=git_labels@hash.” |
| Sourcery | Sentry issue → **open a fix PR** | Wrong arrow. Doug’s arrow is verdict → clock → incident **without writing the fix**. If they join the triggering PR’s review verdict to the incident, they steal the sentence. They have not. |

### Ranked threats (steal the *sentence*, not feature count)

1. **Cursor ships “graded against reverts.”** Not shipped. Analytics already have `resolution_status`; a revert detector is a small increment on their volume. They can occupy the language with a sloppy label (no windows, no cleared-band denominator, no pre-registration). Defense is the **checkable commitment**, not secrecy (`design-lock.md` risk #6).
2. **Category language capture:** “online / real-world outcomes” now means author acted (Martian, Bugbot resolution, Graphite acceptance). Doug must not use “outcomes” for anything pre-merge.
3. **GitHub default-on + cloud-agent fix PRs.** Doug will often be the third commenter. Neutral check-run + ledger is the only non-losing surface.
4. **Everyone writes code now.** The threat is *Doug copying them*, not them copying Doug. Autofix would destroy the independent adjudicator.
5. **Qodo occupies the agent door** with a codebase MCP. Garden must still not ship refusing — but the window is real.

**Negative evidence that matters:** no vendor published a cleared-band miss rate with N, window, censoring, and a pre-registered denominator. MSR 2026 is using reverts as a *research* label for agentic PRs (~2.66% contain a reverting commit) — Doug’s ontology leaking into the literature, not a product.

---

## 2. What Doug actually has vs the IOU

The backend loop is real. The product surface is not. First adjudications are due **2026-08-16** (Task 7 backfill completed 2026-08-11; v9 hash pinned). Until M3’s exit gate closes, Doug sells a ranking result plus a dated IOU — exactly what `design-lock.md:41` permits, but not yet unbeatable.

### Built

| Component | Evidence |
|---|---|
| Clock start + dual 14/60-day writes | M1 complete |
| Adjudicator + Cloud Run Job + Scheduler | `adjudicate.py`, `ROADMAP.md:258-274` |
| 60-day backfill Task 7, v9 LOCKED | `ROADMAP.md:317-326` |
| Receipts API (partial) | `GET /v1/prs/{n}/receipt` — `api/doug/api.py:916` |
| `governing_verdict()` = publication SQL | `api/doug/store.py:1569-1654` |
| Multi-tenant isolation proven | `ROADMAP.md:432-441` |
| Spend caps + coverage integrity | M2 complete |
| Showcase queue (risk routing, not scoreboard) | `GET /v1/showcase/queue` — `api/doug/api.py:640-678` |
| Convergence module | `api/doug/convergence.py` — **Bar 1 FAIL**, must not enter `score()` |
| Example Pack **code** | Zero packs on disk |

### Must-close-now (without these, unbeatable is fiction)

1. **First production adjudications + manual `git log` audit** — `ROADMAP.md:328-331`. Detector trust. Closes on calendar starting 2026-08-16; audit does not close itself.
2. **Check-run footer** — `adjudicated N · pending M · as of <date>` + `deep reads x/200`. `check_run.py:97-156` ends at findings. `experience.md:13`: “the two lines no competitor can render.”
3. **Publication query + venue** — no `/v1/scoreboard`, no publication script. `store.py:1579-1586` comments “future publication query.” Pre-registration is theater until this exists.
4. **Public Doug-on-Doug scoreboard** — `ROADMAP.md:312` unchecked. `/queue` is a threshold slider, not the instrument. M4 interviews pitch off this page.
5. **Bot-author exclusion from deep reads** — fork skip exists; bot-author is a scoring signal (`scoring.py:88-94`), not a skip gate. Spend + denominator integrity before strangers.

### Compounding (each week loses history)

- Example Pack capture OFF — Lane 0.3 still operator action; zero labelled reader corpus.
- 90-day replay not productized — `outcome_jobs` has no `source` column (`publication-preregistration.md:316`); building replay without a discriminator contaminates prospective counters.
- Install welcome IOU + decidability projection — missing. Anti-disappointment device.
- Deep-read meter has a writer (`store.record_deep_read`) and no customer-facing reader.

### Honesty holes on the landing page (copy, not architecture)

`experience.md:25` bans the verb “learned.” Current copy:

- Hero: “scores it against what actually reverted in **repos like yours**” (`web/app/page.tsx:114-115`) — banned cross-repo implication (`product-spec.md:48`).
- Layer title: “**Learns** what production did” (`web/app/page.tsx:54`) — banned until *that customer’s* loop has closed (`product-spec.md:43`).
- Rule 03: “Every escaped defect Doug cleared is counted, dated, and **published**” (`web/app/page.tsx:22`) — miss rate is explicitly `—` three screens down (`web/app/page.tsx:263-271`).
- MCP docs preview: “412 episodes · **87 repos**” — trains the wrong expectation.

The evidence panel (`0.69/0.67` + `Published miss rate: —`) is honest. Keep it. Fix the hero.

### Ranking quality (do not “just improve the prompt”)

- Deterministic tier: sentry AUC 0.591 / grafana 0.518. Near-random on repo #2. Fallback only.
- Probed LLM reader (30k, original order): 0.687 / 0.668. **Shipped reader is 100k + tier-ordered and has never been AUC-measured.** Quoting 0.687/0.668 for production is an inference.
- ADR-0012 freezes SYSTEM/SCHEMA/MODEL/EFFORT/MAX_TOKENS. Prompt v2 needs a pre-registered experiment; Andrew already declined one 653-PR re-run.
- Highest-ROI finding-quality work without model spend: expand `settle.py` (5/5 schema findings already disproved on Doug self-review), fix finding `file` persistence (description-match is lossy), post-settlement routing honesty (FLAGGED with all findings dropped confuses operators).
- Intent second read: UNBELIEVED, burns >half of input tokens. Keep OFF outside dogfood.

### Agent door

- Verdict MCP: **does not exist.** Receipt API does. Tenancy is FastAPI-free *because* MCP is a later consumer (`tenancy.py:3-6`). Scopes column exists; mint still always grants `queue:read` + `receipt:read`.
- Convergence as halt signal: **STOP.** Bar 1 FAIL (precision ≤ 0.884). Root cause is reader nondeterminism, not coverage bugs. Do not tell agents “done.”
- Garden: correctly gated on min-n adjudications. Probe #1 FAIL. Word “pattern” stays locked.
- Session lane: design-only (`docs/design/session-lane/design.md`). Smallest unbeatable wedge vs Bugbot/Copilot: Claude Code adapter → session↔PR correlator → boot brief at SessionStart. Not on the M3 path.

---

## 3. Three approaches

### A — Make the instrument visible *(recommended)*

**Scope of the next increment:** check-run footer + public scoreboard + publication query (even if the first row is `N=0 · not yet decidable`) + landing copy honesty + bot-author deep-read skip.

**Why this wins even if Cursor announces revert-grading next month:** they cannot retroactively pre-register a denominator they didn’t commit to. The public page with an empty prospective panel and a ticking clock is the thing incumbents structurally will not ship (it would falsify resolution/F1 marketing). M4 interviews become runnable.

**Trade-offs:** does not make findings better; does not open the agent door; 90-day replay still missing (needs a `source` discriminator — do not sneak replay into this increment). Calendar-gated on 2026-08-16+ for the first non-zero `adjudicated` count — the empty state is still the product (`experience.md:17`).

### B — Become the grader of Bugbot and Copilot

**Scope:** bot-comment ingest (issue comments, not just `pull_request_review`) for Copilot + Bugbot; per-source cleared-band table on the scoreboard; sales sentence *Keep Bugbot. Doug grades it.*

**Why it’s the strategic prize:** Copilot is default-on; Cursor shops already have Bugbot. Doug as a *commenter* loses that bake-off. Doug as the **neutral grader** of the market leader is a lane Cursor cannot occupy without grading themselves in public.

**Trade-offs:** parsing bot comment formats is messy (design-lock deferred this for a reason). Without (A)’s surfaces, the per-source table has nowhere honest to live. Do this *on top of A*, not instead of A. Comment-format work can start as a design note this increment and ship the increment after.

### C — Agent door first (verdict MCP v0)

**Scope:** `doug-mcp` as its own Cloud Run service, same image (`architecture.md:158`); `get_receipt` / `get_verdict`; MCP-scoped keys (`receipt:read` without `queue:read`); per-PR read ceiling before any loop. **No** `get_convergence` as a halt signal. **No** garden.

**Why it’s tempting:** “tells your agents before they type” is the v1.5 promise; Qodo already offers agents a codebase MCP; tenancy seams are paid for.

**Trade-offs:** a verdict MCP without visible adjudication is a me-too “here’s the review JSON” tool. Landscape report: band/receipt/convergence are the differentiation; convergence failed; garden has no rows. Shipping a refusing or empty-history MCP spends the honesty budget on theater (`design-lock.md:32`). Per-PR ceiling is still required before dogfood loops — that piece can land inside A as a worker admission check without standing up MCP.

**Rejected as the *first* increment.** Ship after the instrument is visible and at least one adjudication exists, so the payload can point at a clock.

---

## 4. Recommended increment (Approach A)

One autonomous session, own worktree off `origin/main`. Zero new model spend. Does not enter `score()`. Does not write code or open PRs on customer repos.

### 4.1 Check-run footer

Every `Doug` check summary ends with two lines sourced from the ledger (not env):

```
adjudicated N · pending M · as of <date>
deep reads x/200 this cycle
```

N = `count(outcome_jobs WHERE status='done')` for that installation+repo (design-lock: never `count(outcomes)`). M = jobs not `done`. Date = as-of of the query. Meter from `deep_read_counters`. Fallback-tier and incomplete-read honesty already in the body stay.

If N=0, still render: `adjudicated 0 · pending M · first due <date>`. Empty is the product.

### 4.2 Public scoreboard (not the queue)

Unauthenticated page for `DOUG_SHOWCASE_REPO`:

- Prospective panel: `adjudicated / pending / first due / as of`. Rates labeled `not yet decidable — a count, not a rate` until the prereg two-sided interval fires.
- No replay panel in this increment (no `source` discriminator yet). Do not fake a retrospective.
- No per-author-type breakdown (honesty contract).
- Distinct from `/queue`. Queue remains the attention router.

### 4.3 Publication query

A pure function over the ledger that emits the §3 table in `publication-preregistration.md` (cleared-band miss, N, censoring, `remediated_clears`, decidability). Receipts and the public page both call it. First publication may be “N pending, 0 done.” That is a successful discharge of the IOU, not a failure.

Venue can be the scoreboard page in this increment; `drewjst.github.io/doug/publication/` can wait.

### 4.4 Landing copy (honesty, not repositioning)

- Hero: drop “repos like yours.” Score against *this repo’s* reverts, or name the two research repos.
- Layers: “Learns” → counts/dates (“Every merge starts a clock…” already in the body — promote that).
- Rule 03: future tense until first publication (“will be published on the locked cadence”).
- Keep the evidence panel’s `—` exactly.

### 4.5 Bot-author skip

Same gate pattern as fork: webhook + worker refuse to enqueue/charge bot-authored PRs for the reader path. Merges still clock (prereg §2.4). Deterministic `agent-authored` rule stays for the fallback tier on human-authored PRs that touch bot-shaped diffs; do not deep-read Dependabot.

### 4.6 Explicitly not in this increment

- 90-day replay (needs `source` on `outcome_jobs` or equivalent discriminator — its own design note).
- Bot-comment parsing (Approach B; design note allowed).
- Verdict MCP (Approach C; after first adjudication).
- Convergence on receipt (Bar 1 FAIL).
- Garden / “pattern” / prompt v2 / intent v2 / 653-PR remeasure (Andrew’s call, not this spec).
- Autofix, required checks, Martian F1, TREX-like sandboxes.

### 4.7 Exit gate

- A PR on `drewjst/doug` shows the footer with live N/M (zero is fine).
- `/scoreboard` (name TBD) renders the same numbers from the publication query.
- Mutation proofs: footer omitting the empty state fails a test; publication query using `count(outcomes)` as denominator fails a test; landing “learns” / “repos like yours” fail a copy pin.
- `make test` + `make lint` green. Doug dogfood review of the PR comes back clean or is itself adjudicated in the findings log.

---

## 5. Hard no’s (do not re-litigate)

From `design-lock.md` and this research:

- Doug never writes code, never opens a PR, never blocks.
- Nothing outcome-derived enters `score()` unless `backtest/replay.py` can replay it.
- Convergence does not enter `score()`. Convergence `resolved` is not a halt signal until Bar 1 passes.
- No auto-merge of the cleared band.
- No “learns from outcomes” verb until that customer’s loop has closed.
- No capture-rate % in sales copy. No per-author-type miss rates. No cross-repo pattern claims.
- No garden MCP before min-n adjudicated rows.
- Do not quote 0.687/0.668 as the shipped reader’s AUC.

---

## 6. Decision needed

Approve **A**, pick **B** or **C** instead, or mix (A + copy-only now, B/C as follow-on specs).

Recommendation: **A**. The market spent 2026 becoming a player. Doug stays unbeatable by remaining the scoreboard, and the scoreboard is currently invisible. Three days from first adjudications, the footer and the public page are what turn a backend IOU into the instrument nobody else will pre-commit to.
