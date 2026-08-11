import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const TOKEN = "fixture-purpose-token";
const PACK_HASH = "a".repeat(64);
const FINDING_ID = "b".repeat(64);
const children = [];

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function start(command, args, env) {
  const child = spawn(command, args, { cwd: ROOT, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
  child.output = "";
  child.stdout.on("data", (chunk) => { child.output += chunk; });
  child.stderr.on("data", (chunk) => { child.output += chunk; });
  children.push(child);
  return child;
}

async function waitFor(url, child, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`process exited ${child.exitCode}\n${child.output}`);
    try {
      const response = await fetch(url);
      if (response.status < 500) return response;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(`timed out waiting for ${url}\n${child.output}`);
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  const fixturePort = await freePort();
  const consolePort = await freePort();
  const fixture = start(process.execPath, [path.join(ROOT, "scripts/example-pack-fixture-api.mjs")], {
    PORT: String(fixturePort),
    DOUG_EXAMPLE_PACK_TOKEN: TOKEN,
  });
  await waitFor(`http://127.0.0.1:${fixturePort}/v1/example-pack-cohorts`, fixture);

  const next = start(path.resolve(ROOT, "../node_modules/.bin/next"), ["dev", "--hostname", "127.0.0.1", "--port", String(consolePort)], {
    DOUG_API_URL: `http://127.0.0.1:${fixturePort}`,
    DOUG_EXAMPLE_PACK_TOKEN: TOKEN,
    DOUG_API_TOKEN: "operator-token-not-used-by-example-pack",
  });
  await waitFor(`http://127.0.0.1:${consolePort}/example-packs`, next);

  const list = await fetch(`http://127.0.0.1:${consolePort}/example-packs`);
  const listHtml = await list.text();
  assert(list.status === 200, `list returned ${list.status}`);
  assert(listHtml.includes("complete-docket"), "list omitted deterministic newest cohort");
  assert(listHtml.includes("100.0%") && listHtml.includes("N=1"), "list omitted denominator-bearing scorecard");
  assert(listHtml.includes(PACK_HASH), "list omitted exact pack link");

  const blocked = await fetch(`http://127.0.0.1:${consolePort}/example-packs?cohort=blocked-missing`);
  const blockedHtml = await blocked.text();
  assert(blocked.status === 200, `blocked cohort returned ${blocked.status}`);
  assert(blockedHtml.includes("Scorecards blocked"), "blocked cohort omitted its scorecard boundary");
  assert(blockedHtml.includes("drewjst/doug #81"), "blocked cohort omitted the exact missing identity");
  assert(!blockedHtml.includes("100.0%"), "blocked cohort rendered a plausible rate");

  const detailUrl = `http://127.0.0.1:${consolePort}/example-packs/${PACK_HASH}?cohort=complete-docket`;
  const detail = await fetch(detailUrl);
  const detailHtml = await detail.text();
  assert(detail.status === 200, `detail returned ${detail.status}`);
  assert(detailHtml.includes("Finding docket"), "detail omitted adjudication docket");
  assert(detailHtml.includes("Evidence receipts"), "detail omitted capture receipts");
  assert(detailHtml.includes("Whole instrument manifest"), "detail omitted instrument identity");
  assert(!detailHtml.includes("<script>alert('fixture')</script>"), "captured script reached HTML as executable markup");
  assert(detailHtml.includes("&lt;script&gt;"), "captured script was not rendered as escaped text");

  const adjudicationUrl = `http://127.0.0.1:${fixturePort}/v1/example-pack-cohorts/complete-docket/packs/${PACK_HASH}/findings/${FINDING_ID}/adjudications`;
  const input = { disposition: "unknown", evidence: [], verifier_receipts: [], expected_current_adjudication_id: null };
  const first = await fetch(adjudicationUrl, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Doug-Example-Pack-Token": TOKEN },
    body: JSON.stringify(input),
  });
  assert(first.status === 200, `adjudication returned ${first.status}`);
  const stale = await fetch(adjudicationUrl, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Doug-Example-Pack-Token": TOKEN },
    body: JSON.stringify(input),
  });
  assert(stale.status === 409, `stale correction returned ${stale.status}`);

  const refreshed = await fetch(detailUrl);
  const refreshedHtml = await refreshed.text();
  assert(refreshedHtml.includes("andrew-fixture"), "detail did not refresh the append-only adjudication head");
  process.stdout.write("Example Pack smoke passed: list, exact evidence, adjudication, stale correction, refresh\n");
}

try {
  await main();
} finally {
  for (const child of children.reverse()) {
    if (child.exitCode === null) child.kill("SIGTERM");
  }
}
