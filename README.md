<h1 align="center">Magpie</h1>

<p align="center"><em>62 open. 5 need you.</em></p>

---

Most pull requests don't need a human. Magpie works out which ones do.

Every AI code reviewer on the market runs a language model over every diff. That makes their cost scale with the exact thing coding agents are inflating, and it still leaves a person reading bot comments on 100% of pull requests. Magpie inverts it: cheap deterministic analysis scores every PR, most are cleared, and only the small fraction that carries real risk gets a deep look.

The name is the pitch. A magpie ignores the whole field and picks out the few bright things in it.

## Three rules

**Route, never block.** The PR proceeds either way. Magpie only decides who has to look. Tools that block get disabled.

**Never write code, never open a PR.** The moment it authors, it owns the authorship.

**Publish the miss rate.** Every quarter, including the incidents that came from PRs it cleared. A gate that never publishes its errors is a marketing claim; one that does can survive being wrong.

## What it looks at

Routing is deterministic — no model invocation, fractions of a cent per PR:

- Boundary crossings against a declared or harvested architecture
- Schema migrations landing in the same diff as a boundary or auth change
- Dependency major bumps where the tests mock the dependency (green CI is anti-signal here)
- Approval latency relative to diff size
- Test delta disproportionate to the change
- Cross-repo blast radius from the org lockfile and config graph
- Authorship (agent or human) against how recently a human touched the module

Diff size is deliberately de-weighted. It predicts poorly once the rest are controlled for.

## Status

**Pre-build.** Nothing here is installable yet.

The whole idea rests on one claim: that a small set of cheaply-computable structural features captures a disproportionate share of bad changes. If flagging 10% of PRs catches 40% of the trouble instead of 70%, this is an expensive random sampler and it should be abandoned.

That's testable on public data before a service exists — reconstruct the features over historical PRs, label defect-inducing changes via revert anchors, and plot capture rate against flag rate. That measurement comes first. The first shippable thing after it is a CLI that replays your last 90 days and shows you which PRs it would have flagged, overlaid with the reverts you actually had.

## License

Apache-2.0. See [LICENSE](LICENSE).

The code is open because the code was never the moat. What can't be copied is a labeled set of routing verdicts paired with what actually happened afterward, and that lives outside this repository.
