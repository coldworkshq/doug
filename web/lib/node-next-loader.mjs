// Next intentionally supports extensionless package subpaths through its
// bundler. Node's test runner does not, so resolve those SDK imports exactly
// as their `.js` files only when the normal resolver rejects them.
export async function resolve(specifier, context, nextResolve) {
  if (specifier === "@workos-inc/authkit-nextjs") {
    // Matcher tests exercise Doug's exported Next config. AuthKit itself is
    // an external server-only dependency, so replace only its factory with
    // a no-op instead of loading the whole session stack in bare Node.
    const errorsModule = new URL(
      "../../node_modules/@workos-inc/authkit-nextjs/dist/esm/errors.js",
      import.meta.url,
    ).href;
    const stub = `
      export { CallbackError } from ${JSON.stringify(errorsModule)};
      export const authkitProxy = () => () => new Response();
      export const authkit = async () => ({
        session: { user: null },
        headers: new Headers(),
        authorizationUrl: "https://auth.workos.test/authorize",
      });
      export const handleAuthkitProxy = (_request, _headers, options = {}) =>
        options.redirect ? Response.redirect(options.redirect, 307) : new Response();
      export const handleAuthkitHeaders = handleAuthkitProxy;
      export const signOut = async () => {
        globalThis.__workosSignOutCalls = (globalThis.__workosSignOutCalls ?? 0) + 1;
      };
      export const handleAuth = (options) => {
        globalThis.__workosHandleAuthOptions = options;
        return async (request) => {
          if (globalThis.__workosCallbackError !== undefined) {
            return options.onError({ error: globalThis.__workosCallbackError, request });
          }
          return new Response();
        };
      };
      export const withAuth = async (options = {}) => {
        globalThis.__workosWithAuthOptions = [...(globalThis.__workosWithAuthOptions ?? []), options];
        return globalThis.__workosAuth ?? { user: null };
      };
      export const getSignInUrl = async (options = {}) => {
        globalThis.__workosSignInCalls = [...(globalThis.__workosSignInCalls ?? []), options];
        return globalThis.__workosSignInUrl ?? "https://auth.workos.test/authorize";
      };
    `;
    return {
      shortCircuit: true,
      url: `data:text/javascript,${encodeURIComponent(stub)}`,
    };
  }
  if (specifier === "@/lib/entitlements") {
    return nextResolve(new URL("../../../lib/entitlements.ts", context.parentURL).href, context);
  }
  if (specifier === "@/lib/install-flow") {
    return nextResolve(new URL("../../../lib/install-flow.ts", context.parentURL).href, context);
  }
  if (specifier === "@/lib/auth-origin") {
    return nextResolve(new URL("./auth-origin.ts", import.meta.url).href, context);
  }
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (specifier.startsWith("next/")) return nextResolve(`${specifier}.js`, context);
    // Lib-to-lib imports are written extensionless in app source because
    // Next's bundler resolves them (`lib/api.ts` does it too). Node needs the
    // real file. Extensionless specifiers ONLY: appending .ts to a failing
    // "./foo.mjs" would report "./foo.mjs.ts not found" and mask the real
    // error (Doug PR #90 review, reader:tooling-resolution-fallback).
    if (
      (specifier.startsWith("./") || specifier.startsWith("../")) &&
      !/\.[a-zA-Z]+$/.test(specifier)
    ) {
      return nextResolve(`${specifier}.ts`, context);
    }
    throw error;
  }
}
