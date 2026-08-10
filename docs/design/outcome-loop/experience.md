# Experience: The Outcome Loop

**Companion to:** `product-spec.md` (journeys, claims), `design-lock.md` (decisions). This is the user experience — what makes it differentiated, and a ready-to-paste brief for Claude design at the end.

## The thesis: calibration, not confidence

Every competitor's UX performs *confidence*: green checkmarks, "16 issues found!", walls of authoritative comments. That performance is exactly what the market has stopped believing — reviewers rate AI code higher while incident rates climb. Doug's differentiated experience is the opposite move: **an instrument panel that grades itself in front of you.** Numbers appear with their sample size or not at all. Empty states tell you the date they stop being empty. The product's aesthetic *is* its honesty contract — a user should be able to feel the difference between Doug and a confidence performance within ten seconds of looking at either.

The Saint Bernard carries the tone: calm, unhurried, reliable. Doug doesn't bark at every hiker. It finds the traveler in trouble and brings a human. The voice is a working dog's handler, not a marketing deck: short declaratives, dates, counts, zero exclamation marks.

## The five surfaces

**1. The check run — where the product actually lives.** One neutral check named `Doug` on every PR, in the list the developer already reads. Verdict line ("cleared 0.22" / "needs you 0.71 — schema migration + auth boundary in one diff"), top findings, then the two lines no competitor can render: `adjudicated 41 · pending 37 · as of Feb 3` and `deep reads 143/200 this cycle`. Never a comment, never a block, never a red X. The habit isn't formed by a dashboard; it's formed by this line quietly appearing on every PR until the day the counters make the developer curious enough to click.

**2. The receipt — the artifact you paste into an incident review.** A dated, immutable claim that later gets graded. Five blocks: the verdict with its threshold *pinned at scoring time*; findings (reader findings shown with "did not move the score" honesty for weight-0 entries); inputs seen — files read vs. dropped, deep read vs. fallback-grade, model + prompt hash + pre-registration hash; the adjudication block — `adjudicates Aug 19` → later `reverted day 6, commit abc123` or `no revert observed in 14 days · 60-day window pending` or `censored: merged to release-2.4, outside our view — we say so rather than guess`; permalink. The receipt is the product's whole argument in one screen: *we said this, on this date, seeing exactly this, and here is what production did about it.*

**3. The scoreboard — the empty state IS the product.** Day 1 has two panels, visually distinct: the **replay panel** — the last 90 days scored and adjudicated against reverts that already happened, labeled `replay · retrospective` — full on day 1, never blending into the live numbers; and the **prospective panel**: `0 adjudicated · 37 pending · first adjudication Aug 19 · rates publish on schedule · first possibly decidable ~Nov`. A visible per-PR state machine (scored → merged → adjudicating → survived / reverted / censored) that fills row by row. Every rate renders with N and its interval; until the locked two-sided interval excludes the repo/window base rate it carries the label `not yet decidable — a count, not a rate` in the UI itself. The right-censoring rate sits beside it, not in a footnote. Watching this fill is the week-3 retention moment — design for the *tick*, the moment a pending row flips.

**4. The queue — "62 open. 5 need you."** The attention router: open PRs pinned by risk, threshold slider, tier pill on every row (deep read vs fallback-grade), author shown because routing needs it. Cleared band permanently footnoted: *cleared = not deeply inspected by a human — on one of two research repos our cleared band was not safer than blind; your number is what we're measuring.*

**5. The meter — billing as receipts.** The deep-read count lives in the check run and scoreboard, not in a billing portal. The invoice is verifiable from the surface the customer already sees — the company selling graded claims cannot send an ungraded invoice.

## Copy rules (the honesty contract as UI law)

Counts and dates, never verbs of ability: "41 adjudicated," never "Doug has learned." Literal events: "no revert observed within 14 days," never "safe/validated." Every number carries its N or doesn't render. Banned everywhere: prevented, caught before production, learned, validated, per-author trust claims, any cross-repo statistic. The word "pattern" is reserved until the probes pass — until then it's "history." When Doug can't see, it says so as a first-class state (`censored`, `fallback-grade`, `read incomplete: 14 of 150 files dropped`), styled with the same care as success — **honest states are never rendered as failure states.**

## Why this is profitable from day 1

The UX sells the instrument, not the answer: install → dated projection → visible countdown → counters tick → pre-committed publication. The buyer pays $99/mo from day 1 for something no one else sells (a grading of the process they already run, with a date), the meter's transparency removes billing friction, and the empty scoreboard converts the product's weakest moment (no data yet) into its most distinctive screen. Retention is the clock itself.

