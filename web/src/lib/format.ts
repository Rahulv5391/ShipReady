import type { Readiness, RunBrief, ShipmentListItem } from "@/lib/types";

const countries = new Intl.DisplayNames(["en"], { type: "region" });

/** "NL" as "Netherlands"; a code the browser does not know stays as it is. */
export function countryName(code: string | null): string | null {
  if (!code) return null;
  try {
    return countries.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** "Just now", "10 minutes ago", "yesterday". */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000);
  for (const [unit, size] of STEPS) {
    if (seconds >= size) return relative.format(-Math.floor(seconds / size), unit);
  }
  return "Just now";
}

export const MODES: Record<NonNullable<ShipmentListItem["mode"]>, string> = {
  sea: "Sea",
  air: "Air",
  road: "Road",
  rail: "Rail",
  courier: "Courier",
};

export const READINESS: Record<Readiness, { label: string; tone: Tone }> = {
  needs_fix: { label: "Needs fix", tone: "fix" },
  needs_review: { label: "Needs review", tone: "review" },
  ready: { label: "Ready", tone: "ready" },
};

export type Tone = "fix" | "review" | "ready" | "running" | "idle";

export const STAGES: Record<NonNullable<RunBrief["stage"]>, string> = {
  reading: "Reading files",
  extracting: "Reading the fields",
  checking: "Checking",
  drafting: "Drafting messages",
};

/** Where a shipment's processing stands, in a line and a detail, as the queue shows it. */
export function progress(item: ShipmentListItem): { title: string; detail: string; tone: Tone } {
  const run = item.run;
  const files = `${item.files} ${item.files === 1 ? "file" : "files"}`;
  if (!run) return { title: "No files yet", detail: "Add the shipment's documents", tone: "idle" };
  switch (run.status) {
    case "running":
      return { title: run.stage ? STAGES[run.stage] : "Starting", detail: files, tone: "running" };
    case "awaiting_review":
      return { title: "Waiting for you", detail: "Review the findings", tone: "review" };
    case "done":
      return { title: "Reviewed", detail: files, tone: "idle" };
    case "failed":
      return { title: "Could not finish", detail: run.error ?? "See the shipment", tone: "fix" };
  }
}
