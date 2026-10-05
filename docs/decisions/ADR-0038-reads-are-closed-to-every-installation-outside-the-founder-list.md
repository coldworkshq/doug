---
title: Reads are closed to every installation outside the deploy's founder list
status: accepted
date: 2026-10-04
amends: ADR-0031
---

> **A fail-closed gate, not a list of tenants.** Every installation outside a
> short list the deploy names is refused a model read, and the refusal is shown
> on the pull request. Opening reads to anyone else is a later, separate
> decision. Nothing here prices, sizes, or admits it.

## Context

Any GitHub account can install the App. Until this record, the webhook
accepted every installation. It queued a review for each ready pull request in
the granted repositories, and `installation.created` also swept the open
backlog. Each review was a paid model read. The intent and verify tiers were
already limited to the dogfood installation by allowlist (ADR-0017's shape),
but the risk read was not. Its only bound was the per-installation runaway
guard in `reader._charge`, which is "not a plan limit".

ADR-0014 removed the comment allowlist as a second, invisible switch, and
recorded that losing "the ability to dark every installation at once" should
be revisited "before the first tenant outside these three installations, not
after." This record is that revisit.

## Decision

1. **The deploy names the founder installations.** `deploy/gcp.sh` sets
   `DOUG_FOUNDER_INSTALLATIONS` on doug-api, space-separated because
   `--set-env-vars` splits on commas. `doug/outside.py` parses it, and
   `test_deploy_gcp.py` pins each id. With the App enabled, the lifespan
   refuses to boot on an empty or malformed list. A candidate that cannot boot
   is never promoted, so a lost list fails the deploy instead of refusing the
   founder's own pull requests.

2. **Every other installation is refused, in two places.**
   - (a) `worker.process_job` asks after the idempotency read, so a verdict
     recorded before this gate still replays, and before `pulls.get`. A
     refused job completes with no verdict. It posts one neutral check run
     titled "Not read: not open", with no band, score, meter, cap, or count
     (`check_run.render_not_read`). It also posts the mirrored comment
     through the repository's own `pr_comment` toggle, with no receipt links.
     Nothing is fetched and nothing is bought, and its log line says so.
   - (b) `reader._charge` asks before the counter and before any client. A
     scope that names a refused installation under any tier prefix raises
     `OutsideRefused` and moves no counter. It is a `SpendCapExceeded`, so
     every existing "no read this time" handler treats it quietly, never as
     a broken reader. `review.score_one` re-raises it ahead of its cap
     clause, so it never becomes a capped verdict, and `process_job` routes
     it to (a)'s surface.

3. **No sweep reaches a refused installation.** `reconcile_installation`
   returns before minting a token, and `reconcile_all` inherits the skip. A
   refused installation's pull requests arrive only through their own
   webhooks, which is how each one gets its "Not read". The review lane is
   webhook-only for them because a sweep would mint tokens and queue work only
   to refuse it.

4. **A refused installation is never traced and leaves no stance.** This
   amends ADR-0031's decision 1. `tracing.create` builds no Langfuse client
   for a call charged to a refused installation, and `tracing.job` opens no
   trace root for its job, so its source and the model's reading of it never
   reach Langfuse. `_record_external_review` writes no stance for it.

## Why this is not the allowlist ADR-0014 and ADR-0019 rejected

- ADR-0014's comment allowlist was invisible: a repository sat dark with its
  toggle reading "on" and nothing to explain it. This gate is never silent.
  Every refused pull request shows "Not read: not open" on its own check run,
  which is the state ADR-0014's D8 exists to make visible.
- ADR-0019 rejected a per-installation reader switch in a deploy environment
  because it made the operator the bottleneck for a tenant's opt-out. This
  list is not an opt-out. It bounds who is read at all, and it fails closed:
  an unknown installation, a missing id, and an empty list are all refused.

## Consequences

- The founder's installations read exactly as before.
  `test_a_founder_installation_reads_exactly_as_before` pins both reads to the
  installation's scope and the paid log line.
- An installation outside the list sees a neutral check run and a comment on
  each ready pull request, and nothing else. A refused job still writes its
  queue row, because the enqueue happens before the decision. It writes no
  verdict, no deep-read count, no trace, and no stance.
- The rollback is a traffic shift to the previous revision, because a revision
  carries the gate and its list together. Adding an installation means
  changing the list in `gcp.sh` and its test, then redeploying.
- **Not decided here:** who else is read, under what allowance, and how they
  are admitted; and the outcome lane's sweeps (`reconcile_outcomes`,
  `reconcile_all_outcomes`), which stay as they are.

## Rejected

- **A private App as the only gate.** A private App installs only on its
  owner's account, and GitHub refuses to make an App private while another
  account has it installed. Visibility also says nothing about reads for
  installations that already exist, so the service needs its own gate.
- **Refusing silently, with no check run.** That's the invisible state ADR-0014
  exists to refuse.
- **A deterministic verdict for a refused installation.** It would put a band
  no model read produced on a pull request that nobody chose to have read.
- **An admission record in the ledger.** It needs a migration and a policy
  nobody has ruled. The deploy's list fails closed today with no new state.
