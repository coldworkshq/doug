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
  // One rule for the whole `@/lib/*` alias, not a line per module. The three
  // hand-written entries this replaces had drifted into two shapes: two resolved
  // `../../../lib/<name>.ts` against the IMPORTER, which is only correct for an
  // importer exactly three segments deep, and one resolved against this file,
  // which is correct for every importer. Adding a fourth by hand is how the
  // route's `@/lib/links` import failed to load at all. This loader lives in
  // `web/lib/`, so the alias is always the sibling.
  //
  // THE EXTENSIONLESS-ONLY RULE FROM THE FALLBACK AT THE END OF THIS FUNCTION
  // APPLIES HERE TOO, and for the same reason it is stated there: appending
  // `.ts` to `@/lib/queue-fixture.json` would report `queue-fixture.json.ts`
  // missing and mask the real error. A specifier that names its extension is
  // resolved exactly as written.
  if (specifier.startsWith("@/lib/")) {
    const target = new URL(`./${specifier.slice("@/lib/".length)}`, import.meta.url);
    const namesExtension = /\.[a-zA-Z]+$/.test(target.pathname);
    return nextResolve(namesExtension ? target.href : `${target.href}.ts`, context);
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
