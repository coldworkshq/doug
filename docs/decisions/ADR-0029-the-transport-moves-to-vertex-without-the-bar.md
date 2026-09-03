---
title: The reader's transport moves to Vertex without ADR-0028's bar, by direction, because the balance funds one of the two
status: accepted
date: 2026-08-28
amends: ADR-0012, ADR-0027, ADR-0028
amended_by: ADR-0030
---

> **Amended by ADR-0030, 2026-08-30: `ANTHROPIC_API_KEY` is no longer
> mounted. Item 4 below is superseded to that extent; the rollback it
> protects is intact.**
>
> The api service now authenticates to the first-party API by Workload
> Identity Federation, so that transport is reachable with no key at all.
> Item 4's reasoning — that removing the key would convert a one-command
> revert into a redeploy — still holds and is still honored: the secret and
> its IAM binding stay, and the rollback is
> `--update-secrets ANTHROPIC_API_KEY=doug-anthropic-key:latest` on the
> running service. The key had to leave the MOUNT rather than merely be
> unused, because it outranks federation in SDK credential precedence and a
> leftover key silently wins.
>
> **The Consequences' "rollback has a clock" is now half true.** Its first
> condition (the key stays mounted) is retired. Its second (the balance is
> non-zero) is untouched, and remains the thing to watch.

> **This record authorizes an unmeasured instrument change and says so in its
> title.**
>
> ADR-0028 declared a bar and rejected, by name, "shipping the move and
> measuring afterward". This record does that anyway. It is not a reinterpretation
> of ADR-0028 and it does not argue that the bar was met, was unnecessary, or was
> satisfied by something else. The bar was never run. Andrew directed the move on
> 2026-08-28 after the funding constraint below was put to him, and the direction
> is the authorization.
>
> **ADR-0018 is the precedent for the shape, not for the practice.** That record
> shipped a value against the same rule, by direction, and was candid that the
> value ships governed by nothing. ADR-0028 warned about exactly this: "Doing it
> twice would make the exception the practice." This is the second time. Whoever
> reads this next should treat a third as evidence that the bars are decorative.

## Context

### What forced it

The Anthropic console balance is running out. Every paid call Doug makes in
production is billed there: `read_diff` and `read_with_decisions` through
`reader._client`, and `verify_finding` and `attribute_findings` through
`reader._verify_client`. `settle.py` makes no model call — it is AST analysis
over the diff — so those four are the whole surface.

ADR-0028's paired silent run scores 300 PRs on both transports. It therefore
**doubles** the Anthropic bill for its duration, and A2 requires it to complete
*before* any traffic moves. The balance funds the study or the cutover. It does
not fund both, and a study that exhausts the balance leaves the service on a
dead account with its evidence intact and nothing to serve.

### The bar was also not runnable as written

Independent of the funding, ADR-0028's bar could not have been executed as
declared. Both defects were found while building the runner and are recorded in
**#268**, which stays open:

- **The baseline does not reproduce.** ADR-0028 names its extraction —
  `rate --repo doug --rule-prefix reader:` — and reports n=153 at 44.4% `real` /
  32.0% `disproved` / 23.5% `adjacent`. That command on `837ce57`, the commit
  that declared the table, returns n=201 at 49.3% / 30.8% / 19.9%. All eight
  combinations of the three scoping axes were checked, and every cumulative date
  cutoff: 68 `real` never occurs. Because the two thresholds are *derived* from
  that table, the declared 39.4% floor sits 9.9 pp below the reproducible
  baseline rather than the ruled 5.0 pp — which is the 10 pp option ADR-0028
  enumerates and rejects as certifying a visible regression.
- **The named corpus cannot produce the measured quantity.** The bar measures
  finding dispositions. Those exist only in `docs/findings-log.jsonl`, are
  hand-settled (`settled_by`), and cover 34 distinct doug PRs. The 653-PR corpus
  is `api/.backtest-cache/llm-probe/sample.json` (sentry, 136 defects + 230
  clean) and `llm-probe-grafana/sample.json` (grafana, 57 + 230): PR numbers and
  a binary defect/clean label at `diff_budget: 30000`, with no findings, no
  dispositions and no adjudicator. It is the corpus the probe measured AUC on,
  and AUC is a PR-level discrimination statistic, not validated yield. Running
  the bar as written needs on the order of 3,500 hand dispositions against a
  historical total of 201, and #237 records that no bot produces a gradeable row.

