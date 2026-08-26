// Source-text pin on components/runs-table.tsx (house rule: no component
// render tests — see web/lib/design-system.test.mjs's own note on the same
// rule). This is the console-side counterpart of web's
// dashboard-contract.test.mjs "the 14-day and 60-day outcomes render as two
// independent cells" test; the two pin the same property on each surface's
// own render site.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const tableUrl = new URL("../components/runs-table.tsx", import.meta.url);

test("the 14-day and 60-day outcomes render as two independent cells, never one collapsed to the other", async () => {
  // RULING (plan D-outcome-surface, project owner): 14-day and 60-day are two
  // separate, always-shown, separately-labelled columns, each with its own
  // pending state — NOT one column resolving to the strongest signal. They
  // are different observations of different windows, and collapsing them
  // (`outcome_60 ?? outcome_14`) would let a row's rendered "clean" silently
  // mean either window depending on data the reader cannot see.
  //
  // Mutation proof (brief Step 5): collapse the two <OutcomeCell> renders
  // into one fed `run.outcome_60 ?? run.outcome_14` and this test fails —
  // the independent `kind={run.outcome_14}` the first assertion requires is
  // gone, replaced by a single cell fed the fallback expression.
  const table = await readFile(tableUrl, "utf8");
  assert.match(
    table,
    /<OutcomeCell kind=\{run\.outcome_14\}/,
    "the 14-day cell must render run.outcome_14 through OutcomeCell, on its own",
  );
  assert.match(
    table,
    /<OutcomeCell kind=\{run\.outcome_60\}/,
    "the 60-day cell must render run.outcome_60 through OutcomeCell, on its own",
  );
  for (const collapsed of ["outcome_60 ?? run.outcome_14", "run.outcome_60 ?? run.outcome_14", "outcome_60 ?? outcome_14"]) {
    assert.equal(
      table.includes(collapsed),
      false,
      `the outcome columns must not collapse to one value (found "${collapsed}")`,
    );
  }
  // BOTH COLUMNS NAME THEIR OWN WINDOW — a row is never left to infer which
  // window a bare "outcome" header meant. That is the property; "14d outcome"
  // was one spelling of it, and it is no longer the spelling. The headers now
  // read "14d" / "60d" with the word they dropped in the ⓘ beside them,
  // because "14d outcome" overflowed its own column (the arithmetic is in the
  // COLUMNS comment). So the pin moved to the property rather than being
  // deleted along with the string it used to check.
  // Sliced to COLUMNS before matching, not scanned over the whole file:
  // the repositories table declares its own `label:` entries, and a bare
  // scan would judge this column set by another one's spelling.
  const columnArray = table.match(/const COLUMNS[^=]*=\s*\[([\s\S]*?)\n\];/)?.[1];
  assert.ok(columnArray, "COLUMNS is gone — the ledger has no pinned headers");
  const labels = [...columnArray.matchAll(/label:\s*"([^"]*)"/g)].map((m) => m[1]);
  assert.deepEqual(
    labels.filter((label) => /^\d+d$/.test(label)),
    ["14d", "60d"],
    "the two outcome columns no longer name their windows",
  );
  assert.equal(
    labels.includes("outcome"),
    false,
    'a bare "outcome" header leaves the reader to guess the window',
  );
  // …and each one hands back the word it dropped. A header shortened WITHOUT
  // the ⓘ is the regression this half exists to catch: it would leave the
  // ledger's most misread column labelled with nothing but a number.
  assert.match(columnArray, /hint: outcomeWindowHint\(14\)/);
  assert.match(columnArray, /hint: outcomeWindowHint\(60\)/);
});
