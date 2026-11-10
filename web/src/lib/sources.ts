/** How the sources page words what the API returns. */

export function rowsLabel(rows: number): string {
  if (rows === 0) return "Not loaded";
  return `${rows.toLocaleString("en-IN")} ${rows === 1 ? "row" : "rows"}`;
}

/** "2026-10-17" as "17 Oct 2026". Read as a calendar date, so no time zone shifts the day. */
export function dayLabel(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** A moment as a day in India time, where ShipReady's users work: "25 Oct 2026". */
function indianDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  });
}

/** "Downloaded 25 Oct 2026, loaded 10 Nov 2026"; null when either is unknown: lists kept in
 * the code, data loaded before this was recorded, or an API older than the web app, whose answer
 * has no such field. */
export function freshnessLabel(
  fetchedAt: string | null | undefined,
  loadedAt: string | null | undefined,
): string | null {
  if (!fetchedAt || !loadedAt) return null;
  if (Number.isNaN(Date.parse(fetchedAt)) || Number.isNaN(Date.parse(loadedAt))) return null;
  return `Downloaded ${indianDay(fetchedAt)}, loaded ${indianDay(loadedAt)}`;
}

/** The site a link opens, without "www.": "content.dgft.gov.in". */
export function siteOf(url: string): string {
  return new URL(url).hostname.replace(/^www\./, "");
}
