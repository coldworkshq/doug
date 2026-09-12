import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";

// The harness under the deploy-time smoke scripts' tests: run one script
// with its arguments and collect its exit code and output, and stand up a
// throwaway node:http server on a loopback port for it to probe. Not a test
// file itself; the test glob is `lib/**/*.test.mjs`.

export function runScript(script, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn("bash", [script, ...args], { cwd });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal, stdout, stderr }));
  });
}

export async function withServer(handler, run) {
  const server = createServer(handler);
  server.listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  const address = server.address();
  assert.equal(typeof address, "object");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    // Close idle keep-alive sockets too, or `close` waits on them.
    server.closeAllConnections?.();
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}
