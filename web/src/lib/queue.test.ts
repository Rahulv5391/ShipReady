import { describe, expect, it } from "vitest";

import { matches, parseFilter, parseSort, sortItems } from "./queue";
import type { ShipmentListItem } from "./types";

function shipment(reference: string, change: Partial<ShipmentListItem> = {}): ShipmentListItem {
  return {
    id: reference,
    reference,
    mode: "sea",
    status: "RECEIVED",
    error: null,
    readiness: null,
    readiness_score: null,
    created_at: "2026-11-10T10:00:00Z",
    exporter: null,
    consignee: null,
    destination_country: null,
    port_of_loading: null,
    port_of_discharge: null,
    files: 0,
    run: null,
    updated_at: "2026-11-10T10:00:00Z",
    ...change,
  };
}

const fix = shipment("B-2", { readiness: "needs_fix", readiness_score: "75.2" });
const ready = shipment("A-1", { readiness: "ready", readiness_score: "100.0" });
const running = shipment("C-3", { run: { status: "running", stage: "reading", error: null } });

describe("matches", () => {
  it("keeps everything without a filter", () => {
    expect([fix, ready, running].filter((s) => matches(s, null))).toHaveLength(3);
  });

  it("filters by readiness, and in progress by a running run", () => {
    expect(matches(fix, "needs_fix")).toBe(true);
    expect(matches(ready, "needs_fix")).toBe(false);
    expect(matches(running, "active")).toBe(true);
    expect(matches(fix, "active")).toBe(false);
  });
});

describe("sortItems", () => {
  it("keeps the API's order (newest first) for most recent", () => {
    expect(sortItems([fix, ready, running], "recent").map((s) => s.reference)).toEqual(["B-2", "A-1", "C-3"]);
  });

  it("sorts by reference", () => {
    expect(sortItems([fix, running, ready], "reference").map((s) => s.reference)).toEqual(["A-1", "B-2", "C-3"]);
  });

  it("puts the lowest score first and unchecked shipments last", () => {
    expect(sortItems([running, ready, fix], "score").map((s) => s.reference)).toEqual(["B-2", "A-1", "C-3"]);
  });

  it("leaves the list it was given as it was", () => {
    const list = [running, ready, fix];
    sortItems(list, "reference");
    expect(list.map((s) => s.reference)).toEqual(["C-3", "A-1", "B-2"]);
  });
});

describe("parsing the address", () => {
  it("accepts only known filters and sorts", () => {
    expect(parseFilter("needs_review")).toBe("needs_review");
    expect(parseFilter("everything")).toBeNull();
    expect(parseFilter(undefined)).toBeNull();
    expect(parseSort("score")).toBe("score");
    expect(parseSort("toString")).toBe("recent");
    expect(parseSort(undefined)).toBe("recent");
  });
});
