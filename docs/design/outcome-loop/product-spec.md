# Product Spec: The Outcome Loop

**Companion to:** `design-lock.md` (decisions), `build-plan.md` (execution). PM voice.

## How it changes everything

Every AI code reviewer on the market emits opinions at review time and never learns whether the opinion was right. Their feedback loops end at developer reaction — a thumbs-down, a reply — which measures whether the comment *felt* useful, not whether the code broke. CodeRabbit's learnings come from chat; Bugbot's 44k learned rules come from downvotes and missed-flag comments; Copilot's customization is a static 4,000-character file. Nobody joins a verdict to what production did. (Sources: coderabbit.ai/blog MCP + knowledge-base docs; cursor.com/blog/bugbot-learning; github.blog changelog 2026-07-17.)

Meanwhile the buyer's actual situation, per New Relic's 2026 State of AI Coding: **94% of tech leaders rate AI-generated code higher quality at review time, and 78% report more incidents once it ships** (newrelic.com/press-release/20260610). The review moment says "fine"; production disagrees; nobody's instrument spans the gap.

Doug is that instrument. Every PR gets a verdict; every merge starts a clock; every clock ends in an adjudication — *reverted* or *survived the window* — recorded in a ledger the customer can query and we publish on a pre-committed cadence. The change is not "a better reviewer." It is that **for the first time, review claims get graded**, including the reviews you already run: native GitHub reviews (and, later, other bots' comments) land in the same ledger and get adjudicated by the same clock. Doug is the scoreboard, not another player barking from the sidelines.

Honesty about the before/after: on day 1 this is a *nice-to-have* plus a dated promise. It becomes a change-everything product the week the customer's own scoreboard fills — and the design's whole job is making that week arrive credibly.

## Journeys

**Install (day 0).** GitHub App install, two clicks, no CI edit, no index step — first verdict on the next PR opened. And the first *filled* screen arrives the same hour: **the 90-day replay** — Doug scores the repo's recent history and adjudicates it against the reverts that already happened (same detector as everything else), so day 1 shows a retrospective scoreboard: "over your last 90 days, these are the PRs Doug would have flagged, overlaid with the reverts you actually had." Replay rows are labeled `replay` and never blend into the prospective numbers — the live clock still starts at zero, and the welcome says so in the product's own voice: *"Doug scores every PR and grades every verdict against what your repo actually does. Your prospective scoreboard: 0 adjudicated · 0 pending. At your merge volume, your first adjudication lands ~<date+14d> and a rate worth reading (N≥30) lands ~<projected date>."* The pre-registration document — metric definitions, denominator, both windows (14d/60d), right-censoring, publication cadence — is public, dated, and its hash will appear in every receipt. The projection is the anti-disappointment device: a 150-PR/month repo at a 0.4% revert rate is told *up front* that a quarterly number may stay "below our floor" for months.

**Week 1 (the empty scoreboard).** Every PR carries one neutral check run named `Doug`: verdict, band, top findings, and the counters — "0 adjudicated · 37 pending · first adjudication Aug 19." The cleared band is labeled: *cleared = not deeply inspected by a human. On one of two research repos, our cleared band was not safer than blind — your number is what we're here to measure.* No cliff: the check is on every PR the developer already looks at; there is nothing to remember to open.

**Week 3+ (the loop closes).** First adjudications land. The check-run counters tick. The receipt for PR #212, flagged three weeks ago, now reads "reverted at day 6 — revert commit `abc123`." The receipt for #208, cleared, reads "no revert observed in 14 days (60-day window pending)." A staff engineer pastes a receipt into an incident review — that artifact (dated verdict, pinned threshold, prompt hash, inputs seen, adjudication with evidence sha) is the product doing its job.

**Quarter 1 (publication).** The pre-committed report ships on its date, whatever it says: cleared-band miss rate against the repo's own historical base rate (backfilled with the same detector), N, CI, right-censoring rate — or, honestly, "N=22; below our pre-registered floor; this is a rumor." Publishing the ugly version *is* the differentiator: Greptile's benchmark is recall-only and self-run; CodeRabbit's number is a third-party F1 on a benchmark; nobody grades themselves against a population they declined to inspect. The vendor pre-commitment is the moat because incumbents structurally cannot match it while marketing "resolution nearing 80%."

**v1.5 (the garden, when it can answer).** A writing agent, before generation, calls Doug over MCP and gets *adjudicated history with citations*: "In this repo, 7 of 9 PRs adding a NOT NULL column without a backfill were reverted within 14 days (latest #4412, 2026-06-02). The two that survived used dual-write → backfill → flip." Sample size and provenance live inside the sentence — an agent that quotes it quotes the caveat. Below n=5 it is labeled *history*, not pattern; the word "pattern" waits for the pre-registered probes. The same content is exportable as an AGENTS.md/DOUG.md fragment the *customer* commits (Doug never writes to the repo) — and that commit is itself adjudicable, which is how we get the first traced example: reverted PR → adjudicated lesson → served before generation → changed a later diff.

## v1 / vNext

- **v1 (the load-bearing minimum):** App ingest (step-2 plan + clock-start amendment), outcome_jobs + adjudicator + both windows, receipts API, check-run surface with counters and meter, third-party review ingest (`pull_request_review` events), **90-day replay onboarding** (retrospective, `source='replay'`, quarantined from prospective rates), public Doug-on-Doug scoreboard, per-installation tokens, spend caps, hand invoicing. Deviations/intent: OFF for tenants, ON for dogfood, labeled experimental.
- **vNext, with promotion triggers:** tenant web dashboard + WorkOS (tenancy spec steps 3-4; trigger: >3 tenants or first tenant request); MCP garden (trigger: adjudicated rows ≥ min-n on ≥1 tenant + the probes' positive results for the "pattern" label); bot-comment parsing for named reviewers (trigger: a design partner running Bugbot/CodeRabbit asks); 60-day rows live (runbook backfill before first publication — hard gate); staging env (trigger: tenant #2 or first deploy incident); public cross-repo garden (own store, permissive-license sources, separate design pass — not before).

**Pricing:** $99/installation/month — 5 active repos, 200 pooled deep reads, full adjudication history, publication, export. $15/additional active repo; $0.40/deep-read overage. The meter line lives in the check-run summary ("deep reads: 143/200 this cycle") so the invoice is verifiable from the surface the customer already sees. What the $99 buys is the *ledger* — the graded history that compounds — not the reads; reads are metered because they're the COGS (ADR-0004: every ranked PR is deep-read; the routing dial moves human attention, not the bill, and the copy says so). Design partners: hand-comped allowances, hand invoices; no self-serve free tier.

## Honesty contract

**We claim:**
- "On two public repos (pre-registered, replicated), reading the diff ranked defect-carrying PRs above every metadata baseline — AUC 0.687 / 0.668. We don't know your number yet; here is the date we publish it."
- "Every verdict — ours and your reviewers' — is adjudicated against observed reverts at 14 and 60 days. N adjudicated, M pending, right-censoring rate alongside."
- "Reverted means: a revert commit we can point to (sha in the receipt). Survived means: no revert observed within the window. Nothing more."
- "Our miss rate is published quarterly, on a pre-registered definition, including when it's bad."

**We refuse to claim:**
- "Learns from outcomes" as a verb, until *that customer's* loop has closed — until then it's counts and a date.
- Any capture-rate percentage in sales copy (post-hoc, reweighted, single-repo).
- "Prevents incidents / catches bugs before they ship" — causal language over correlational data (Krutauz et al., arxiv.org/abs/2005.09217: review measures add little over prior defects, size, authorship).
- "Validated / safe / endorsed" for survived code — survival is *not yet detected*, and the garden only ever sees merged code.
- Per-author-type (agent vs human) miss rates — ~150k PRs of data short of measurable.
- Any cross-repo pattern claim ("across 8,400 repos…" is banned copy; we have two research repos).

**On the edge cases, stated plainly:** the 14-day window over-samples fast, loud failures (flaky-bug median detection is 34 days; vulnerability lifespans run years — arxiv.org/pdf/2103.11518), which is why the 60-day window and the censoring rate publish together. Reverts are a noisy label (flags, dep conflicts, release mechanics — arxiv.org/abs/2509.09192); the published number carries a stated noise estimate. Merges to non-default branches adjudicate as *unknown*, never *clean*. A read that couldn't see every file says so in the receipt and the meter (coverage requires `files_sent == changed_files` after the v1 fix). And if the reader is down, the fallback verdict is labeled fallback-grade — deterministic ranking measured near-random on repo #2 and we say so rather than sell it.

## Key sources

New Relic 2026 State of AI Coding (newrelic.com/press-release/20260610) · Bugbot learning (cursor.com/blog/bugbot-learning) · Graphite acquisition (cursor.com/blog/graphite) · Copilot review billing/customization (docs.github.com/copilot; github.blog 2026-07-17) · Greptile benchmark methodology (greptile.com/benchmarks) · CodeRabbit pricing/Martian (coderabbit.ai) · Qodo best_practices.md (qodo.ai/blog) · Context7 (upstash.com/blog/new-context7) · llms.txt non-adoption (ppc.land, May 2026) · AGENTS.md (agents.md) · Krutauz et al. (arxiv.org/abs/2005.09217) · OSS-Fuzz detection latencies (arxiv.org/pdf/2103.11518) · revert-label noise (arxiv.org/abs/2509.09192) · Cloud Run MCP hosting (docs.cloud.google.com/run/docs/host-mcp-servers) · Cloud Tasks limits (docs.cloud.google.com/tasks/docs/quotas) · Claude on Vertex (docs.cloud.google.com/vertex-ai/generative-ai/docs/partner-models/claude) · Doug's own evidence record: `workspace/research/phase1-entry-preregistration.md`.
