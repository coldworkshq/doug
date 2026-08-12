// The generated shadcn files are ours to edit — that is the whole point of the
// copy-in model. Two edits to table.tsx are load-bearing rather than cosmetic,
// so they are pinned here: a future `shadcn add table --overwrite` regenerates
// the file with both reverted, silently, and nothing else in the suite would
// notice.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const tableUrl = new URL("../components/ui/table.tsx", import.meta.url);
const popoverUrl = new URL("../components/ui/popover.tsx", import.meta.url);
const sliderUrl = new URL("../components/ui/slider.tsx", import.meta.url);

test("the run ledger's table primitives stay server components", async () => {
  // Every one of shadcn's eight table components is a pure prop spread over an
  // intrinsic element — no hooks, no handlers, no state. The generated
  // "use client" is boilerplate, and keeping it would drag a client boundary
  // around the entire run ledger for styling that needs none. The dashboard is
  // a server component by ruling; this is what keeps its biggest subtree one.
  const table = await readFile(tableUrl, "utf8");
  assert.equal(table.includes('"use client"'), false);
  assert.equal(table.includes("'use client'"), false);

  // Non-vacuity: this test is only meaningful while the file still HAS the
  // components. A deleted table.tsx would otherwise pass it.
  assert.match(table, /export \{[\s\S]*\bTable\b[\s\S]*\}/);
  assert.match(table, /function TableHead\(/);

  // ...and the guard is only real if it is the absence of hooks that makes it
  // safe, not an oversight. If any of these appear, the directive must come
  // back and this test must be reconsidered — not deleted.
  for (const hook of ["useState", "useEffect", "useRef", "onClick"]) {
    assert.equal(table.includes(hook), false, `table.tsx uses ${hook} — it is not a server component`);
  }
});

test("Table's own scroll container is the one the caller can bound", async () => {
  // Table renders a container div with overflow-x-auto. The run ledger needs a
  // BOUNDED height on that same element: a max-h wrapper around Table would
  // nest a second scroll container inside the first, and a sticky <th> inside
  // the inner one scrolls away with the rows it is supposed to pin.
  const table = await readFile(tableUrl, "utf8");
  assert.match(table, /containerClassName/);
  assert.match(table, /data-slot="table-container"/);

  // The div's own attribute list, bounded at ITS closing `>`. A lazy match to
  // the first `/>` runs past it into the self-closing <table> inside, which
  // means the assertion would still pass with containerClassName moved onto
  // the table — the exact defect this test exists to catch.
  const container = table.match(/<div[^>]*data-slot="table-container"[^>]*>/)?.[0] ?? "";
  assert.ok(container, "the table container div is gone");
  assert.match(container, /containerClassName/);
  // ...and it must NOT be on the table, where it would nest a second scroll
  // container inside the first and unstick the header.
  const tableEl = table.match(/<table[\s\S]*?\/>/)?.[0] ?? "";
  assert.ok(tableEl, "the <table> element is gone");
  assert.equal(tableEl.includes("containerClassName"), false);
});

test("the primitives that genuinely need a client boundary keep it", async () => {
  // The inverse pin. Popover and Slider are Radix primitives with real state
  // and event handling; stripping their directive to match table.tsx would
  // break them at runtime, not at build time.
  const [popover, slider] = await Promise.all([
    readFile(popoverUrl, "utf8"),
    readFile(sliderUrl, "utf8"),
  ]);
  assert.match(popover, /^"use client"/);
  assert.match(slider, /^"use client"/);
});
