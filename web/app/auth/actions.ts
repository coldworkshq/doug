"use server";

import { signOut } from "@workos-inc/authkit-nextjs";

/** Server Actions are POSTed by their form caller; never make logout a GET. */
export async function signOutAction(): Promise<void> {
  await signOut();
}
