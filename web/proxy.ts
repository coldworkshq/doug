import { authkitProxy } from "@workos-inc/authkit-nextjs";

export default authkitProxy();

// This must remain literal: Next statically analyzes proxy configuration.
export const config = {
  matcher: ["/dashboard/:path*"],
};