Neither defect is the reason for this record. The funding is. They are recorded
here because a future reader finding an unrun bar deserves to know it was also
an unrunnable one, and because #268 must be settled before any bar is declared
against this transport later.

### What is actually being changed

Claude Opus 5 through Vertex is the same weights over a different API surface.
Verified on this commit:

| Fact | State |
|---|---|
| `anthropic` version | 0.120.2, `anthropic[vertex]` already declared in `api/pyproject.toml` |
| `AnthropicVertex.__init__` | `region` required, `project_id` resolved from application default credentials |
| Env fallbacks the SDK reads | `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID` |
| Construction with `region` only | succeeds; without it, `ValueError` naming `CLOUD_ML_REGION` |
| `max_retries` SDK default | 2 on both clients, so `MAX_READ_RETRIES` is still passed explicitly |
| New SDK or new vendor | none |

`MODEL` stays `"claude-opus-5"` and reaches the wire verbatim. `tool_versions`
does not move.

## Decision

**1. Both clients move to Vertex.** `_client` and `_verify_client` now delegate
to one construction site, `_build_client`. ADR-0028's prose scoped itself to
"the risk and intent reads' transport" while its facts table and its guard test
both named `_verify_client`, which serves neither. That ambiguity is settled
here in the direction the funding forces: the mechanical tier's *transport*
moves with the rest, so nothing is left billing the Anthropic console. Its
*vendor* does not move, and ADR-0027's three conditions still bind before it can.

**2. `provider` names the API surface actually called.** It is `"anthropic-vertex"`
on Vertex and `"anthropic"` on the first-party API, computed at capture time
rather than hardcoded. This moves `instrument_id` and partitions the labelled
corpus at the cutover, exactly as ADR-0028 item 1 ruled. That partition is the
one part of ADR-0028 this record does not weaken.

**3. The transport is a value, the deploy names the destination, and the
default is what unconfigured environments get.** `DOUG_READER_TRANSPORT` is read
at client construction. `deploy/gcp.sh` pins it to `vertex` on the service;
`DEFAULT_TRANSPORT` is `anthropic`.

Those are two different jobs and the first draft conflated them, defaulting to
Vertex so that production's value was also the fallback everywhere else. Doug
flagged it (`reader:unsafe-default-flip`) and was right: a laptop, a script or a
CI job has no Vertex region and no application default credentials, so the
client raises at construction and the read falls soft into the deterministic
score — silently, because that fallback is contracted behaviour for a stalled
upstream and says nothing about a misconfiguration. Flipping the default
confines this change to the one environment configured for it.

The rollback property is unaffected. Production is pinned by env, so reverting
is still a value change on the running service and not a release. An unreadable
value falls back to the default rather than constructing something arbitrary,
because a typo during a rollback must not become an outage.

**4. `ANTHROPIC_API_KEY` stays mounted.** It is the rollback. Removing it as
cleanup would convert a one-command revert into a redeploy, which is the state
ADR-0028 item 6 exists to prevent. It leaves in its own change when the rollback
window closes.

> **Amended by ADR-0030.** It left in its own change, as this item anticipated,
> but earlier than the closing of the rollback window and for a different
> reason: federation reaches this transport without a key, so the revert stayed
> one command. The secret and its binding remain for exactly that.

**5. The region is required, has no default, and is verified before the deploy.**
`deploy/gcp.sh` refuses without `VERTEX_REGION`, then probes each model in that
region and refuses again on 404, 401/403, or 429.

A wrong region does not fail loudly. Every read falls soft into the
deterministic score, which reads as "the reader is down" rather than "the region
is wrong", so the regression is unattributable days later. A set region is also
not a working one, and measurement rather than assumption says how far apart
those are. Probed live on 2026-08-28 against `doug-prod0`:

| Fact | Value |
|---|---|
| Regions probed | 13 |
| Regions serving `claude-opus-5` | **3** — `us-east5`, `us-central1`, `europe-west4` |
| `global` | **not served**, 404 |
| Throughput quota on all three | **zero** — 429 on `online_prediction_input_tokens_per_minute_per_base_model` |

Ten of thirteen regions 404, so a plausible-looking region is close to a coin
flip. Model Garden access and throughput quota are separate grants, and holding
only the first fails exactly like holding neither. Both states are invisible to
a non-empty-string check, which is why item 5 is a probe and not a validation.

