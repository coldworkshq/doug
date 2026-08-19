"use server";

import { switchToOrganization, withAuth } from "@workos-inc/authkit-nextjs";
import { revalidatePath } from "next/cache";

import {
  frontDoor,
  isFinishableSetupConnection,
  parseFlagLine,
  parseGithubRepoId,
  parseInstallationId,
  readyOrganizationAfterSetup,
} from "@/lib/dashboard-model";
import {
  SessionApiError,
  bindInstallation,
  getConnections,
  setRepositoryThreshold,
} from "@/lib/session-api";

const SETUP_ERROR = "That repository connection is not available.";
const FLAG_LINE_ERROR = "Doug could not save that flag line.";
const FLAG_LINE_REAUTH =
  "Your session's repository access has aged out — sign in again to change settings.";

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
  revalidatePath("/dashboard");
}
