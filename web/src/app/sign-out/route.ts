import { NextResponse, type NextRequest } from "next/server";

import { clearSession } from "@/lib/session";

/**
 * Ends the session: from the sign-out button (POST) or when the API refuses the token (GET).
 * 303, so the browser fetches the sign-in page rather than posting to it again.
 */
async function signOut(request: NextRequest) {
  await clearSession();
  return NextResponse.redirect(new URL("/sign-in", request.url), 303);
}

export { signOut as GET, signOut as POST };
