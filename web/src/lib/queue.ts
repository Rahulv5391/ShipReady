import type { Readiness, ShipmentListItem } from "@/lib/types";

/** The queue's filters and sort orders, read from the address (?show=…&sort=…&q=…). */

export const SORTS = { recent: "Most recent", score: "Lowest score", reference: "Reference" } as const;
export type Sort = keyof typeof SORTS;

export type Filter = Readiness | "active";
export const FILTERS: { id: Filter; label: string; hint: string }[] = [
  { id: "needs_fix", label: "Needs fix", hint: "A blocker or major check failed" },
  { id: "needs_review", label: "Needs review", hint: "A check could not be confirmed" },
  { id: "ready", label: "Ready", hint: "Every blocker and major check passed" },
  { id: "active", label: "In progress", hint: "Files being read and checked" },
];

export function matches(item: ShipmentListItem, filter: Filter | null): boolean {
  if (filter === null) return true;
  if (filter === "active") return item.run?.status === "running";
  return item.readiness === filter;
}

export function sortItems(items: ShipmentListItem[], sort: Sort): ShipmentListItem[] {
  const sorted = [...items];
  if (sort === "reference") sorted.sort((a, b) => a.reference.localeCompare(b.reference));
  if (sort === "score") {
    // Unchecked shipments have no score yet; they go last.
    const score = (item: ShipmentListItem) =>
      item.readiness_score === null ? Infinity : Number(item.readiness_score);
    sorted.sort((a, b) => score(a) - score(b));
  }
  return sorted; // "recent": as the API sends them, newest first
}

export function parseFilter(value: string | undefined): Filter | null {
  return FILTERS.some((f) => f.id === value) ? (value as Filter) : null;
}

export function parseSort(value: string | undefined): Sort {
  return value !== undefined && Object.hasOwn(SORTS, value) ? (value as Sort) : "recent";
}
