/**
 * Reads a ShipReady token's expiry without checking its signature. The API checks every token
 * it receives; this only lets the proxy send a person with an expired token to sign in again
 * instead of failing their first request.
 */
export function tokenExpired(token: string, now: number = Date.now()): boolean {
  const payload = token.split(".")[1];
  if (!payload) return true;
  try {
    const claims: unknown = JSON.parse(
      atob(payload.replace(/-/g, "+").replace(/_/g, "/")),
    );
    const exp = (claims as { exp?: unknown }).exp;
    return typeof exp !== "number" || exp * 1000 <= now;
  } catch {
    return true;
  }
}
