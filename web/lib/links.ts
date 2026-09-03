/** Canonical GitHub repo identity. Hand-typed as a literal in enough places
 *  (site header, landing page, about page) that a rename or org transfer
 *  would otherwise mean grepping and editing every occurrence by hand —
 *  import from here instead of retyping the string. */
export const GITHUB_REPO_SLUG = "coldworkshq/doug";
export const GITHUB_REPO_URL = `https://github.com/${GITHUB_REPO_SLUG}`;

/** The company Doug is a product of. Doug ships independently and its
 *  records stay Doug-native (docs/repos.md), so this is an attribution and
 *  a link, never a dependency — nothing in `web/` imports from Coldworks.
 *
 *  THE APEX HAS TO BE MAPPED BEFORE THIS MERGES. `coldworks.dev` was
 *  registered 2026-08-20 and had no DNS records at all when this was
 *  written; the Coldworks landing page runs on the registry service's bare
 *  origin. Merging this while the apex is unmapped puts a dead link in the
 *  footer of the two most-read public pages.
 *
 *  THE SCRIPT THAT MAPS IT IS NOT IN THIS REPO. `coldworks.dev` fronts the
 *  `coldworks-registry` service in the `coldworks` GCP project, so it is
 *  mapped by `scripts/map_apex_domain.sh` in `coldworkshq/coldworks`.
 *  `api/deploy/domains.sh` here maps `doug.coldworks.dev` onto `doug-web`,
 *  which is a different service in a different project and does not make
 *  this link resolve. The two are independent; neither one blocks the other.
 */
export const COLDWORKS_URL = "https://coldworks.dev";
