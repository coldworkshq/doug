# Outcome Surface Residual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the receipt endpoint its first consumer — a per-PR trust document at `/dashboard/pr/[number]` — and surface the 60-day outcome beside the 14-day one in every run list.

**Architecture:** All honesty logic lives in `web/lib/` as pure functions over the API's JSON, because `npm test` runs `node --test 'lib/**/*.test.mjs'` and reaches nothing else. The page is a thin server component that renders what those functions decide. The 60-day join is a `store.run_history` change plus a second column on both clients; no migration, because `enqueue` has always written both windows.

**Tech Stack:** Next.js 16 App Router (server components), TypeScript, Tailwind 4, shadcn/ui; `node --test` for web; Python 3.14 + FastAPI + SQLAlchemy Core + pytest for api; uv for Python deps.

Spec: `docs/superpowers/specs/2026-08-12-outcome-surface-residual-design.md`
Baseline: `origin/main` @ `da8bf97`

## Global Constraints

- **Never collapse an honesty state.** Every rule in spec §2.2 is a required behaviour, and each gets a test proven to discriminate.
- **No render tests.** Logic goes in `lib/`; the page renders it. This is why every task below tests a pure function, never a component.
- **Mutation proof required on every honesty test:** reintroduce the bug, watch the test fail, restore. Clear `__pycache__` between weaken and restore on the Python side.
- **Never a third data colour.** `.data-flag` / `.data-clear` only; iridescent is chrome-only (CVD rule, `console/app/globals.css:160-196`).
- **Colour is always accompanied by its word** — use `BandChip`, never a bare swatch.
- **Numbers use `.mono` with tabular-nums.**
- **`node --test` only sees `lib/**/*.test.mjs`.** A test placed anywhere else does not run and is worse than no test.
- **Import extensions are asymmetric, and getting it wrong breaks the build, not the tests.** A `.test.mjs` file MUST import the module under test with an explicit `.ts` extension — node's `--experimental-strip-types` resolves it. A `.ts` source file MUST NOT: `tsconfig` has `allowImportingTsExtensions` disabled, so `next build` fails type-checking with TS5097 while `npm test` stays green. Precedent: `web/lib/api.ts` imports `from "./scoreboard-shape"`, while `web/lib/scoreboard-shape.test.mjs` imports `from "./scoreboard-shape.ts"`. Because `npm test` does not catch this, **run `npm run build` before committing any task that adds an import to a `.ts` file.**
- Verify with `make test` and `make lint` from the repo root. Web-only iteration: `npm test --workspace=web`.

## File Structure

**Create:**
- `web/lib/receipt-shape.ts` — wire types mirroring `ReceiptResponse` + `isReceiptResponse()`. One responsibility: reject a payload the page would otherwise dereference blindly.
- `web/lib/receipt-shape.test.mjs`
- `web/lib/receipt-verdict-view.ts` — pure verdict-level honesty decisions (read recorded, prompt hash, latest-vs-governing).
- `web/lib/receipt-verdict-view.test.mjs`
- `web/lib/receipt-merge-view.ts` — pure merge/window-level honesty decisions (window kind, prereg stamp, governing absence, merge identity).
- `web/lib/receipt-merge-view.test.mjs`
- `web/lib/receipt-fixture.json` — one payload exercising every §2.2 state.
- `web/app/dashboard/pr/[number]/page.tsx` — thin server component.

**Modify:**
- `web/lib/session-api.ts` — carry HTTP status on `SessionApiError`; add `getReceipt()`.
- `web/lib/session-api.test.mjs` — cover both.
- `web/app/dashboard/page.tsx` — link PR groups to the receipt route.
- `api/doug/store.py:2407` — the 60-day join.
- `api/doug/models.py:184` — `outcome_60` on `RunSummaryItem`.
- `api/doug/api.py` — `_run_item` passes it through.
- `api/tests/test_store.py`, `api/tests/test_api.py`
- `web/lib/session-api.ts`, `console/lib/api.ts` — row types.
- `web/lib/facets.ts`, `console/lib/facets.ts` — the 60-day facet.
- `web/app/dashboard/page.tsx`, `console/app/page.tsx` — the second column.

---

### Task 1: Receipt wire types and validator

**Files:**
- Create: `web/lib/receipt-shape.ts`
- Test: `web/lib/receipt-shape.test.mjs`

**Interfaces:**
- Consumes: nothing.
- Produces: `ReceiptResponse`, `ReceiptVerdict`, `ReceiptMerge`, `ReceiptWindow`, `ReceiptRead`, `ReceiptPreregistration` types; `isReceiptResponse(value: unknown): value is ReceiptResponse`.

- [ ] **Step 1: Write the failing test**

Create `web/lib/receipt-shape.test.mjs`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import { isReceiptResponse } from "./receipt-shape.ts";

function verdict(overrides = {}) {
  return {
    verdict_id: 1044,
    scored_at: "2026-08-10T12:00:00Z",
    tier: "reader",
    source: "webhook",
    head_sha: "fe307ab6",
    model: "claude-opus-5",
    prompt_hash: "abc123",
    read: { diff_budget: 100000, read_order: "tier", recorded: true },
    score: 0.42,
    band: "cleared",
    threshold: 0.6,
    risk_score: 12,
    rationale: "no boundary crossing",
    reasons: [],
    deviations: [],
    intent_alignment: null,
    intent_refs: [],
    coverage: null,
    ...overrides,
  };
}

