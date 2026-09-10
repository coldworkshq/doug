/** Canonical GitHub repo identity. Hand-typed as a literal in enough places
 *  (site header, landing page, about page) that a rename or org transfer
 *  would otherwise mean grepping and editing every occurrence by hand —
 *  import from here instead of retyping the string. */
export const GITHUB_REPO_SLUG = "coldworkshq/doug";
export const GITHUB_REPO_URL = `https://github.com/${GITHUB_REPO_SLUG}`;

/** The company Doug is a product of, and the origin this app is ruled to
 *  serve (ADR-0034). Doug still ships independently and its records stay
 *  Doug-native (docs/repos.md). The one runtime dependency on Coldworks is
 *  `registry-api.ts`, a fetch of a public JSON document under a pinned
 *  contract, and it degrades to a chip with a reason when the document is
 *  missing; nothing in `web/` imports code from Coldworks.
 *
 *  The apex is live. `coldworks.dev` fronts the `coldworks-registry` service
 *  in the `coldworks` GCP project today; ADR-0034 moves it onto `doug-web`
 *  as a second domain mapping through `api/deploy/domains.sh`, with
 *  `doug.coldworks.dev` kept and redirecting. Until that cutover this link
 *  resolves to the registry's landing page, which is the same door.
 */
export const COLDWORKS_URL = "https://coldworks.dev";
