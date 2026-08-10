"use server";

import { switchToOrganization, withAuth } from "@workos-inc/authkit-nextjs";

import {
  isFinishableSetupConnection,
  parseInstallationId,
  readyOrganizationAfterSetup,
} from "@/lib/dashboard-model";
import { bindInstallation, getConnections } from "@/lib/session-api";

const SETUP_ERROR = "That repository connection is not available.";

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
