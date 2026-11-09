import "server-only";

import { redirect } from "next/navigation";

import { readSession } from "@/lib/session";

/** The ShipReady API's address, from SHIPREADY_API_URL. */
export function apiUrl(path: string): string {
  const base = process.env.SHIPREADY_API_URL;
  if (!base) throw new Error("SHIPREADY_API_URL is not set; see web/.env.example");
  return `${base.replace(/\/$/, "")}${path}`;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/**
 * A request to the API as the signed-in person. Without a session, or when the API no longer
 * accepts the token, the person is sent to sign in again.
 */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const session = await readSession();
  if (!session) redirect("/sign-in");
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${session.token}` },
    cache: "no-store",
  });
  if (response.status === 401) redirect("/sign-out");
  if (!response.ok) throw new ApiError(response.status, await detail(response));
  return (await response.json()) as T;
}

/** The API's error message ({"detail": ...}), or the status when there is none. */
export async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON: fall through to the status line.
  }
  return `the API answered ${response.status}`;
}