function body(overrides = {}) {
  return {
    repo: "drewjst/doug",
    pr_number: 90,
    preregistration: { hash: "c8e30da3", in_force: true },
    latest_verdict: verdict(),
    merges: [
      {
        merge_commit_sha: "70fe216",
        merged_at: "2026-08-10T13:00:00Z",
        base_ref: "main",
        merged_head_sha: "fe307ab6",
        governing_verdict: verdict(),
        publication_governing: true,
        publication_note: "governing merge",
        adjudication: [
          {
            window_days: 14,
            status: "pending",
            due_at: "2026-08-24T13:00:00Z",
            kind: null,
            observed_at: null,
            source: null,
            detail: null,
            prereg_hash: null,
          },
        ],
      },
    ],
    ...overrides,
  };
}

test("accepts a full receipt", () => {
  assert.equal(isReceiptResponse(body()), true);
});

test("accepts a PR with no verdict and no merges", () => {
  assert.equal(isReceiptResponse(body({ latest_verdict: null, merges: [] })), true);
});

test("accepts a merge whose governing verdict is absent", () => {
  const merges = body().merges.map((m) => ({ ...m, governing_verdict: null }));
  assert.equal(isReceiptResponse(body({ merges })), true);
});

test("rejects a missing preregistration block", () => {
  const withoutPrereg = body();
  delete withoutPrereg.preregistration;
  assert.equal(isReceiptResponse(withoutPrereg), false);
});

test("rejects a window whose kind is not a string or null", () => {
  const merges = body().merges.map((m) => ({
    ...m,
    adjudication: m.adjudication.map((w) => ({ ...w, kind: 7 })),
  }));
  assert.equal(isReceiptResponse(body({ merges })), false);
});

test("rejects merges that is not an array", () => {
  assert.equal(isReceiptResponse(body({ merges: null })), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test 2>&1 | grep -A3 receipt-shape`
Expected: FAIL — cannot find module `./receipt-shape.ts`.

- [ ] **Step 3: Write the implementation**

Create `web/lib/receipt-shape.ts`:

```typescript
/** Wire types for `GET /v1/prs/{n}/receipt`, mirroring the Pydantic models in
 *  `api/doug/api.py:704-830`. Kept structurally identical on purpose: this is
 *  the one document whose fields all carry honesty meaning, and a silent
 *  rename here would let the page render a state the API did not send. */

export interface ReceiptRead {
  diff_budget: number | null;
  read_order: string | null;
  /** False whenever EITHER column is null. Half a pair describes no
   *  instrument, so absence can never be read as a value. */
  recorded: boolean;
}

export interface ReceiptVerdict {
  verdict_id: number;
  scored_at: string;
  tier: string;
  source: string | null;
  head_sha: string | null;
  model: string | null;
  /** Null means the row predates prompt-hash stamping. NOT a match against
   *  the frozen prompt, and must never render as one. */
  prompt_hash: string | null;
  read: ReceiptRead;
  score: number;
  band: string;
  threshold: number;
  risk_score: number | null;
  rationale: string | null;
  reasons: unknown[];
  deviations: unknown[];
  intent_alignment: number | null;
  intent_refs: string[];
  coverage: Record<string, unknown> | null;
}

export interface ReceiptWindow {
  window_days: number;
  /** The JOB's state: pending | running | done | failed. */
  status: string;
  due_at: string;
  /** The ADJUDICATION's: revert | clean | censored. Null while the window is
   *  open or the job never completed — never substituted with `clean`. */
  kind: string | null;
  observed_at: string | null;
  source: string | null;
  detail: Record<string, unknown> | null;
  /** Stamped at adjudication time. Null on a pending window. */
  prereg_hash: string | null;
}

export interface ReceiptMerge {
  merge_commit_sha: string;
  merged_at: string;
  base_ref: string;
  merged_head_sha: string | null;
  governing_verdict: ReceiptVerdict | null;
  publication_governing: boolean;
  publication_note: string;
  adjudication: ReceiptWindow[];
}

export interface ReceiptPreregistration {
  hash: string | null;
  in_force: boolean;
}

export interface ReceiptResponse {
  repo: string;
  pr_number: number;
  preregistration: ReceiptPreregistration;
  latest_verdict: ReceiptVerdict | null;
  merges: ReceiptMerge[];
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function nullableNumber(value: unknown): boolean {
  return value === null || typeof value === "number";
}

function isRead(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    nullableNumber(value.diff_budget) &&
    nullableString(value.read_order) &&
    typeof value.recorded === "boolean"
  );
}

function isVerdict(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    typeof value.verdict_id === "number" &&
    typeof value.scored_at === "string" &&
    typeof value.tier === "string" &&
    nullableString(value.source) &&
    nullableString(value.head_sha) &&
    nullableString(value.model) &&
    nullableString(value.prompt_hash) &&
    isRead(value.read) &&
    typeof value.score === "number" &&
    typeof value.band === "string" &&
    typeof value.threshold === "number" &&
    nullableNumber(value.risk_score) &&
    nullableString(value.rationale) &&
    Array.isArray(value.reasons) &&
    Array.isArray(value.deviations) &&
    nullableNumber(value.intent_alignment) &&
    Array.isArray(value.intent_refs) &&
    (value.coverage === null || record(value.coverage))
  );
}

function isWindow(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    typeof value.window_days === "number" &&
    typeof value.status === "string" &&
    typeof value.due_at === "string" &&
    nullableString(value.kind) &&
    nullableString(value.observed_at) &&
    nullableString(value.source) &&
    (value.detail === null || record(value.detail)) &&
    nullableString(value.prereg_hash)
  );
}

function isMerge(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    typeof value.merge_commit_sha === "string" &&
    typeof value.merged_at === "string" &&
    typeof value.base_ref === "string" &&
    nullableString(value.merged_head_sha) &&
    (value.governing_verdict === null || isVerdict(value.governing_verdict)) &&
    typeof value.publication_governing === "boolean" &&
    typeof value.publication_note === "string" &&
    Array.isArray(value.adjudication) &&
    value.adjudication.every(isWindow)
  );
}

