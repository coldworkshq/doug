"use server";

import { switchToOrganization, withAuth } from "@workos-inc/authkit-nextjs";
import { revalidatePath } from "next/cache";

import {
  frontDoor,
  isFinishableSetupConnection,
  parseBool,
  parseFlagLine,
  parseGithubRepoId,
  parseInstallationId,
  readyOrganizationAfterSetup,
} from "@/lib/dashboard-model";
import {
  SessionApiError,
  bindInstallation,
  getConnections,
  setRepositoryDeepRead,
  setRepositoryPrComment,
  setRepositoryThreshold,
} from "@/lib/session-api";

const SETUP_ERROR = "That repository connection is not available.";
const FLAG_LINE_ERROR = "Doug could not save that flag line.";
const FLAG_LINE_REAUTH =
  "Your session's repository access has aged out — sign in again to change settings.";
const PR_COMMENT_ERROR = "Doug could not save that PR comment setting.";
const DEEP_READ_ERROR = "Doug could not save that deep read setting.";

/** Every route that renders the per-repository controls. All three settings
 *  writes revalidate ALL of them, because the repositories table and
 *  /dashboard/settings render the same component over the same row —
 *  revalidating one would leave the other showing the state before the click,
 *  and two surfaces disagreeing about a setting is worse than either being
 *  stale: it makes the reader doubt the write landed at all.
 *
 *  A LOOP, not a spread: `revalidatePath(path, type?)` takes a second
 *  argument that is `'page' | 'layout'`, so `revalidatePath(...paths)` would
 *  hand it "/dashboard/settings" as a `type` — invalid, and silently the
 *  wrong call rather than a compile error worth reading. */
const DASHBOARD_SURFACES = ["/dashboard", "/dashboard/settings"] as const;

function revalidateDashboard(): void {
  for (const path of DASHBOARD_SURFACES) revalidatePath(path);
}

export async function finishSetupAction(formData: FormData): Promise<void> {
  let organizationId: string;
  try {
    const installationId = parseInstallationId(formData.get("installation_id"));
    if (installationId === null) throw new Error(SETUP_ERROR);

    const auth = await withAuth();
    if (!auth.user || !auth.accessToken) throw new Error(SETUP_ERROR);

    const before = await getConnections(auth.accessToken);
    if (!isFinishableSetupConnection(before.connections, installationId)) {
      throw new Error(SETUP_ERROR);
    }

    await bindInstallation(auth.accessToken, installationId);

    const after = await getConnections(auth.accessToken);
    const readyOrganizationId = readyOrganizationAfterSetup(
      after.connections,
      installationId,
    );
    if (!readyOrganizationId) throw new Error(SETUP_ERROR);
    organizationId = readyOrganizationId;
  } catch {
    throw new Error(SETUP_ERROR);
  }

  await switchToOrganization(organizationId, { returnTo: "/dashboard" });
}

export async function switchConnectionAction(formData: FormData): Promise<void> {
  const organizationId = formData.get("organization_id");
  if (typeof organizationId !== "string" || !organizationId) {
    throw new Error("That connected space is not available.");
  }

  const auth = await withAuth();
  if (!auth.user || !auth.accessToken) {
    throw new Error("That connected space is not available.");
  }
  const { connections } = await getConnections(auth.accessToken);
  const allowed = connections.some(
    (connection) =>
      connection.status === "ready" && connection.organization_id === organizationId,
  );
  if (!allowed) throw new Error("That connected space is not available.");

  await switchToOrganization(organizationId, { returnTo: "/dashboard" });
}

/** Write one repository's flag line — the line Doug scores its FUTURE reviews
 *  against. Nothing already recorded moves; the API stamps the resolved line
 *  onto each verdict at scoring time, so this changes what happens next and
 *  never what was said before.
 *
 *  An unreadable value is refused rather than defaulted. `parseFlagLine`
 *  returns undefined for garbage and null only for the exact empty string the
 *  reset form carries, so "clear this override" can never be performed by
 *  accident on input Doug could not read. */
