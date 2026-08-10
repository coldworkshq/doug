"use server";

import { switchToOrganization, withAuth } from "@workos-inc/authkit-nextjs";

import { getConnections } from "@/lib/session-api";

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