---

## Prompt for Claude design (self-contained — paste as-is)

```
Design the product surfaces for **Doug** — an AI code-review scoreboard, dark-mode web app +
GitHub check-run content. Doug is a GitHub App that scores every PR with an LLM diff-read,
routes attention ("62 open. 5 need you."), and — uniquely — GRADES every verdict against what
production actually did: every merge starts a 14- and 60-day clock, then the verdict is
adjudicated as reverted / survived / censored, and the results are published on a
pre-committed schedule, including when they're ugly. Positioning: "Others learn what
reviewers say. Doug learns what production did, remembers it, and tells your agents before
they type."

BRAND. Doug is a Saint Bernard: calm, reliable, finds the traveler in trouble and brings a
human. Never barks at every hiker. Voice = a working dog's handler: short declaratives,
counts and dates, no exclamation marks, no confetti. Existing visual language to extend, not
replace: near-black ground, glass-morphism cards (subtle blur, 1px white/10 borders), one
iridescent teal-cyan accent for identity moments, a warm flag color for "needs you", a cool
clear color for "cleared", monospace for all numbers/labels/timestamps, an elegant humanist
heading face for statements.

THE DESIGN THESIS — CALIBRATION, NOT CONFIDENCE. Every competitor performs certainty (green
checks, "16 issues found!"). Doug is an instrument panel that grades itself in front of you.
Hard rules: a number never renders without its sample size (N) or an em-dash; empty states
always carry the date they stop being empty; honest-limitation states (censored, fallback-
grade, partial read) are styled with the same visual dignity as success — never as errors;
banned words: prevented, caught, learned, validated, safe.

DESIGN THESE FIVE SURFACES:

1. CHECK-RUN SUMMARY (GitHub-flavored markdown, so typography/layout via markdown only) —
   verdict line ("needs you · 0.71 — schema migration + auth boundary in one diff" or
   "cleared · 0.22"), top findings, then two footer lines: "adjudicated 41 · pending 37 ·
   as of Feb 3" and "deep reads 143/200 this cycle". Neutral tone — never reads as pass/fail.

2. RECEIPT (web, the hero artifact — designed to be screenshot into an incident review):
   a dated immutable claim, five blocks: verdict + threshold pinned at scoring time;
   findings (weight-0 reader findings honestly marked "did not move the score"); inputs
   seen (files read vs dropped, deep-read vs fallback-grade pill, model + prompt hash +
   pre-registration hash as quiet monospace provenance); ADJUDICATION block — the emotional
   center: "adjudicates Aug 19" countdown that later becomes "reverted day 6 · commit
   abc123" or "no revert observed in 14 days · 60-day window pending" or "censored: merged
   to release-2.4, outside our view"; permalink.

3. SCOREBOARD (web) — the empty state is the product: "0 adjudicated · 37 pending · first
   adjudication Aug 19 · rates publish on schedule · first possibly decidable ~Nov". Per-PR state machine rows
   (scored → merged → adjudicating → survived/reverted/censored) that visibly fill over
   weeks; design the TICK — the moment a pending row flips. Rates render with N + CI; until
   the two-sided interval excludes the repo/window base rate they carry the inline label
   "not yet decidable — a count, not a rate".
   Right-censoring rate sits beside the headline number, not in a footnote.

4. QUEUE (web) — "62 open. 5 need you." Open PRs pinned by risk score strip, threshold
   slider, per-row tier pill (deep read / fallback-grade), author visible. Permanent
   cleared-band footnote: "cleared = not deeply inspected by a human. On one of two research
   repos our cleared band was not safer than blind; your number is what we're measuring."

5. INSTALL / WELCOME (web) — the dated IOU: what Doug will measure, the two windows (14/60
   days), the projection ("first adjudication lands ~<date>; first possibly decidable
   ~<date>; scheduled publications may remain not yet decidable"), and a link to the hashed
   public pre-registration document. Pricing card:
   $99/installation/month — 5 repos, 200 deep reads pooled, $0.40/read after; the meter is
   always visible in-product.

DELIVERABLE: high-fidelity mockups of all five surfaces (desktop; the check-run rendered as
GitHub would show it), consistent as one system, with the calibration thesis legible in
every screen. Show the scoreboard twice: day-1 empty and month-3 filling.
```