export function isReceiptResponse(value: unknown): value is ReceiptResponse {
  if (!record(value)) return false;
  const prereg = value.preregistration;
  return (
    typeof value.repo === "string" &&
    typeof value.pr_number === "number" &&
    record(prereg) &&
    nullableString(prereg.hash) &&
    typeof prereg.in_force === "boolean" &&
    (value.latest_verdict === null || isVerdict(value.latest_verdict)) &&
    Array.isArray(value.merges) &&
    value.merges.every(isMerge)
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test 2>&1 | tail -20`
Expected: all `receipt-shape` tests PASS, no other suite regressed.

- [ ] **Step 5: Commit**

```bash
git add web/lib/receipt-shape.ts web/lib/receipt-shape.test.mjs
git commit -m "feat(web): receipt wire types and structural validator"
```

---

### Task 2: Carry HTTP status on session errors, and fetch the receipt

**Files:**
- Modify: `web/lib/session-api.ts`
- Test: `web/lib/session-api.test.mjs`

**Why status must survive.** `sessionJson` currently collapses every non-ok response into one `SessionApiError(message)`, discarding the code. The receipt screen must tell 404 (no receipt, or not yours — deliberately indistinguishable) from 401 (session expired) from 503 (the ledger is not answering). Adding an optional field is backward-compatible: existing callers ignore it.

**Interfaces:**
- Consumes: `isReceiptResponse` and `ReceiptResponse` from Task 1.
- Produces: `SessionApiError.status: number | null`; `getReceipt(accessToken: string, repo: string, prNumber: number): Promise<ReceiptResponse>`.

- [ ] **Step 1: Write the failing test**

Append to `web/lib/session-api.test.mjs`:

```javascript
test("SessionApiError carries the HTTP status when there was one", () => {
  const err = new SessionApiError("nope", 404);
  assert.equal(err.status, 404);
});

test("SessionApiError status is null when the request never got a response", () => {
  const err = new SessionApiError("nope");
  assert.equal(err.status, null);
});

test("getReceipt rejects a payload that is not a receipt", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ repo: "x" }), { status: 200 });
  try {
    await assert.rejects(() => getReceipt("token", "drewjst/doug", 90), SessionApiError);
  } finally {
    globalThis.fetch = original;
  }
});

test("getReceipt surfaces a 404 as a 404, not as a generic failure", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("{}", { status: 404 });
  try {
    await getReceipt("token", "drewjst/doug", 90);
    assert.fail("should have thrown");
  } catch (error) {
    assert.equal(error.status, 404);
  } finally {
    globalThis.fetch = original;
  }
});

test("getReceipt sends repo as a query parameter, encoded", async () => {
  const original = globalThis.fetch;
  let seen = "";
  globalThis.fetch = async (url) => {
    seen = String(url);
    return new Response("{}", { status: 404 });
  };
  try {
    await getReceipt("token", "drewjst/doug", 90).catch(() => {});
    assert.ok(seen.includes("/v1/prs/90/receipt?repo=drewjst%2Fdoug"));
  } finally {
    globalThis.fetch = original;
  }
});
```

Add `getReceipt` to that file's existing import from `./session-api.ts`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test 2>&1 | grep -A3 session-api`
Expected: FAIL — `getReceipt` is not exported; `status` is undefined.

- [ ] **Step 3: Write the implementation**

In `web/lib/session-api.ts`, replace the `SessionApiError` class:

```typescript
export class SessionApiError extends Error {
  /** The HTTP status when the request reached the API, null when it did not
   *  (timeout, DNS, connection refused). The receipt screen needs 404 told
   *  apart from 401 and 503: they are three different true statements, and
   *  reporting a deployment fault as a credential problem is the failure the
   *  API's own status contract exists to prevent. */
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.status = status;
  }
}
```

In `sessionJson`, pass the status through:

```typescript
    if (!response.ok) throw new SessionApiError(message, response.status);
```

Add the import at the top of the file:

```typescript
import { isReceiptResponse, type ReceiptResponse } from "./receipt-shape";
```

No `.ts` extension — this is a source file, and `next build` rejects the extension with TS5097. The test file is the opposite case and keeps its `.ts`.

Add the fetch at the end of the file:

```typescript
/** One PR's evidentiary record.
 *
 *  `repo` travels as a query parameter because a PR number alone is ambiguous
 *  across repositories — the API requires it for that reason. No new scope is
 *  needed: SESSION_SCOPES already carries `receipt:read`
 *  (`api/doug/session_auth.py:27`). */
export async function getReceipt(
  accessToken: string,
  repo: string,
  prNumber: number,
): Promise<ReceiptResponse> {
  const message = "Doug could not load this receipt.";
  const body = await sessionJson(
    `/v1/prs/${prNumber}/receipt?repo=${encodeURIComponent(repo)}`,
    accessToken,
    message,
  );
  if (!isReceiptResponse(body)) throw new SessionApiError(message);
  return body;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test 2>&1 | tail -20`
Expected: PASS, and every pre-existing session-api test still passes.

- [ ] **Step 5: Mutation proof**

Temporarily revert the `sessionJson` line to `throw new SessionApiError(message)`. Run `npm test --workspace=web`. Expected: the 404 test FAILS with `undefined !== 404`. Restore the line and re-run to green.

