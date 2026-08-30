---
title: The reader authenticates by workload identity, and the API key leaves the service
status: accepted
date: 2026-08-30
amends: ADR-0029
---

> **This record removes a mount ADR-0029 required, and preserves the property
> that record was protecting.**
>
> ADR-0029 item 4 says `ANTHROPIC_API_KEY` stays mounted because it is the
> rollback, and that "it leaves in its own change when the rollback window
> closes". This is that change, and the window has NOT closed — Vertex still
> cannot serve. The key leaves anyway, because federation makes the first-party
> transport reachable **without** it: the rollback ADR-0028 item 6 asked for is
> intact, and one of the two hands on the clock ADR-0029 named has been removed.

## Context

### What forced it

The mounted key was expiring. Rotating it is four commands and a redeploy, and
it is the third credential event this service has had. Anthropic's Workload
Identity Federation removes the class: a Cloud Run workload presents a
Google-signed OIDC token for its own service account, exchanges it for a token
that lives ten minutes, and the SDK re-exchanges before expiry. There is no
static secret to mint, mount, rotate, leak, or expire.

The prerequisites were already true, which is why this is small. `doug-api` runs
under a dedicated, user-managed service account (`doug-api-sa`) rather than the
default compute identity — the posture `deploy/gcp.sh` established for
unrelated reasons — and that is exactly what Google's metadata server signs
tokens for.

### The one hazard, and it is a silent one

`ANTHROPIC_API_KEY` sits **above** federation in every SDK's credential
precedence. A key left in the environment does not conflict with federation and
does not error: it silently wins. The service would go on authenticating with
the credential everyone believes was retired, with no log line and no failed
read to say so — the same shape as `reader:unsafe-default-flip` and the stale
secret binding revoked in #152, and the same shape as every failure this
codebase's alerting exists to convert into noise.

So the mount is removed rather than kept as a belt, and its absence is asserted
by `test_the_api_deploy_mounts_no_anthropic_key`. A guard that only fires when
someone deliberately re-adds a line is worth little; a guard on an absence that
would otherwise be invisible is worth the test.

### What this is not

It is **not** a transport change. ADR-0029's `DOUG_READER_TRANSPORT` chooses
which API surface is called; this chooses how the caller proves who it is on the
first-party one. The two are orthogonal, and `_build_client` keeps them so:
Vertex authenticates with application default credentials and never consults
federation, which is pinned by
`test_federation_does_not_reach_the_vertex_transport`.

It is also **not** a spend change. Federation replaces a credential, not a
budget. The balance still funds every read, and the reader still fails soft when
it runs out — now with the alert from #278 to say so.

## Decision

**1. The api service authenticates to the first-party API by Workload Identity
Federation.** The federation rule pins both `doug-api-sa`'s email and its numeric
unique ID, and the audience `https://api.anthropic.com`. Only that workload, on a
token Google itself signed, can mint against it.

**2. `ANTHROPIC_API_KEY` is no longer mounted on `doug-api`.** ADR-0029 item 4 is
amended to that extent and to no other.

**3. The secret and its IAM binding stay.** `doug-anthropic-key` remains in
Secret Manager, readable by `doug-api-sa`, precisely so the rollback below is not
a privileged operation during an incident. Pinned by
`test_the_anthropic_key_secret_survives_as_the_rollback`.

**4. Rollback is an env change on the running service, unchanged in kind from
ADR-0029's:**

```
gcloud run services update doug-api --region us-central1 \
  --update-secrets ANTHROPIC_API_KEY=doug-anthropic-key:latest
```

Restoring the mount restores the old credential with no code change and no
deploy. It is never restored by editing the deploy script, which is what keeps
decision 2's assertion true.