> **Facts updated 2026-09-02, decision unchanged.** Google Support answered the
> quota case (#274): Claude 5 models carry shared-lineage quota under the
> unversioned base models `anthropic-claude-opus` and `anthropic-claude-sonnet`,
> and that quota is served on the multi-region and global endpoints only. A
> single region cannot be granted, so the three regions in the table above are
> not deployment targets for this lineage. Re-probed the same day: `us`
> (`aiplatform.us.rep.googleapis.com`) and `global` now resolve for both models
> and return 429 on the lineage quota. The staged value is `us`, which keeps
> tenant source in the US. `vertex_host` in `deploy/gcp.sh` mirrors the SDK's
> host table so the preflight probes the route the service will call. Nothing
> in items 1 through 7 changes: the location is still required, still
> undefaulted, and still probed before a deploy. The remaining gate is a
> capacity grant, which Google issues only through an account team.

The probe posts an empty body. That fails request validation before the model
generates anything, so it costs nothing, and it cannot be rate-limited by its
own token count — which is what lets a 429 be read as "the allocation is zero"
rather than "the endpoint is busy". A 400 is the healthy answer.

The preflight **allowlists**: only 200 and 400 pass. The first draft refused a
named list and let everything else through, so a 5xx — or an empty string from a
missing `curl` — passed the gate the function exists to provide. Doug flagged it
(`reader:incomplete-error-handling`). A check that fails open on the outcomes
nobody enumerated is not a check.

**A Vertex deploy is gated; an urgent deploy is not.** `READER_TRANSPORT`
selects what a deploy pins, and the preflight runs only when that is `vertex`.
Quota is zero today, so an unconditional gate would have made every unrelated
hotfix hostage to a founder-level quota grant — R1 says production Doug wins
every conflict, and a hotfix blocked by a half-finished migration is that
conflict. `READER_TRANSPORT=anthropic ./deploy/gcp.sh deploy` ships the current
transport and never touches Vertex. Doug raised this as
`reader:deploy-blocking-precondition` and it was a fair objection to a gate with
no way out.

**What the probe does not establish.** It runs as the operator's credentials,
not as `doug-api-sa`, so it proves the model is reachable in the region and says
nothing about whether the runtime identity may call it. That half is the
`roles/aiplatform.user` binding in `setup`. Two checks, two identities, and the
gap between them is named rather than papered over.

`VERTEX_REGION` is still not defaulted to `$REGION`, and the two coinciding at
`us-central1` does not weaken that. Ten regions do not serve the model, which is
the hazard; that the service's own region is one of the three is luck.

**6. No mapping layer between `MODEL` and the wire.** Vertex serves
current-generation models under the bare first-party id, so the string is
identical on both transports. A mapping is how `MODEL` comes to say one thing
while the wire says another, which is the state ADR-0012's freeze exists to make
impossible. `test_the_transport_carries_MODEL_verbatim_with_no_mapping_layer`
asserts the construction site names no model id. If a dated snapshot is ever
pinned, the two transports stop sharing a string and that reopens this record.

**7. The guard test was deleted without the result its docstring required.**
`test_the_risk_read_has_not_moved_to_vertex_before_its_bar_is_run` named one way
to remove it: run the study, record the result against the four numbers, and
cite it. That is not what happened. The comment block that replaced it says so
in the test file, where anyone changing this code will read it, rather than only
here.

**8. The cutover is one word in `.github/workflows/deploy.yml`.** That file
sets `READER_TRANSPORT` on the deploy step, and it ships `anthropic` until
Vertex quota exists (#274). `vertex` there pins the transport on the service and
makes the preflight binding; `VERTEX_REGION: us-central1` is pre-staged beside
it so the flip is genuinely one word and not a small research task performed
under pressure.

This item exists because the first version of this record did not have it, and
the omission cost a deploy. `gcp.sh` gained a required `VERTEX_REGION` with a
refusal, a mutation-verified test, and a harness that set it — and the workflow,
which was not in that diff, never did. The merge of #273 deployed nothing: run
33237025355 died on `ERROR: set VERTEX_REGION`, leaving `main` and production
disagreeing, which is the drift ADR-0025 exists to prevent. A required variable
with no test binding it to its caller is a variable that is only required in
tests. `test_the_workflow_supplies_every_variable_the_deploy_requires` now
derives the set from the script rather than listing it, so the next one fails
before a merge instead of after.

**9. ADR-0012 and ADR-0027 are marked on their own sides.** ADR-0012's banner
asserted that no traffic had moved and that the deleted guard test would fail
the suite if a Vertex client shipped first; both are false after this record.
ADR-0027's Consequences described the transport move as covering only the risk
and intent reads. Doug found the first as `missing-from-pr` and the second as
`beyond-ticket`, and both were right. `docs/decisions/README.md` requires both
sides to be marked, and the first draft of this record repeated one record over
the exact one-sided-amendment defect ADR-0028 had been corrected for five days
earlier.

## Rejected

**Running ADR-0028's bar first.** The option that should have won, and it loses
only on funding. It was put to Andrew with the arithmetic — the study doubles the
bill on the line item that sets margin, and the balance does not cover both —
and he directed the move. Recorded as a rejected alternative rather than as an
obstacle, because the difference matters: this was a choice between measured and
solvent, not a case of nobody noticing.

**A smaller sample so the study fits the balance.** It reopens the ruled 300,
which ADR-0028 derives: 3 pp needs roughly 800 PRs per arm to beat sampling
noise, so a smaller n at the same margin is underpowered and its PASS would not
mean what it says. Buying a number that cannot fail is worse than admitting there
is no number, and this record admits it.

**Re-declaring a corrected bar in this record and running that.** It has the same
funding problem, and it would let the party doing the move choose the bar it is
measured against, one commit after discovering the old bar was too loose. #268
carries that decision to Andrew instead, unattached to a change that benefits
from the answer.

**Moving only `_client` and leaving the mechanical tier on the Anthropic API.**
It is the narrower reading of ADR-0028 and it fails the purpose: the console has
to be empty, and two of the four paid calls would still bill there.

**Moving to Gemini in the same change.** The original request. It is a vendor
change, not a transport change: ADR-0027 licenses it for the mechanical tier
under three conditions, C3 is undischarged (#263, reopened after an accidental
close), and ADR-0027 item 5 refuses it outright for the risk and intent reads.
The record that picks a model reports C1 and C2 and cites ADR-0027; this one does
not pick one.

**Bedrock.** `anthropic.AnthropicBedrock` reaches the same two functions. The
service already runs on Cloud Run with GCP credentials in the image, so Vertex
adds no new cloud relationship. Unchanged from ADR-0028.

## Consequences

- **The published series partitions at the cutover, and the new era is
  unvalidated.** `example_pack_eval.py` partitions by `instrument_id`, so the
  split is mechanical. What is *not* mechanical is that the new partition has no
  evidence behind it at all. Every surface reporting a rate names which era it
  covers, and no number measured before the cutover may be quoted for after it.
- **Doug's published quality claims describe the old instrument.** Until
  something is measured on Vertex, the honest statement about the live reader is
  that it runs the same weights over an unvalidated transport. Any page, receipt
  or pre-registration that implies otherwise is wrong from the cutover onward and
  is a defect, not a nuance.
- **#268 stays open.** The bar's two defects are unresolved and are a founder
  ruling. Nothing here fixes them, and a bar declared against this transport
  later must not inherit ADR-0028's table.
- **The rollback has a clock.** It works only while `ANTHROPIC_API_KEY` is
  mounted and the balance is non-zero. (ADR-0030 retired the first condition:
  the first-party transport now needs no key. The balance condition stands.) When the balance reaches zero the rollback
  stops existing, and this transport becomes the only one. That is worth knowing
  before it happens rather than after.
- **The transport cannot deploy until quota is granted.** All three serving
  regions return 429 with a zero allocation today. That is a founder action and
  it is tracked in **#274**, along with the region evidence. The preflight in
  item 5 is what stops that state from shipping as a silent outage.
- **`scripts/llm_probe.py` stays on the first-party API.** It reports what it
  measured, which is the same reason ADR-0018 left its `EFFORT` alone.
- **The mechanical tier's vendor boundary is untouched.** ADR-0027's C1, C2 and
  C3 all still bind. Moving its transport is not moving its vendor, and this
  record must not be cited as though it were.
- **Nothing downstream reads the `provider` string, so the partition is by hash
  only.** Doug raised `reader:metric-label-change` — that a dashboard or query
  keyed on `"anthropic"` would silently split at the cutover. Checked across
  `api/doug`, `web/`, and `console/`: the only occurrences are the manifest
  field itself and the reader setting it. Every other `provider` in the tree is
  the identity provider and unrelated. `example_pack_eval.py` partitions on
  `instrument_id`, which is the intended behaviour and is a hash, not a label.
  The finding names a real hazard and this codebase does not currently have it.