- [ ] **Step 6: Commit**

```bash
git add web/lib/session-api.ts web/lib/session-api.test.mjs
git commit -m "feat(web): carry HTTP status on SessionApiError, add getReceipt"
```

---

### Task 3: Verdict-level honesty decisions

**Files:**
- Create: `web/lib/receipt-verdict-view.ts`
- Test: `web/lib/receipt-verdict-view.test.mjs`

**Interfaces:**
- Consumes: `ReceiptVerdict`, `ReceiptResponse` from Task 1.
- Produces: `readLine(read: ReceiptRead): string`, `promptHashLine(v: ReceiptVerdict): string`, `latestVerdictCaption(): string`, `verdictGap(receipt: ReceiptResponse): VerdictGap | null` where `interface VerdictGap { latestId: number; governingId: number; mergeSha: string }`.

- [ ] **Step 1: Write the failing test**

Create `web/lib/receipt-verdict-view.test.mjs`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  latestVerdictCaption,
  promptHashLine,
  readLine,
  verdictGap,
} from "./receipt-verdict-view.ts";

test("an unrecorded read renders as not recorded, never as a number", () => {
  const line = readLine({ diff_budget: null, read_order: null, recorded: false });
  assert.equal(line, "not recorded");
});

test("a half-stamped read is still not recorded — a budget with no ordering is not an instrument", () => {
  const line = readLine({ diff_budget: 100000, read_order: null, recorded: false });
  assert.equal(line, "not recorded");
  assert.ok(!line.includes("100000"), "must not quote a budget nothing was read under");
});

test("a recorded read quotes both halves", () => {
  const line = readLine({ diff_budget: 100000, read_order: "tier", recorded: true });
  assert.equal(line, "100000 chars · tier order");
});

test("an unstamped prompt hash never reads as a match against the frozen prompt", () => {
  const line = promptHashLine({ prompt_hash: null });
  assert.equal(line, "not stamped");
  assert.ok(!/match|frozen|verified/i.test(line));
});

test("a stamped prompt hash renders the hash", () => {
  assert.equal(promptHashLine({ prompt_hash: "abc123" }), "abc123");
});

test("the latest-verdict caption states the external EXCLUSION, not merely the topic", () => {
  const caption = latestVerdictCaption();
  // Exact equality, deliberately. A /external/i check would pass on
  // "…including external reviews" — the precise inversion this caption
  // exists to prevent — so it cannot discriminate the thing that matters.
  assert.equal(
    caption,
    "Doug's most recent score. Excludes external reviews, which carry no read.",
  );
});

test("a gap between latest and governing is reported with both ids", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1076 },
    merges: [
      { merge_commit_sha: "70fe216", publication_governing: true, governing_verdict: { verdict_id: 1044 } },
    ],
  });
  assert.deepEqual(gap, { latestId: 1076, governingId: 1044, mergeSha: "70fe216" });
});

test("no gap is reported when latest IS the governing verdict", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1044 },
    merges: [
      { merge_commit_sha: "70fe216", publication_governing: true, governing_verdict: { verdict_id: 1044 } },
    ],
  });
  assert.equal(gap, null);
});

test("no gap is reported when the governing merge has no governing verdict", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1044 },
    merges: [
      { merge_commit_sha: "70fe216", publication_governing: true, governing_verdict: null },
    ],
  });
  assert.equal(gap, null);
});

