/**
 * Which installation may see the engine's registry as its Guards screen.
 *
 * `DOUG_GUARDS_INSTALLATIONS` is a comma-separated list of
 * `<installation id>:<engine tenant id>` pairs. It is the same house shape
 * as `DOUG_INTENT_INSTALLATIONS` in the API (`intent.enabled_for`): unset
 * maps nobody, and the mapping is set by the founder (design lock, R11 item
 * 3), because the registry today holds one tenant of synthetic wind-tunnel
 * data and the only honest reader of it is the dogfood installation.
 *
 * An installation with no mapping renders the `later` chip, on the same
 * code path as a mapped one: the branch is decided by this lookup, not by a
 * build flag, so a stranger and the founder run the same page.
 *
 * A malformed entry throws rather than being skipped. Skipping would turn a
 * typo in the one value that enables the dogfood into a silent "nobody", and
 * a silent nobody is the failure `intent.enabled_for` was rewritten to avoid.
 */
export class GuardsMappingError extends Error {}

export function parseGuardsMapping(raw: string | undefined): Map<number, string> {
  const out = new Map<number, string>();
  const text = (raw ?? "").trim();
  if (!text) return out;
  for (const entry of text.split(",")) {
    const pair = entry.trim();
    if (!pair) continue;
    const at = pair.indexOf(":");
    const id = at === -1 ? "" : pair.slice(0, at).trim();
    const tenant = at === -1 ? "" : pair.slice(at + 1).trim();
    if (!/^\d+$/.test(id) || !tenant) {
      throw new GuardsMappingError(
        `DOUG_GUARDS_INSTALLATIONS entry ${JSON.stringify(pair)} is not ` +
          "<installation id>:<engine tenant id>; refusing to guess who may see the registry",
      );
    }
    out.set(Number(id), tenant);
  }
  return out;
}

/** The engine tenant this installation may read, or null: render the chip. */
export function engineTenantFor(
  installationId: number | null | undefined,
  raw: string | undefined = process.env.DOUG_GUARDS_INSTALLATIONS,
): string | null {
  if (installationId === null || installationId === undefined) return null;
  return parseGuardsMapping(raw).get(installationId) ?? null;
}
