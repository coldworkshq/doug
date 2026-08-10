// Next intentionally supports extensionless package subpaths through its
// bundler. Node's test runner does not, so resolve those SDK imports exactly
// as their `.js` files only when the normal resolver rejects them.
export async function resolve(specifier, context, nextResolve) {
  if (specifier === "@workos-inc/authkit-nextjs") {
    // Matcher tests exercise Doug's exported Next config. AuthKit itself is
    // an external server-only dependency, so replace only its factory with
    // a no-op instead of loading the whole session stack in bare Node.
    return {
      shortCircuit: true,
      url: "data:text/javascript,export const authkitProxy = () => () => new Response(); export const signOut = async () => { globalThis.__workosSignOutCalls = (globalThis.__workosSignOutCalls ?? 0) + 1; }; export const handleAuth = (options) => { globalThis.__workosHandleAuthOptions = options; return async () => new Response(); };",
    };
  }
  if (specifier === "@/lib/entitlements") {
    return nextResolve(new URL("../../../lib/entitlements.ts", context.parentURL).href, context);
  }
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (specifier.startsWith("next/")) return nextResolve(`${specifier}.js`, context);
    throw error;
  }
}