**This required code, not just precedence.** The SDK ranks an explicit
`credentials=` constructor argument *above* `ANTHROPIC_API_KEY`, so a client
built with federation credentials ignores a mounted key — and the first draft of
this change did exactly that, which would have made the rollback above a no-op
discovered during an incident. `federation_configured()` therefore defers to a
mounted key and reports False, restoring the precedence the SDK documents and
this record assumes. Doug caught the gap between this record and the code
(`beyond-ticket`, 250c10e); it is pinned by
`test_a_mounted_key_wins_so_the_rollback_actually_rolls_back`.

**5. The four federation ids are plain environment variables in
`deploy/gcp.sh`.** They name resources; they are not credentials. Putting them in
Secret Manager would imply a secrecy they do not have and hide from review the
one thing worth reviewing — which workload identity is trusted.

**6. Federation requires all three of rule, organization and service-account
id, or it is not configured.** Any-of would build a client that raises at the
exchange and fail every read soft into the deterministic score. A missing id
means this environment was not configured for federation, so the key path — or
its absence — is the honest answer. Unconfigured environments (a laptop, a
script, CI) are unchanged, the same posture as `DEFAULT_TRANSPORT` staying
`anthropic` under ADR-0029.

## Rejected

**Keeping the key mounted alongside federation, as a belt.** It is not a belt.
Precedence means the key wins, so "both" is just "the key", and the migration
would appear to have happened while nothing changed. This is the whole reason
decision 2 exists.

**`ANTHROPIC_IDENTITY_TOKEN_FILE` and the zero-config env-var path.** It suits
Kubernetes, whose projected tokens are rotated on disk by the kubelet. Nothing on
Cloud Run rewrites that file, Google's tokens last about an hour, and the SDK
re-reads the file on every exchange — so the first refresh after an hour would
present a stale, already-exchanged token and fail. The token provider is a
callable for that reason, and the single-use `jti` rule makes it the correct
shape rather than merely the working one.

**Waiting for the Vertex cutover.** The two are independent, the key was expiring
now, and coupling them would have made a credential rotation wait on a Google
sales relationship (#274).

**A second rule for local development.** Nothing outside Cloud Run has a Google
identity for `doug-api-sa`, and a rule loose enough to cover a laptop is a rule
loose enough to cover anyone's laptop. Local development uses a personal key, as
it did before.

## Consequences

- **The rotation class is gone.** No key expiry, no `gcloud secrets versions
  add`, no redeploy to pick up a new version, no key in a shell history. The
  credential is minted per exchange and lives ten minutes.
- **`instrument_id` does not move.** `tool_versions` is an explicit
  three-entry tuple (anthropic-sdk, pydantic, python), not a package scan, and
  the pinned SDK already carried the federation classes — so no version changed.
  ADR-0027's Consequences warn that adding a dependency moves the hash; that
  warning does not bind here, and this record says so rather than leaving a
  future reader to check.
- **`google-auth` becomes a declared dependency.** It was already installed
  transitively through `google-cloud-storage`; `reader.py` now calls it directly,
  and the house rule (the `httpx` entry's comment in `pyproject.toml`) is that a
  directly-called dependency is declared.
- **ADR-0029's clock loses a hand.** That record notes the rollback works "only
  while `ANTHROPIC_API_KEY` is mounted and the balance is non-zero". The first
  condition is retired: the first-party transport now needs no key at all. The
  balance condition is untouched and is still the thing to watch.
- **The failure mode of a misconfigured federation is the familiar one.** A
  dropped env var, a revoked rule, or a rotated service account all produce a
  failed exchange, which produces a `ReaderError`, which falls soft to the
  deterministic score — and now emits the `reader fell back to deterministic`
  line the #278 alert watches. This change is safe to make partly because that
  alert landed first.
- **One IAM grant may be outstanding.** Verifying the rule by hand required
  `roles/iam.serviceAccountTokenCreator` on `doug-api-sa` for the operator who
  ran it. The deployed workload does not need it — Cloud Run's metadata server
  signs for its own attached identity — so if it was granted, it should be
  revoked.
