import { withAuth } from "@workos-inc/authkit-nextjs";
import { redirect } from "next/navigation";

import { frontDoor } from "./dashboard-model";
import { type ConnectionsResponse, type RepositoryConnection, getConnections } from "./session-api";

/** The prelude every workspace screen shares (ADR-0034): the session, the
 *  connections, and the one connection the person is in.
 *
 *  The three failure arms live on the ledger, worded once and pinned in
 *  dashboard-contract.test.mjs, and the ledger renders them inline, so every
 *  other screen redirects there rather than carrying a second copy: a failed
 *  connections read, and any front-door state but `runs`. `redirect` works
 *  by throwing, so this never returns in those cases. ADR-0019 rejected a
 *  route-segment layout for this (an extra fetch, no `searchParams`); a
 *  helper each Server Component calls once is not that. */
export async function loadWorkspace(): Promise<{
  user: { email: string };
  accessToken: string;
  connections: ConnectionsResponse;
  connection: RepositoryConnection;
}> {
  const { user, accessToken, organizationId } = await withAuth();
  if (!user || !accessToken) redirect("/sign-in");

  let connections: ConnectionsResponse | null = null;
  try {
    connections = await getConnections(accessToken);
  } catch (error) {
    // Said once, here, so the failure reaches the logs even though the
    // ledger owns the sentence the person sees.
    console.error("doug: connections read failed on a workspace screen", error);
    connections = null;
  }
  if (connections === null) redirect("/dashboard");

  const door = frontDoor(connections.connections, organizationId);
  if (door.state !== "runs") redirect("/dashboard");

  return { user, accessToken, connections, connection: door.current };
}

/** Every repository this connection covers, in one order everywhere. */
export function sortedRepositories(connection: RepositoryConnection) {
  return [...connection.repositories].sort((a, b) => a.full_name.localeCompare(b.full_name));
}
