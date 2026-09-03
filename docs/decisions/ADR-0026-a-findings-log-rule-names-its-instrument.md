---
title: A findings-log rule names the instrument that raised it, and the 20 untagged rows were corrected in place
status: accepted
date: 2026-08-27
---

## Context

`docs/findings-log.jsonl` is the denominator `docs/REVIEWING.md` designates,
and more than one instrument writes to it. The diff reader writes `reader:`
rows. The plan lane writes `deviation:` / `beyond-ticket:` / `missing-from-pr:`
rows. They are different vocabularies measuring different things, and on
2026-08-27 they ran at different rates: 176 reader rows at 48.3% `real`, 12
plan-lane rows at 75%.

`findings_log.rates()` sliced by `verdict`, `layer` and `repo` — not by
instrument — so it published one share of two populations, 50.0%, which
describes neither. That number was on the hosted docs page and in `llms.txt`,
and both told readers to reproduce it with the unscoped command.

The repo had already ruled this hazard wrong one path over. `patterns.from_rule`
returns `None` for anything outside `RULE_PREFIX`, on the recorded grounds that
"deterministic-tier reasons share the findings table but are a different
vocabulary; pattern analysis must not silently pool the two."

Twenty committed rows carried no prefix at all. They were not a third
vocabulary: they are reader findings recorded without the tag. `7fa5869` states
"Doug's review of #71 raised five findings… dispositions for all five are
logged"; `da43e13` covers the four on #75; `3f7d156` seeded the eleven backfill
rows. `reader:`-prefixed rows already existed by 2026-08-04 (#48), so the
twenty do not predate the convention — the tag was dropped.

## Decision

**A `rule` is `<prefix>:<slug>`, both halves kebab-case, and the schema refuses
anything else.** The prefix names the instrument. `rates()` scopes on it the
way it already scopes on `repo`, always reports `by_rule_prefix`, and any
published number comes from a call scoped on both axes.

**The twenty untagged rules were rewritten in place to `reader:<slug>`.**
Verdicts, dates, `settled_by`, notes and every other field are untouched;
the edit was verified field-by-field against the previous commit as rule-only.
Andrew ruled this before it was made, choosing it over leaving the file frozen.

**The slug half is pinned too.** On the reader tier the slug is
`category_slug`, a free-form schema string with no enum and no pattern
(`reader.py:130-137`), so `reader:Foo Bar` is reachable model output and
`patterns.normalize` — which neither case-folds nor slugifies — would group it
as its own pattern beside `reader:foo-bar`. Transcription into this file is the
last place that can refuse it, so it does: kebab-case the slug and put the
original in `note`.

**`docs/design/reader-effort/preregistration.md` is amended, not restated.**
Its corpus is now extracted with `rate --repo doug --rule-prefix reader:`. Two
`deviation:` rows fall inside its recorded window, both on its last day, so the
baseline table stands exactly as recorded and no pre-registered number moves.
This record is what sanctions that amendment; ADR-0018 is the precedent for the
shape — a record that names what it contradicts rather than a quiet edit.

Numbered 0026 because 0022–0025 are claimed by unmerged branches.

## Rejected

**Ship the prefix slicing and leave the twenty rows untagged, in a `(none)`
bucket.** This was the issue's literal ask (#235) and it corrects half the error: it
stops foreign rows inflating the reader's share and starts nine reader rows
deflating it. A wrong denominator in the other direction is still a wrong
denominator.

**A closed registry of known prefixes.** It would catch a misspelled prefix, which
the slug rule does not. It would also reject a real finding at disposition time
whenever a new instrument appears — the security lane is next — and a schema
that makes recording a finding harder than not recording it will be obeyed by
not recording it.

**Leave the slug free-form.** The stated reason was that `category_slug` is the
reader's own output and a schema should not second-guess it. That conflates
rejecting a *finding* with rejecting a *transcription*: the human holds the
finding either way and can kebab-case the slug in the moment. Doug raised this
against its own PR (`reader:loose-regex-validation`) and was right.

**Restate the preregistration's baseline with the two `deviation:` rows
removed.** Recomputing a pre-registered number after the fact is the thing a
preregistration exists to prevent, and ADR-0004 rests on it: "the bars were
frozen before the run, which is the only reason the result is worth anything."

**Record this only in the commit message and `HANDOFF.md`.** That is where the
justification lived until Doug's own review of this PR objected. `HANDOFF.md`
is ephemeral by design, and a rewrite of committed evidence should be findable
from the decisions directory rather than from `git log -S`.

## Consequences

- A row cannot enter the log without naming its instrument, so a fourth
  vocabulary — `security:` is next — cannot pool silently into an existing
  share.
- Any published share must name both scopes. The unscoped command no longer
  appears on either public surface, and `public-surface.test.mjs` fails if it
  returns.
- The reader's own share on `doug` is **48.3%** `real` over 176 prospective
  rows, not the 50.0% that was published. The number got worse, which is the
  point of measuring it separately.
- The plan lane's rows remain split across three prefixes (`deviation:`,
  `beyond-ticket:`, `missing-from-pr:`), so "the plan lane's share" still takes
  three calls to compute. Tracked as an issue, not resolved here.
- `patterns.normalize` still neither case-folds nor slugifies, so a dirty
  `category_slug` in the production findings table can still split one pattern
  in two. That path is untouched by this record and is tracked separately.

  > **Facts updated 2026-09-03, decision unchanged.** #287 made
  > `patterns.normalize` fold spelling (lower-case, kebab, no edge dashes)
  > before the merge map, closing the path above (#244). The transcription
  > rule in this record stands on a different ground than the Context gave
  > it: the log is hand-transcribed, so a dirty slug here is a transcription
  > error rather than model output, and the last place that can refuse it
  > still does. Measured the same day across every Doug check run on the
  > last 120 PRs: 672 distinct reader slugs, none dirty, so the fold changes
  > no historical grouping. Doug raised the shift in rationale on its review
  > of #287 (`deviation:beyond-ticket`); this note is the record of it.
