import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";
import { tokenExpired } from "@/lib/token";

/**
 * A quick check before each page: without a current session a person is sent to sign in, and a
 * signed-in person skips the sign-in page. The API checks the token itself on every request.
 */
export function proxy(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const signedIn = token !== undefined && !tokenExpired(token);
  const onSignIn = request.nextUrl.pathname === "/sign-in";
  if (onSignIn && signedIn) {
    return NextResponse.redirect(new URL("/shipments", request.url));
  }
  if (!onSignIn && !signedIn) {
    return NextResponse.redirect(new URL("/sign-in", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Every page except Next.js's own files, the icon, signing out and the API relay (which
  // answers 401 itself rather than redirecting a script to the sign-in page).
  matcher: ["/((?!_next/|icon.svg|sign-out|api/).*)"],
};
