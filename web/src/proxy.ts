import { NextResponse, type NextRequest } from "next/server";

import { tokenExpired } from "@/lib/token";

const SESSION_COOKIE = "shipready_session";

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
  // Every page except Next.js's own files, the icon and signing out.
  matcher: ["/((?!_next/|icon.svg|sign-out).*)"],
};
