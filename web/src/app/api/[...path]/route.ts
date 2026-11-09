import { type NextRequest } from "next/server";

import { apiUrl } from "@/lib/api";
import { readSession } from "@/lib/session";

/**
 * The few API requests the browser makes itself (uploads, Drive imports, live progress), passed
 * on with the session's token so the token never reaches page scripts (Decision.md D-38).
 * Bodies and answers are streamed, not buffered: uploads can be large and progress never ends
 * until the run does.
 */
const ID = "[0-9a-f-]{36}";
const ALLOWED: [string, RegExp][] = [
  ["POST", new RegExp(`^shipments/${ID}/documents$`)],
  ["POST", new RegExp(`^shipments/${ID}/documents:import-drive$`)],
  ["GET", new RegExp(`^shipments/${ID}/runs$`)],
  ["GET", new RegExp(`^runs/${ID}/events$`)],
];
const PASSED_ON = ["content-type", "accept", "last-event-id"];

async function relay(request: NextRequest, { params }: RouteContext<"/api/[...path]">) {
  const path = (await params).path.join("/");
  if (!ALLOWED.some(([method, pattern]) => method === request.method && pattern.test(path))) {
    return Response.json({ detail: "not found" }, { status: 404 });
  }
  const session = await readSession();
  if (!session) return Response.json({ detail: "signed out" }, { status: 401 });

  const headers = new Headers({ Authorization: `Bearer ${session.token}` });
  for (const name of PASSED_ON) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let upstream: Response;
  try {
    upstream = await fetch(apiUrl(`/${path}`), {
      method: request.method,
      headers,
      body: request.method === "POST" ? request.body : undefined,
      // Lets the request body stream to the API instead of being read into memory first.
      duplex: "half",
      cache: "no-store",
      signal: request.signal,
    } as RequestInit);
  } catch {
    return Response.json({ detail: "ShipReady's server didn't answer. Try again." }, { status: 502 });
  }
  const answer = new Headers();
  for (const name of ["content-type", "cache-control"]) {
    const value = upstream.headers.get(name);
    if (value) answer.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: answer });
}

export { relay as GET, relay as POST };
