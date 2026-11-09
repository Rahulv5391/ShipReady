import "server-only";

import { cookies } from "next/headers";

import { tokenExpired } from "@/lib/token";

/**
 * The signed-in person: the API's token and who they are, each in an HttpOnly cookie, so page
 * scripts never see the token (Decision.md D-38). Only server code reads or sets them.
 */
export const SESSION_COOKIE = "shipready_session";
export const USER_COOKIE = "shipready_user";

export type SessionUser = { email: string; name: string; orgId: string };
export type Session = { token: string; user: SessionUser };

const cookieOptions = (expires: Date) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  expires,
});

export async function saveSession(token: string, expires: Date, user: SessionUser) {
  const store = await cookies();
  store.set(SESSION_COOKIE, token, cookieOptions(expires));
  store.set(USER_COOKIE, JSON.stringify(user), cookieOptions(expires));
}

export async function readSession(): Promise<Session | null> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  const user = store.get(USER_COOKIE)?.value;
  if (!token || !user || tokenExpired(token)) return null;
  try {
    return { token, user: JSON.parse(user) as SessionUser };
  } catch {
    return null;
  }
}

export async function clearSession() {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  store.delete(USER_COOKIE);
}
