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

/** The site a link opens, without "www.": "content.dgft.gov.in". */
export function siteOf(url: string): string {
  return new URL(url).hostname.replace(/^www\./, "");
}