test("the gap reads the publication-governing merge, not merely the first", () => {
  const gap = verdictGap({
    latest_verdict: { verdict_id: 1076 },
    merges: [
      { merge_commit_sha: "aaa", publication_governing: false, governing_verdict: { verdict_id: 900 } },
      { merge_commit_sha: "bbb", publication_governing: true, governing_verdict: { verdict_id: 1044 } },
    ],
  });
  assert.equal(gap.governingId, 1044);
  assert.equal(gap.mergeSha, "bbb");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test 2>&1 | grep -A3 receipt-verdict-view`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

Create `web/lib/receipt-verdict-view.ts`:

```typescript
import type { ReceiptRead, ReceiptResponse, ReceiptVerdict } from "./receipt-shape";

/** What the reader was configured to see.
 *
 *  `recorded` is the API's own AND of both columns, and this function trusts
 *  it rather than re-deriving: a budget with no ordering does not say which
 *  part of the diff the model saw, and an ordering with no budget does not
 *  say how much of it. Quoting either half alone would let a reader cite a
 *  budget nothing was actually read under. */
export function readLine(read: Pick<ReceiptRead, "diff_budget" | "read_order" | "recorded">): string {
  if (!read.recorded) return "not recorded";
  return `${read.diff_budget} chars · ${read.read_order} order`;
}

/** Null means the row predates prompt-hash stamping on the worker path. It is
 *  NOT a match against the frozen prompt and must never render as one. */
export function promptHashLine(verdict: Pick<ReceiptVerdict, "prompt_hash">): string {
  return verdict.prompt_hash ?? "not stamped";
}

/** `latest_verdict` excludes `tier='external'` (`store.py:1786-1798`), and the
 *  reason is not tidiness: `save_external_review` fires on every
 *  `pull_request_review` and writes a row stamped with the human reviewer's
 *  `submitted_at` and 0.0/0.0 score/threshold placeholders, because no model
 *  ran and no diff was read. On a PR approved after Doug's last score that row
 *  is newest and would win the sort. So this is not "the newest verdict on
 *  this PR" — a human approval may well be newer. */
export function latestVerdictCaption(): string {
  return "Doug's most recent score. Excludes external reviews, which carry no read.";
}

export interface VerdictGap {
  latestId: number;
  governingId: number;
  mergeSha: string;
}

/** The gap a reader of an incident review came for: what Doug says NOW versus
 *  what was standing when a human chose to merge. Read from the
 *  publication-governing merge specifically — with several merges, the first
 *  is not necessarily the one that governs. */
export function verdictGap(
  receipt: Pick<ReceiptResponse, "latest_verdict" | "merges">,
): VerdictGap | null {
  const latest = receipt.latest_verdict;
  if (!latest) return null;
  const governingMerge = receipt.merges.find((merge) => merge.publication_governing);
  const governing = governingMerge?.governing_verdict;
  if (!governingMerge || !governing) return null;
  if (governing.verdict_id === latest.verdict_id) return null;
  return {
    latestId: latest.verdict_id,
    governingId: governing.verdict_id,
    mergeSha: governingMerge.merge_commit_sha,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test 2>&1 | tail -20`
Expected: PASS.

- [ ] **Step 5: Mutation proof — the three that matter**

Each of these must turn a test red. Run `npm test --workspace=web` after each, then restore.

1. In `readLine`, change the guard to `if (read.diff_budget === null) return "not recorded";` — the half-stamped test must FAIL.
2. In `promptHashLine`, change the fallback to `"verified against the frozen prompt"` — the unstamped test must FAIL.
3. In `verdictGap`, change `receipt.merges.find((merge) => merge.publication_governing)` to `receipt.merges[0]` — the multi-merge test must FAIL.

- [ ] **Step 6: Commit**

```bash
git add web/lib/receipt-verdict-view.ts web/lib/receipt-verdict-view.test.mjs
git commit -m "feat(web): verdict-level receipt honesty states"
```

---

### Task 4: Merge and window-level honesty decisions

**Files:**
- Create: `web/lib/receipt-merge-view.ts`
- Test: `web/lib/receipt-merge-view.test.mjs`

**Interfaces:**
- Consumes: `ReceiptWindow`, `ReceiptMerge`, `ReceiptPreregistration` from Task 1.
- Produces: `windowOutcome(w: ReceiptWindow): { text: string; tone: "clear" | "flag" | "neutral" }`, `windowPreregLine(w: ReceiptWindow, inForce: ReceiptPreregistration): string`, `governingLine(m: ReceiptMerge): string`, `mergedHeadLine(m: ReceiptMerge): string`, `mergeCaption(m: ReceiptMerge, total: number): string`.

**Why `mergeCaption` exists.** §2.2 state #8 — a merge that is not publication-governing must render its `publication_note` verbatim and must never be silently dropped — is otherwise only observable in the page, and render tests are banned. Making it a pure function is what puts it inside `node --test`'s reach.

- [ ] **Step 1: Write the failing test**

Create `web/lib/receipt-merge-view.test.mjs`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  governingLine,
  mergedHeadLine,
  windowOutcome,
  windowPreregLine,
} from "./receipt-merge-view.ts";

function win(overrides = {}) {
  return {
    window_days: 14,
    status: "pending",
    due_at: "2026-08-24T00:00:00Z",
    kind: null,
    observed_at: null,
    source: null,
    detail: null,
    prereg_hash: null,
    ...overrides,
  };
}

test("an open window reports the JOB status, never an adjudication word", () => {
  const out = windowOutcome(win({ status: "pending", kind: null }));
  assert.equal(out.text, "pending");
  assert.equal(out.tone, "neutral");
  assert.ok(!/clean|revert|censored/i.test(out.text));
});

test("a failed job is not a clean result", () => {
  const out = windowOutcome(win({ status: "failed", kind: null }));
  assert.equal(out.text, "failed");
  assert.equal(out.tone, "neutral");
});

test("clean adjudicates to clear", () => {
  const out = windowOutcome(win({ status: "done", kind: "clean" }));
  assert.deepEqual(out, { text: "clean", tone: "clear" });
});

test("revert adjudicates to flag", () => {
  const out = windowOutcome(win({ status: "done", kind: "revert" }));
  assert.deepEqual(out, { text: "revert", tone: "flag" });
});

test("censored is a NON-OBSERVATION, never painted as a miss", () => {
  const out = windowOutcome(win({ status: "done", kind: "censored" }));
  assert.equal(out.text, "censored");
  assert.equal(out.tone, "neutral", "censored in the miss colour is the #93 defect");
});

test("a pending window points at what WILL govern it, labelled as such", () => {
  const line = windowPreregLine(win({ prereg_hash: null }), { hash: "c8e30da3", in_force: true });
  assert.ok(line.includes("c8e30da3"));
  assert.ok(/will govern/i.test(line), "must not claim this document governed it");
});

test("an adjudicated window quotes ITS OWN stamp, not the one in force", () => {
  const line = windowPreregLine(win({ prereg_hash: "v8old" }), { hash: "c8e30da3", in_force: true });
  assert.ok(line.includes("v8old"));
  assert.ok(!line.includes("c8e30da3"), "reprinting today's hash manufactures a claim");
});

test("no pre-registration in force renders as absence, never a fabricated hash", () => {
  const line = windowPreregLine(win({ prereg_hash: null }), { hash: null, in_force: false });
  assert.equal(line, "no pre-registration in force");
});

test("a merge with no governing verdict falls back to its own words, not the latest verdict", () => {
  // publication_note is deliberately EMPTY here. A fixture whose note already
  // reads "no governing verdict" would pass whether or not the null-branch
  // exists — the note would simply pass through — so it proves nothing about
  // the branch it is named for.
  const line = governingLine({ governing_verdict: null, publication_note: "" });
  assert.equal(line, "no governing verdict at this merge");
});

test("a merge WITH a governing verdict renders its note verbatim", () => {
  const line = governingLine({
    governing_verdict: { verdict_id: 1044 },
    publication_note: "governing merge",
  });
  assert.equal(line, "governing merge");
});

test("an unrecorded merged head sha renders as not recorded", () => {
  assert.equal(mergedHeadLine({ merged_head_sha: null }), "not recorded");
});

test("a recorded merged head sha renders it", () => {
  assert.equal(mergedHeadLine({ merged_head_sha: "fe307ab6" }), "fe307ab6");
});

test("a non-governing merge is named as not governing", () => {
  const caption = mergeCaption(
    { publication_governing: false, publication_note: "superseded by a later merge" },
    2,
  );
  assert.equal(caption, "not the governing merge");
  // The note is governingLine's job. Repeating it here would print the same
  // sentence twice per merge on the page.
  assert.ok(!caption.includes("superseded by a later merge"));
});

test("the governing merge is named as governing", () => {
  const caption = mergeCaption(
    { publication_governing: true, publication_note: "governing merge" },
    2,
  );
  assert.equal(caption, "governs the published record");
});

test("a single merge needs no governing qualifier", () => {
  const caption = mergeCaption({ publication_governing: true, publication_note: "" }, 1);
  assert.equal(caption, "");
});
```

Add `mergeCaption` to that file's import list.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test 2>&1 | grep -A3 receipt-merge-view`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

Create `web/lib/receipt-merge-view.ts`:

```typescript
import type {
  ReceiptMerge,
  ReceiptPreregistration,
  ReceiptWindow,
} from "./receipt-shape";

export type OutcomeTone = "clear" | "flag" | "neutral";

/** §6.2 keeps two vocabularies apart and so does this: `status` is the JOB's
 *  (pending | running | done | failed), `kind` is the ADJUDICATION's
 *  (revert | clean | censored). A null `kind` means the window is still open
 *  or the job never completed — which is not a clean result and is never
 *  substituted with one.
 *
 *  The tone mapping is the rule ruled in the two-lane plan and shipped in #93:
 *  `clean` → clear, `censored` → NEUTRAL, any other non-null → flag, null →
 *  neutral. `censored` is an UNOBSERVED outcome; painting it in the miss
 *  colour reports a non-observation as a miss.
 *
 *  KNOWN LATENT CASE: `store.py:126-129` documents that `outcomes.kind` is
 *  wide enough to hold `hotfix` — "permitted, not produced", and explicitly
 *  NOT a miss. Nothing writes it today (prereg §10 says it is deliberately
 *  never written), so the default branch never sees it. If that ever changes,
 *  `hotfix` would land in `flag` and repeat #93's error on a new value. Add
 *  its branch at the same time as its writer, not before — an unreachable
 *  branch is untestable, and this comment is the reminder. */
export function windowOutcome(w: Pick<ReceiptWindow, "status" | "kind">): {
  text: string;
  tone: OutcomeTone;
} {
  if (w.kind === null) return { text: w.status, tone: "neutral" };
  if (w.kind === "clean") return { text: "clean", tone: "clear" };
  if (w.kind === "censored") return { text: "censored", tone: "neutral" };
  return { text: w.kind, tone: "flag" };
}

/** Which methodology document governs this window.
 *
 *  A window's own stamp is authoritative for it forever. Reprinting the
 *  in-force hash over an already-adjudicated window would manufacture a
 *  confident-but-derived claim about which document actually governed it —
 *  the one thing the receipt design exists to prevent. A pending window has
 *  no stamp, so it names what WILL govern it, in those words. */
export function windowPreregLine(
  w: Pick<ReceiptWindow, "prereg_hash">,
  inForce: ReceiptPreregistration,
): string {
  if (w.prereg_hash !== null) return `${w.prereg_hash} · stamped at adjudication`;
  if (!inForce.in_force || inForce.hash === null) return "no pre-registration in force";
  return `${inForce.hash} · will govern this window`;
}

/** A merged PR with no governing verdict says so. Falling back to
 *  `latest_verdict` here would claim advice was standing at a merge it was
 *  not standing at. */
export function governingLine(
  merge: Pick<ReceiptMerge, "governing_verdict" | "publication_note">,
): string {
  if (merge.governing_verdict === null) {
    return merge.publication_note || "no governing verdict at this merge";
  }
  return merge.publication_note;
}

/** Null on merges recorded before migration 008, and on any payload carrying
 *  no `pull_request.head` (a deleted fork branch). Never inferred. */
export function mergedHeadLine(merge: Pick<ReceiptMerge, "merged_head_sha">): string {
  return merge.merged_head_sha ?? "not recorded";
}

/** A PR can carry several merges — `uq_outcome_job` includes
 *  `merge_commit_sha`, and revert-and-reland is the ordinary case. Exactly one
 *  is publication-governing. Every merge renders; this caption is what stops a
 *  non-governing one from reading as though it were the record, and what stops
 *  the page from quietly showing only one.
 *
 *  Silent above a single merge: there is nothing to disambiguate, and a
 *  "governs" badge on the only merge present would imply a choice was made. */
export function mergeCaption(
  merge: Pick<ReceiptMerge, "publication_governing" | "publication_note">,
  totalMerges: number,
): string {
  if (totalMerges <= 1) return "";
  // The ROLE only. `governingLine` already renders `publication_note`, and a
  // page that calls both would print the same sentence twice per merge.
  return merge.publication_governing
    ? "governs the published record"
    : "not the governing merge";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test 2>&1 | tail -20`
Expected: PASS.

- [ ] **Step 5: Mutation proof — the two asymmetric ones**

1. In `windowOutcome`, change the null branch to `return { text: "clean", tone: "clear" };` — the open-window and failed-job tests must FAIL. This is the single most dangerous substitution on the screen.
2. In `windowPreregLine`, make the in-force hash win over a window's own stamp — replace the whole body with `return inForce.hash ? \`${inForce.hash} · will govern this window\` : "no pre-registration in force";`. The adjudicated-window test must FAIL, because the window's own `prereg_hash` is no longer consulted.

   Be careful with this one: merely reordering the `!inForce.in_force` guard above the `w.prereg_hash` check is **inert** — it changes nothing for a window that has a stamp, stays green, and proves nothing. A mutation that cannot fail is not a proof.

3. In `mergeCaption`, change the guard to `if (totalMerges >= 1) return "";` — the non-governing test must FAIL, because a multi-merge PR would then render every merge with no indication of which one governs.

Restore all three, re-run to green.

- [ ] **Step 6: Commit**

```bash
git add web/lib/receipt-merge-view.ts web/lib/receipt-merge-view.test.mjs
git commit -m "feat(web): merge and window-level receipt honesty states"
```

---

### Task 5: The receipt page

**Files:**
- Create: `web/app/dashboard/pr/[number]/page.tsx`
- Create: `web/lib/receipt-fixture.json`
- Modify: `web/app/dashboard/page.tsx`

**Interfaces:**
- Consumes: `getReceipt`, `SessionApiError` (Task 2); every exported function from Tasks 3 and 4; existing `BandChip`, `CoverageRuler`, `.panel`, `.mono`.
- Produces: the route `/dashboard/pr/[number]?repo=<full_name>`.

**Note on the fixture.** `receipt-fixture.json` is a test-and-development artifact exercising every §2.2 state at once: a PR with two merges, one publication-governing and one not; one merge with a null `governing_verdict`; a 14-day window adjudicated `censored` with its own `prereg_hash`; a 60-day window `pending` with none; a verdict with `read.recorded: false` and `prompt_hash: null`; and `merged_head_sha: null` on the older merge. Unlike the scoreboard fixture, it is **not** wired as a runtime fallback — a receipt that cannot be loaded renders an honest error state, never invented evidence.

- [ ] **Step 1: Write the page**

Create `web/app/dashboard/pr/[number]/page.tsx`. Render, in order: PR identity; the pre-registration block; `latest_verdict` with `latestVerdictCaption()` beneath it and `readLine(v.read)` / `promptHashLine(v)` in its provenance row; the gap banner when `verdictGap()` returns non-null, naming both verdict ids and the merge sha; then **every** entry of `merges` in order — each headed by `mergeCaption(merge, receipt.merges.length)`, carrying `governingLine(merge)` and `mergedHeadLine(merge)`, and listing its windows through `windowOutcome(w)` for the value and tone and `windowPreregLine(w, receipt.preregistration)` for the stamp.

The page holds no conditionals of its own beyond `failure` below: every honesty decision is already made by a tested function, and a `?:` added here is a decision that escaped the test suite.

Error states, per spec §2.4 — each is a distinct true statement:

```tsx
  let receipt: ReceiptResponse | null = null;
  let failure: "missing" | "expired" | "unavailable" | null = null;
  try {
    receipt = await getReceipt(accessToken, repo, prNumber);
  } catch (error) {
    const status = error instanceof SessionApiError ? error.status : null;
    // 404 covers BOTH "no such PR" and "not your repo", deliberately: the API
    // gives them one code AND one body so a caller cannot use this endpoint to
    // probe another tenant's repository names. Rendering them differently here
    // would rebuild the leak the API refused to open.
    if (status === 404) failure = "missing";
    // 503 is a deployment fault — no ledger, or no operator secret. The API
    // checks it BEFORE the token precisely so a misconfiguration is not
    // reported as a bad credential, and this must not undo that.
    else if (status === 503) failure = "unavailable";
    // 401 ONLY. `sessionJson` throws status:null on a transport failure AND on
    // a body the validator rejects; a 500 or 502 is neither. Routing any of
    // those to the expiry copy tells a reader to sign out and back in over a
    // network blip — a confident false claim on the one surface built to make
    // those impossible.
    else if (status === 401) failure = "expired";
    else failure = "unreachable";
  }
```

Copy for each: `missing` → "No receipt for this pull request."; `unavailable` → "The ledger is not answering."; `expired` → reuse the existing `reauthorize_required` treatment from #99/#100 rather than inventing a second expiry story; `unreachable` → "Doug could not load this receipt." with no instruction to sign in and no claim about why.

A PR with verdicts but no merges is the ordinary open-PR case, not an error: render `latest_verdict` and the literal line "not merged — no window has started".

- [ ] **Step 2: Link the dashboard's PR groups to it**

In `web/app/dashboard/page.tsx`, each `PrGroup` row links to `/dashboard/pr/${group.prNumber}?repo=${encodeURIComponent(group.repo)}`. `PrGroup` already carries both fields (`web/lib/grouping.ts:22-32`).

- [ ] **Step 3: Verify it builds and renders**

Run: `cd web && npm run build`
Expected: compiles, and the route list includes `/dashboard/pr/[number]`.

- [ ] **Step 4: Run the full suite and lint**

Run: `make test && make lint`
Expected: green in both workspaces.

- [ ] **Step 5: Commit**

```bash
git add web/app/dashboard/pr web/lib/receipt-fixture.json web/app/dashboard/page.tsx
git commit -m "feat(web): receipt screen at /dashboard/pr/[number]"
```

---

### Task 6: The 60-day join (API)

**Files:**
- Modify: `api/doug/store.py:2407`
- Modify: `api/doug/models.py:184`
- Modify: `api/doug/api.py` (`_run_item`)
- Test: `api/tests/test_store.py`, `api/tests/test_api.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `outcome_60: str | None` on every `run_history` row and on `RunSummaryItem`, beside the existing `outcome_14`.

- [ ] **Step 1: Write the failing test**

In `api/tests/test_store.py`, add a test that seeds one PR with a 14-day `clean` outcome and a 60-day `revert` outcome, then asserts `run_history` returns `outcome_14 == "clean"` **and** `outcome_60 == "revert"` on the same row — and that the row count is unchanged, i.e. two windows did not fan one run into two.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_store.py -k outcome_60 -v`
Expected: FAIL with `KeyError: 'outcome_60'`.

- [ ] **Step 3: Write the implementation**

In `store.run_history`, drop the `window_days == 14` filter and key the reduction by window. The existing last-observation-wins reduction is preserved **per window** — the comment at that site explains why a list column would fan one run into two rows, and that reasoning is unchanged:

```python
        outcome_query = (
            select(outcomes)
            .where(outcomes.c.window_days.in_((14, 60)))
            .where(outcomes.c.repo.in_({k[0] for k in keys}))
            .where(outcomes.c.pr_number.in_({k[1] for k in keys}))
        )
```

then key by the triple:

```python
        outcome_by_pr = {
            (row["repo"], row["pr_number"], row["window_days"]): row["kind"]
            for row in conn.execute(outcome_query.order_by(outcomes.c.id)).mappings()
        }
```

and emit two scalars:

```python
        row["outcome_14"] = outcome_by_pr.get((row["repo"], row["pr_number"], 14))
        row["outcome_60"] = outcome_by_pr.get((row["repo"], row["pr_number"], 60))
```

Add `outcome_60: str | None` to `RunSummaryItem` beside `outcome_14`, and pass it through in `_run_item`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest -q`
Expected: full suite green.

- [ ] **Step 5: Mutation proofs**

1. Reintroduce `.where(outcomes.c.window_days == 14)` — the new test must FAIL on `outcome_60 is None`.
2. Key the dict by `(repo, pr_number)` again — one window silently overwrites the other and the test must FAIL.

Clear `__pycache__` between weaken and restore. Restore and re-run to green.

- [ ] **Step 6: Commit**

```bash
git add api/doug/store.py api/doug/models.py api/doug/api.py api/tests/test_store.py api/tests/test_api.py
git commit -m "feat(api): join the 60-day outcome beside the 14-day one in run_history"
```

---

### Task 7: The 60-day column (both clients)

**Files:**
- Modify: `web/lib/session-api.ts` (`RunSummary`, `runSummary` validator, the `exact` key list)
- Modify: `console/lib/api.ts` (`RunSummary`)
- Modify: `web/lib/facets.ts`, `console/lib/facets.ts`
- Modify: `web/lib/search.ts`, `console/lib/search.ts`
- Modify: `web/app/dashboard/page.tsx`, `console/app/page.tsx`
- Test: `web/lib/facets.test.mjs`, `web/lib/console-lockstep.test.mjs`, `console/lib/facets.test.mjs`

**Interfaces:**
- Consumes: `outcome_60` from Task 6.
- Produces: a second always-shown outcome column and a `outcome_60` facet on both surfaces.

- [ ] **Step 1: Write the failing test**

In `web/lib/facets.test.mjs`, assert a 60-day facet exists and that a null `outcome_60` buckets as `"pending"` — mirroring the existing `outcome_14 ?? "pending"` treatment at `web/lib/facets.ts:63-67`. In `web/lib/console-lockstep.test.mjs`, extend the shared-row fixture with `outcome_60` so the two clients stay pinned together.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test 2>&1 | grep -A3 facets`
Expected: FAIL — no 60-day facet.

- [ ] **Step 3: Write the implementation**

Add `outcome_60: string | null` to both clients' `RunSummary`, to `web/lib/session-api.ts`'s `runSummary` validator and its `exact` key list, and to both `search.ts` searchable-field lists. Add the facet mirroring the 14-day one. Render **two separate labelled cells** per Decision 5 — 14d and 60d, each with its own pending state — so a row reading `clean` / `pending` shows exactly that.

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: green in api, web, and console.

- [ ] **Step 5: Mutation proof**

Collapse the two cells into one resolving to `outcome_60 ?? outcome_14` — a test asserting both cells render independently must FAIL. Restore.

- [ ] **Step 6: Commit**

```bash
git add web/lib console/lib web/app/dashboard/page.tsx console/app/page.tsx
git commit -m "feat(web,console): render the 60-day outcome beside the 14-day one"
```

---

## Exit gate (spec §5)

- [ ] `/dashboard/pr/[number]` renders a real receipt from the live ledger for a PR on `drewjst/doug`, with every §2.2 state exercised by `receipt-fixture.json` and each proven to discriminate.
- [ ] Both outcome columns render, and a row where 14d is `clean` and 60d is `pending` shows exactly that.
- [ ] Zero contradictions against the console on identical data.
- [ ] `make test` + `make lint` + `npm run build` green in both workspaces.
- [ ] Screenshots attached to the PR.
- [ ] Doug's own review comes back clean or is adjudicated into `docs/findings-log.jsonl`.