export async function setFlagLineAction(formData: FormData): Promise<void> {
  const repoId = parseGithubRepoId(formData.get("github_repo_id"));
  const line = parseFlagLine(formData.get("needs_you_threshold"));
  if (repoId === null || line === undefined) throw new Error(FLAG_LINE_ERROR);

  const auth = await withAuth();
  if (!auth.user || !auth.accessToken) throw new Error(FLAG_LINE_ERROR);

  // The API is authoritative about who may write this row; this pre-check only
  // makes the failure legible when the id belongs to a connection other than
  // the selected one — the same shape of check switchConnectionAction makes
  // before opening a space.
  const { connections } = await getConnections(auth.accessToken);
  const door = frontDoor(connections, auth.organizationId ?? null);
  if (!door.current?.repositories.some((repository) => repository.id === repoId)) {
    throw new Error(FLAG_LINE_ERROR);
  }

  try {
    await setRepositoryThreshold(auth.accessToken, repoId, line);
  } catch (error) {
    // 401 is the one failure with a different remedy: the session's derived
    // repository scope has aged past entitlements.TTL, and no amount of
    // retrying this form fixes it. Reporting that as "could not save" would
    // send someone back to a control that cannot work yet.
    if (error instanceof SessionApiError && error.status === 401) {
      throw new Error(FLAG_LINE_REAUTH);
    }
    throw new Error(FLAG_LINE_ERROR);
  }
  revalidateDashboard();
}

/** Turn the sticky PR comment on or off for one repository.
 *
 *  Deliberately a SEPARATE action from `setFlagLineAction`, matching the
 *  separate <form> that calls it. The control is JS-free, and `formData.get`
 *  returns the first entry for a name — so one action reading both fields off
 *  one form would let a toggle click re-save the flag line sitting beside it.
 *  Two forms, two actions, two independent writes; the API's PATCH is
 *  field-set-gated on the same principle.
 *
 *  An unreadable value is refused rather than defaulted. `parseBool` returns
 *  undefined for anything that is not the literal "true" or "false", so
 *  "turn this off" can never be performed by accident — `Boolean("false")`
 *  being true is exactly the accident it exists to prevent. */
export async function setFlagLineCommentAction(formData: FormData): Promise<void> {
  const repoId = parseGithubRepoId(formData.get("github_repo_id"));
  const value = parseBool(formData.get("pr_comment"));
  if (repoId === null || value === undefined) throw new Error(PR_COMMENT_ERROR);

  const auth = await withAuth();
  if (!auth.user || !auth.accessToken) throw new Error(PR_COMMENT_ERROR);

  // The API is authoritative about who may write this row; this pre-check only
  // makes the failure legible when the id belongs to a connection other than
  // the selected one — the same shape of check setFlagLineAction makes above.
  const { connections } = await getConnections(auth.accessToken);
  const door = frontDoor(connections, auth.organizationId ?? null);
  if (!door.current?.repositories.some((repository) => repository.id === repoId)) {
    throw new Error(PR_COMMENT_ERROR);
  }

  try {
    await setRepositoryPrComment(auth.accessToken, repoId, value);
  } catch (error) {
    // 401 is the one failure with a different remedy: the session's derived
    // repository scope has aged past entitlements.TTL, and no amount of
    // retrying this form fixes it.
    if (error instanceof SessionApiError && error.status === 401) {
      throw new Error(FLAG_LINE_REAUTH);
    }
    throw new Error(PR_COMMENT_ERROR);
  }
  revalidateDashboard();
}

/** Turn the deep read on or off for one repository.
 *
 *  A THIRD action for a fourth form, on the same principle as the second:
 *  the control is JS-free, `formData.get` returns the first entry for a name,
 *  and one action reading several fields off one form would let a toggle
 *  click re-save whatever sat beside it.
 *
 *  `parseBool` again, and it earns its keep hardest here — `Boolean("false")`
 *  is true, and the accident it would cause on this field is a repository
 *  quietly switched back onto the paid reader by a click that meant to turn
 *  it off. Anything that is not the literal "true" or "false" is refused
 *  rather than defaulted. */
export async function setDeepReadAction(formData: FormData): Promise<void> {
  const repoId = parseGithubRepoId(formData.get("github_repo_id"));
  const value = parseBool(formData.get("deep_read"));
  if (repoId === null || value === undefined) throw new Error(DEEP_READ_ERROR);

  const auth = await withAuth();
  if (!auth.user || !auth.accessToken) throw new Error(DEEP_READ_ERROR);

  // The API is authoritative about who may write this row; this pre-check only
  // makes the failure legible when the id belongs to a connection other than
  // the selected one — the same shape of check the two actions above make.
  const { connections } = await getConnections(auth.accessToken);
  const door = frontDoor(connections, auth.organizationId ?? null);
  if (!door.current?.repositories.some((repository) => repository.id === repoId)) {
    throw new Error(DEEP_READ_ERROR);
  }

  try {
    await setRepositoryDeepRead(auth.accessToken, repoId, value);
  } catch (error) {
    // 401 is the one failure with a different remedy: the session's derived
    // repository scope has aged past entitlements.TTL, and no amount of
    // retrying this form fixes it.
    if (error instanceof SessionApiError && error.status === 401) {
      throw new Error(FLAG_LINE_REAUTH);
    }
    throw new Error(DEEP_READ_ERROR);
  }
  revalidateDashboard();
}
